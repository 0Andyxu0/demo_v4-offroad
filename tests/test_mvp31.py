"""MVP-3.1 route request and thematic map tests."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Point, box

from demo.run_mvp2_nanjing import _sample_manifest
from demo.run_mvp31_route import select_distant_endpoint_cells
from h3_offroad_planner.dynamics import CostFunction
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    GridBuildError,
    H3Cell,
    H3Graph,
    PlanningInputError,
    RouteEndpoint,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.routing import (
    estimate_h3_cells_for_roi,
    load_route_endpoints,
    run_route,
    snap_endpoint,
)


def test_t042_coordinate_route_snaps_and_plans(tmp_path: Path) -> None:
    """T-042: coordinate endpoints snap to passable H3 cells and produce a route."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    start, goal = _edge_endpoint_cells(graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal)

    manifest = run_route(request)

    assert int(manifest["planned_path_length"]) >= 2
    assert Path(str(manifest["output_gpkg"])).exists()


def test_t043_role_point_layer_parses_and_rejects_invalid_roles(tmp_path: Path) -> None:
    """T-043: role point layers parse start/end and reject duplicate or missing roles."""
    endpoint_path = tmp_path / "endpoints.geojson"
    _write_endpoint_layer(endpoint_path, ["start", "end"])

    endpoints = load_route_endpoints(str(endpoint_path))

    assert [endpoint.role for endpoint in endpoints] == ["start", "goal"]
    duplicate_path = tmp_path / "duplicate.geojson"
    _write_endpoint_layer(duplicate_path, ["start", "start"])
    with pytest.raises(PlanningInputError, match="start|goal/end"):
        load_route_endpoints(str(duplicate_path))
    missing_role_path = tmp_path / "missing_role.geojson"
    gpd.GeoDataFrame(geometry=[Point(118.0, 32.0)], crs="EPSG:4326").to_file(
        missing_role_path,
        driver="GeoJSON",
    )
    with pytest.raises(PlanningInputError, match="role"):
        load_route_endpoints(str(missing_role_path))


def test_t044_snap_endpoint_rejects_far_points(tmp_path: Path) -> None:
    """T-044: endpoint snapping fails when the nearest passable cell is too far away."""
    _, graph = _write_route_parquet(tmp_path)

    with pytest.raises(PlanningInputError, match="exceeding"):
        snap_endpoint(graph, RouteEndpoint("start", 0.0, 0.0), max_distance_m=1.0)


def test_t045_explicit_roi_layer_has_priority(tmp_path: Path) -> None:
    """T-045: explicit ROI is used before auto corridor ROI."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    start, goal = _edge_endpoint_cells(graph)
    roi_path = tmp_path / "roi.geojson"
    _write_roi_layer(roi_path, graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal, roi_path=roi_path)

    manifest = run_route(request)

    assert manifest["roi_source"] == "explicit_layer"


def test_t046_auto_corridor_roi_is_recorded(tmp_path: Path) -> None:
    """T-046: auto corridor ROI is generated when no explicit ROI is supplied."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    start, goal = _edge_endpoint_cells(graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal)

    manifest = run_route(request)

    assert manifest["roi_source"] == "auto_corridor"


