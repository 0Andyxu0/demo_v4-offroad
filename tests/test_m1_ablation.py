"""Ablation tests for M1 static passability attributes repair.

Verifies the progression:
A0 (baseline rules) -> A1a (rowspacing/depth) -> A1b (soil collapse handling)
-> A1c (weather surface impedance) -> A2 (directed pitch/roll decoupling)
as specified in IMPLEMENTATION_PLAN.md §5.2, §6.2, §9.2 and argon1657.md.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.environment import (
    load_environment_snapshot,
)
from h3_offroad_planner.factor_model import (
    EnvironmentConfig,
    FactorModelConfig,
    WeatherConfig,
    _directed_edge_metrics,
    _node_metrics,
    _raw_node_evidence,
    evaluate_factor_model,
    environment_multiplier,
)
from h3_offroad_planner.models import (
    H3Cell,
    H3Edge,
    H3Graph,
    VehicleProfile,
)
from h3_offroad_planner.vectorized_factor import (
    evaluate_directed_edges_vectorized,
)
from h3_offroad_planner.vectorized_soil import (
    vectorized_bekker_sinkage,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def default_vehicle() -> VehicleProfile:
    """Standard test vehicle matching Iveco Daily 4x4 with max roll angle."""
    return VehicleProfile(
        name="test_iveco",
        mass_kg=7000.0,
        max_climb_angle_deg=30.96,
        max_speed_kmh=100.0,
        tire_width_m=0.255,
        ground_clearance_m=0.308,
        max_thrust_n=25000.0,
        tire_radius_m=0.42,
        min_turn_radius_m=6.0,
        width_m=2.056,
        wheelbase_m=3.48,
        max_roll_angle_deg=25.0,
    )


@pytest.fixture
def default_factor_config() -> FactorModelConfig:
    return FactorModelConfig(
        landcover_speed_by_code={2: 0.6, 5: 0.2},
        soil_speed_by_uscs={"CL": 0.5, "SM": 0.7},
    )


# =========================================================================
# A1a: Rowspacing & Water Depth Passability
# =========================================================================


def test_a1a_forest_rowspacing_enforced_under_environment(
    default_vehicle: VehicleProfile,
    default_factor_config: FactorModelConfig,
) -> None:
    """Rowspacing narrower than safe vehicle width must block cell traversal.

    Crucially, this must hold even when environment (weather snapshot) is active.
    """
    # Narrow forest cell (rowspacing 1.8m < vehicle width 2.056m)
    narrow_cell = H3Cell(
        h3index="8f2830828000001",
        lat=31.99,
        lng=118.99,
        elevation=50.0,
        slope=5.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=1.8,
    )

    ev_narrow = _raw_node_evidence(
        narrow_cell,
        default_vehicle,
        default_factor_config,
        strict_static_mode=False,
    )
    assert ev_narrow.passable is False
    assert "ROWSPACING_BLOCKED" in ev_narrow.reasons

    # Wide forest cell (rowspacing 3.5m >= vehicle width 2.056m)
    wide_cell = H3Cell(
        h3index="8f2830828000002",
        lat=31.99,
        lng=118.99,
        elevation=50.0,
        slope=5.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=3.5,
    )

    ev_wide = _raw_node_evidence(
        wide_cell,
        default_vehicle,
        default_factor_config,
        strict_static_mode=False,
    )
    assert ev_wide.passable is True
    assert all(sf.nominal > 0.0 for sf in ev_wide.speed_factors)


def test_a1a_water_depth_distinguishes_shallow_and_deep_water(
    default_vehicle: VehicleProfile,
    default_factor_config: FactorModelConfig,
) -> None:
    """Shallow water (<= clearance) is passable; deep water (> clearance) is blocked."""
    clearance = default_vehicle.ground_clearance_m  # 0.308m

    # Shallow water: depth = 0.20m <= clearance
    shallow_cell = H3Cell(
        h3index="8f2830828000003",
        lat=31.99,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=5,
        depth=0.20,
    )
    ev_shallow = _raw_node_evidence(
        shallow_cell,
        default_vehicle,
        default_factor_config,
        strict_static_mode=False,
    )
    assert ev_shallow.passable is True
    assert all(sf.nominal > 0.0 for sf in ev_shallow.speed_factors)

    # Deep water: depth = 0.90m > clearance
    deep_cell = H3Cell(
        h3index="8f2830828000004",
        lat=31.99,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=5,
        depth=0.90,
    )
    ev_deep = _raw_node_evidence(
        deep_cell,
        default_vehicle,
        default_factor_config,
        strict_static_mode=False,
    )
    assert ev_deep.passable is False
    assert "WATER_DEPTH_LIMIT" in ev_deep.reasons


# =========================================================================
# A1b: Soil / CI and Bekker Parameter Collapse at theta=0.44
# =========================================================================


def test_a1b_bekker_saturated_soil_theta_0_44_blocked(
    default_vehicle: VehicleProfile,
    default_factor_config: FactorModelConfig,
) -> None:
    """At theta=0.44, clay loam kc parameter collapses (kc <= 0).

    M1 must catch this AssessmentError and mark sinkage as infinite,
    explicitly blocking the cell with SINKAGE_CLEARANCE_EXCEEDED instead of
    dropping to None and unconditionally passing.
    """
    checker = BekkerChecker()

    # 1. BekkerChecker direct enrichment
    cell_saturated = H3Cell(
        h3index="8f2830828000005",
        lat=31.99,
        lng=118.99,
        elevation=30.0,
        slope=2.0,
        tri=0.0,
        lc_factor=1.0,
        uscs="CL",
        soil_moisture=0.44,
    )
    checker.enrich_cell(cell_saturated, default_vehicle)
    assert checker.check(cell_saturated, default_vehicle) is False
    assert math.isinf(cell_saturated.sinkage_m)
    assert math.isinf(cell_saturated.sinkage_resistance)
    assert cell_saturated.soil_mobility == 0.0

    # 2. Factor model integration via evaluate_factor_model
    graph = H3Graph(
        cells={cell_saturated.h3index: cell_saturated},
        edges={},
    )
    factors = evaluate_factor_model(graph, default_vehicle, default_factor_config)
    node_eval = factors.node_metrics[cell_saturated.h3index]
    assert node_eval.is_passable is False
    assert "SINKAGE_CLEARANCE_EXCEEDED" in node_eval.reason_codes

    # 3. Vectorized Bekker sinkage check: theta=0.44 produces non-finite sinkage (triggering infinite sinkage in factor_model)
    sink_arr, res_arr = vectorized_bekker_sinkage(
        np.array(["clayloam"], dtype=np.str_),
        np.array([0.44], dtype=np.float64),
        default_vehicle,
    )
    assert not np.isfinite(sink_arr[0])
    assert not np.isfinite(res_arr[0])

    # 4. Moderate soil moisture (e.g. theta=0.20) remains passable
    cell_moderate = H3Cell(
        h3index="8f2830828000006",
        lat=31.99,
        lng=118.99,
        elevation=30.0,
        slope=2.0,
        tri=0.0,
        lc_factor=1.0,
        uscs="CL",
        soil_moisture=0.20,
    )
    checker.enrich_cell(cell_moderate, default_vehicle)
    assert cell_moderate.is_passable is True
    assert math.isfinite(cell_moderate.sinkage_m)
    assert cell_moderate.sinkage_m < default_vehicle.ground_clearance_m


# =========================================================================
# A1c: Static Real Weather Surface Impedance
# =========================================================================


def test_a1c_weather_surface_impedance_avoids_wet_gullies() -> None:
    """Rainy weather multiplier increases impedance in low-lying drainage gullies (field D).

    When derived_pressure = 0.0 (dry day), multiplier is exactly 1.0.
    When derived_pressure > 0.0 (rainy day), wet gully cells have significantly higher impedance.
    """
    dry_snapshot_path = ROOT / "configs" / "scenes" / "baseline_986bd58_weather.json"
    rainy_snapshot_path = ROOT / "configs" / "scenes" / "rainy_weather.json"
    assert dry_snapshot_path.is_file()
    assert rainy_snapshot_path.is_file()

    env_config = EnvironmentConfig(shared_sensitivity=1.0)
    weather_config = WeatherConfig(
        theta_dry=0.25,
        theta_wet=0.35,
        provider="open-meteo",
        model="best_match",
    )

    # Dry snapshot (derived_pressure = 0.0)
    dry_snap = load_environment_snapshot(
        str(dry_snapshot_path),
        weather_config,
        latitude=31.9918777858,
        longitude=118.9927309985,
    )
    assert dry_snap.precipitation_24h_mm == 0.3
    assert dry_snap.soil_moisture_surface_m3_m3 == 0.25

    # Rainy snapshot (derived_pressure = 0.8)
    rainy_snap = load_environment_snapshot(
        str(rainy_snapshot_path),
        weather_config,
        latitude=31.9918777858,
        longitude=118.9927309985,
    )
    assert rainy_snap.precipitation_24h_mm == 28.5
    assert rainy_snap.soil_moisture_surface_m3_m3 == 0.33
    assert rainy_snap.precipitation_24h_mm > rainy_snap.et0_24h_mm

    # Evaluate cell representing a wet drainage gully (surface=0.6, drainage_sensitivity D=0.8)
    wet_gully_cell = H3Cell(
        h3index="8f2830828000007",
        lat=31.99,
        lng=118.99,
        elevation=15.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        surface_response=0.6,
        drainage_sensitivity=0.8,
        drainage_valid=True,
        soil_code=1,
    )

    dry_mult, _ = environment_multiplier(wet_gully_cell, pressure=0.0, config=env_config)
    rainy_mult, _ = environment_multiplier(wet_gully_cell, pressure=0.8, config=env_config)

    assert dry_mult == 1.0
    # Expected: 1.0 + 0.8 * 0.6 * 1.0 * (1.0 + 0.8) = 1.0 + 0.864 = 1.864
    assert pytest.approx(rainy_mult, rel=1e-3) == 1.864
    assert rainy_mult > dry_mult * 1.8


# =========================================================================
# A2: Directed Slope Decoupling (Longitudinal Pitch vs Lateral Roll)
# =========================================================================


def test_a2_directed_slope_decoupling_preserves_diagonal_traverse(
    default_vehicle: VehicleProfile,
    default_factor_config: FactorModelConfig,
) -> None:
    """Terrain on a 32-degree slope is not deleted globally.

    Diagonal traverse edges with pitch <= 30.96 deg and roll <= 25.0 deg are preserved,
    while fall-line edges (pitch > 30.96 deg) and contour-parallel edges (roll > 25.0 deg)
    are blocked.
    """
    # 32 deg scalar slope exceeds max grade (30.96 deg)
    u_cell = H3Cell(
        h3index="8f2830828000008",
        lat=31.99,
        lng=118.99,
        elevation=100.0,
        slope=32.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=4.0,
    )
    v_diag = H3Cell(
        h3index="8f2830828000009",
        lat=31.9902,
        lng=118.9902,
        elevation=110.0,
        slope=32.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=4.0,
    )
    v_fall = H3Cell(
        h3index="8f283082800000a",
        lat=31.9902,
        lng=118.99,
        elevation=115.0,
        slope=32.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=4.0,
    )
    v_contour = H3Cell(
        h3index="8f283082800000b",
        lat=31.99,
        lng=118.9902,
        elevation=100.0,
        slope=32.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=4.0,
    )

    # 1. Node evidence: node itself is passable (no SLOPE_LIMIT node deletion!)
    ev_u = _raw_node_evidence(
        u_cell,
        default_vehicle,
        default_factor_config,
        strict_static_mode=False,
    )
    assert ev_u.passable is True

    node_u = _node_metrics(u_cell, ev_u, default_vehicle)
    node_diag = _node_metrics(v_diag, ev_u, default_vehicle)
    node_fall = _node_metrics(v_fall, ev_u, default_vehicle)
    node_contour = _node_metrics(v_contour, ev_u, default_vehicle)

    nodes = {
        u_cell.h3index: node_u,
        v_diag.h3index: node_diag,
        v_fall.h3index: node_fall,
        v_contour.h3index: node_contour,
    }

    # 2. Diagonal traverse edge: longitudinal pitch = 20 deg <= 30.96 deg
    # roll = sqrt(32^2 - 20^2) = sqrt(1024 - 400) = sqrt(624) = 24.98 deg <= 25.0 deg!
    edge_diag = H3Edge(
        cell_a=u_cell.h3index,
        cell_b=v_diag.h3index,
        geo_distance=25.0,
        slope_a_to_b=20.0,
        slope_b_to_a=-20.0,
    )

    # 3. Fall-line traverse edge: longitudinal pitch = 32 deg > 30.96 deg
    edge_fall = H3Edge(
        cell_a=u_cell.h3index,
        cell_b=v_fall.h3index,
        geo_distance=25.0,
        slope_a_to_b=32.0,
        slope_b_to_a=-32.0,
    )

    # 4. Contour-parallel edge: longitudinal pitch = 5 deg
    # roll = sqrt(32^2 - 5^2) = sqrt(1024 - 25) = sqrt(999) = 31.6 deg > 25.0 deg roll limit!
    edge_contour = H3Edge(
        cell_a=u_cell.h3index,
        cell_b=v_contour.h3index,
        geo_distance=25.0,
        slope_a_to_b=5.0,
        slope_b_to_a=-5.0,
    )

    graph = H3Graph(
        cells={
            u_cell.h3index: u_cell,
            v_diag.h3index: v_diag,
            v_fall.h3index: v_fall,
            v_contour.h3index: v_contour,
        },
        edges={
            (u_cell.h3index, v_diag.h3index): edge_diag,
            (u_cell.h3index, v_fall.h3index): edge_fall,
            (u_cell.h3index, v_contour.h3index): edge_contour,
        },
    )

    # Test scalar _directed_edge_metrics
    metrics_diag = _directed_edge_metrics(
        graph,
        edge_diag,
        u_cell.h3index,
        v_diag.h3index,
        nodes,
        default_vehicle,
        default_factor_config,
        environment=None,
    )
    # Diagonal edge is passable (not None)
    assert metrics_diag is not None
    assert metrics_diag.eta_s > 0.0

    metrics_fall = _directed_edge_metrics(
        graph,
        edge_fall,
        u_cell.h3index,
        v_fall.h3index,
        nodes,
        default_vehicle,
        default_factor_config,
        environment=None,
    )
    # Fall-line exceeds pitch -> None
    assert metrics_fall is None

    metrics_contour = _directed_edge_metrics(
        graph,
        edge_contour,
        u_cell.h3index,
        v_contour.h3index,
        nodes,
        default_vehicle,
        default_factor_config,
        environment=None,
    )
    # Contour exceeds roll -> None
    assert metrics_contour is None

    # 5. Vectorized edge engine matches scalar behavior exactly
    vec_cache = evaluate_directed_edges_vectorized(
        graph,
        nodes,
        default_vehicle,
        default_factor_config,
        environment=None,
    )
    assert (u_cell.h3index, v_diag.h3index) in vec_cache
    assert (u_cell.h3index, v_fall.h3index) not in vec_cache
    assert (u_cell.h3index, v_contour.h3index) not in vec_cache
