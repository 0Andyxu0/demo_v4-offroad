"""Spec-derived tests for MVP-4.2 route-time tile cache loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from demo.run_mvp31_route import select_distant_endpoint_cells
from demo.run_mvp42_tile_route import run_tile_route_smoke
from h3_offroad_planner.dynamics import CostFunction
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    GridBuildError,
    H3Graph,
    PlanningInputError,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.routing import run_route


def test_t068_run_route_loads_tile_manifest_source(tmp_path: Path) -> None:
    """T-068: route planning can load a graph from tile_manifest.json."""
    manifest_path, graph = _write_tile_cache(tmp_path)
    request = _tile_route_request(tmp_path, manifest_path, graph)

    manifest = run_route(request)

    assert int(manifest["planned_path_length"]) > 2
    assert Path(str(manifest["output_gpkg"])).exists()
    assert int(manifest["source_loaded_tile_count"]) >= 2


def test_t069_tile_manifest_resolution_mismatch_is_rejected(tmp_path: Path) -> None:
    """T-069: request resolution must match tile manifest resolution."""
    manifest_path, graph = _write_tile_cache(tmp_path)
    request = _tile_route_request(tmp_path, manifest_path, graph, res_coarse=7)

    with pytest.raises(PlanningInputError, match="res_fine/res_coarse"):
        run_route(request)


def test_t070_failed_route_tile_blocks_planning(tmp_path: Path) -> None:
    """T-070: failed route-relevant tiles are not silently ignored."""
    manifest_path, graph = _write_tile_cache(tmp_path)
    _rewrite_tile_statuses(manifest_path, first_status="failed")
    request = _tile_route_request(tmp_path, manifest_path, graph)

    with pytest.raises(GridBuildError, match="failed tile|rebuild"):
        run_route(request)


def test_t071_no_completed_tiles_in_roi_is_rejected(tmp_path: Path) -> None:
    """T-071: route ROI must intersect at least one completed or skipped tile."""
    manifest_path, graph = _write_tile_cache(tmp_path)
    _rewrite_tile_statuses(manifest_path, all_status="empty")
    request = _tile_route_request(tmp_path, manifest_path, graph)

    with pytest.raises(GridBuildError, match="no completed tile cache records"):
        run_route(request)


def test_t072_tile_route_manifest_records_source_metadata(tmp_path: Path) -> None:
    """T-072: successful tile-cache routes record source tile metadata."""
    manifest_path, graph = _write_tile_cache(tmp_path)
    request = _tile_route_request(tmp_path, manifest_path, graph)

    manifest = run_route(request)

    assert manifest["source_artifact_kind"] == "tile_h3_cache"
    assert manifest["source_coverage_mode"] == "h3_polyfill_tile_cache"
    assert manifest["source_res_fine"] == 9
    assert manifest["source_tile_res"] == 8
    assert int(manifest["source_loaded_tile_count"]) >= 2
    assert len(cast(list[str], manifest["source_tiles"])) >= 2


def test_t073_real_tile_cache_route_smoke(tmp_path: Path) -> None:
    """T-073: existing MVP-4.1 tile cache can drive an MVP-4.2 route smoke."""
    if not Path("outputs/mvp41/tile_manifest.json").exists():
        pytest.skip("MVP-4.1 real tile cache is not available in this workspace.")

    manifest = run_tile_route_smoke(output_dir=str(tmp_path))

    assert Path(str(manifest["output_gpkg"])).exists()
    assert manifest["source_artifact_kind"] == "tile_h3_cache"
    assert int(manifest["source_loaded_tile_count"]) >= 1


def _write_tile_cache(tmp_path: Path) -> tuple[Path, H3Graph]:
    res_fine = 9
    tile_res = 8
    frame = _h3_frame(res_fine=res_fine, tile_res=tile_res)
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=tile_res)
    graph = builder.build_graph(frame)
    manifest_path = tmp_path / "tile_manifest.json"
    tile_dir = tmp_path / "tiles" / f"parent_res={tile_res}"
    records: list[dict[str, object]] = []
    for parent_h3, group in frame.groupby("parent_h3"):
        path = tile_dir / f"parent_h3={parent_h3}.parquet"
        builder.save_parquet(cast(pd.DataFrame, group), str(path))
        tile_graph = builder.build_graph(cast(pd.DataFrame, group))
        records.append(
            {
                "bounds": list(_h3_polygon(str(parent_h3)).bounds),
                "cells_count": len(tile_graph.cells),
                "edges_count": len(tile_graph.edges),
                "error": None,
                "parent_h3": str(parent_h3),
                "path": str(path),
                "status": "completed",
            }
        )
    if len(records) < 2:
        raise AssertionError("tile cache fixture must span at least two parent tiles.")
    GISExporter.write_manifest(
        str(manifest_path),
        {
            "artifact_kind": "tile_h3_cache",
            "cells_count": len(graph.cells),
            "coverage_mode": "h3_polyfill_tile_cache",
            "edges_count": len(graph.edges),
            "is_continuous_coverage": True,
            "max_cells_per_tile": 100,
            "max_tiles": 80,
            "output_dir": str(tmp_path),
            "res_fine": res_fine,
            "sampling_mode": "center",
            "status_counts": {"completed": len(records)},
            "tile_res": tile_res,
            "tiles": records,
        },
    )
    return manifest_path, graph


def _tile_route_request(
    tmp_path: Path,
    manifest_path: Path,
    graph: H3Graph,
    res_fine: int = 9,
    res_coarse: int = 8,
) -> RouteRequest:
    config_path, vehicle_path = _write_demo_configs(tmp_path)
    vehicle = VehicleProfile(
        name="test_truck",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=8000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )
    start, goal = select_distant_endpoint_cells(graph, CostFunction(vehicle))
    roi_path = tmp_path / f"tile_route_roi_{res_coarse}.geojson"
    _write_roi_layer(roi_path, graph)
    start_cell = graph.cells[start]
    goal_cell = graph.cells[goal]
    return RouteRequest(
        input_mode="coordinates",
        parquet_path=str(manifest_path),
        planner_config_path=str(config_path),
        vehicle_path=str(vehicle_path),
        output_dir=str(tmp_path / f"route_out_{res_fine}_{res_coarse}"),
        start_lat=start_cell.lat,
        start_lng=start_cell.lng,
        goal_lat=goal_cell.lat,
        goal_lng=goal_cell.lng,
        roi_layer_path=str(roi_path),
        res_fine=res_fine,
        res_coarse=res_coarse,
        theme_attributes=["score", "cost_score"],
        max_estimated_cells=5_000_000,
    )


def _h3_frame(res_fine: int, tile_res: int) -> pd.DataFrame:
    center = h3.latlng_to_cell(32.0, 118.0, res_fine)
    rows: list[dict[str, object]] = []
    for index, cell_id in enumerate(sorted(str(cell) for cell in h3.grid_disk(center, 3))):
        lat, lng = h3.cell_to_latlng(cell_id)
        score = 1.0 - index / 100.0
        rows.append(
            {
                "cost_score": 1.0 - score,
                "elevation": float(index) / 10.0,
                "h3index": cell_id,
                "has_road": False,
                "is_passable": True,
                "landcover_code": 1,
                "landcover_type": "cropland",
                "lat": float(lat),
                "lc_factor": 1.0,
                "lng": float(lng),
                "parent_h3": str(h3.cell_to_parent(cell_id, tile_res)),
                "score": score,
                "slope": 0.0,
                "soil_code": 44,
                "soil_type": "paddy",
                "tri": 0.0,
            }
        )
    return pd.DataFrame.from_records(rows)


def _h3_polygon(h3index: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3index)])


def _write_roi_layer(path: Path, graph: H3Graph) -> None:
    min_lng = min(cell.lng for cell in graph.cells.values()) - 0.01
    max_lng = max(cell.lng for cell in graph.cells.values()) + 0.01
    min_lat = min(cell.lat for cell in graph.cells.values()) - 0.01
    max_lat = max(cell.lat for cell in graph.cells.values()) + 0.01
    gpd.GeoDataFrame(geometry=[box(min_lng, min_lat, max_lng, max_lat)], crs="EPSG:4326").to_file(
        path,
        driver="GeoJSON",
    )


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


def _rewrite_tile_statuses(
    manifest_path: Path,
    first_status: str | None = None,
    all_status: str | None = None,
) -> None:
    payload = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    records = cast(list[dict[str, object]], payload["tiles"])
    for index, record in enumerate(records):
        if all_status is not None:
            record["status"] = all_status
            record["path"] = None
        elif first_status is not None and index == 0:
            record["status"] = first_status
            record["path"] = None
    GISExporter.write_manifest(str(manifest_path), payload)
