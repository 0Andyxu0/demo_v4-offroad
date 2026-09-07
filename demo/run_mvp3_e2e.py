"""Run MVP-3 persisted graph planning and GIS export demo."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from math import isfinite
from pathlib import Path
from typing import cast

from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.dynamics import CostFunction, LOSPathSmoother
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    H3Graph,
    PlannerInput,
    PlanningFailedError,
    VehicleProfile,
)
from h3_offroad_planner.models import (
    Path as PlannerPath,
)
from h3_offroad_planner.planners import PlannerFactory

DEFAULT_PARQUET: Path = Path("outputs/nanjing_h3_sample.parquet")
DEFAULT_CONFIG: Path = Path("configs/mvp3_planner.yaml")
DEFAULT_VEHICLE: Path = Path("configs/mvp3_vehicle.yaml")
DEFAULT_OUTPUT_DIR: Path = Path("outputs/mvp3")
RAW_LAYER: str = "raw_path"
REPLANNED_LAYER: str = "replanned_path"
SMOOTHED_LAYER: str = "smoothed_path"


def run_demo(
    parquet_path: str,
    planner_config_path: str,
    vehicle_path: str,
    output_dir: str,
    res_fine: int = 7,
    res_coarse: int = 5,
) -> dict[str, object]:
    """Run persisted H3 graph planning, blockage recovery, smoothing, and GIS export."""
    vehicle = load_vehicle(vehicle_path)
    graph = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse).load_graph(parquet_path)
    planner_config = _planner_config_with_vehicle(planner_config_path, vehicle)
    facade = PlannerFactory.from_config(planner_config)

    start, goal = _select_start_goal(graph, _cost_function(planner_config, vehicle))
    planner_input = PlannerInput(graph=graph, start=start, goal=goal, vehicle=vehicle)
    raw_path = facade.plan(planner_input).paths[0]
    blocked_cell = _select_blocked_cell_for_replan(
        graph,
        raw_path,
        _cost_function(planner_config, vehicle),
    )
    replanned_path = facade.on_blockage(graph, {blocked_cell}, raw_path)
    smoothed_cells = LOSPathSmoother(graph).smooth(replanned_path.cells)
    smoothed_path = PlannerPath(cells=smoothed_cells, total_cost=replanned_path.total_cost)

    outputs = _export_outputs(graph, raw_path, replanned_path, smoothed_path, output_dir)
    manifest = _manifest(
        graph=graph,
        parquet_path=parquet_path,
        planner_config_path=planner_config_path,
        vehicle_path=vehicle_path,
        start=start,
        goal=goal,
        blocked_cell=blocked_cell,
        raw_path=raw_path,
        replanned_path=replanned_path,
        smoothed_path=smoothed_path,
        outputs=outputs,
        res_fine=res_fine,
        res_coarse=res_coarse,
    )
    GISExporter.write_manifest(str(Path(output_dir) / "manifest.json"), manifest)
    return manifest


def _planner_config_with_vehicle(path: str, vehicle: VehicleProfile) -> dict[str, object]:
    planner_config = load_config(path)
    planner_config["_vehicle"] = vehicle
    return planner_config


def _cost_function(config: Mapping[str, object], vehicle: VehicleProfile) -> CostFunction:
    cost_cfg = cast(dict[str, object], config["cost"])
    return CostFunction(
        vehicle=vehicle,
        k_r=float(cost_cfg.get("tri_coefficient", 0.1)),
        gravity_coeff=float(cost_cfg.get("gravity_coefficient", 5.0)),
    )


def _select_start_goal(graph: H3Graph, cost_function: CostFunction) -> tuple[str, str]:
    adjacency = _finite_adjacency(graph, cost_function)
    component = _largest_component(adjacency)
    if len(component) < 3:
        raise PlanningFailedError("no finite connected component with at least three cells.")
    return _farthest_pair(graph, component)


def _select_blocked_cell_for_replan(
    graph: H3Graph,
    raw_path: PlannerPath,
    cost_function: CostFunction,
) -> str:
    if len(raw_path.cells) < 3:
        raise PlanningFailedError("initial path must include at least three cells.")
    adjacency = _finite_adjacency(graph, cost_function)
    for cell_id in _center_first_internal_cells(raw_path.cells):
        if _has_alternate_path(adjacency, raw_path.cells[0], raw_path.cells[-1], cell_id):
            return cell_id
    raise PlanningFailedError("planned path has no internal blockage with an alternate route.")


def _center_first_internal_cells(path_cells: list[str]) -> list[str]:
    center = (len(path_cells) - 1) / 2.0
    indexed = list(enumerate(path_cells[1:-1], start=1))
    return [cell_id for _, cell_id in sorted(indexed, key=lambda item: abs(item[0] - center))]


def _has_alternate_path(
    adjacency: dict[str, set[str]],
    start: str,
    goal: str,
    blocked_cell: str,
) -> bool:
    if start == blocked_cell or goal == blocked_cell:
        return False
    visited: set[str] = {blocked_cell}
    queue: deque[str] = deque([start])
    visited.add(start)
    while queue:
        cell_id = queue.popleft()
        if cell_id == goal:
            return True
        for neighbor in adjacency.get(cell_id, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return False


def _finite_adjacency(graph: H3Graph, cost_function: CostFunction) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {cell_id: set() for cell_id in graph.cells}
    for edge in graph.edges.values():
        if not _edge_cells_passable(graph, edge.cell_a, edge.cell_b):
            continue
        if _finite_bidirectional_cost(graph, cost_function, edge.cell_a, edge.cell_b):
            adjacency[edge.cell_a].add(edge.cell_b)
            adjacency[edge.cell_b].add(edge.cell_a)
    return adjacency


def _edge_cells_passable(graph: H3Graph, first: str, second: str) -> bool:
    return graph.cells[first].is_passable and graph.cells[second].is_passable


def _finite_bidirectional_cost(
    graph: H3Graph,
    cost_function: CostFunction,
    first: str,
    second: str,
) -> bool:
    return isfinite(cost_function.compute(graph, first, second)) and isfinite(
        cost_function.compute(graph, second, first)
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
        raise PlanningFailedError("finite component does not contain a valid start-goal pair.")
    return best_pair


def _squared_lnglat_distance(graph: H3Graph, first: str, second: str) -> float:
    first_cell = graph.cells[first]
    second_cell = graph.cells[second]
    return (first_cell.lng - second_cell.lng) ** 2 + (first_cell.lat - second_cell.lat) ** 2


def _export_outputs(
    graph: H3Graph,
    raw_path: PlannerPath,
    replanned_path: PlannerPath,
    smoothed_path: PlannerPath,
    output_dir: str,
) -> dict[str, object]:
    output_root = Path(output_dir)
    gpkg_path = output_root / "mvp3_e2e.gpkg"
    geojson_paths = {
        RAW_LAYER: output_root / "raw_path.geojson",
        REPLANNED_LAYER: output_root / "replanned_path.geojson",
        SMOOTHED_LAYER: output_root / "smoothed_path.geojson",
    }
    GISExporter.export_graph_gpkg(graph, str(gpkg_path))
    GISExporter.export_path_gpkg(graph, raw_path, str(gpkg_path), RAW_LAYER)
    GISExporter.export_path_gpkg(graph, replanned_path, str(gpkg_path), REPLANNED_LAYER)
    GISExporter.export_path_gpkg(graph, smoothed_path, str(gpkg_path), SMOOTHED_LAYER)
    GISExporter.export_path_geojson(graph, raw_path, str(geojson_paths[RAW_LAYER]))
    GISExporter.export_path_geojson(graph, replanned_path, str(geojson_paths[REPLANNED_LAYER]))
    GISExporter.export_path_geojson(graph, smoothed_path, str(geojson_paths[SMOOTHED_LAYER]))
    return {
        "gpkg": str(gpkg_path),
        "geojson": {name: str(path) for name, path in geojson_paths.items()},
    }


def _manifest(
    graph: H3Graph,
    parquet_path: str,
    planner_config_path: str,
    vehicle_path: str,
    start: str,
    goal: str,
    blocked_cell: str,
    raw_path: PlannerPath,
    replanned_path: PlannerPath,
    smoothed_path: PlannerPath,
    outputs: dict[str, object],
    res_fine: int,
    res_coarse: int,
) -> dict[str, object]:
    return {
        "blocked_cell": blocked_cell,
        "cells_count": len(graph.cells),
        "edges_count": len(graph.edges),
        "goal": goal,
        "input_parquet": parquet_path,
        "output_gpkg": outputs["gpkg"],
        "output_geojsons": outputs["geojson"],
        "planner_config": planner_config_path,
        "raw_path": raw_path.cells,
        "raw_path_length": len(raw_path.cells),
        "replanned_path": replanned_path.cells,
        "replanned_path_length": len(replanned_path.cells),
        "res_coarse": res_coarse,
        "res_fine": res_fine,
        "smoothed_path": smoothed_path.cells,
        "smoothed_path_length": len(smoothed_path.cells),
        "start": start,
        "vehicle_config": vehicle_path,
    }


def main() -> None:
    """Run the default MVP-3 demo and print artifact locations."""
    manifest = run_demo(
        parquet_path=str(DEFAULT_PARQUET),
        planner_config_path=str(DEFAULT_CONFIG),
        vehicle_path=str(DEFAULT_VEHICLE),
        output_dir=str(DEFAULT_OUTPUT_DIR),
    )
    print(
        " ".join(
            [
                f"raw={manifest['raw_path_length']}",
                f"replanned={manifest['replanned_path_length']}",
                f"smoothed={manifest['smoothed_path_length']}",
                f"gpkg={manifest['output_gpkg']}",
            ]
        )
    )


if __name__ == "__main__":
    main()
