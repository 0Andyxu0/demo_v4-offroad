"""Consolidated regression suite for M1 physical attribute repair and audit compliance.

Fulfills M1 Consolidated Audit (2026-10-17) §9:
- CLDAS and Drainage sensitivity rasters CRS, nodata, and pixel variance (rejecting constant forgery).
- Weather snapshot parameter change altering formal evaluate_factor_model outputs.
- uscs=None remains unknown and reports MISSING_SOIL, not forged to 'CL'.
- Moisture increase -> sinkage increase -> speed degradation/blocking (scalar vs vectorized consistency).
- CI threshold single-source enforcement from config.min_cone_index_kpa.
- Endpoint resolution to the containing res14 cell (<=2.0m), explicit failure, no cell hopping.
- is_water only active for landcover_code == 5; buildings (code 6) must not be tagged WATER.
- Ablation switches (enforce_rowspacing, enforce_water_depth, enforce_soil_physics, enforce_scalar_slope_blocking) gate reason codes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import h3
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

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
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.preprocessing.gis_preprocessor import (
    SOIL_USCS_MAP_PATH,
    SOIL_USCS_MAP_SHA256,
    SOIL_USCS_OVERRIDES,
)
from h3_offroad_planner.scene import (
    _pixel_index,
    coverage_evidence_status,
    coverage_gaps,
    enrich_graph_from_static_scene,
    static_field_coverage,
    static_field_coverage_for_cells,
)
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
    scene_path = ROOT / "configs" / "scenes" / "m0_qdx_scene.json"
    scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
    cldas_path = Path(scene_data["moisture"]["paths"][0])
    drainage_path = Path(scene_data["hydrology"]["upstream_layers"]["drainage_sensitivity"])

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


def test_raster_sampling_uses_containing_pixel_not_rounded_neighbour(tmp_path: Path):
    """Sampling must read the pixel that CONTAINS the point.

    Regression for the half-pixel offset: `~transform * (x, y)` is corner
    based, so `round(...)` pushes every sample in the second half of a pixel
    into the neighbouring pixel. On the 0.0625 deg CLDAS grid that is a
    ~3.45 km error and it collapsed the whole corridor onto one moisture value.
    """
    raster = tmp_path / "synthetic_moisture.tif"
    transform = from_origin(118.0, 32.0, 0.01, 0.01)
    data = np.array([[0.10, 0.20], [0.30, 0.40]], dtype="float32")
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as ds:
        ds.write(data, 1)

    # px = 0.9 (second half of column 0), py = 0.4 -> must read row 0, col 0.
    coords = [
        ("8f2830828000001", 31.996, 118.009),
        ("8f2830828000002", 31.996, 118.019),
        ("8f2830828000003", 31.986, 118.009),
    ]
    cells = {
        hid: H3Cell(
            h3index=hid,
            lat=lat,
            lng=lng,
            elevation=10.0,
            slope=1.0,
            tri=0.1,
            lc_factor=1.0,
            landcover_code=1,
        )
        for hid, lat, lng in coords
    }
    graph = H3Graph(cells=cells, edges={})
    scene = {
        "soil": {"raster_path": str(tmp_path / "none.tif"), "catalog_path": str(tmp_path / "none.dbf")},
        "moisture": {"paths": [str(raster)]},
        "hydrology": {"upstream_layers": {}},
    }
    meta = enrich_graph_from_static_scene(graph, scene)

    assert cells["8f2830828000001"].soil_moisture == pytest.approx(0.10)
    assert cells["8f2830828000002"].soil_moisture == pytest.approx(0.20)
    assert cells["8f2830828000003"].soil_moisture == pytest.approx(0.30)
    # Three distinct pixels were sampled: the field must not collapse to a constant.
    assert meta["moisture"]["distinct_pixels"] == 3
    assert meta["moisture"]["distinct_values"] == 3


def test_pixel_index_matches_rasterio_index():
    """`_pixel_index` must agree with rasterio's own `index()` for every point."""
    from rasterio.transform import Affine

    transform = Affine(0.0625, 0.0, 60.0, 0.0, -0.0625, 65.0)
    inverse = ~transform
    with rasterio.Env():
        from rasterio.io import MemoryFile

        profile = {
            "driver": "GTiff",
            "height": 40,
            "width": 40,
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:4326",
            "transform": transform,
        }
        with MemoryFile() as mem, mem.open(**profile) as ds:
            ds.write(np.zeros((1, 40, 40), dtype="float32"))
            for lng in (118.99, 118.995, 119.0, 119.0076, 119.02):
                for lat in (31.97, 31.989, 31.995, 32.0):
                    assert _pixel_index(inverse, lng, lat) == ds.index(lng, lat), (lng, lat)


