"""Parameterized route planning entry points for MVP-3.1."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from heapq import heappop, heappush
from math import atan2, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from time import perf_counter
from typing import cast

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    GISInputError,
    GridBuildError,
    H3Cell,
    H3Edge,
    H3Graph,
    PlannerInput,
    PlanningInputError,
    RouteEndpoint,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.models import (
    Path as PlannerPath,
)
from h3_offroad_planner.planners import PlannerFactory
from h3_offroad_planner.routing_index import (
    ROUTING_INDEX_KIND,
    RoutingIndex,
    open_routing_index,
)

__all__ = [
    "estimate_h3_cells_for_roi",
    "load_route_endpoints",
    "run_route",
    "snap_endpoint",
]

CRS_WGS84: str = "EPSG:4326"
EARTH_RADIUS_M: float = 6_371_000.0
ROUTE_GPKG_NAME: str = "mvp31_route.gpkg"
ROUTE_GEOJSON_NAME: str = "planned_path.geojson"
ROUTE_MANIFEST_NAME: str = "route_manifest.json"
STYLE_MANIFEST_NAME: str = "style_manifest.json"
PLANNED_PATH_LAYER: str = "planned_path"
TILE_CACHE_KIND: str = "tile_h3_cache"
TILE_ROUTE_STATUSES: frozenset[str] = frozenset({"completed", "skipped"})
TILE_EMPTY_STATUS: str = "empty"
TILE_FAILED_STATUS: str = "failed"
JsonObject = dict[str, object]


def run_route(request: RouteRequest) -> dict[str, object]:
    """Run a user-parameterized single-vehicle route request.

    Args:
        request: Valid route request with coordinate or layer endpoints.

    Returns:
        JSON-serializable manifest describing inputs, snapped cells, outputs, and route.

    Raises:
        GridBuildError: If the ROI estimate is too large or filtering removes all cells.
        PlanningInputError: If endpoint input is invalid or cannot be snapped.
        PlanningFailedError: Propagated from the configured planner when no path exists.
    """
    endpoints = _request_endpoints(request)
    roi_geometry, roi_source = _resolve_roi(request, endpoints)
    estimated_cells = estimate_h3_cells_for_roi(roi_geometry, request.res_fine)
    if estimated_cells > request.max_estimated_cells:
        raise GridBuildError(_oversize_message(estimated_cells, request.max_estimated_cells))
    source_metadata = _source_metadata(request.parquet_path)
    graph, source_metadata = _load_route_graph(request, roi_geometry, source_metadata)
    vehicle = load_vehicle(request.vehicle_path)
    route_path, candidates, replanned = _plan_route(request, graph, vehicle, endpoints)
    outputs = _export_route_outputs(graph, route_path, request, source_metadata)
    manifest = _route_manifest(
        request=request,
        graph=graph,
        endpoints=endpoints,
        route_path=route_path,
        outputs=outputs,
        roi_source=roi_source,
        estimated_cells=estimated_cells,
        source_metadata=source_metadata,
        candidates=candidates,
        replanned=replanned,
    )
    GISExporter.write_manifest(str(Path(request.output_dir) / ROUTE_MANIFEST_NAME), manifest)
    return manifest


def load_route_endpoints(path: str) -> list[RouteEndpoint]:
    """Load route endpoints from a point vector layer with a `role` field."""
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"endpoint layer does not exist: {path}")
    gdf = _read_wgs84_layer(input_path)
    if "role" not in gdf.columns:
        raise PlanningInputError("endpoint layer must contain a 'role' field.")
    endpoints = [_endpoint_from_mapping(row._asdict()) for row in gdf.itertuples()]
    _validate_endpoint_roles(endpoints)
    return endpoints


def snap_endpoint(graph: H3Graph, endpoint: RouteEndpoint, max_distance_m: float) -> str:
    """Snap one endpoint to the nearest passable H3 cell in a graph."""
    if max_distance_m <= 0.0:
        raise ValueError("max_distance_m must be positive.")
    best_cell = ""
    best_distance = float("inf")
    for cell_id, cell in graph.cells.items():
        if not cell.is_passable:
            continue
        distance = _haversine_m(endpoint.lat, endpoint.lng, cell.lat, cell.lng)
        if distance < best_distance:
            best_cell = cell_id
            best_distance = distance
    if not best_cell:
        raise PlanningInputError("graph has no passable cells for endpoint snapping.")
    if best_distance > max_distance_m:
        raise PlanningInputError(
            f"endpoint role={endpoint.role!r} is {best_distance:.1f} m from nearest "
            f"passable cell, exceeding max_snap_distance_m={max_distance_m:.1f}."
        )
    return best_cell


def estimate_h3_cells_for_roi(roi: BaseGeometry, resolution: int) -> int:
    """Estimate H3 cell count for a WGS84 ROI polygon."""
    if resolution < 0:
        raise GridBuildError("H3 resolution must be non-negative.")
    if roi.is_empty or roi.area <= 0.0:
        raise GridBuildError("ROI geometry must be non-empty with positive area.")
    area_m2 = _approx_wgs84_area_m2(roi)
    average_area = float(h3.average_hexagon_area(resolution, unit="m^2"))
    return max(1, int(area_m2 / max(average_area, 1.0)))


def _request_endpoints(request: RouteRequest) -> list[RouteEndpoint]:
    if request.input_mode == "layer":
        if request.endpoint_layer_path is None:
            raise PlanningInputError("endpoint_layer_path is required in layer mode.")
        return load_route_endpoints(request.endpoint_layer_path)
    if (
        request.start_lat is None
        or request.start_lng is None
        or request.goal_lat is None
        or request.goal_lng is None
    ):
        raise PlanningInputError("coordinate route request is missing endpoint coordinates.")
    return [
        RouteEndpoint("start", request.start_lat, request.start_lng),
        RouteEndpoint("goal", request.goal_lat, request.goal_lng),
    ]


def _resolve_roi(
    request: RouteRequest,
    endpoints: list[RouteEndpoint],
) -> tuple[BaseGeometry, str]:
    if request.roi_layer_path is not None:
        return _load_roi_geometry(request.roi_layer_path), "explicit_layer"
    start = _single_endpoint(endpoints, "start")
    goal = _single_endpoint(endpoints, "goal")
    line = LineString([(start.lng, start.lat), (goal.lng, goal.lat)])
    if line.length == 0.0:
        raise PlanningInputError("start and goal coordinates must be different.")
    return line.buffer(request.corridor_buffer_deg), "auto_corridor"


def _load_route_graph(
    request: RouteRequest,
    roi_geometry: BaseGeometry,
    source_metadata: dict[str, object],
    progress: Callable[[str, int, str], None] | None = None,
    progress_range: tuple[int, int] = (75, 84),
    corridor_ring: int = 1,
    max_widest_detour_ratio: float | None = None,
) -> tuple[H3Graph, dict[str, object]]:
    if _is_routing_index_metadata(source_metadata):
        return _load_index_route_graph(
            request,
            source_metadata,
            corridor_ring,
            max_widest_detour_ratio=max_widest_detour_ratio,
        )
    if _is_tile_cache_metadata(source_metadata):
        return _load_tile_route_graph(
            request, roi_geometry, source_metadata, progress=progress, progress_range=progress_range
        )
    graph = H3GridBuilder(res_fine=request.res_fine, res_coarse=request.res_coarse).load_graph(
        request.parquet_path
    )
    return _filter_graph_by_roi(graph, roi_geometry), source_metadata


def _source_metadata(parquet_path: str) -> dict[str, object]:
    source_path = Path(parquet_path)
    if source_path.suffix.lower() == ".json":
        if source_path.name == "current.json" and source_path.parent.name == "routing_index":
            return _routing_index_metadata(source_path)
        metadata = _read_source_manifest(source_path)
        if _is_tile_cache_metadata(metadata):
            current = source_path.parent / "routing_index" / "current.json"
            if current.is_file():
                indexed = _routing_index_metadata(current)
                if indexed["static_input_hash"] != metadata.get("static_input_hash"):
                    raise PlanningInputError("routing index does not match the tile manifest.")
                indexed["tile_source_manifest"] = str(source_path)
                return indexed
        elif not _is_routing_index_metadata(metadata):
            raise PlanningInputError(
                "JSON route sources must be a tile cache manifest or routing index."
            )
        return metadata
    sidecar_path = _parquet_manifest_path(parquet_path)
    if not sidecar_path.exists():
        return {}
    return _read_source_manifest(sidecar_path)


def _read_source_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"source manifest does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningInputError(f"invalid source manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise PlanningInputError(f"source manifest must be a JSON object: {path}")
    metadata = dict(payload)
    metadata["source_manifest"] = str(path)
    return metadata


def _parquet_manifest_path(parquet_path: str) -> Path:
    return Path(parquet_path).with_suffix(".manifest.json")


def _is_tile_cache_metadata(source_metadata: JsonObject) -> bool:
    return source_metadata.get("artifact_kind") == TILE_CACHE_KIND


def _is_routing_index_metadata(source_metadata: JsonObject) -> bool:
    return source_metadata.get("artifact_kind") == ROUTING_INDEX_KIND


def _routing_index_metadata(path: Path) -> JsonObject:
    resolved = path.resolve()
    index = open_routing_index(resolved)
    metadata = dict(index.manifest)
    metadata["source_manifest"] = str(resolved)
    metadata["routing_index_manifest"] = str(index.build_dir / "routing_index.json")
    return metadata


def _load_index_route_graph(
    request: RouteRequest,
    source_metadata: JsonObject,
    corridor_ring: int,
    *,
    max_widest_detour_ratio: float | None = None,
) -> tuple[H3Graph, JsonObject]:
    if corridor_ring not in {1, 2}:
        raise ValueError("routing-index corridor ring must be 1 or 2.")
    res_fine = _metadata_int(source_metadata, "res_fine")
    res_coarse = _metadata_int(source_metadata, "res_coarse")
    if request.res_fine != res_fine or request.res_coarse != res_coarse:
        raise PlanningInputError(
            "RouteRequest resolutions do not match the loaded routing index "
            f"({res_fine}/{res_coarse})."
        )
    index_started = perf_counter()
    index = open_routing_index(_metadata_str(source_metadata, "source_manifest"))
    index_open_elapsed = perf_counter() - index_started
    endpoints = _request_endpoints(request)
    if request.input_mode != "coordinates":
        raise PlanningInputError("routing-index planning accepts start and goal coordinates only.")
    coarse_started = perf_counter()
    skeletons, coarse_diagnostics = _coarse_skeletons(
        index,
        _single_endpoint(endpoints, "start"),
        _single_endpoint(endpoints, "goal"),
        max_widest_detour_ratio=max_widest_detour_ratio,
    )
    coarse_elapsed = perf_counter() - coarse_started
    active = _expanded_corridor_parents(index, skeletons, corridor_ring)
    load_started = perf_counter()
    frame = index.load_cells(active)
    load_elapsed = perf_counter() - load_started
    graph_started = perf_counter()
    graph = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse).build_graph(frame)
    metadata = dict(source_metadata)
    metadata.update(
        {
            "routing_index_build_id": index.build_id,
            "source_loaded_tile_count": len(active),
            "source_loaded_file_count": 1,
            "source_raw_row_count": len(frame),
            "source_tiles": sorted(active),
            "active_parent_h3": sorted(active),
            "corridor_ring": corridor_ring,
            "coarse_skeletons": skeletons,
            **coarse_diagnostics,
            "performance": {
                "index_open_s": index_open_elapsed,
                "coarse_search_s": coarse_elapsed,
                "corridor_load_s": load_elapsed,
                "graph_build_s": perf_counter() - graph_started,
            },
        }
    )
    return graph, metadata


def _coarse_skeletons(
    index: RoutingIndex,
    start: RouteEndpoint,
    goal: RouteEndpoint,
    *,
    max_widest_detour_ratio: float | None = None,
) -> tuple[dict[str, list[str]], JsonObject]:
    if max_widest_detour_ratio is not None and (
        not isfinite(max_widest_detour_ratio) or max_widest_detour_ratio < 0.0
    ):
        raise ValueError("max_widest_detour_ratio must be finite and non-negative.")
    frame = index.coarse_graph.drop_duplicates(subset=["parent_a", "parent_b"])
    nodes = set(frame["parent_a"].astype(str)).union(frame["parent_b"].astype(str))
    if not nodes:
        raise GridBuildError("routing-index coarse graph is empty.")
    resolution = _metadata_int(dict(index.manifest), "res_coarse")
    start_parent = _snap_parent(nodes, start, resolution)
    goal_parent = _snap_parent(nodes, goal, resolution)
    adjacency: dict[str, list[tuple[str, dict[str, float]]]] = defaultdict(list)
    for row in frame.itertuples(index=False):
        first = str(row.parent_a)
        second = str(row.parent_b)
        metrics = {
            "distance": float(str(row.distance_m)),
            "slope": float(str(row.slope_mean)),
            "tri": float(str(row.tri_mean)),
            "road": float(str(row.road_fraction)),
            "passable": float(str(row.passable_fraction)),
            "environment": float(str(row.environment_proxy)),
        }
        adjacency[first].append((second, metrics))
        adjacency[second].append((first, metrics))
    skeletons: dict[str, list[str]] = {}
    profiles = ("distance", "eta_road", "terrain_travel", "environment")
    for profile in profiles:
        skeletons[profile] = _coarse_shortest_path(
            adjacency, start_parent, goal_parent, profile, frozenset()
        )
    widest = _coarse_widest_path(adjacency, start_parent, goal_parent)
    shortest_distance = _coarse_path_distance(adjacency, skeletons["distance"])
    widest_distance = _coarse_path_distance(adjacency, widest)
    widest_limit = (
        None
        if max_widest_detour_ratio is None
        else shortest_distance * (1.0 + max_widest_detour_ratio)
    )
    widest_included = widest_limit is None or widest_distance <= widest_limit
    skeletons["widest"] = widest if widest_included else []
    blocked = frozenset(skeletons["distance"][1:-1])
    try:
        skeletons["independent_backup"] = _coarse_shortest_path(
            adjacency, start_parent, goal_parent, "distance", blocked
        )
    except GridBuildError:
        skeletons["independent_backup"] = []
    return skeletons, {
        "coarse_widest_included": widest_included,
        "coarse_widest_parent_count": len(widest),
        "coarse_widest_distance_m": widest_distance,
        "coarse_widest_limit_m": widest_limit,
    }


def _coarse_path_distance(
    adjacency: Mapping[str, list[tuple[str, dict[str, float]]]],
    path: list[str],
) -> float:
    total = 0.0
    for current, neighbor in zip(path[:-1], path[1:], strict=True):
        metrics = next(
            (edge for target, edge in adjacency.get(current, []) if target == neighbor),
            None,
        )
        if metrics is None:
            raise GridBuildError(f"coarse path contains a missing edge: {current}->{neighbor}.")
        total += metrics["distance"]
    return total


def _snap_parent(nodes: set[str], endpoint: RouteEndpoint, resolution: int) -> str:
    direct = str(h3.latlng_to_cell(endpoint.lat, endpoint.lng, resolution))
    if direct in nodes:
        return direct
    return min(
        nodes,
        key=lambda cell: _haversine_m(
            endpoint.lat,
            endpoint.lng,
            float(h3.cell_to_latlng(cell)[0]),
            float(h3.cell_to_latlng(cell)[1]),
        ),
    )


def _coarse_shortest_path(
    adjacency: Mapping[str, list[tuple[str, dict[str, float]]]],
    start: str,
    goal: str,
    profile: str,
    blocked: frozenset[str],
) -> list[str]:
    queue: list[tuple[float, str]] = [(0.0, start)]
    costs = {start: 0.0}
    previous: dict[str, str] = {}
    while queue:
        cost, current = heappop(queue)
        if cost != costs.get(current):
            continue
        if current == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return list(reversed(path))
        for neighbor, metrics in adjacency.get(current, []):
            if neighbor in blocked and neighbor not in {start, goal}:
                continue
            candidate = cost + _coarse_weight(metrics, profile)
            if candidate < costs.get(neighbor, float("inf")):
                costs[neighbor] = candidate
                previous[neighbor] = current
                heappush(queue, (candidate, neighbor))
    raise GridBuildError(f"coarse routing index has no {profile} path between endpoints.")


def _coarse_weight(metrics: Mapping[str, float], profile: str) -> float:
    distance = metrics["distance"]
    if profile == "eta_road":
        return distance / (1.0 + 2.0 * metrics["road"])
    if profile == "terrain_travel":
        return distance * (1.0 + metrics["slope"] / 30.0 + metrics["tri"] / 10.0)
    if profile == "environment":
        return distance * (1.0 + metrics["environment"])
    return distance


def _coarse_widest_path(
    adjacency: Mapping[str, list[tuple[str, dict[str, float]]]],
    start: str,
    goal: str,
) -> list[str]:
    queue: list[tuple[float, float, float, str]] = [(-1.0, 0.0, 0.0, start)]
    best = {start: (-1.0, 0.0, 0.0)}
    previous: dict[str, str] = {}
    while queue:
        negative_margin, risk, distance, current = heappop(queue)
        if best.get(current) != (negative_margin, risk, distance):
            continue
        if current == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return list(reversed(path))
        current_margin = -negative_margin
        for neighbor, metrics in adjacency.get(current, []):
            proxy = min(
                metrics["passable"],
                max(0.0, 1.0 - metrics["slope"] / 30.0),
                max(0.0, 1.0 - metrics["tri"] / 10.0),
            )
            candidate = (
                -min(current_margin, proxy),
                risk + metrics["slope"] + metrics["tri"],
                distance + metrics["distance"],
            )
            if candidate < best.get(neighbor, (float("inf"),) * 3):
                best[neighbor] = candidate
                previous[neighbor] = current
                heappush(queue, (*candidate, neighbor))
    raise GridBuildError("coarse routing index has no widest path between endpoints.")


def _expanded_corridor_parents(
    index: RoutingIndex,
    skeletons: Mapping[str, list[str]],
    ring: int,
) -> set[str]:
    available = set(index.coarse_graph["parent_a"].astype(str)).union(
        index.coarse_graph["parent_b"].astype(str)
    )
    backbone = {parent for path in skeletons.values() for parent in path}
    active = {
        str(neighbor)
        for parent in backbone
        for neighbor in h3.grid_disk(parent, ring)
        if str(neighbor) in available
    }
    if not active:
        raise GridBuildError("coarse skeleton expansion selected no indexed parents.")
    return active


def _load_tile_route_graph(
    request: RouteRequest,
    roi_geometry: BaseGeometry,
    source_metadata: JsonObject,
    progress: Callable[[str, int, str], None] | None = None,
    progress_range: tuple[int, int] = (75, 84),
) -> tuple[H3Graph, JsonObject]:
    load_started = perf_counter()
    res_fine = _metadata_int(source_metadata, "res_fine")
    tile_res = _metadata_int(source_metadata, "tile_res")
    if request.res_fine != res_fine or request.res_coarse != tile_res:
        raise PlanningInputError(
            "RouteRequest res_fine/res_coarse must match tile manifest "
            f"res_fine/tile_res ({res_fine}/{tile_res})."
        )
    manifest_path = Path(str(source_metadata["source_manifest"]))
    selected = _selected_tile_records(source_metadata, roi_geometry)
    frames = _load_tile_frames(
        selected,
        manifest_path,
        res_fine,
        tile_res,
        progress=progress,
        progress_range=progress_range,
    )
    load_finished = perf_counter()
    if progress is not None:
        progress("global_plan", progress_range[1], f"building graph from {len(selected)} tiles")
    graph = H3GridBuilder(res_fine=res_fine, res_coarse=tile_res).build_graph(
        pd.concat(frames, ignore_index=True).drop_duplicates(subset="h3index")
    )
    filtered = _filter_graph_by_roi(graph, roi_geometry)
    metadata = _tile_route_metadata(source_metadata, selected, res_fine, tile_res)
    metadata["source_raw_row_count"] = sum(len(frame) for frame in frames)
    metadata["source_loaded_file_count"] = len(selected)
    metadata["performance"] = {
        "corridor_load_s": load_finished - load_started,
        "graph_build_s": perf_counter() - load_finished,
    }
    return filtered, metadata


def _selected_tile_records(
    source_metadata: JsonObject,
    roi_geometry: BaseGeometry,
) -> list[JsonObject]:
    selected: list[JsonObject] = []
    for record in _tile_records(source_metadata):
        if not _tile_record_geometry(record).intersects(roi_geometry):
            continue
        status = _metadata_str(record, "status")
        if status == TILE_FAILED_STATUS:
            raise GridBuildError(
                f"route ROI intersects failed tile {record.get('parent_h3')}; "
                "rebuild the tile cache before planning this corridor."
            )
        if status == TILE_EMPTY_STATUS:
            continue
        if status not in TILE_ROUTE_STATUSES:
            raise PlanningInputError(f"unsupported tile status in manifest: {status!r}")
        selected.append(record)
    if not selected:
        raise GridBuildError(
            "route ROI intersects no completed tile cache records; "
            "expand/rebuild the tile cache or adjust the route ROI."
        )
    return selected


def _tile_records(source_metadata: JsonObject) -> list[JsonObject]:
    records = source_metadata.get("tiles")
    if not isinstance(records, list):
        raise PlanningInputError("tile manifest must contain a tiles array.")
    typed: list[JsonObject] = []
    for record in records:
        if not isinstance(record, dict):
            raise PlanningInputError("tile manifest records must be JSON objects.")
        typed.append(dict(record))
    return typed


def _tile_record_geometry(record: JsonObject) -> BaseGeometry:
    bounds = record.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise PlanningInputError("tile record bounds must be a 4-value list.")
    values = _tile_bounds_values(bounds)
    return box(values[0], values[1], values[2], values[3])


def _tile_bounds_values(bounds: list[object]) -> tuple[float, float, float, float]:
    values: list[float] = []
    for value in bounds:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PlanningInputError("tile record bounds must contain numeric values.")
        values.append(float(value))
    return (values[0], values[1], values[2], values[3])


def _load_tile_frames(
    selected_records: list[JsonObject],
    manifest_path: Path,
    res_fine: int,
    tile_res: int,
    progress: Callable[[str, int, str], None] | None = None,
    progress_range: tuple[int, int] = (75, 84),
) -> list[pd.DataFrame]:
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=tile_res)
    frames: list[pd.DataFrame] = []
    total = len(selected_records)
    start_pct, end_pct = progress_range
    span = max(0, end_pct - start_pct)
    stride = max(1, total // 50) if total > 20 else 1
    for idx, record in enumerate(selected_records, 1):
        tile_path = _tile_record_path(record, manifest_path)
        try:
            frames.append(builder.load_parquet(str(tile_path)))
        except (FileNotFoundError, GridBuildError) as exc:
            parent_h3 = record.get("parent_h3")
            raise GridBuildError(f"failed to load selected tile {parent_h3}: {tile_path}") from exc
        if progress is not None and (idx % stride == 0 or idx == total):
            pct = start_pct + int(span * (idx / total))
            progress("global_plan", pct, f"loading corridor tiles: [{idx}/{total}]")
    return frames


def _tile_record_path(record: JsonObject, manifest_path: Path) -> Path:
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise GridBuildError(f"selected tile has no readable path: {record.get('parent_h3')}")
    candidate = Path(raw_path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    relative_candidate = manifest_path.parent / candidate
    if relative_candidate.exists():
        return relative_candidate
    return candidate


def _tile_route_metadata(
    source_metadata: JsonObject,
    selected_records: list[JsonObject],
    res_fine: int,
    tile_res: int,
) -> JsonObject:
    metadata = dict(source_metadata)
    metadata["source_res_fine"] = res_fine
    metadata["source_res_coarse"] = tile_res
    metadata["source_tile_res"] = tile_res
    metadata["source_tile_count"] = len(_tile_records(source_metadata))
    metadata["source_loaded_tile_count"] = len(selected_records)
    metadata["source_tiles"] = [_metadata_str(record, "parent_h3") for record in selected_records]
    return metadata


def _metadata_int(source: JsonObject, key: str) -> int:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"source manifest field must be integer: {key}")
    return value


def _metadata_str(source: JsonObject, key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise PlanningInputError(f"source manifest field must be non-empty string: {key}")
    return value


def _plan_route(
    request: RouteRequest,
    graph: H3Graph,
    vehicle: VehicleProfile,
    endpoints: list[RouteEndpoint],
) -> tuple[PlannerPath, list[PlannerPath], bool]:
    config = load_config(request.planner_config_path)
    config["_vehicle"] = vehicle
    facade = PlannerFactory.from_config(config)
    start_cell = snap_endpoint(
        graph,
        _single_endpoint(endpoints, "start"),
        request.max_snap_distance_m,
    )
    goal_cell = snap_endpoint(
        graph,
        _single_endpoint(endpoints, "goal"),
        request.max_snap_distance_m,
    )
    inp = PlannerInput(
        graph=graph,
        start=start_cell,
        goal=goal_cell,
        vehicle=vehicle,
        objectives=request.objectives,
    )
    candidates = facade.plan(inp).paths
    if request.candidate_index >= len(candidates):
        raise PlanningInputError(
            f"candidate_index={request.candidate_index} is outside {len(candidates)} candidates."
        )
    selected = candidates[request.candidate_index]
    if not request.blocked_cells:
        return selected, candidates, False
    blocked = set(request.blocked_cells)
    missing = sorted(blocked.difference(graph.cells))
    if missing:
        raise PlanningInputError(f"blocked H3 cells are absent from the route graph: {missing}")
    return facade.on_blockage(graph, blocked, selected), candidates, True


def _export_route_outputs(
    graph: H3Graph,
    route_path: PlannerPath,
    request: RouteRequest,
    source_metadata: dict[str, object],
) -> dict[str, object]:
    output_root = Path(request.output_dir)
    gpkg_path = output_root / ROUTE_GPKG_NAME
    geojson_path = output_root / ROUTE_GEOJSON_NAME
    style_manifest_path = output_root / STYLE_MANIFEST_NAME
    GISExporter.export_graph_gpkg(
        graph,
        str(gpkg_path),
        theme_attributes=request.theme_attributes,
        style_manifest_path=str(style_manifest_path),
        layer_metadata=source_metadata,
    )
    GISExporter.export_path_gpkg(graph, route_path, str(gpkg_path), PLANNED_PATH_LAYER)
    GISExporter.export_path_geojson(graph, route_path, str(geojson_path))
    return {
        "gpkg": str(gpkg_path),
        "path_geojson": str(geojson_path),
        "style_manifest": str(style_manifest_path),
    }


def _route_manifest(
    request: RouteRequest,
    graph: H3Graph,
    endpoints: list[RouteEndpoint],
    route_path: PlannerPath,
    outputs: dict[str, object],
    roi_source: str,
    estimated_cells: int,
    source_metadata: dict[str, object],
    candidates: list[PlannerPath],
    replanned: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "cells_count": len(graph.cells),
        "edges_count": len(graph.edges),
        "endpoints": [_endpoint_payload(endpoint) for endpoint in endpoints],
        "estimated_cells": estimated_cells,
        "input_mode": request.input_mode,
        "output_gpkg": outputs["gpkg"],
        "output_path_geojson": outputs["path_geojson"],
        "parquet_path": request.parquet_path,
        "graph_source_path": request.parquet_path,
        "planned_path": route_path.cells,
        "planned_path_length": len(route_path.cells),
        "candidate_index": request.candidate_index,
        "candidate_count": len(candidates),
        "candidate_paths": [_candidate_payload(candidate) for candidate in candidates],
        "requested_objectives": request.objectives,
        "blocked_cells": request.blocked_cells,
        "replanned": replanned,
        "res_coarse": request.res_coarse,
        "res_fine": request.res_fine,
        "roi_source": roi_source,
        "style_manifest": outputs["style_manifest"],
        "theme_attributes": request.theme_attributes,
        "vehicle_path": request.vehicle_path,
    }
    payload.update(_route_source_metadata_payload(source_metadata))
    return payload


def _candidate_payload(candidate: PlannerPath) -> dict[str, object]:
    """Return one JSON-safe candidate summary for WebGIS selection."""
    return {
        "cells": candidate.cells,
        "objectives": candidate.objectives,
        "total_cost": candidate.total_cost,
    }


def _route_source_metadata_payload(source_metadata: dict[str, object]) -> dict[str, object]:
    source_res_coarse = source_metadata.get(
        "source_res_coarse",
        source_metadata.get("res_coarse", source_metadata.get("tile_res")),
    )
    return {
        "source_artifact_kind": source_metadata.get("artifact_kind"),
        "source_coverage_mode": source_metadata.get("coverage_mode"),
        "source_is_continuous_coverage": source_metadata.get("is_continuous_coverage"),
        "source_loaded_tile_count": source_metadata.get("source_loaded_tile_count"),
        "source_manifest": source_metadata.get("source_manifest"),
        "source_max_cells": source_metadata.get("max_cells"),
        "source_res_coarse": source_res_coarse,
        "source_res_fine": source_metadata.get("source_res_fine", source_metadata.get("res_fine")),
        "source_sample_stride": source_metadata.get("sample_stride"),
        "source_tile_count": source_metadata.get("source_tile_count"),
        "source_tile_res": source_metadata.get("source_tile_res", source_metadata.get("tile_res")),
        "source_tiles": source_metadata.get("source_tiles"),
        "source_warning": source_metadata.get("warning"),
    }


def _read_wgs84_layer(path: Path) -> gpd.GeoDataFrame:
    try:
        gdf = gpd.read_file(path)
    except (OSError, ValueError) as exc:
        raise GISInputError(f"failed to read vector layer: {path}") from exc
    if gdf.empty:
        raise PlanningInputError(f"vector layer must not be empty: {path}")
    if gdf.crs is not None and gdf.crs.to_string() != CRS_WGS84:
        gdf = gdf.to_crs(CRS_WGS84)
    return cast(gpd.GeoDataFrame, gdf)


def _endpoint_from_mapping(row: dict[str, object]) -> RouteEndpoint:
    geometry = row.get("geometry")
    if not isinstance(geometry, Point):
        raise PlanningInputError("endpoint layer geometries must be Point features.")
    role = str(row["role"])
    source_id = str(row.get("source_id", row.get("Index", "")))
    return RouteEndpoint(
        role=role,
        lat=float(geometry.y),
        lng=float(geometry.x),
        source_id=source_id,
    )


def _validate_endpoint_roles(endpoints: list[RouteEndpoint]) -> None:
    roles = [endpoint.role for endpoint in endpoints]
    if roles.count("start") != 1:
        raise PlanningInputError("endpoint layer must contain exactly one start role.")
    if roles.count("goal") != 1:
        raise PlanningInputError("endpoint layer must contain exactly one goal/end role.")


def _single_endpoint(endpoints: list[RouteEndpoint], role: str) -> RouteEndpoint:
    matches = [endpoint for endpoint in endpoints if endpoint.role == role]
    if len(matches) != 1:
        raise PlanningInputError(f"route request must contain exactly one {role} endpoint.")
    return matches[0]


def _load_roi_geometry(path: str) -> BaseGeometry:
    gdf = _read_wgs84_layer(Path(path))
    geometry = cast(BaseGeometry, gdf.geometry.union_all())
    if geometry.is_empty or geometry.area <= 0.0:
        raise GridBuildError("ROI layer must contain non-empty polygonal geometry.")
    return geometry


def _filter_graph_by_roi(graph: H3Graph, roi_geometry: BaseGeometry) -> H3Graph:
    cells = {
        cell_id: cell
        for cell_id, cell in graph.cells.items()
        if roi_geometry.covers(Point(cell.lng, cell.lat))
    }
    if not cells:
        raise GridBuildError("ROI filtering removed all H3 cells.")
    edges = _filtered_edges(graph, set(cells))
    parent_children = _filtered_parent_children(cells)
    return H3Graph(
        resolution_fine=graph.resolution_fine,
        resolution_coarse=graph.resolution_coarse,
        cells=cells,
        edges=edges,
        parent_children=parent_children,
    )


def _filtered_edges(graph: H3Graph, cell_ids: set[str]) -> dict[tuple[str, str], H3Edge]:
    return {
        key: edge
        for key, edge in graph.edges.items()
        if edge.cell_a in cell_ids and edge.cell_b in cell_ids
    }


def _filtered_parent_children(cells: dict[str, H3Cell]) -> dict[str, set[str]]:
    parent_children: dict[str, set[str]] = {}
    for cell_id, cell in cells.items():
        parent_children.setdefault(cell.parent_h3, set()).add(cell_id)
    return parent_children


def _approx_wgs84_area_m2(geometry: BaseGeometry) -> float:
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    mean_lat = radians((min_lat + max_lat) / 2.0)
    meters_per_degree_lng = 111_320.0 * max(cos(mean_lat), 0.01)
    meters_per_degree_lat = 111_320.0
    return float(geometry.area) * meters_per_degree_lng * meters_per_degree_lat


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    first_lat = radians(lat_a)
    second_lat = radians(lat_b)
    root = sin(d_lat / 2.0) ** 2 + cos(first_lat) * cos(second_lat) * sin(d_lng / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * atan2(sqrt(root), sqrt(max(0.0, 1.0 - root)))


def _endpoint_payload(endpoint: RouteEndpoint) -> dict[str, object]:
    return {
        "lat": endpoint.lat,
        "lng": endpoint.lng,
        "role": endpoint.role,
        "source_id": endpoint.source_id,
    }


def _oversize_message(estimated_cells: int, max_cells: int) -> str:
    return (
        f"estimated H3 cell count {estimated_cells} exceeds max_estimated_cells={max_cells}; "
        "shrink ROI, reduce auto corridor buffer, or use parent res9/res8 for coarse planning."
    )