def test_t047_oversized_roi_estimate_rejects_request(tmp_path: Path) -> None:
    """T-047: oversized res13 ROI estimates produce actionable GridBuildError."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    start, goal = _edge_endpoint_cells(graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal, res_fine=13)
    request.max_estimated_cells = 1

    with pytest.raises(GridBuildError, match="res9/res8|shrink ROI"):
        run_route(request)
    assert estimate_h3_cells_for_roi(box(0.0, 0.0, 1.0, 1.0), 13) > 1


def test_t048_cost_score_tracks_score() -> None:
    """T-048: H3Cell cost_score is constrained to the inverse of score."""
    cell = _cell("a", score=0.25)
    assert cell.cost_score == pytest.approx(0.75)
    explicit = _cell("b", score=0.6, cost_score=0.4)
    assert explicit.cost_score == pytest.approx(0.4)
    with pytest.raises(ValueError, match="1 - score"):
        _cell("c", score=0.6, cost_score=0.2)


def test_t049_score_coefficient_increases_low_score_cost(vehicle: VehicleProfile) -> None:
    """T-049: score-aware cost penalizes low trafficability cells."""
    graph = _two_cell_graph()

    base = CostFunction(vehicle, score_coefficient=0.0).compute(graph, "a", "b")
    penalized = CostFunction(vehicle, score_coefficient=5.0).compute(graph, "a", "b")

    assert penalized > base


def test_t050_theme_export_writes_score_layer(tmp_path: Path) -> None:
    """T-050: thematic graph export writes h3_theme_score."""
    _, graph = _write_route_parquet(tmp_path)
    output_path = tmp_path / "theme.gpkg"

    GISExporter.export_graph_gpkg(graph, str(output_path), theme_attributes=["score"])

    theme = gpd.read_file(output_path, layer="h3_theme_score")
    assert len(theme) == len(graph.cells)


def test_t051_theme_layer_contains_style_fields(tmp_path: Path) -> None:
    """T-051: thematic layers contain style fields for ArcGIS classification."""
    _, graph = _write_route_parquet(tmp_path)
    output_path = tmp_path / "theme_fields.gpkg"

    GISExporter.export_graph_gpkg(graph, str(output_path), theme_attributes=["score"])

    theme = gpd.read_file(output_path, layer="h3_theme_score")
    assert {"style_value", "style_bin", "style_color"}.issubset(theme.columns)


def test_t052_style_manifest_records_theme_metadata(tmp_path: Path) -> None:
    """T-052: style manifest records selected attributes and min/max metadata."""
    _, graph = _write_route_parquet(tmp_path)
    output_path = tmp_path / "theme_manifest.gpkg"
    style_path = tmp_path / "style_manifest.json"

    GISExporter.export_graph_gpkg(
        graph,
        str(output_path),
        theme_attributes=["score"],
        style_manifest_path=str(style_path),
    )

    payload = json.loads(style_path.read_text(encoding="utf-8"))
    assert "score" in payload["attributes"]
    assert payload["attributes"]["score"]["min"] is not None
    assert payload["color_ramp"]


def test_t053_real_nanjing_parquet_coordinate_route(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """T-053: real Nanjing Parquet produces route, theme map, and manifest."""
    parquet_path = Path("outputs/nanjing_h3_sample.parquet")
    if not parquet_path.exists():
        pytest.skip("real Nanjing Parquet artifact is not available")
    graph = H3GridBuilder(res_fine=7, res_coarse=5).load_graph(str(parquet_path))
    start, goal = select_distant_endpoint_cells(
        graph,
        CostFunction(vehicle=vehicle, score_coefficient=1.0),
    )
    roi_path = tmp_path / "nanjing_roi.geojson"
    _write_roi_layer(roi_path, graph)
    request = _route_request(
        tmp_path,
        parquet_path,
        graph,
        start,
        goal,
        roi_path=roi_path,
        res_fine=7,
        res_coarse=5,
    )

    manifest = run_route(request)

    assert Path(str(manifest["output_gpkg"])).exists()
    assert Path(str(manifest["style_manifest"])).exists()
    assert int(manifest["planned_path_length"]) > 2


def test_t054_sampled_parquet_manifest_records_artifact_semantics(tmp_path: Path) -> None:
    """T-054: sampled Parquet sidecar records resolution and continuity semantics."""
    _, graph = _write_route_parquet(tmp_path)

    payload = _sample_manifest(graph)

    assert payload["artifact_kind"] == "sampled_h3_graph"
    assert payload["coverage_mode"] == "sampled_dem_stride"
    assert payload["is_continuous_coverage"] is False
    assert payload["res_fine"] == graph.resolution_fine
    assert payload["res_coarse"] == graph.resolution_coarse
    assert payload["sample_stride"] > 1
    assert "not a continuous" in str(payload["warning"])


def test_t055_run_route_copies_source_metadata(tmp_path: Path) -> None:
    """T-055: route manifest copies source sampled-cache metadata."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    source_manifest, source_payload = _write_source_manifest(parquet_path, graph)
    start, goal = _edge_endpoint_cells(graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal)

    manifest = run_route(request)

    assert manifest["source_manifest"] == str(source_manifest)
    assert manifest["source_artifact_kind"] == source_payload["artifact_kind"]
    assert manifest["source_coverage_mode"] == source_payload["coverage_mode"]
    assert manifest["source_is_continuous_coverage"] is False
    assert manifest["source_res_fine"] == graph.resolution_fine
    assert manifest["source_sample_stride"] == source_payload["sample_stride"]
    assert manifest["source_warning"] == source_payload["warning"]


