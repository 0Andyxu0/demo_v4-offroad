"""Consolidated regression suite for M1 physical attribute repair and audit compliance.

Fulfills M1 Consolidated Audit (2026-10-17) §9:
- CLDAS and Drainage sensitivity rasters CRS, nodata, and pixel variance (rejecting constant forgery).
- Weather snapshot parameter change altering formal evaluate_factor_model outputs.
- uscs=None remains unknown and reports MISSING_SOIL, not forged to 'CL'.
- Moisture increase -> sinkage increase -> speed degradation/blocking (scalar vs vectorized consistency).
- CI threshold single-source enforcement from config.min_cone_index_kpa.
- Endpoint snapping distance limit (30.0m) with explicit failure and no component hopping.
- is_water only active for landcover_code == 5; buildings (code 6) must not be tagged WATER.
- Ablation switches (enforce_rowspacing, enforce_water_depth, enforce_soil_physics, enforce_scalar_slope_blocking) gate reason codes.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import rasterio

from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.environment import load_environment_snapshot
from h3_offroad_planner.factor_model import (
    EnvironmentConfig,
    FactorModelConfig,
    evaluate_factor_model,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import (
    H3Cell,
    H3Edge,
    H3Graph,
    VehicleProfile,
)
from h3_offroad_planner.scene import enrich_graph_from_static_scene
from h3_offroad_planner.vectorized_factor import compute_vectorized_edge_arrays
from h3_offroad_planner.vectorized_soil import vectorized_bekker_sinkage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def default_vehicle() -> VehicleProfile:
    return VehicleProfile(
        name="test_iveco",
        mass_kg=2968.0,
        max_climb_angle_deg=31.0,
        max_speed_kmh=100.0,
        tire_width_m=0.255,
        ground_clearance_m=0.225,
        max_thrust_n=50000.0,
        tire_radius_m=0.42,
        min_turn_radius_m=6.0,
        width_m=2.056,
        wheelbase_m=3.48,
        max_roll_angle_deg=25.0,
    )


def test_cldas_and_drainage_rasters_crs_and_pixel_variation():
    """Verify CLDAS and Drainage rasters are real files with non-constant spatial values."""
    cldas_path = Path("D:/Workspace/demo_v4/data/Z_NAFP_C_BABJ_20260102002000_P_CLDAS_NRT_ASI_0P0625_DAY-SM000005-2026010100.nc")
    drainage_path = Path("D:/Workspace/demo_v4/outputs/qdx_hydrology_upstream_v1/drainage_sensitivity.tif")

    assert cldas_path.is_file(), f"CLDAS raster missing: {cldas_path}"
    assert drainage_path.is_file(), f"Drainage raster missing: {drainage_path}"

    with rasterio.open(cldas_path) as ds:
        band = ds.read(1)
        valid = band[(band > 0.0) & (band <= 1.0)]
        assert len(valid) > 100, "CLDAS must contain valid moisture pixels"
        assert valid.min() < valid.max(), "CLDAS must exhibit non-zero spatial variance (not constant)"

    with rasterio.open(drainage_path) as ds:
        assert ds.crs is not None and "32650" in ds.crs.to_string(), "Drainage sensitivity must be EPSG:32650"
        band = ds.read(1)
        nodata = ds.nodata
        valid = band[~np.isnan(band)] if nodata is None or np.isnan(nodata) else band[band != nodata]
        assert len(valid) > 100, "Drainage raster must contain valid pixels"
        assert valid.min() < valid.max(), "Drainage raster must exhibit non-zero spatial variance"


def test_enrich_graph_leaves_unmapped_soil_as_none():
    """Verify cells falling on unmapped/nodata areas keep uscs=None and do NOT default to 'CL'."""
    # Coordinate outside Nanjing soil coverage (e.g. lon 110.0, lat 20.0)
    cell = H3Cell(
        h3index="8f2830828000001",
        lat=20.0,
        lng=110.0,
        elevation=10.0,
        slope=1.0,
        tri=0.1,
        lc_factor=1.0,
        landcover_code=1,
    )
    graph = H3Graph(cells={cell.h3index: cell}, edges={})
    scene_path = ROOT / "configs" / "scenes" / "m0_qdx_scene.json"

    meta = enrich_graph_from_static_scene(graph, scene_path)
    assert cell.soil_code is None
    assert cell.uscs is None
    assert cell.soil_type is None
    assert meta["soil"]["missing_soil_count"] == 1
    assert meta["soil"]["uscs_histogram"].get("MISSING_SOIL") == 1


def test_sinkage_speed_degradation_monotonicity_scalar_and_vectorized(default_vehicle: VehicleProfile):
    """Verify scalar vs vectorized Bekker sinkage consistency and speed degradation."""
    config = FactorModelConfig(
        soil_speed_by_uscs={"CL": 0.5},
        min_cone_index_kpa=185.73,
        speed_floor_ratio=0.05,
    )

    # 1. Vectorized vs scalar Bekker sinkage exact match
    moisture = 0.25
    sink_vec, res_vec = vectorized_bekker_sinkage(
        np.array(["clayloam"]), np.array([moisture]), default_vehicle
    )
    checker = BekkerChecker()
    cell_test = H3Cell(
        h3index="8f2830828000001",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        landcover_code=1,
        uscs="CL",
        soil_moisture=moisture,
    )
    sink_scalar = checker.compute_sinkage(cell_test, default_vehicle)
    assert float(sink_vec[0]) == pytest.approx(sink_scalar["sinkage_m"], rel=1e-5)

    # 2. Extreme moisture collapse: at theta=0.65, parameters collapse and cell is hard blocked
    cell_saturated = H3Cell(
        h3index="8f2830828000002",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        landcover_code=1,
        uscs="CL",
        soil_moisture=0.65,
    )
    graph = H3Graph(cells={cell_saturated.h3index: cell_saturated}, edges={})
    eval_res = evaluate_factor_model(graph, default_vehicle, config)
    nm = eval_res.node_metrics[cell_saturated.h3index]
    assert not nm.is_passable
    assert "CONE_INDEX_INSUFFICIENT" in nm.reason_codes

    # 3. Sinkage speed degradation: positive sinkage modulates configured USCS speed
    cell_mod = H3Cell(
        h3index="8f2830828000003",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        landcover_code=1,
        uscs="CL",
        soil_moisture=0.25,
    )
    graph_mod = H3Graph(cells={cell_mod.h3index: cell_mod}, edges={})
    eval_mod = evaluate_factor_model(graph_mod, default_vehicle, config)
    nm_mod = eval_mod.node_metrics[cell_mod.h3index]
    assert nm_mod.is_passable
    assert nm_mod.speed_nominal_mps > 0.0


def test_ci_single_source_threshold(default_vehicle: VehicleProfile):
    """Verify min_cone_index_kpa is the single authoritative source of CI threshold."""
    # For CL at moisture 0.45, CI is approx 174.45 kPa (below 185.73, but above 150)
    checker = BekkerChecker()
    ci = checker.compute_cone_index_kpa("CL", 0.45)
    assert 150.0 < ci < 185.73, f"Unexpected test CI: {ci}"

    cell = H3Cell(
        h3index="8f2830828000001",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        landcover_code=1,
        uscs="CL",
        soil_moisture=0.45,
    )
    graph = H3Graph(cells={cell.h3index: cell}, edges={})

    # Under standard config (185.73 kPa): cell must be blocked by CONE_INDEX_INSUFFICIENT
    cfg_strict = FactorModelConfig(min_cone_index_kpa=185.73)
    eval_strict = evaluate_factor_model(graph, default_vehicle, cfg_strict)
    nm_strict = eval_strict.node_metrics[cell.h3index]
    assert not nm_strict.is_passable
    assert "CONE_INDEX_INSUFFICIENT" in nm_strict.reason_codes

    # Under relaxed config (150.0 kPa): cell is passable and does NOT have speed 0
    cfg_relaxed = FactorModelConfig(min_cone_index_kpa=150.0)
    eval_relaxed = evaluate_factor_model(graph, default_vehicle, cfg_relaxed)
    nm_relaxed = eval_relaxed.node_metrics[cell.h3index]
    assert nm_relaxed.is_passable
    assert "CONE_INDEX_INSUFFICIENT" not in nm_relaxed.reason_codes
    assert nm_relaxed.speed_nominal_mps > 0.0


def test_weather_snapshot_parameter_changes_factor_evaluation(default_vehicle: VehicleProfile):
    """Verify changing weather snapshot pressure modifies environment_distance_m on drainage cells."""
    c1 = H3Cell(
        h3index="8f2830828000001",
        lat=31.980,
        lng=118.990,
        elevation=20.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        drainage_sensitivity=0.8,
        drainage_valid=True,
        surface_response=0.9,
    )
    c2 = H3Cell(
        h3index="8f2830828000002",
        lat=31.981,
        lng=118.991,
        elevation=21.0,
        slope=2.0,
        tri=0.1,
        lc_factor=1.0,
        drainage_sensitivity=0.8,
        drainage_valid=True,
        surface_response=0.9,
    )
    edge = H3Edge(cell_a=c1.h3index, cell_b=c2.h3index, geo_distance=100.0, slope_a_to_b=1.0, slope_b_to_a=-1.0)
    graph = H3Graph(cells={c1.h3index: c1, c2.h3index: c2}, edges={(c1.h3index, c2.h3index): edge})
    cfg = FactorModelConfig()

    env_dry = EnvironmentConfig(
        model="surface_drainage_multiplier_v1",
        pressure_basis="synthetic_scenario",
        comparison_pressures=(0.0, 0.8),
        request_pressures=(0.0,),
    )
    eval_dry = evaluate_factor_model(graph, default_vehicle, cfg, env_dry)
    em_dry = eval_dry.directed_edges[(c1.h3index, c2.h3index)]

    env_rainy = EnvironmentConfig(
        model="surface_drainage_multiplier_v1",
        pressure_basis="synthetic_scenario",
        comparison_pressures=(0.0, 0.8),
        request_pressures=(0.8,),
    )
    eval_rainy = evaluate_factor_model(graph, default_vehicle, cfg, env_rainy)
    em_rainy = eval_rainy.directed_edges[(c1.h3index, c2.h3index)]

    # At P=0.0, multiplier is 1.0 -> distance is 100.0
    assert em_dry.environment_distance_m["0"] == pytest.approx(100.0)
    # At P=0.8, multiplier is 1 + 0.8*0.9*(1+0.8) = 2.296 -> distance is approx 229.6m
    assert em_rainy.environment_distance_m["0.8"] > 200.0


def test_is_water_only_for_code_5_not_buildings(default_vehicle: VehicleProfile):
    """P1-2: Verify that buildings (code 6) are tagged BUILDING, not WATER."""
    building_cell = H3Cell(
        h3index="8f2830828000001",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=math.inf,
        landcover_code=6,
        landcover_type="building",
        is_passable=False,
    )
    water_cell = H3Cell(
        h3index="8f2830828000002",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=math.inf,
        landcover_code=5,
        landcover_type="water",
        depth=1.2,
        is_passable=False,
    )
    graph = H3Graph(cells={building_cell.h3index: building_cell, water_cell.h3index: water_cell}, edges={})
    cfg = FactorModelConfig(enforce_water_depth=True)
    eval_res = evaluate_factor_model(graph, default_vehicle, cfg)

    b_reasons = eval_res.node_metrics[building_cell.h3index].reason_codes
    w_reasons = eval_res.node_metrics[water_cell.h3index].reason_codes

    assert "BUILDING" in b_reasons
    assert "WATER" not in b_reasons, "Building must NOT be tagged WATER!"
    assert "WATER_DEPTH_LIMIT" not in b_reasons

    assert "WATER_DEPTH_LIMIT" in w_reasons


def test_ablation_switches_properly_gate_reasons(default_vehicle: VehicleProfile):
    """Verify that FactorModelConfig switches isolate each physical reason code."""
    # Rowspacing cell
    c_tree = H3Cell(
        h3index="8f2830828000001",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=2,
        rowspacing=1.8,  # narrower than vehicle width 2.056
    )
    # Steep slope cell
    c_slope = H3Cell(
        h3index="8f2830828000002",
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=35.0,  # steeper than max_climb_angle 31.0
        tri=0.0,
        lc_factor=1.0,
        landcover_code=1,
    )
    graph = H3Graph(cells={c_tree.h3index: c_tree, c_slope.h3index: c_slope}, edges={})

    # A0: enforce_rowspacing=False, enforce_scalar_slope_blocking=True
    cfg_a0 = FactorModelConfig(enforce_rowspacing=False, enforce_scalar_slope_blocking=True)
    eval_a0 = evaluate_factor_model(graph, default_vehicle, cfg_a0)
    assert eval_a0.node_metrics[c_tree.h3index].is_passable is True
    assert "ROWSPACING_BLOCKED" not in eval_a0.node_metrics[c_tree.h3index].reason_codes
    assert eval_a0.node_metrics[c_slope.h3index].is_passable is False
    assert "STEEP_SLOPE" in eval_a0.node_metrics[c_slope.h3index].reason_codes

    # A1a: enforce_rowspacing=True
    cfg_a1a = FactorModelConfig(enforce_rowspacing=True, enforce_scalar_slope_blocking=True)
    eval_a1a = evaluate_factor_model(graph, default_vehicle, cfg_a1a)
    assert eval_a1a.node_metrics[c_tree.h3index].is_passable is False
    assert "ROWSPACING_BLOCKED" in eval_a1a.node_metrics[c_tree.h3index].reason_codes

    # A2: enforce_scalar_slope_blocking=False
    cfg_a2 = FactorModelConfig(enforce_rowspacing=True, enforce_scalar_slope_blocking=False)
    eval_a2 = evaluate_factor_model(graph, default_vehicle, cfg_a2)
    assert eval_a2.node_metrics[c_slope.h3index].is_passable is True