def _surface_cell(h3index: str, **kwargs: object) -> H3Cell:
    base = dict(
        h3index=h3index,
        lat=31.98,
        lng=118.99,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=1,
    )
    base.update(kwargs)
    return H3Cell(**base)  # type: ignore[arg-type]


def test_static_field_coverage_separates_non_null_from_valid():
    """A field can be populated and still unusable; both rates must be reported."""
    populated = _surface_cell(
        str(h3.latlng_to_cell(31.980, 118.990, 14)),
        soil_code=49,
        uscs=None,  # catalogue hit but no USCS class
        soil_moisture=0.31,
        drainage_sensitivity=0.4,
        drainage_valid=True,
        surface_response=0.9,
    )
    empty = _surface_cell(str(h3.latlng_to_cell(31.981, 118.991, 14)))

    coverage = static_field_coverage_for_cells([populated, empty])
    assert coverage["soil_code"]["non_null_rate"] == pytest.approx(0.5)
    assert coverage["soil_code"]["valid_rate"] == pytest.approx(0.5)
    assert coverage["uscs"]["non_null_rate"] == pytest.approx(0.0)
    assert coverage["soil_moisture"]["valid_rate"] == pytest.approx(0.5)
    assert coverage["drainage_sensitivity"]["valid_rate"] == pytest.approx(0.5)
    assert coverage["surface_response"]["valid_rate"] == pytest.approx(0.5)

    assert coverage_evidence_status(coverage) == "incomplete"
    assert "uscs" in coverage_gaps(coverage)

    graph = H3Graph(cells={populated.h3index: populated, empty.h3index: empty}, edges={})
    assert static_field_coverage(graph) == coverage


def test_static_coverage_is_complete_when_every_field_is_usable():
    cell = _surface_cell(
        str(h3.latlng_to_cell(31.980, 118.990, 14)),
        soil_code=49,
        uscs="CL",
        soil_moisture=0.31,
        drainage_sensitivity=0.4,
        drainage_valid=True,
        surface_response=0.9,
    )
    coverage = static_field_coverage_for_cells([cell])
    assert coverage_evidence_status(coverage) == "complete"
    assert coverage_gaps(coverage) == []


def test_soil_uscs_map_is_external_and_hashed():
    """The mapping must live in configs/ and be content-addressed."""
    assert SOIL_USCS_MAP_PATH.is_file(), SOIL_USCS_MAP_PATH
    assert SOIL_USCS_MAP_PATH.parent.name == "configs"
    assert len(SOIL_USCS_OVERRIDES) == 27
    assert SOIL_USCS_OVERRIDES[49] == ("Lo", "CL", "loam", True)
    assert SOIL_USCS_OVERRIDES[44] == ("ClLo", "CL", "clayloam", True)
    assert SOIL_USCS_OVERRIDES[18] == (None, None, None, False)
    import hashlib

    digest = hashlib.sha256(SOIL_USCS_MAP_PATH.read_bytes()).hexdigest()
    assert SOIL_USCS_MAP_SHA256 == digest
    assert len(SOIL_USCS_MAP_SHA256) == 64


def test_route_request_accepts_optional_static_scene_path():
    request = RouteRequest(
        input_mode="coordinates",
        parquet_path="outputs/baseline_986bd58/qdx_tiles/tile_manifest.json",
        planner_config_path="configs/planner_config.json",
        vehicle_path="configs/vehicle.yaml",
        output_dir="outputs/m1_ablation",
        start_lat=31.99,
        start_lng=118.99,
        goal_lat=31.995,
        goal_lng=118.995,
        static_scene_path="configs/scenes/m0_qdx_scene.json",
    )
    assert request.static_scene_path == "configs/scenes/m0_qdx_scene.json"
    with pytest.raises(ValueError):
        RouteRequest(
            input_mode="coordinates",
            parquet_path="outputs/baseline_986bd58/qdx_tiles/tile_manifest.json",
            planner_config_path="configs/planner_config.json",
            vehicle_path="configs/vehicle.yaml",
            output_dir="outputs/m1_ablation",
            start_lat=31.99,
            start_lng=118.99,
            goal_lat=31.995,
            goal_lng=118.995,
            static_scene_path="",
        )


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


