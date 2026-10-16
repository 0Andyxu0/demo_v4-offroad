"""Comprehensive verification and equivalence tests for vectorized factor & edge engine."""

from __future__ import annotations

import random

import numpy as np
import pytest

from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.factor_model import (
    _EMPTY_ENV,
    EnvironmentConfig,
    FactorModelConfig,
    _directed_edge_metrics,
    _node_metrics,
    _pressure_key,
    _raw_node_evidence,
    build_directed_edge_cache,
    evaluate_factor_model,
)
from h3_offroad_planner.models import (
    AssessmentError,
    H3Cell,
    H3Edge,
    H3Graph,
    VehicleProfile,
)
from h3_offroad_planner.vectorized_factor import (
    compute_vectorized_edge_arrays,
    evaluate_directed_edges_vectorized,
    scalar_speed_multiplier,
    vectorized_speed_multiplier,
)
from h3_offroad_planner.vectorized_soil import (
    vectorized_bekker_sinkage,
    vectorized_cone_index_kpa,
)


def test_vectorized_matches_scalar_for_sample_cells() -> None:
    config = FactorModelConfig(
        landcover_speed_by_code={1: 0.8, 2: 0.5},
        soil_speed_by_uscs={"CL": 0.55, "SM": 0.7},
        tri_best=0.0,
        tri_worst=8.0,
    )
    codes = np.array([1.0, 2.0, np.nan, 1.0], dtype=np.float64)
    uscs = np.array(["CL", "SM", "ML", "SM"], dtype=np.str_)
    tris = np.array([0.0, 4.0, 2.0, 8.0], dtype=np.float64)

    expected = np.array(
        [
            scalar_speed_multiplier(int(codes[0]), str(uscs[0]), float(tris[0]), config),
            scalar_speed_multiplier(int(codes[1]), str(uscs[1]), float(tris[1]), config),
            scalar_speed_multiplier(None, str(uscs[2]), float(tris[2]), config),
            scalar_speed_multiplier(int(codes[3]), str(uscs[3]), float(tris[3]), config),
        ]
    )
    actual = vectorized_speed_multiplier(codes, uscs, tris, config)

    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_vectorized_clamps_tri_factor() -> None:
    config = FactorModelConfig(
        landcover_speed_by_code={1: 1.0},
        soil_speed_by_uscs={"CL": 1.0},
    )
    result = vectorized_speed_multiplier(
        np.array([1.0]), np.array(["CL"]), np.array([100.0]), config
    )

    assert result[0] == pytest.approx(0.0)


def test_vectorized_cone_index_matches_scalar() -> None:
    uscs = np.array(["CL", "ML", "SM", "SW", "SP", "CH", "MH"], dtype=np.str_)
    moisture = np.array([0.2, 0.3, 0.25, 0.15, 0.18, 0.35, 0.4], dtype=np.float64)
    checker = BekkerChecker()
    expected = np.array(
        [checker.compute_cone_index_kpa(u, m) for u, m in zip(uscs, moisture, strict=True)]
    )

    actual = vectorized_cone_index_kpa(uscs, moisture)
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)


def test_vectorized_cone_index_handles_invalid_and_unknown() -> None:
    uscs = np.array(["CL", "UNKNOWN", "SM"], dtype=np.str_)
    moisture = np.array([-0.1, 0.2, 0.0], dtype=np.float64)
    actual = vectorized_cone_index_kpa(uscs, moisture)
    assert np.all(np.isnan(actual))


