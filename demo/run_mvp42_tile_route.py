"""Run MVP-4.2 route planning directly from a tile cache manifest."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.dynamics import CostFunction
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    GridBuildError,
    H3Graph,
    PlanningInputError,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.routing import run_route

try:
    from demo.run_mvp31_route import select_distant_endpoint_cells
except ModuleNotFoundError:
    from run_mvp31_route import select_distant_endpoint_cells

DEFAULT_TILE_MANIFEST: Path = Path("outputs/mvp41/tile_manifest.json")
DEFAULT_CONFIG: Path = Path("configs/mvp3_planner.yaml")
DEFAULT_VEHICLE: Path = Path("configs/mvp3_vehicle.yaml")
DEFAULT_OUTPUT_DIR: Path = Path("outputs/mvp42")
DEFAULT_ROI: Path = DEFAULT_OUTPUT_DIR / "mvp42_tile_route_roi.geojson"
MIN_ROUTE_CELLS: int = 3


def run_tile_route_smoke(
    tile_manifest_path: str = str(DEFAULT_TILE_MANIFEST),
    planner_config_path: str = str(DEFAULT_CONFIG),
    vehicle_path: str = str(DEFAULT_VEHICLE),
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
) -> dict[str, object]:
    """Run route planning from a tile manifest produced by MVP-4.1."""
    manifest_path = Path(tile_manifest_path)
    source_manifest = _read_manifest(manifest_path)
    res_fine = _manifest_int(source_manifest, "res_fine")
    tile_res = _manifest_int(source_manifest, "tile_res")
    graph = _load_completed_tile_graph(source_manifest, manifest_path, res_fine, tile_res)
    vehicle = load_vehicle(vehicle_path)
    config = load_config(planner_config_path)
    start, goal = select_distant_endpoint_cells(graph, _cost_function(config, vehicle))
    roi_path = Path(output_dir) / DEFAULT_ROI.name
    _write_roi_layer(roi_path, graph)
    start_cell = graph.cells[start]
    goal_cell = graph.cells[goal]
    request = RouteRequest(
        input_mode="coordinates",
        parquet_path=str(manifest_path),
        planner_config_path=planner_config_path,
        vehicle_path=vehicle_path,
        output_dir=output_dir,
        start_lat=start_cell.lat,
        start_lng=start_cell.lng,
        goal_lat=goal_cell.lat,
        goal_lng=goal_cell.lng,
        roi_layer_path=str(roi_path),
        res_fine=res_fine,
        res_coarse=tile_res,
        theme_attributes=["score", "cost_score", "landcover_type", "soil_type", "slope"],
        max_estimated_cells=50_000_000,
    )
    route_manifest = run_route(request)
    if int(route_manifest["planned_path_length"]) < MIN_ROUTE_CELLS:
        raise GridBuildError("MVP-4.2 route smoke must use a non-trivial tile route.")
    return route_manifest


def _read_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"tile manifest does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanningInputError(f"tile manifest must be a JSON object: {path}")
    return dict(payload)


def _manifest_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"tile manifest field must be integer: {key}")
    return value


def _load_completed_tile_graph(
    manifest: dict[str, object],
    manifest_path: Path,
    res_fine: int,
    tile_res: int,
) -> H3Graph:
    records = manifest.get("tiles")
    if not isinstance(records, list):
        raise PlanningInputError("tile manifest must contain a tiles array.")
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=tile_res)
    frames: list[pd.DataFrame] = []
    for record in records:
        if isinstance(record, dict) and record.get("status") in {"completed", "skipped"}:
            frames.append(builder.load_parquet(str(_tile_path(dict(record), manifest_path))))
    if not frames:
        raise GridBuildError("tile manifest contains no completed route smoke tiles.")
    return builder.build_graph(pd.concat(frames, ignore_index=True).drop_duplicates("h3index"))


def _tile_path(record: dict[object, object], manifest_path: Path) -> Path:
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise GridBuildError(f"completed tile record has no path: {record.get('parent_h3')}")
    candidate = Path(raw_path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return manifest_path.parent / candidate


def _cost_function(config: Mapping[str, object], vehicle: VehicleProfile) -> CostFunction:
    cost_cfg = config.get("cost", {})
    if not isinstance(cost_cfg, dict):
        raise PlanningInputError("planner cost config must be a mapping.")
    return CostFunction(
        vehicle=vehicle,
        k_r=float(cost_cfg.get("tri_coefficient", 0.1)),
        gravity_coeff=float(cost_cfg.get("gravity_coefficient", 5.0)),
        score_coefficient=float(cost_cfg.get("score_coefficient", 1.0)),
    )


def _write_roi_layer(path: Path, graph: H3Graph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    min_lng = min(cell.lng for cell in graph.cells.values()) - 0.01
    max_lng = max(cell.lng for cell in graph.cells.values()) + 0.01
    min_lat = min(cell.lat for cell in graph.cells.values()) - 0.01
    max_lat = max(cell.lat for cell in graph.cells.values()) + 0.01
    gpd.GeoDataFrame(geometry=[box(min_lng, min_lat, max_lng, max_lat)], crs="EPSG:4326").to_file(
        path,
        driver="GeoJSON",
    )


def main() -> None:
    """Run the default MVP-4.2 tile-route smoke."""
    manifest = run_tile_route_smoke()
    print(
        " ".join(
            [
                f"route={manifest['planned_path_length']}",
                f"loaded_tiles={manifest['source_loaded_tile_count']}",
                f"gpkg={manifest['output_gpkg']}",
                f"source={manifest['source_artifact_kind']}",
            ]
        )
    )


if __name__ == "__main__":
    main()