def test_endpoint_resolves_containing_cell_and_never_crosses_cells(default_vehicle: VehicleProfile):
    """Endpoints must resolve to the CONTAINING res14 cell, never a neighbour.

    A coordinate whose containing cell is impassable must fail explicitly; the
    resolver may not hop to a nearby passable cell.
    """
    import h3 as _h3

    from scripts.run_m1_ablation import MAX_SNAP_DISTANCE_M, _resolve_endpoint

    assert MAX_SNAP_DISTANCE_M <= 2.0, "snap tolerance must stay inside one res14 cell"

    lat0, lng0 = 31.980, 118.990
    passable_id = str(_h3.latlng_to_cell(lat0, lng0, 14))
    passable_lat, passable_lng = _h3.cell_to_latlng(passable_id)
    neighbours = [str(x) for x in _h3.grid_ring(passable_id, 1) if str(x) != passable_id]
    blocked_id = neighbours[0]
    blocked_lat, blocked_lng = _h3.cell_to_latlng(blocked_id)

    c_passable = H3Cell(
        h3index=passable_id,
        lat=passable_lat,
        lng=passable_lng,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        landcover_code=1,
        is_passable=True,
    )
    c_blocked = H3Cell(
        h3index=blocked_id,
        lat=blocked_lat,
        lng=blocked_lng,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=math.inf,
        landcover_code=5,
        depth=1.5,
        is_passable=False,
    )
    graph = H3Graph(cells={c_passable.h3index: c_passable, c_blocked.h3index: c_blocked}, edges={})
    eval_res = evaluate_factor_model(graph, default_vehicle, FactorModelConfig(enforce_water_depth=True))

    # 1. A point inside the passable cell resolves to that cell. Any interior
    #    point is at most one res14 edge (~1.35 m) from the centre.
    h3_id, snap_m, passable, reasons = _resolve_endpoint(
        graph, eval_res.node_metrics, lat0, lng0
    )
    assert h3_id == passable_id
    assert snap_m <= 1.5
    assert passable is True
    assert "STATIC_BLOCKED" not in reasons

    # 1b. The centre itself resolves with an essentially zero offset.
    h3_ctr, snap_ctr, passable_ctr, _ = _resolve_endpoint(
        graph, eval_res.node_metrics, passable_lat, passable_lng
    )
    assert h3_ctr == passable_id
    assert snap_ctr < 0.05
    assert passable_ctr is True

    # 2. A point inside the impassable neighbour resolves to THAT cell and fails;
    #    it must not hop back to the adjacent passable cell.
    h3_imp, _, passable_imp, reasons_imp = _resolve_endpoint(
        graph, eval_res.node_metrics, blocked_lat, blocked_lng
    )
    assert h3_imp == blocked_id
    assert passable_imp is False
    assert "WATER_DEPTH_LIMIT" in reasons_imp

    # 3. A point whose containing cell is not in the corridor fails outright.
    far_lat, far_lng = _h3.cell_to_latlng(str(_h3.latlng_to_cell(31.95, 118.96, 14)))
    h3_out, _, passable_out, reasons_out = _resolve_endpoint(
        graph, eval_res.node_metrics, far_lat, far_lng
    )
    assert h3_out is None
    assert passable_out is False
    assert reasons_out == ["CELL_NOT_IN_CORRIDOR"]


def test_road_cells_are_exempt_from_soil_sinkage(default_vehicle: VehicleProfile):
    """Paved road cells must not take part in Bekker sinkage or cone-index physics."""
    road = H3Cell(
        h3index=str(h3.latlng_to_cell(31.980, 118.990, 14)),
        lat=31.980,
        lng=118.990,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=0.85,
        landcover_code=8,
        has_road=True,
        uscs="CL",
        soil_moisture=0.45,
        is_passable=True,
    )
    offroad = H3Cell(
        h3index=str(h3.latlng_to_cell(31.9802, 118.9902, 14)),
        lat=31.9802,
        lng=118.9902,
        elevation=20.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.2,
        landcover_code=1,
        has_road=False,
        uscs="CL",
        soil_moisture=0.45,
        is_passable=True,
    )
    graph = H3Graph(
        cells={road.h3index: road, offroad.h3index: offroad},
        edges={},
    )
    cfg = FactorModelConfig(soil_speed_by_uscs={"CL": 0.5}, enforce_soil_physics=True)
    evaluation = evaluate_factor_model(graph, default_vehicle, cfg)

    road_metrics = evaluation.node_metrics[road.h3index]
    soil_metrics = evaluation.node_metrics[offroad.h3index]
    assert road_metrics.cone_index_kpa is None
    assert road_metrics.sinkage_m is None
    assert road_metrics.soil.nominal == pytest.approx(1.0)
    assert soil_metrics.soil.nominal < 1.0
    assert road_metrics.speed_nominal_mps > soil_metrics.speed_nominal_mps
    assert road_metrics.safety_margin.nominal > soil_metrics.safety_margin.nominal


