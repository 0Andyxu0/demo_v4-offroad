"""Spec-derived tests for MVP-7 hierarchical PortsMap planning."""

from __future__ import annotations

import pytest

from h3_offroad_planner.dynamics import CostFunction
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, PlannerInput, PlanningFailedError
from h3_offroad_planner.planners import H3AStarPlanner


def make_parent_graph(include_goal: bool = True) -> H3Graph:
    """Create a small parent-partitioned graph with disconnected passable noise."""
    cells = {
        cell_id: H3Cell(
            h3index=cell_id,
            lat=0.0,
            lng=float(index),
            elevation=0.0,
            slope=0.0,
            tri=0.0,
            lc_factor=1.0,
            parent_h3=parent,
        )
        for index, (cell_id, parent) in enumerate(
            [
                ("start", "p0"),
                ("p1_cell", "p1"),
                ("p2_cell", "p2"),
                ("p3_cell", "p3"),
                ("goal", "p4"),
                ("noise_a", "noise_a"),
                ("noise_b", "noise_b"),
            ]
        )
    }
    edges = {
        ("start", "p1_cell"): H3Edge("start", "p1_cell", 1.0),
        ("p1_cell", "p2_cell"): H3Edge("p1_cell", "p2_cell", 1.0),
        ("p2_cell", "p3_cell"): H3Edge("p2_cell", "p3_cell", 1.0),
        ("noise_a", "noise_b"): H3Edge("noise_a", "noise_b", 1.0),
    }
    if include_goal:
        edges[("p3_cell", "goal")] = H3Edge("p3_cell", "goal", 1.0)
    return H3Graph(cells=cells, edges=edges)


def test_t093_ports_map_groups_cross_parent_connectivity(vehicle: object) -> None:
    """T-093: PortsMap records only passable parent-to-parent adjacency."""
    graph = make_parent_graph()
    planner = H3AStarPlanner(CostFunction(vehicle))

    ports_map = planner._build_ports_map(graph)

    assert ports_map["p0"] == {"p1": 1.0}
    assert ports_map["p2"] == {"p1": 1.0, "p3": 1.0}
    assert ports_map["noise_a"] == {"noise_b": 1.0}


def test_t094_macro_astar_returns_intermediate_parent_route(vehicle: object) -> None:
    """T-094: Macro A* returns the complete parent route between endpoints."""
    graph = make_parent_graph()
    planner = H3AStarPlanner(CostFunction(vehicle))

    route = planner._macro_astar(planner._build_ports_map(graph), graph, "start", "goal")

    assert route == ["p0", "p1", "p2", "p3", "p4"]


def test_t095_corridor_is_parent_route_not_full_passable_graph(vehicle: object) -> None:
    """T-095: Zero-dilation corridor excludes unrelated passable parent groups."""
    graph = make_parent_graph()
    planner = H3AStarPlanner(CostFunction(vehicle))

    corridor = planner._extract_corridor(graph, ["p0", "p1", "p2", "p3", "p4"], dilation=0)

    assert {"start", "goal"}.issubset(corridor)
    assert "noise_a" not in corridor
    assert len(corridor) < sum(cell.is_passable for cell in graph.cells.values())


def test_t096_planner_uses_bounded_parent_corridor(vehicle: object) -> None:
    """T-096: Fine A* returns a finite path with smaller corridor metadata."""
    graph = make_parent_graph()
    planner = H3AStarPlanner(CostFunction(vehicle))

    result = planner.plan(PlannerInput(graph=graph, start="start", goal="goal", vehicle=vehicle))

    assert result.paths[0].cells == ["start", "p1_cell", "p2_cell", "p3_cell", "goal"]
    assert result.metadata["corridor_size"] < sum(cell.is_passable for cell in graph.cells.values())


def test_t097_disconnected_parent_route_raises(vehicle: object) -> None:
    """T-097: Macro planning raises when the goal parent is disconnected."""
    graph = make_parent_graph(include_goal=False)
    planner = H3AStarPlanner(CostFunction(vehicle))

    with pytest.raises(PlanningFailedError, match="no passable parent route"):
        planner._macro_astar(planner._build_ports_map(graph), graph, "start", "goal")


def test_t103_ports_map_uses_boundary_physical_cost(vehicle: object) -> None:
    """T-103: Macro graph uses directional crossing cost instead of a constant weight."""
    graph = make_parent_graph()
    graph.edges[("start", "p1_cell")].geo_distance = 7.0
    planner = H3AStarPlanner(CostFunction(vehicle))

    ports_map = planner._build_ports_map(graph)

    assert ports_map["p0"]["p1"] == 7.0
