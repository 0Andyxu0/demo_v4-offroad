"""Spec-derived tests for physical margins and immutable directed-edge metrics."""

from __future__ import annotations

from dataclasses import replace
from math import log, radians, sin

import pytest

from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.factor_model import (
    FactorModelConfig,
    evaluate_factor_model,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, VehicleProfile


def test_cl001_edge_margin_and_risk_are_hand_calculable(
    vehicle: VehicleProfile,
) -> None:
    """CL-001: edge margin is an unweighted physical minimum and risk is additive."""
    graph = _line_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    edge = evaluation.directed_edges[("a", "b")]
    slope_margin = 1.0 - 5.0 / vehicle.max_climb_angle_deg
    grade_force = vehicle.mass_kg * 9.81 * sin(radians(5.0))
    thrust_margin = 1.0 - grade_force / vehicle.max_thrust_n
    expected = min(1.0, slope_margin, thrust_margin)
    assert edge.safety_margin_lower == pytest.approx(expected)
    assert edge.safety_margin_nominal == pytest.approx(expected)
    assert edge.safety_margin_upper == pytest.approx(expected)
    assert edge.terrain_risk == pytest.approx(10.0 * -log(expected))


def test_cl002_known_soil_margins_and_boundaries_are_enforced(
    vehicle: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CL-002: known cone and sinkage evidence contributes directly to the bottleneck."""
    graph = _line_graph(with_soil=True)

    def enrich_ok(
        _checker: BekkerChecker,
        cell: H3Cell,
        _vehicle: VehicleProfile,
    ) -> None:
        cell.cone_index_kpa = 200.0
        cell.sinkage_m = 0.05
        cell.soil_mobility = 0.8

    monkeypatch.setattr(BekkerChecker, "enrich_cell", enrich_ok)
    config = FactorModelConfig(
        min_cone_index_kpa=100.0,
        max_sinkage_clearance_ratio=0.5,
    )
    evaluation = evaluate_factor_model(graph, vehicle, config)
    assert evaluation.node_metrics["a"].safety_margin.nominal == pytest.approx(0.5)
    assert evaluation.directed_edges[("a", "b")].safety_margin_lower == pytest.approx(0.5)

    def enrich_at_limit(
        _checker: BekkerChecker,
        cell: H3Cell,
        _vehicle: VehicleProfile,
    ) -> None:
        cell.cone_index_kpa = 100.0
        cell.sinkage_m = 0.2

    monkeypatch.setattr(BekkerChecker, "enrich_cell", enrich_at_limit)
    blocked = evaluate_factor_model(graph, vehicle, config)
    assert blocked.node_metrics["a"].is_passable is False
    assert "SINKAGE_CLEARANCE_EXCEEDED" in blocked.node_metrics["a"].reason_codes

    def enrich_weak_soil(
        _checker: BekkerChecker,
        cell: H3Cell,
        _vehicle: VehicleProfile,
    ) -> None:
        cell.cone_index_kpa = 99.0
        cell.sinkage_m = 0.05

    monkeypatch.setattr(BekkerChecker, "enrich_cell", enrich_weak_soil)
    weak_soil = evaluate_factor_model(graph, vehicle, config)
    assert weak_soil.node_metrics["a"].is_passable is False
    assert "CONE_INDEX_INSUFFICIENT" in weak_soil.node_metrics["a"].reason_codes


def test_cl003_missing_evidence_is_not_fabricated(vehicle: VehicleProfile) -> None:
    """CL-003: missing categories lower confidence without creating a score substitute."""
    evaluation = evaluate_factor_model(_line_graph(), vehicle, FactorModelConfig())
    node = evaluation.node_metrics["a"]
    assert node.is_passable is True
    assert node.safety_margin.nominal == pytest.approx(1.0)
    assert node.confidence == pytest.approx(0.5)
    assert node.reason_codes == ("MISSING_LANDCOVER", "MISSING_SOIL")


def test_landcover_code_zero_uses_configured_speed_factor(
    vehicle: VehicleProfile,
) -> None:
    graph = _line_graph()
    for cell in graph.cells.values():
        cell.landcover_code = 0
        cell.landcover_type = "configured-zero"
    evaluation = evaluate_factor_model(
        graph,
        vehicle,
        FactorModelConfig(landcover_speed_by_code={0: 0.9}),
    )

    assert evaluation.node_metrics["a"].landcover.nominal == pytest.approx(0.9)


def test_cl004_hard_water_constraint_removes_incident_edges(
    vehicle: VehicleProfile,
) -> None:
    """CL-004: a water node remains impassable and has no directed incident edge."""
    graph = _line_graph()
    water = graph.cells["b"]
    water.landcover_type = "water"
    water.lc_factor = float("inf")
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    assert evaluation.node_metrics["b"].is_passable is False
    assert evaluation.node_metrics["b"].safety_margin.nominal == 0.0
    assert ("a", "b") not in evaluation.directed_edges
    assert ("b", "a") not in evaluation.directed_edges


def test_cl005_grade_force_is_directional(vehicle: VehicleProfile) -> None:
    """CL-005: insufficient thrust blocks uphill travel but retains the reverse edge."""
    graph = _line_graph()
    normal = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    uphill = normal.directed_edges[("a", "b")]
    downhill = normal.directed_edges[("b", "a")]
    assert uphill.directed_slope_deg == -downhill.directed_slope_deg
    assert uphill.safety_margin_lower < downhill.safety_margin_lower
    assert uphill.eta_s > downhill.eta_s
    assert uphill.terrain_risk > downhill.terrain_risk
    assert uphill.travel_cost > downhill.travel_cost

    weak = replace(vehicle, name="weak", max_thrust_n=1_000.0)
    evaluation = evaluate_factor_model(graph, weak, FactorModelConfig())
    assert ("a", "b") not in evaluation.directed_edges
    assert ("b", "a") in evaluation.directed_edges
    reverse = evaluation.directed_edges[("b", "a")]
    assert reverse.directed_slope_deg == pytest.approx(-5.0)
    assert reverse.safety_margin_lower == pytest.approx(
        1.0 - 5.0 / weak.max_climb_angle_deg
    )


def test_cl005a_slope_limit_boundary_and_excess_are_explicit(
    vehicle: VehicleProfile,
) -> None:
    graph = _line_graph()
    graph.edges[("a", "b")] = H3Edge(
        "a",
        "b",
        10.0,
        slope_a_to_b=30.0,
        slope_b_to_a=-30.0,
    )
    strong = replace(vehicle, name="strong", max_thrust_n=20_000.0)
    config = FactorModelConfig(epsilon=1.0e-6)
    boundary = evaluate_factor_model(graph, strong, config)
    edge = boundary.directed_edges[("a", "b")]
    assert edge.safety_margin_lower == 0.0
    assert edge.terrain_risk == pytest.approx(10.0 * -log(config.epsilon))

    graph.edges[("a", "b")] = replace(
        graph.edges[("a", "b")],
        slope_a_to_b=30.1,
        slope_b_to_a=-30.1,
    )
    excessive = evaluate_factor_model(graph, strong, config)
    assert ("a", "b") not in excessive.directed_edges
    assert ("b", "a") not in excessive.directed_edges


def test_cl006_eta_and_cost_are_exact_directed_edge_sums(
    vehicle: VehicleProfile,
) -> None:
    """CL-006: route metrics are exact sums of cached directed edges."""
    graph = _line_graph()
    config = FactorModelConfig(tri_coefficient=0.1, gravity_coefficient=5.0)
    evaluation = evaluate_factor_model(graph, vehicle, config)
    metrics = evaluate_path_metrics(["a", "b", "c"], evaluation)
    first = evaluation.directed_edges[("a", "b")]
    second = evaluation.directed_edges[("b", "c")]
    expected_first_cost = 10.0 * (1.0 + (5.0 / 30.0) ** 2) + 5.0
    assert first.travel_cost == pytest.approx(expected_first_cost)
    assert metrics.distance_m == pytest.approx(first.distance_m + second.distance_m)
    assert metrics.eta_s == pytest.approx(first.eta_s + second.eta_s)
    assert metrics.terrain_risk == pytest.approx(first.terrain_risk + second.terrain_risk)
    assert metrics.travel_cost == pytest.approx(first.travel_cost + second.travel_cost)


def test_cl007_zero_speed_lower_produces_unbounded_eta(
    vehicle: VehicleProfile,
) -> None:
    """CL-007: a zero lower speed is represented by null ETA upper, never infinity."""
    graph = _line_graph()
    config = FactorModelConfig(
        missing_speed_lower=0.0,
        missing_speed_nominal=0.6,
        missing_speed_upper=0.85,
        speed_floor_ratio=0.0,
    )
    evaluation = evaluate_factor_model(graph, vehicle, config)
    edge = evaluation.directed_edges[("a", "b")]
    assert edge.eta_upper_bounded is False
    assert edge.eta_upper_s is None
    assert evaluate_path_metrics(["a", "b"], evaluation).eta_upper_s is None


def test_cl008_two_vehicles_reuse_static_graph_but_change_eta(
    vehicle: VehicleProfile,
) -> None:
    """CL-008: vehicle-independent facts hash equally while route-time ETA changes."""
    graph = _line_graph()
    faster = replace(vehicle, name="faster", max_speed_kmh=vehicle.max_speed_kmh * 1.5)
    first = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    second = evaluate_factor_model(graph, faster, FactorModelConfig())
    assert first.static_input_hash == second.static_input_hash
    assert first.graph_topology_hash == second.graph_topology_hash
    assert first.vehicle_hash != second.vehicle_hash
    assert first.directed_edges[("a", "b")].eta_s > second.directed_edges[("a", "b")].eta_s


def test_cl039_route_time_evaluation_does_not_mutate_reusable_tile(
    vehicle: VehicleProfile,
) -> None:
    """CL-039: multiple vehicle evaluations leave the shared static Tile unchanged."""
    graph = _line_graph(with_soil=True)
    original_cells = {cell_id: replace(cell) for cell_id, cell in graph.cells.items()}
    original_edges = {edge_id: replace(edge) for edge_id, edge in graph.edges.items()}
    faster = replace(vehicle, name="faster", max_speed_kmh=vehicle.max_speed_kmh * 1.5)

    evaluate_factor_model(graph, vehicle, FactorModelConfig())
    evaluate_factor_model(graph, faster, FactorModelConfig())

    assert graph.cells == original_cells
    assert graph.edges == original_edges


def _line_graph(*, with_soil: bool = False) -> H3Graph:
    cells = {
        name: H3Cell(
            h3index=name,
            lat=0.0,
            lng=float(index),
            elevation=float(index),
            slope=0.0,
            tri=0.0,
            lc_factor=1.0,
            landcover_code=1 if with_soil else None,
            landcover_type="grass" if with_soil else None,
            uscs="CL" if with_soil else None,
            soil_moisture=0.2 if with_soil else None,
            parent_h3="p",
            is_passable=True,
        )
        for index, name in enumerate(("a", "b", "c"))
    }
    edges = {
        ("a", "b"): H3Edge("a", "b", 10.0, slope_a_to_b=5.0, slope_b_to_a=-5.0),
        ("b", "c"): H3Edge("b", "c", 20.0, slope_a_to_b=5.0, slope_b_to_a=-5.0),
    }
    return H3Graph(cells=cells, edges=edges, parent_children={"p": set(cells)})