def test_t056_gpkg_layers_include_source_metadata_fields(tmp_path: Path) -> None:
    """T-056: graph and theme layers expose sampled-cache metadata for ArcGIS."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    _write_source_manifest(parquet_path, graph)
    start, goal = _edge_endpoint_cells(graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal)

    manifest = run_route(request)

    cells = gpd.read_file(str(manifest["output_gpkg"]), layer="h3_cells")
    edges = gpd.read_file(str(manifest["output_gpkg"]), layer="h3_edges")
    theme = gpd.read_file(str(manifest["output_gpkg"]), layer="h3_theme_score")
    expected = {
        "artifact_kind",
        "coverage_mode",
        "is_continuous",
        "source_res_fine",
        "source_res_coarse",
        "sample_stride",
        "max_cells",
    }
    assert expected.issubset(cells.columns)
    assert expected.issubset(edges.columns)
    assert expected.issubset(theme.columns)
    assert set(cells["is_continuous"]) == {False}


def test_t057_mvp31a_route_uses_non_adjacent_endpoints(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """T-057: MVP-3.1a smoke route is longer than an adjacent two-cell edge."""
    parquet_path, graph = _write_route_parquet(tmp_path)
    start, goal = select_distant_endpoint_cells(graph, CostFunction(vehicle))
    roi_path = tmp_path / "route_smoke_roi.geojson"
    _write_roi_layer(roi_path, graph)
    request = _route_request(tmp_path, parquet_path, graph, start, goal, roi_path=roi_path)

    manifest = run_route(request)

    assert int(manifest["planned_path_length"]) > 2


def _write_route_parquet(tmp_path: Path) -> tuple[Path, H3Graph]:
    frame = _h3_frame(radius=2)
    builder = H3GridBuilder(res_fine=9, res_coarse=7)
    parquet_path = tmp_path / "route_graph.parquet"
    builder.save_parquet(frame, str(parquet_path))
    return parquet_path, builder.build_graph(frame)


def _write_source_manifest(parquet_path: Path, graph: H3Graph) -> tuple[Path, dict[str, object]]:
    payload = _sample_manifest(graph)
    payload["coverage_mode"] = "unit_test_stride"
    payload["max_cells"] = len(graph.cells)
    payload["sample_stride"] = 3
    manifest_path = parquet_path.with_suffix(".manifest.json")
    GISExporter.write_manifest(str(manifest_path), payload)
    return manifest_path, payload


def _route_request(
    tmp_path: Path,
    parquet_path: Path,
    graph: H3Graph,
    start: str,
    goal: str,
    roi_path: Path | None = None,
    res_fine: int = 9,
    res_coarse: int = 7,
) -> RouteRequest:
    config_path, vehicle_path = _write_demo_configs(tmp_path)
    start_cell = graph.cells[start]
    goal_cell = graph.cells[goal]
    return RouteRequest(
        input_mode="coordinates",
        parquet_path=str(parquet_path),
        planner_config_path=str(config_path),
        vehicle_path=str(vehicle_path),
        output_dir=str(tmp_path / f"out_{res_fine}_{res_coarse}_{'roi' if roi_path else 'auto'}"),
        start_lat=start_cell.lat,
        start_lng=start_cell.lng,
        goal_lat=goal_cell.lat,
        goal_lng=goal_cell.lng,
        roi_layer_path=str(roi_path) if roi_path is not None else None,
        res_fine=res_fine,
        res_coarse=res_coarse,
        theme_attributes=["score", "cost_score"],
        corridor_buffer_deg=0.01,
        max_estimated_cells=5_000_000,
    )


def _h3_frame(radius: int) -> pd.DataFrame:
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    cells = sorted(str(cell) for cell in h3.grid_disk(center, radius))
    rows: list[dict[str, object]] = []
    for index, cell_id in enumerate(cells):
        lat, lng = h3.cell_to_latlng(cell_id)
        score = 1.0 - index / max(len(cells), 1) * 0.5
        rows.append(
            {
                "cost_score": 1.0 - score,
                "elevation": float(index),
                "h3index": cell_id,
                "has_road": False,
                "is_passable": True,
                "landcover_code": 1,
                "landcover_type": "cropland",
                "lat": float(lat),
                "lc_factor": 1.0,
                "lng": float(lng),
                "parent_h3": str(h3.cell_to_parent(cell_id, 7)),
                "score": score,
                "slope": 0.0,
                "soil_code": 44,
                "soil_type": "水稻土",
                "tri": 0.0,
            }
        )
    return pd.DataFrame.from_records(rows)


def _edge_endpoint_cells(graph: H3Graph) -> tuple[str, str]:
    for edge in graph.edges.values():
        first = graph.cells[edge.cell_a]
        second = graph.cells[edge.cell_b]
        if first.is_passable and second.is_passable and isfinite(second.lc_factor):
            return edge.cell_a, edge.cell_b
    raise AssertionError("test graph must contain at least one passable edge")


def _write_endpoint_layer(path: Path, roles: list[str]) -> None:
    geometries = [Point(118.0 + index * 0.001, 32.0) for index in range(len(roles))]
    gpd.GeoDataFrame({"role": roles}, geometry=geometries, crs="EPSG:4326").to_file(
        path,
        driver="GeoJSON",
    )


def _write_roi_layer(path: Path, graph: H3Graph) -> None:
    min_lng = min(cell.lng for cell in graph.cells.values()) - 0.01
    max_lng = max(cell.lng for cell in graph.cells.values()) + 0.01
    min_lat = min(cell.lat for cell in graph.cells.values()) - 0.01
    max_lat = max(cell.lat for cell in graph.cells.values()) + 0.01
    gpd.GeoDataFrame(geometry=[box(min_lng, min_lat, max_lng, max_lat)], crs="EPSG:4326").to_file(
        path,
        driver="GeoJSON",
    )


def _cell(cell_id: str, score: float, cost_score: float | None = None) -> H3Cell:
    return H3Cell(
        h3index=cell_id,
        lat=0.0,
        lng=0.0,
        elevation=0.0,
        slope=0.0,
        tri=0.0,
        lc_factor=1.0,
        score=score,
        cost_score=cost_score,
    )


def _two_cell_graph() -> H3Graph:
    cells = {
        "a": _cell("a", score=1.0),
        "b": H3Cell(
            h3index="b",
            lat=0.0,
            lng=1.0,
            elevation=0.0,
            slope=0.0,
            tri=0.0,
            lc_factor=1.0,
            score=0.2,
            cost_score=0.8,
        ),
    }
    from h3_offroad_planner.models import H3Edge

    return H3Graph(cells=cells, edges={("a", "b"): H3Edge("a", "b", 10.0)})


def _write_demo_configs(tmp_path: Path) -> tuple[Path, Path]:
    config_path = tmp_path / "planner.yaml"
    vehicle_path = tmp_path / "vehicle.yaml"
    config_path.write_text(
        "\n".join(
            [
                "global_planner: H3AStar",
                "local_replanner: DStarLite",
                "cost:",
                "  tri_coefficient: 0.1",
                "  gravity_coefficient: 5.0",
                "  score_coefficient: 1.0",
            ]
        ),
        encoding="utf-8",
    )
    vehicle_path.write_text(
        "\n".join(
            [
                "name: test_truck",
                "mass_kg: 2000.0",
                "max_climb_angle_deg: 30.0",
                "max_speed_kmh: 80.0",
                "tire_width_m: 0.35",
                "ground_clearance_m: 0.4",
                "max_thrust_n: 8000.0",
                "tire_radius_m: 0.45",
                "min_turn_radius_m: 5.0",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, vehicle_path
