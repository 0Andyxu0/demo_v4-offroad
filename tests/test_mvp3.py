"""MVP-3 persistence, GIS export, and demo-loop tests."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pytest

from demo.run_mvp3_e2e import run_demo
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import Path as PlannerPath
from h3_offroad_planner.models import PlanningFailedError


def test_t034_load_parquet_valid_h3_table(tmp_path: Path) -> None:
    """T-034: load_parquet validates and returns a persisted H3 table."""
    builder = H3GridBuilder(res_fine=9, res_coarse=7)
    parquet_path = tmp_path / "graph.parquet"
    expected = _h3_frame(radius=1)
    builder.save_parquet(expected, str(parquet_path))

    actual = builder.load_parquet(str(parquet_path))

    assert len(actual) == len(expected)
    assert set(expected["h3index"]) == set(actual["h3index"])


def test_t035_load_graph_rebuilds_edges_from_parquet(tmp_path: Path) -> None:
    """T-035: load_graph rebuilds a connected H3Graph from Parquet."""
    builder = H3GridBuilder(res_fine=9, res_coarse=7)
    parquet_path = tmp_path / "graph.parquet"
    builder.save_parquet(_h3_frame(radius=1), str(parquet_path))

    graph = builder.load_graph(str(parquet_path))

    assert len(graph.cells) == 7
    assert graph.edges


def test_t036_export_graph_gpkg_writes_cells_and_edges(tmp_path: Path) -> None:
    """T-036: GeoPackage graph export creates ArcGIS-readable vector layers."""
    graph = _graph(radius=1)
    output_path = tmp_path / "graph.gpkg"

    GISExporter.export_graph_gpkg(graph, str(output_path))

    cells = gpd.read_file(output_path, layer="h3_cells")
    edges = gpd.read_file(output_path, layer="h3_edges")
    assert output_path.exists()
    assert len(cells) == len(graph.cells)
    assert len(edges) == len(graph.edges)


def test_t037_export_path_geojson_writes_feature_collection(tmp_path: Path) -> None:
    """T-037: GeoJSON path export writes a common debug vector format."""
    graph = _graph(radius=1)
    path = _two_cell_path(graph)
    output_path = tmp_path / "path.geojson"

    GISExporter.export_path_geojson(graph, path, str(output_path))

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert payload["features"][0]["geometry"]["type"] == "LineString"


def test_t038_export_path_gpkg_writes_named_layer(tmp_path: Path) -> None:
    """T-038: GeoPackage path export appends a named route layer."""
    graph = _graph(radius=1)
    path = _two_cell_path(graph)
    output_path = tmp_path / "path.gpkg"

    GISExporter.export_path_gpkg(graph, path, str(output_path), "planned_path")

    route = gpd.read_file(output_path, layer="planned_path")
    assert len(route) == 1
    assert int(route.iloc[0]["cell_count"]) == 2


def test_t039_write_manifest_persists_json_payload(tmp_path: Path) -> None:
    """T-039: manifest export writes reproducible JSON metadata."""
    output_path = tmp_path / "manifest.json"

    GISExporter.write_manifest(str(output_path), {"cells_count": 7, "start": "a"})

    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "cells_count": 7,
        "start": "a",
    }


def test_t040_run_demo_synthetic_end_to_end(tmp_path: Path) -> None:
    """T-040: run_demo closes load, plan, replan, smooth, and export loop."""
    parquet_path = tmp_path / "graph.parquet"
    H3GridBuilder(res_fine=9, res_coarse=7).save_parquet(_h3_frame(radius=2), str(parquet_path))
    config_path, vehicle_path = _write_demo_configs(tmp_path)
    output_dir = tmp_path / "out"

    manifest = run_demo(
        str(parquet_path),
        str(config_path),
        str(vehicle_path),
        str(output_dir),
        9,
        7,
    )

    assert manifest["blocked_cell"] not in manifest["replanned_path"]
    assert int(manifest["smoothed_path_length"]) <= int(manifest["replanned_path_length"])
    assert Path(str(manifest["output_gpkg"])).exists()
    for output_path in dict(manifest["output_geojsons"]).values():
        assert Path(str(output_path)).exists()
    assert (output_dir / "manifest.json").exists()


def test_t041_run_demo_without_finite_component_raises(tmp_path: Path) -> None:
    """T-041: run_demo raises when persisted graph has no usable path component."""
    parquet_path = tmp_path / "single.parquet"
    H3GridBuilder(res_fine=9, res_coarse=7).save_parquet(_h3_frame(radius=0), str(parquet_path))
    config_path, vehicle_path = _write_demo_configs(tmp_path)

    with pytest.raises(PlanningFailedError, match="finite connected component"):
        run_demo(
            str(parquet_path),
            str(config_path),
            str(vehicle_path),
            str(tmp_path / "out"),
            9,
            7,
        )


def _h3_frame(radius: int) -> pd.DataFrame:
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    cells = sorted(str(cell) for cell in h3.grid_disk(center, radius))
    rows: list[dict[str, object]] = []
    for cell_id in cells:
        lat, lng = h3.cell_to_latlng(cell_id)
        rows.append(
            {
                "elevation": 0.0,
                "h3index": cell_id,
                "has_road": False,
                "is_passable": True,
                "lat": float(lat),
                "lc_factor": 1.0,
                "lng": float(lng),
                "parent_h3": str(h3.cell_to_parent(cell_id, 7)),
                "slope": 0.0,
                "tri": 0.0,
            }
        )
    return pd.DataFrame.from_records(rows)


def _graph(radius: int) -> object:
    return H3GridBuilder(res_fine=9, res_coarse=7).build_graph(_h3_frame(radius))


def _two_cell_path(graph: object) -> PlannerPath:
    edge = next(iter(graph.edges.values()))
    return PlannerPath(cells=[edge.cell_a, edge.cell_b], total_cost=edge.geo_distance)


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
