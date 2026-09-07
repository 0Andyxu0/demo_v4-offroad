"""Run MVP-3.1a route and theme-map smoke with non-adjacent endpoints."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from math import isfinite
from pathlib import Path
from typing import cast

import geopandas as gpd
from shapely.geometry import box

from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.dynamics import CostFunction
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    H3Edge,
    H3Graph,
    PlanningFailedError,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.routing import run_route

DEFAULT_PARQUET: Path = Path("outputs/nanjing_h3_sample.parquet")
DEFAULT_CONFIG: Path = Path("configs/mvp3_planner.yaml")
DEFAULT_VEHICLE: Path = Path("configs/mvp3_vehicle.yaml")
DEFAULT_OUTPUT_DIR: Path = Path("outputs/mvp31")
DEFAULT_ROI: Path = DEFAULT_OUTPUT_DIR / "mvp31a_route_roi.geojson"
RES_FINE: int = 7
RES_COARSE: int = 5
MIN_SMOKE_ROUTE_CELLS: int = 3


def run_route_smoke(
    parquet_path: str = str(DEFAULT_PARQUET),
    planner_config_path: str = str(DEFAULT_CONFIG),
    vehicle_path: str = str(DEFAULT_VEHICLE),
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
    res_fine: int = RES_FINE,
    res_coarse: int = RES_COARSE,
) -> dict[str, object]:
    """Run route planning on the sampled Nanjing cache with distant endpoints."""
    vehicle = load_vehicle(vehicle_path)
    config = load_config(planner_config_path)
    graph = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse).load_graph(parquet_path)
    start, goal = select_distant_endpoint_cells(graph, _cost_function(config, vehicle))
    roi_path = Path(output_dir) / DEFAULT_ROI.name
    _write_roi_layer(roi_path, graph)
    start_cell = graph.cells[start]
    goal_cell = graph.cells[goal]
    request = RouteRequest(
        input_mode="coordinates",
        parquet_path=parquet_path,
        planner_config_path=planner_config_path,
        vehicle_path=vehicle_path,
        output_dir=output_dir,
        start_lat=start_cell.lat,
        start_lng=start_cell.lng,
        goal_lat=goal_cell.lat,
        goal_lng=goal_cell.lng,
        roi_layer_path=str(roi_path),
        res_fine=res_fine,
        res_coarse=res_coarse,
        theme_attributes=[
            "score",
            "cost_score",
            "landcover_type",
            "soil_type",
            "elevation",
            "slope",
            "soil_mobility",
        ],
        max_estimated_cells=50_000_000,
    )
    manifest = run_route(request)
    if int(manifest["planned_path_length"]) < MIN_SMOKE_ROUTE_CELLS:
        raise PlanningFailedError("MVP-3.1a route smoke must not use only adjacent cells.")
    return manifest


def select_distant_endpoint_cells(
    graph: H3Graph,
    cost_function: CostFunction,
) -> tuple[str, str]:
    """Select a non-adjacent start/goal pair from the largest finite component."""
    adjacency = _finite_adjacency(graph, cost_function)
    component = _largest_component(adjacency)
    if len(component) < MIN_SMOKE_ROUTE_CELLS:
        raise PlanningFailedError("no finite component large enough for route smoke.")
    start, goal = _farthest_pair(graph, component)
    if goal in adjacency[start]:
        raise PlanningFailedError("selected route endpoints are adjacent.")
    return start, goal


def _cost_function(config: Mapping[str, object], vehicle: VehicleProfile) -> CostFunction:
    cost_cfg = cast(dict[str, object], config.get("cost", {}))
    return CostFunction(
        vehicle=vehicle,
        k_r=float(cost_cfg.get("tri_coefficient", 0.1)),
        gravity_coeff=float(cost_cfg.get("gravity_coefficient", 5.0)),
        score_coefficient=float(cost_cfg.get("score_coefficient", 0.0)),
    )


def _finite_adjacency(graph: H3Graph, cost_function: CostFunction) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {cell_id: set() for cell_id in graph.cells}
    for edge in graph.edges.values():
        if not _passable_finite_edge(graph, edge, cost_function):
            continue
        adjacency[edge.cell_a].add(edge.cell_b)
        adjacency[edge.cell_b].add(edge.cell_a)
    return adjacency


def _passable_finite_edge(
    graph: H3Graph,
    edge: H3Edge,
    cost_function: CostFunction,
) -> bool:
    first = graph.cells[edge.cell_a]
    second = graph.cells[edge.cell_b]
    return (
        first.is_passable
        and second.is_passable
        and isfinite(cost_function.compute(graph, edge.cell_a, edge.cell_b))
        and isfinite(cost_function.compute(graph, edge.cell_b, edge.cell_a))
    )


def _largest_component(adjacency: dict[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    largest: set[str] = set()
    for cell_id, neighbors in adjacency.items():
        if cell_id in visited or not neighbors:
            continue
        component = _component_from(adjacency, cell_id, visited)
        if len(component) > len(largest):
            largest = component
    return largest


def _component_from(
    adjacency: dict[str, set[str]],
    start: str,
    visited: set[str],
) -> set[str]:
    component: set[str] = set()
    queue: deque[str] = deque([start])
    visited.add(start)
    while queue:
        cell_id = queue.popleft()
        component.add(cell_id)
        for neighbor in adjacency[cell_id]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return component


def _farthest_pair(graph: H3Graph, component: set[str]) -> tuple[str, str]:
    best_pair = ("", "")
    best_distance = -1.0
    ordered = sorted(component)
    for index, first_id in enumerate(ordered[:-1]):
        for second_id in ordered[index + 1 :]:
            distance = _squared_lnglat_distance(graph, first_id, second_id)
            if distance > best_distance:
                best_distance = distance
                best_pair = (first_id, second_id)
    if not best_pair[0]:
        raise PlanningFailedError("finite component does not contain a valid endpoint pair.")
    return best_pair


def _squared_lnglat_distance(graph: H3Graph, first: str, second: str) -> float:
    first_cell = graph.cells[first]
    second_cell = graph.cells[second]
    return (first_cell.lng - second_cell.lng) ** 2 + (first_cell.lat - second_cell.lat) ** 2


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
    """Run the default MVP-3.1a route smoke and print artifact locations."""
    manifest = run_route_smoke()
    print(
        " ".join(
            [
                f"route={manifest['planned_path_length']}",
                f"gpkg={manifest['output_gpkg']}",
                f"style={manifest['style_manifest']}",
                f"source={manifest['source_artifact_kind']}",
            ]
        )
    )


if __name__ == "__main__":
    main()