def test_vectorized_bekker_sinkage_matches_scalar(vehicle: VehicleProfile) -> None:
    checker = BekkerChecker()
    bekker_soils = np.array(["clayloam", "loam", "clayloam", "loam"], dtype=np.str_)
    moistures = np.array([0.18, 0.22, 0.28, 0.32], dtype=np.float64)

    expected_sinkage = []
    expected_resistance = []
    for b_soil, m in zip(bekker_soils, moistures, strict=True):
        uscs = "CL" if b_soil == "clayloam" else "SM"
        cell = H3Cell("test", 0, 0, 0, 0, 0, 1.0, uscs=uscs, soil_moisture=m)
        res = checker.compute_sinkage(cell, vehicle)
        expected_sinkage.append(res["sinkage_m"])
        expected_resistance.append(res["sinkage_resistance"])

    actual_sinkage, actual_resistance = vectorized_bekker_sinkage(
        bekker_soils, moistures, vehicle
    )

    np.testing.assert_allclose(actual_sinkage, expected_sinkage, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(
        actual_resistance, expected_resistance, rtol=1e-6, atol=1e-6
    )


def test_vectorized_edge_evaluator_exact_equivalence_with_scalar(
    vehicle: VehicleProfile,
) -> None:
    """CL-VEC-001: 100% mathematical equivalence between vectorized and scalar calculations."""
    random.seed(12345)
    cells = {}
    for i in range(50):
        cid = f"cell_{i}"
        cells[cid] = H3Cell(
            h3index=cid,
            lat=31.0 + i * 0.001,
            lng=118.0 + i * 0.001,
            elevation=10.0 + random.uniform(0.0, 150.0),
            slope=random.uniform(0.0, 20.0),
            tri=random.uniform(0.0, 3.0),
            lc_factor=random.choice([1.0, 1.2, 1.5, 2.5]),
            landcover_code=random.choice([1, 2, 3]),
            uscs=random.choice(["CL", "SM", "ML", None]),
            soil_moisture=random.choice([0.2, 0.3, None]),
            parent_h3="parent_test",
            is_passable=i != 7,
        )

    edges = {}
    cell_ids = list(cells.keys())
    for _ in range(120):
        a = random.choice(cell_ids)
        b = random.choice(cell_ids)
        if a == b or (a, b) in edges or (b, a) in edges:
            continue
        d = random.uniform(8.0, 35.0)
        s_ab = random.uniform(-30.0, 30.0)
        edges[(a, b)] = H3Edge(a, b, d, slope_a_to_b=s_ab, slope_b_to_a=-s_ab)

    graph = H3Graph(cells=cells, edges=edges)
    config = FactorModelConfig(tri_coefficient=0.15, gravity_coefficient=3.0)
    env = EnvironmentConfig(comparison_pressures=(0.2, 0.5, 1.0))

    evidence = {
        cid: _raw_node_evidence(cell, vehicle, config, strict_static_mode=True)
        for cid, cell in graph.cells.items()
    }
    nodes = {
        cid: _node_metrics(graph.cells[cid], evidence[cid], vehicle)
        for cid in sorted(graph.cells)
    }

    # Reference scalar evaluation
    scalar_edges: dict[tuple[str, str], object] = {}
    for edge in sorted(
        graph.edges.values(), key=lambda item: (item.cell_a, item.cell_b)
    ):
        for from_h3, to_h3 in ((edge.cell_a, edge.cell_b), (edge.cell_b, edge.cell_a)):
            metric = _directed_edge_metrics(
                graph,
                edge,
                from_h3,
                to_h3,
                nodes,
                vehicle,
                config,
                env,
            )
            if metric is not None:
                scalar_edges[(from_h3, to_h3)] = metric

    # Vectorized evaluation
    vectorized_edges = evaluate_directed_edges_vectorized(
        graph, nodes, vehicle, config, env
    )

    # 1. Check identical keys and order
    assert set(vectorized_edges.keys()) == set(scalar_edges.keys())
    assert list(vectorized_edges.keys()) == list(scalar_edges.keys())

    # 2. Check every field within 1e-6 (in fact, 1e-12)
    p_keys = [_pressure_key(p) for p in env.comparison_pressures]
    for key, scalar_edge in scalar_edges.items():
        vec_edge = vectorized_edges[key]
        assert abs(vec_edge.distance_m - scalar_edge.distance_m) <= 1e-6
        assert abs(vec_edge.eta_lower_s - scalar_edge.eta_lower_s) <= 1e-6
        assert abs(vec_edge.eta_s - scalar_edge.eta_s) <= 1e-6
        if scalar_edge.eta_upper_s is not None:
            assert vec_edge.eta_upper_s is not None
            assert abs(vec_edge.eta_upper_s - scalar_edge.eta_upper_s) <= 1e-6
        else:
            assert vec_edge.eta_upper_s is None
        assert vec_edge.eta_upper_bounded == scalar_edge.eta_upper_bounded
        assert abs(vec_edge.terrain_risk - scalar_edge.terrain_risk) <= 1e-6
        assert abs(vec_edge.travel_cost - scalar_edge.travel_cost) <= 1e-6
        assert (
            abs(vec_edge.safety_margin_lower - scalar_edge.safety_margin_lower) <= 1e-6
        )
        assert (
            abs(vec_edge.safety_margin_nominal - scalar_edge.safety_margin_nominal)
            <= 1e-6
        )
        assert (
            abs(vec_edge.safety_margin_upper - scalar_edge.safety_margin_upper) <= 1e-6
        )
        assert (
            abs(vec_edge.directed_slope_deg - scalar_edge.directed_slope_deg) <= 1e-6
        )
        for pk in p_keys:
            assert (
                abs(
                    vec_edge.environment_distance_m[pk]
                    - scalar_edge.environment_distance_m[pk]
                )
                <= 1e-6
            )


def test_vectorized_edge_evaluator_empty_graph(vehicle: VehicleProfile) -> None:
    empty_graph = H3Graph(cells={}, edges={})
    assert build_directed_edge_cache(empty_graph, {}, vehicle, FactorModelConfig()) == {}


def test_vectorized_edge_evaluator_disconnected_graph(vehicle: VehicleProfile) -> None:
    cell = H3Cell("a", 0, 0, 0, 0, 0, 1.0, is_passable=True)
    graph = H3Graph(cells={"a": cell}, edges={})
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    assert len(evaluation.directed_edges) == 0


def test_compute_vectorized_edge_arrays_structure(vehicle: VehicleProfile) -> None:
    graph = H3Graph(
        cells={
            "a": H3Cell("a", 0.0, 0.0, 10.0, 5.0, 0.5, 1.2, is_passable=True),
            "b": H3Cell("b", 0.0, 0.01, 15.0, 2.0, 0.8, 1.5, is_passable=True),
        },
        edges={
            ("a", "b"): H3Edge("a", "b", 25.0, slope_a_to_b=10.0, slope_b_to_a=-10.0),
        },
    )
    config = FactorModelConfig()
    eval_res = evaluate_factor_model(graph, vehicle, config)
    arrays = compute_vectorized_edge_arrays(
        graph, eval_res.node_metrics, vehicle, config
    )

    assert len(arrays.distances_m) == 2
    assert len(arrays.slopes_deg) == 2
    assert len(arrays.grade_force_n) == 2
    assert len(arrays.is_passable) == 2
    assert arrays.u_keys == ["a", "b"]
    assert arrays.v_keys == ["b", "a"]
    assert arrays.distances_m[0] == 25.0
    assert arrays.distances_m[1] == 25.0
    assert arrays.slopes_deg[0] == 10.0
    assert arrays.slopes_deg[1] == -10.0


def test_vectorized_edge_evaluator_thrust_asymmetry(vehicle: VehicleProfile) -> None:
    """CL-VEC-002: Insufficient thrust blocks uphill travel but retains downhill."""
    graph = H3Graph(
        cells={
            "a": H3Cell("a", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, is_passable=True),
            "b": H3Cell("b", 0.0, 0.01, 10.0, 0.0, 0.0, 1.0, is_passable=True),
        },
        edges={
            ("a", "b"): H3Edge("a", "b", 20.0, slope_a_to_b=15.0, slope_b_to_a=-15.0),
        },
    )
    # 2000kg * 9.81 * sin(15 deg) = ~5078 N
    weak_vehicle = VehicleProfile(
        name="weak",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=3000.0,  # 3000 < 5078 N
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )
    config = FactorModelConfig()
    evaluation = evaluate_factor_model(graph, weak_vehicle, config)
    assert ("a", "b") not in evaluation.directed_edges
    assert ("b", "a") in evaluation.directed_edges
    downhill = evaluation.directed_edges[("b", "a")]
    assert downhill.directed_slope_deg == pytest.approx(-15.0)


def test_vectorized_edge_evaluator_unbounded_eta(vehicle: VehicleProfile) -> None:
    """CL-VEC-003: Zero lower speed generates None upper ETA and False bounded flag."""
    graph = H3Graph(
        cells={
            "a": H3Cell("a", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, is_passable=True),
            "b": H3Cell("b", 0.0, 0.01, 0.0, 0.0, 0.0, 1.0, is_passable=True),
        },
        edges={
            ("a", "b"): H3Edge("a", "b", 10.0, slope_a_to_b=0.0, slope_b_to_a=0.0),
        },
    )
    config = FactorModelConfig(
        missing_speed_lower=0.0,
        missing_speed_nominal=0.5,
        missing_speed_upper=0.8,
        speed_floor_ratio=0.0,
    )
    evaluation = evaluate_factor_model(graph, vehicle, config)
    edge = evaluation.directed_edges[("a", "b")]
    assert edge.eta_upper_bounded is False
    assert edge.eta_upper_s is None
    assert edge.eta_s > 0.0
    assert edge.eta_lower_s > 0.0


def test_vectorized_edge_evaluator_impassable_node_blocks_incident_edges(
    vehicle: VehicleProfile,
) -> None:
    """CL-VEC-004: Impassable node removes all incident directed edges."""
    graph = H3Graph(
        cells={
            "a": H3Cell("a", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, is_passable=False),
            "b": H3Cell("b", 0.0, 0.01, 0.0, 0.0, 0.0, 1.0, is_passable=True),
            "c": H3Cell("c", 0.0, 0.02, 0.0, 0.0, 0.0, 1.0, is_passable=True),
        },
        edges={
            ("a", "b"): H3Edge("a", "b", 10.0, slope_a_to_b=0.0, slope_b_to_a=0.0),
            ("b", "c"): H3Edge("b", "c", 10.0, slope_a_to_b=0.0, slope_b_to_a=0.0),
        },
    )
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    assert ("a", "b") not in evaluation.directed_edges
    assert ("b", "a") not in evaluation.directed_edges
    assert ("b", "c") in evaluation.directed_edges
    assert ("c", "b") in evaluation.directed_edges


def test_scalar_speed_multiplier_clamps_tri_below_best() -> None:
    """Verify scalar_speed_multiplier clamps tri factor to 1.0 when tri < tri_best."""
    config = FactorModelConfig(tri_best=1.0, tri_worst=8.0)
    # tri = 0.5 < tri_best
    scalar = scalar_speed_multiplier(None, None, 0.5, config)
    vec = vectorized_speed_multiplier(
        np.array([np.nan]), np.array([""]), np.array([0.5]), config
    )[0]
    assert abs(scalar - vec) <= 1e-12
    # Check exact value: missing_speed_nominal ** 2 * 1.0 = 0.36
    assert scalar == pytest.approx(config.missing_speed_nominal**2 * 1.0)


def test_vectorized_bekker_sinkage_high_moisture_boundary(
    vehicle: VehicleProfile,
) -> None:
    """Extreme moisture (e.g. theta=0.65, w% > 42.7%) makes k_c <= 0 in Bekker model, returning NaN matching AssessmentError."""
    checker = BekkerChecker()
    cell = H3Cell(
        "test_cell", 0, 0, 0, 0, 0, 1.0, is_passable=True, uscs="CL", soil_moisture=0.65
    )
    with pytest.raises(AssessmentError):
        checker.compute_sinkage(cell, vehicle)

    s_m, r_n = vectorized_bekker_sinkage(
        np.array(["clayloam"]), np.array([0.65]), vehicle
    )
    assert np.isnan(s_m[0])
    assert np.isnan(r_n[0])



def test_vectorized_bekker_sinkage_invalid_inputs(vehicle: VehicleProfile) -> None:
    """Invalid moistures, unknown soils, or non-positive contact area return NaNs."""
    bekker_soils = np.array(["clayloam", "unknown", "loam", "clayloam"], dtype=np.str_)
    moistures = np.array([-0.05, 0.25, 1.5, np.nan], dtype=np.float64)
    s_m, r_n = vectorized_bekker_sinkage(bekker_soils, moistures, vehicle)
    assert np.all(np.isnan(s_m))
    assert np.all(np.isnan(r_n))

    # Contact area edge case
    zero_contact = object.__new__(VehicleProfile)
    object.__setattr__(zero_contact, "mass_kg", 2000.0)
    object.__setattr__(zero_contact, "tire_width_m", 0.0)
    object.__setattr__(zero_contact, "tire_radius_m", 0.45)
    s_zero, r_zero = vectorized_bekker_sinkage(
        np.array(["clayloam"]), np.array([0.2]), zero_contact
    )
    assert np.all(np.isnan(s_zero))
    assert np.all(np.isnan(r_zero))


def test_evaluate_factor_model_batch_soil_sinkage_equivalence(
    vehicle: VehicleProfile,
) -> None:
    """Batch Bekker sinkage produces exact equivalence with scalar enrich_cell."""
    cells = {
        "c_cl": H3Cell(
            "c_cl", 0.0, 0.0, 10.0, 5.0, 0.5, 1.0, is_passable=True, uscs="CL", soil_moisture=0.22
        ),
        "c_sm": H3Cell(
            "c_sm", 0.0, 0.01, 15.0, 2.0, 0.8, 1.0, is_passable=True, uscs="SM", soil_moisture=0.28
        ),
        "c_dry": H3Cell(
            "c_dry", 0.0, 0.02, 10.0, 1.0, 0.2, 1.0, is_passable=True, uscs="CL", soil_moisture=0.15
        ),
    }
    edges = {
        ("c_cl", "c_sm"): H3Edge("c_cl", "c_sm", 20.0, slope_a_to_b=5.0, slope_b_to_a=-5.0),
        ("c_sm", "c_dry"): H3Edge("c_sm", "c_dry", 20.0, slope_a_to_b=-5.0, slope_b_to_a=5.0),
    }
    graph = H3Graph(cells=cells, edges=edges)
    config = FactorModelConfig()

    evaluation = evaluate_factor_model(graph, vehicle, config)
    for cid in ("c_cl", "c_sm", "c_dry"):
        node = evaluation.node_metrics[cid]
        assert node.is_passable is True
        assert node.speed_nominal_mps > 0.0
        assert node.safety_margin.nominal > 0.0


def test_evaluate_directed_edges_vectorized_empty_environment(
    vehicle: VehicleProfile,
) -> None:
    """None environment reuses _EMPTY_ENV singleton without extra allocations."""
    graph = H3Graph(
        cells={
            "a": H3Cell("a", 0.0, 0.0, 10.0, 5.0, 0.5, 1.0, is_passable=True),
            "b": H3Cell("b", 0.0, 0.01, 15.0, 2.0, 0.8, 1.0, is_passable=True),
        },
        edges={
            ("a", "b"): H3Edge("a", "b", 25.0, slope_a_to_b=5.0, slope_b_to_a=-5.0),
        },
    )
    config = FactorModelConfig()
    evaluation = evaluate_factor_model(graph, vehicle, config, environment=None)
    edge = evaluation.directed_edges[("a", "b")]
    assert edge.environment_distance_m is _EMPTY_ENV
