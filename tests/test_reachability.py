"""Tests for pre-flight reachability gate."""

from __future__ import annotations

import pytest

from h3_offroad_planner.factor_model import (
    FactorModelConfig,
    evaluate_factor_model,
)
from h3_offroad_planner.models import (
    H3Cell,
    H3Edge,
    H3Graph,
    PlanningFailedError,
    VehicleProfile,
)
from h3_offroad_planner.reachability import check_route_reachability


@pytest.fixture
def vehicle() -> VehicleProfile:
    return VehicleProfile(
        name="test_truck",
        mass_kg=2500.0,
        max_climb_angle_deg=25.0,
        max_speed_kmh=60.0,
        tire_width_m=0.3,
        ground_clearance_m=0.35,
        max_thrust_n=15000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=6.0,
    )


def _connected_graph() -> H3Graph:
    cells = {
        name: H3Cell(
            h3index=name,
            lat=32.0,
            lng=119.0 + 0.001 * index,
            elevation=50.0,
            slope=5.0,
            tri=0.2,
            lc_factor=1.0,
            parent_h3="parent_1",
            is_passable=True,
        )
        for index, name in enumerate(["c1", "c2", "c3", "c4"])
    }
    edges = {
        ("c1", "c2"): H3Edge(cell_a="c1", cell_b="c2", geo_distance=10.0),
        ("c2", "c3"): H3Edge(cell_a="c2", cell_b="c3", geo_distance=10.0),
        ("c3", "c4"): H3Edge(cell_a="c3", cell_b="c4", geo_distance=10.0),
    }
    return H3Graph(cells=cells, edges=edges)


def _disconnected_graph() -> H3Graph:
    # c1-c2 island, c3-c4 island with no connection between them
    cells = {
        name: H3Cell(
            h3index=name,
            lat=32.0,
            lng=119.0 + 0.001 * index,
            elevation=50.0,
            slope=5.0,
            tri=0.2,
            lc_factor=1.0,
            parent_h3="parent_1",
            is_passable=True,
        )
        for index, name in enumerate(["c1", "c2", "c3", "c4"])
    }
    edges = {
        ("c1", "c2"): H3Edge(cell_a="c1", cell_b="c2", geo_distance=10.0),
        ("c3", "c4"): H3Edge(cell_a="c3", cell_b="c4", geo_distance=10.0),
    }
    return H3Graph(cells=cells, edges=edges)


def test_reachability_passes_when_connected(vehicle: VehicleProfile) -> None:
    graph = _connected_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    progress_calls: list[tuple[str, int, str]] = []

    def progress(module: str, pct: int, msg: str) -> None:
        progress_calls.append((module, pct, msg))

    # Should succeed without raising exception
    check_route_reachability(graph, evaluation, "c1", "c4", progress=progress)
    assert not any(msg == "起终点无连通性" for _, _, msg in progress_calls)


def test_reachability_same_start_and_goal(vehicle: VehicleProfile) -> None:
    graph = _connected_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    check_route_reachability(graph, evaluation, "c2", "c2")


def test_reachability_fails_when_start_impassable(vehicle: VehicleProfile) -> None:
    graph = _connected_graph()
    # Mark start cell c1 as water (impassable)
    graph.cells["c1"].landcover_type = "water"
    graph.cells["c1"].lc_factor = float("inf")
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    progress_calls: list[tuple[str, int, str]] = []

    def progress(module: str, pct: int, msg: str) -> None:
        progress_calls.append((module, pct, msg))

    with pytest.raises(PlanningFailedError, match="起终点无连通性"):
        check_route_reachability(graph, evaluation, "c1", "c4", progress=progress)

    assert ("reachability", 0, "起终点无连通性") in progress_calls


def test_reachability_fails_when_goal_impassable(vehicle: VehicleProfile) -> None:
    graph = _connected_graph()
    # Mark goal cell c4 as extreme slope
    graph.cells["c4"].slope = 80.0
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    with pytest.raises(PlanningFailedError, match="起终点无连通性"):
        check_route_reachability(graph, evaluation, "c1", "c4")


def test_reachability_fails_when_graph_disconnected(vehicle: VehicleProfile) -> None:
    graph = _disconnected_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    progress_calls: list[tuple[str, int, str]] = []

    def progress(module: str, pct: int, msg: str) -> None:
        progress_calls.append((module, pct, msg))

    with pytest.raises(PlanningFailedError, match="起终点无连通性"):
        check_route_reachability(graph, evaluation, "c1", "c4", progress=progress)

    assert ("reachability", 0, "起终点无连通性") in progress_calls


def test_reachability_fails_when_start_isolated(vehicle: VehicleProfile) -> None:
    cells = {
        "solo": H3Cell(
            h3index="solo",
            lat=32.0,
            lng=119.0,
            elevation=50.0,
            slope=5.0,
            tri=0.2,
            lc_factor=1.0,
            parent_h3="parent_1",
            is_passable=True,
        ),
        "target": H3Cell(
            h3index="target",
            lat=32.001,
            lng=119.001,
            elevation=50.0,
            slope=5.0,
            tri=0.2,
            lc_factor=1.0,
            parent_h3="parent_1",
            is_passable=True,
        ),
    }
    graph = H3Graph(cells=cells, edges={})
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    with pytest.raises(PlanningFailedError, match="起终点无连通性"):
        check_route_reachability(graph, evaluation, "solo", "target")