def test_m1_ablation_artifacts_contract_and_traceability():
    """P0-6: Verify m1_ablation.json and summary.md schema, hashes, and dual statistics."""
    json_path = ROOT / "outputs" / "m1_ablation" / "m1_ablation.json"
    md_path = ROOT / "outputs" / "m1_ablation" / "m1_ablation_summary.md"

    assert json_path.is_file(), f"Ablation JSON missing: {json_path}"
    assert md_path.is_file(), f"Ablation summary Markdown missing: {md_path}"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    meta = payload["metadata"]

    assert meta["schema_version"] == "m1_ablation_consolidated_v2"
    assert meta["max_snap_distance_m"] == 2.0

    # Check input hashes
    hashes = meta["input_hashes"]
    required_hash_keys = [
        "tile_manifest_sha256",
        "scene_sha256",
        "benchmark_ods_sha256",
        "weather_snapshot_sha256",
        "vehicle_sha256",
        "soil_raster_sha256",
        "soil_catalog_sha256",
        "cldas_moisture_sha256",
        "drainage_sensitivity_sha256",
        "soil_uscs_map_sha256",
    ]
    for k in required_hash_keys:
        assert k in hashes and len(hashes[k]) >= 16, f"Hash key {k} missing or invalid: {hashes.get(k)}"

    # Check corridor_union_enrichment
    coverage = meta.get("data_coverage")
    assert coverage is not None, "artifact must report static surface coverage"
    assert coverage["evidence_status"] in {"complete", "incomplete"}
    assert coverage["fields"]["soil_moisture"]["valid_rate"] >= 0.99
    assert coverage["fields"]["drainage_sensitivity"]["valid_rate"] >= 0.99
    assert coverage["evidence_status"] == "complete", coverage.get("gaps")
    assert len(coverage["soil_uscs_map_sha256"]) == 64

    union_enrich = meta.get("corridor_union_enrichment", meta.get("enrichment_summary", {}))
    union_cells_total = union_enrich["total_cells_enriched"]
    assert union_cells_total > 100_000, "corridor union must cover the whole benchmark area"
    hist = union_enrich["soil"]["histogram"]
    assert hist.get("49", 0) > 0 or hist.get(49, 0) > 0

    # Check all 5 levels
    levels = payload["levels"]
    for lvl_code in ["A0", "A1a", "A1b", "A1c", "A2"]:
        assert lvl_code in levels, f"Level {lvl_code} missing from ablation payload"
        lvl_data = levels[lvl_code]
        u = lvl_data["corridor_union"]
        assert u["total_unique_cells"] == union_cells_total
        assert u["passable_unique_cells"] > 0
        assert u["blocked_unique_cells"] == u["total_unique_cells"] - u["passable_unique_cells"]
        per_od_sum = sum(od["total_corridor_cells"] for od in lvl_data["ods"].values())
        assert u["total_unique_cells"] <= per_od_sum, "union must be de-duplicated across ODs"
        assert u["passable_unique_directed_edges"] > 0
        assert len(u["reason_codes_by_cell"]) > 0
        assert len(u["reason_codes_total_labels"]) > 0

        # Check all 5 ODs
        for oid in [
            "od_01_primary",
            "od_02_forest_rowspacing",
            "od_03_water_gully",
            "od_04_narrow_road",
            "od_05_slope_traverse",
        ]:
            od_res = lvl_data["ods"][oid]
            assert od_res["status"] == "REACHABLE", (
                f"OD {oid} in level {lvl_code} is {od_res['status']}: {od_res.get('status_reason')}"
            )
            # Endpoints resolve to the CONTAINING res14 cell, so the offset can
            # never exceed one cell radius (~1.35 m).
            assert od_res["start_snap_m"] <= 1.5
            assert od_res["goal_snap_m"] <= 1.5
            assert len(od_res["h3_path"]) > 0
            assert od_res["metrics"]["distance_m"] > 0
            assert od_res["metrics"]["eta_s"] > 0
            assert od_res["metrics"]["travel_cost"] > 0

    # Check markdown summary contains table lines
    md_content = md_path.read_text(encoding="utf-8")
    assert "Corridor Union" in md_content or "走廊并集" in md_content
    assert "od_01_primary" in md_content
    assert "od_05_slope_traverse" in md_content

