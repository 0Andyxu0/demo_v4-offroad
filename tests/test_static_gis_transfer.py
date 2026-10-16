"""Acceptance tests for the static GIS soil, geometry, and robust-route increments."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import h3
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import Point

from h3_offroad_planner.candidate_aggregation import (
    _truncate_candidate_pool,
    _worst_environment_distance,
    select_robust_candidates,
)
from h3_offroad_planner.dynamics.trajectory_geometry import (
    TrajectoryPrimitive,
    TrajectoryResult,
    _continuous_environment_metrics,
    _fillet_polyline,
    _LocalProjection,
    _primitive_sweep,
    _required_geometry,
    _simplify_points,
    _unknown_h3_length,
    _vehicle_footprint,
    build_and_validate_trajectory,
)
from h3_offroad_planner.factor_model import (
    DecisionConfig,
    DirectedEdgeMetrics,
    EnvironmentConfig,
    FactorModelConfig,
    GeometryConfig,
    PathMetrics,
    StaticPlanningConfig,
    environment_multiplier,
    evaluate_factor_model,
    load_static_planning_config,
    write_static_planning_snapshot,
)
from h3_offroad_planner.grid.h3_grid_builder import _sample_raster_values
from h3_offroad_planner.models import (
    GISInputError,
    H3Cell,
    H3Edge,
    H3Graph,
    RouteEndpoint,
    VehicleProfile,
)
from h3_offroad_planner.preprocessing import GISPreprocessor, HydrologyConfig, map_twi_to_drainage
from h3_offroad_planner.preprocessing.hydrology import (
    _prepare_metric_dem,
    _require_metric_dem,
    _run_grass,
    _write_masks_and_drainage,
    preprocess_hydrology,
)
from h3_offroad_planner.route_models import RouteCandidate, candidate_id_for_path
from h3_offroad_planner.route_planning import (
    _restore_static_authority,
    _snap_evaluated,
    _validate_route_plan_planner,
    _with_trajectory,
)


def _cell(name: str, **changes: object) -> H3Cell:
    values: dict[str, object] = {
        "h3index": name,
        "lat": 0.0,
        "lng": 0.0,
        "elevation": 0.0,
        "slope": 0.0,
        "tri": 0.0,
        "lc_factor": 1.0,
    }
    values.update(changes)
    return H3Cell(**values)  # type: ignore[arg-type]


def _vehicle(**changes: object) -> VehicleProfile:
    values: dict[str, object] = {
        "name": "geometry-truck",
        "mass_kg": 2000.0,
        "max_climb_angle_deg": 30.0,
        "max_speed_kmh": 60.0,
        "tire_width_m": 0.35,
        "ground_clearance_m": 0.4,
        "max_thrust_n": 8000.0,
        "tire_radius_m": 0.45,
        "min_turn_radius_m": 5.0,
        "width_m": 2.0,
        "wheelbase_m": 3.0,
        "front_overhang_m": 1.0,
        "rear_overhang_m": 1.0,
    }
    values.update(changes)
    return VehicleProfile(**values)  # type: ignore[arg-type]


def _candidate(
    name: str,
    length: float,
    environment: dict[str, float],
    *,
    clearance: float = 1.0,
    status: str = "valid",
) -> RouteCandidate:
    path = ("s", name, "g")
    metrics = PathMetrics(length, 1.0, 1.0, 1.0, True, 0.0, length, 1.0, 1.0, 2)
    return RouteCandidate(
        candidate_id_for_path(path),
        path,
        (),
        name == "short",
        {"distance": length},
        metrics,
        (),
        trajectory={
            "status": status,
            "length_m": length,
            "environment_distance_m": environment,
            "min_clearance_m": clearance,
            "unknown_coverage_m": 0.0,
        },
    )


def _geometry_graph() -> tuple[H3Graph, str, tuple[str, ...], tuple[str, ...]]:
    center = str(h3.latlng_to_cell(31.98, 118.99, 10))
    cell_ids = {str(value) for value in h3.grid_disk(center, 2)}
    cells: dict[str, H3Cell] = {}
    for cell_id in cell_ids:
        lat, lng = h3.cell_to_latlng(cell_id)
        cells[cell_id] = _cell(
            cell_id,
            lat=lat,
            lng=lng,
            landcover_code=8,
            surface_response=0.0,
            surface_evidence="paved_polygon",
            parent_h3=str(h3.cell_to_parent(cell_id, 8)),
        )
    edges: dict[tuple[str, str], H3Edge] = {}
    for first in cell_ids:
        for second in h3.grid_ring(first, 1):
            second = str(second)
            if second not in cell_ids or first >= second:
                continue
            distance = h3.great_circle_distance(
                h3.cell_to_latlng(first),
                h3.cell_to_latlng(second),
                unit="m",
            )
            edges[(first, second)] = H3Edge(first, second, distance, 0.0, 0.0)
    ring = sorted(str(value) for value in h3.grid_ring(center, 1))
    straight = (ring[0], center, ring[3])
    turning = (ring[0], center, ring[2])
    return H3Graph(10, 8, cells, edges), center, straight, turning


def test_t01_soil_catalog_stays_categorical_without_default_moisture(tmp_path: Path) -> None:
    catalog = tmp_path / "soil.csv"
    catalog.write_text("VALUE,亚类名\n49,黄棕壤\n", encoding="utf-8")
    profile = GISPreprocessor().load_soil_catalog(str(catalog))[49]
    assert profile.name_zh == "黄棕壤"
    assert profile.soil_moisture is None
    assert profile.uscs == "CL"
    assert profile.bekker_soil == "loam"


def test_t01_soil_dbf_rejects_undecodable_field_names(tmp_path: Path) -> None:
    dbf = tmp_path / "corrupt.dbf"
    # Header: 32 bytes main header + 32 bytes field descriptor + 1 byte 0x0D terminator
    header = bytearray(65)
    header[0] = 0x03  # DBF version
    header[4:8] = (0).to_bytes(4, "little")  # 0 records
    header[8:10] = (65).to_bytes(2, "little")  # header length
    header[10:12] = (10).to_bytes(2, "little")  # record length
    # Field descriptor at offset 32: undecodable bytes for both UTF-8 and GBK
    header[32:43] = b"\x80\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00"
    header[43] = ord("C")  # field type
    header[48] = 5  # field length
    header[64] = 0x0D  # terminator
    dbf.write_bytes(header)

    with pytest.raises(GISInputError, match="soil DBF field name is undecodable"):
        GISPreprocessor().load_soil_catalog(str(dbf))


def test_t02_twi_mapping_preserves_invalid_cells_and_clips() -> None:
    twi = np.array([[-1.0, 2.0, 4.0, np.nan]], dtype=np.float64)
    valid = np.array([[True, True, True, True]])
    result = map_twi_to_drainage(twi, valid, 0.0, 3.0)
    assert result[0, :3].tolist() == pytest.approx([0.0, 2.0 / 3.0, 1.0])
    assert np.isnan(result[0, 3])


def test_t02_geographic_dem_is_normalized_to_a_metric_analysis_crs(tmp_path: Path) -> None:
    source = tmp_path / "dem_wgs84.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(118.9, 31.9, 119.0, 32.0, 2, 2),
    ) as dst:
        dst.write(np.ones((2, 2), dtype=np.float32), 1)
    normalized = _prepare_metric_dem(source, tmp_path, None)
    with rasterio.open(normalized) as dataset:
        assert dataset.crs is not None
        assert dataset.crs.is_projected
        assert dataset.crs.linear_units.lower() in {"metre", "meter"}


def test_t03_hydrology_policy_requires_frozen_threshold_pair(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="provided together"):
        HydrologyConfig(mapping_t0=1.0)
    assert HydrologyConfig(mapping_t0=None, mapping_t1=None).upstream_complete is None
    original = StaticPlanningConfig(environment=EnvironmentConfig(shared_sensitivity=0.7))
    snapshot = write_static_planning_snapshot(str(tmp_path), original)
    assert load_static_planning_config(snapshot) == original


def test_static_planning_retains_soil_hydrology_and_weather(tmp_path: Path) -> None:
    path = tmp_path / "static.yaml"
    path.write_text(
        """
soil:
  mode: categorical_drainage
  default_theta_v: 0.25
hydrology:
  mapping_t0: 2.0
  mapping_t1: 5.0
weather:
  enabled: true
  theta_dry: 0.1
  theta_wet: 0.4
""".strip(),
        encoding="utf-8",
    )

    loaded = load_static_planning_config(str(path))

    assert loaded.soil["default_theta_v"] == pytest.approx(0.25)
    assert loaded.hydrology["mapping_t0"] == pytest.approx(2.0)
    assert loaded.hydrology["mapping_t1"] == pytest.approx(5.0)
    assert loaded.weather.enabled is True
    assert loaded.to_dict()["soil"] == {
        "mode": "categorical_drainage",
        "default_theta_v": 0.25,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"backend": "other"},
        {"flow_method": "other"},
        {"analysis_resolution_m": 0.0},
        {"mapping_t0": float("nan"), "mapping_t1": 2.0},
        {"mapping_t0": 2.0, "mapping_t1": 1.0},
        {"version": ""},
    ],
)
def test_hydrology_policy_rejects_ambiguous_or_invalid_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        HydrologyConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EnvironmentConfig(model="other"),
        lambda: EnvironmentConfig(pressure_basis="other"),
        lambda: EnvironmentConfig(comparison_pressures=()),
        lambda: EnvironmentConfig(comparison_pressures=(0.0, 0.0)),
        lambda: EnvironmentConfig(comparison_pressures=(-1.0,)),
        lambda: EnvironmentConfig(request_pressures=(2.0,)),
        lambda: EnvironmentConfig(unknown_drainage_range=(0.8, 0.2)),
        lambda: EnvironmentConfig(unknown_surface_range=(-0.1, 1.0)),
        lambda: EnvironmentConfig(shared_sensitivity=-1.0),
        lambda: GeometryConfig(simplify_tolerance_m=0.0),
        lambda: GeometryConfig(map_error_m=-1.0),
        lambda: GeometryConfig(max_arc_segments=0),
        lambda: DecisionConfig(detour_ratio=-1.0),
        lambda: DecisionConfig(switch_relative_improvement=1.0),
        lambda: DecisionConfig(display_limit=0),
        lambda: DecisionConfig(candidate_limit=4, display_limit=5),
        lambda: StaticPlanningConfig(version="other"),
    ],
)
def test_static_planning_policy_rejects_invalid_contracts(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "yaml_text",
    [
        "- not-a-mapping\n",
        "unknown: true\n",
        "soil: {mode: inferred}\n",
        "soil: {default_theta_v: 1.2}\n",
        "hydrology: {backend: other}\n",
        "hydrology: {mapping_t0: 1.0}\n",
        "hydrology: {mapping_t0: 2.0, mapping_t1: 1.0}\n",
        "vehicle_geometry: {reference_point: center}\n",
        "environment: []\n",
        "environment: {comparison_pressures: bad}\n",
        "environment: {unknown_surface_range: [0.0]}\n",
        "decision: {candidate_limit: 2.5}\n",
        "weather: {enabled: 1}\n",
        "weather: {theta_dry: 0.1}\n",
    ],
)
def test_static_planning_loader_rejects_invalid_schema(
    tmp_path: Path,
    yaml_text: str,
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_static_planning_config(str(path))


def test_hydrology_low_level_guards_and_mask_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="same-shape"):
        map_twi_to_drainage(np.ones((1, 2)), np.ones((2, 1), dtype=bool), 0.0, 1.0)
    with pytest.raises(ValueError, match="t1 > t0"):
        map_twi_to_drainage(np.ones((1, 1)), np.ones((1, 1), dtype=bool), 1.0, 1.0)
    monkeypatch.setattr(
        "h3_offroad_planner.preprocessing.hydrology.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="failure", stdout=""),
    )
    with pytest.raises(ValueError, match="failure"):
        _run_grass(["grass"])

    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:3857",
        "transform": from_bounds(0.0, 0.0, 2.0, 2.0, 2, 2),
        "nodata": np.nan,
    }
    paths = {
        "twi": tmp_path / "twi.tif",
        "accumulation": tmp_path / "accumulation.tif",
        "validity": tmp_path / "validity.tif",
        "boundary": tmp_path / "boundary.tif",
        "drainage_sensitivity": tmp_path / "drainage.tif",
    }
    for name, data in (
        ("twi", np.array([[0.0, 1.0], [2.0, np.nan]], dtype=np.float32)),
        ("accumulation", np.array([[1.0, -1.0], [1.0, 1.0]], dtype=np.float32)),
    ):
        with rasterio.open(paths[name], "w", **profile) as dst:
            dst.write(data, 1)
    _write_masks_and_drainage(paths, HydrologyConfig(mapping_t0=0.0, mapping_t1=2.0))
    assert paths["drainage_sensitivity"].is_file()
    with rasterio.open(paths["boundary"]) as dataset:
        assert dataset.read(1).all()


def test_hydrology_preflight_fails_explicitly_for_missing_inputs_and_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(FileNotFoundError):
        preprocess_hydrology(str(tmp_path / "missing.tif"), str(tmp_path), HydrologyConfig())
    source = tmp_path / "geographic.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(118.9, 31.9, 119.0, 32.0, 1, 1),
    ) as dst:
        dst.write(np.ones((1, 1), dtype=np.float32), 1)
    monkeypatch.setattr("h3_offroad_planner.preprocessing.hydrology.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="unavailable"):
        preprocess_hydrology(str(source), str(tmp_path / "out"), HydrologyConfig())
    with pytest.raises(ValueError, match="projected metric CRS"):
        _require_metric_dem(source)
    with pytest.raises(ValueError, match="finite and non-negative"):
        environment_multiplier(_cell("a"), -1.0, EnvironmentConfig())
    with pytest.raises(ValueError, match="does not exist"):
        load_static_planning_config(str(tmp_path / "missing-static.yaml"))
    invalid = tmp_path / "invalid-static.yaml"
    invalid.write_text("geometry: {map_error_m: bad}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be numeric"):
        load_static_planning_config(str(invalid))


def test_hydrology_pipeline_persists_manifest_with_mocked_grass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "dem.tif"
    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:3857",
        "transform": from_bounds(0.0, 0.0, 2.0, 2.0, 2, 2),
        "nodata": np.nan,
    }
    with rasterio.open(source, "w", **profile) as dst:
        dst.write(np.ones((2, 2), dtype=np.float32), 1)

    def fake_grass(command: list[str]) -> None:
        if "--exec" in command:
            assert command[1].endswith(str(Path("location") / "PERMANENT"))
        output = next((item[7:] for item in command if item.startswith("output=")), None)
        if output and output.endswith(".tif"):
            data = np.array([[1.0, -1.0], [2.0, 3.0]], dtype=np.float32)
            with rasterio.open(output, "w", **profile) as dst:
                dst.write(data, 1)

    monkeypatch.setattr(
        "h3_offroad_planner.preprocessing.hydrology.shutil.which", lambda _: "grass"
    )
    monkeypatch.setattr("h3_offroad_planner.preprocessing.hydrology._run_grass", fake_grass)
    artifacts = preprocess_hydrology(
        str(source),
        str(tmp_path / "out"),
        HydrologyConfig(flow_method="d8", mapping_t0=0.0, mapping_t1=3.0),
    )
    assert Path(artifacts.manifest_path).is_file()
    assert Path(artifacts.drainage_sensitivity_path or "").is_file()


def test_environment_distance_contracts_reject_below_geometry_distance() -> None:
    with pytest.raises(ValueError, match="environment edge"):
        DirectedEdgeMetrics(
            "a",
            "b",
            10.0,
            1.0,
            1.0,
            1.0,
            True,
            0.0,
            1.0,
            1.0,
            1.0,
            1.0,
            0.0,
            {"1": 9.0},
        )
    with pytest.raises(ValueError, match="environment path"):
        PathMetrics(10.0, 1.0, 1.0, 1.0, True, 0.0, 1.0, 1.0, 1.0, 1, {"1": 9.0})


def test_t04_wet_and_dry_requests_choose_different_budgeted_routes() -> None:
    short = _candidate("short", 100.0, {"0": 100.0, "1": 200.0})
    paved = _candidate("paved", 110.0, {"0": 110.0, "1": 110.0})
    policy = DecisionConfig()
    _, dry, _, _ = select_robust_candidates((short, paved), policy, request_pressures=(0.0,))
    _, wet, _, _ = select_robust_candidates((short, paved), policy, request_pressures=(1.0,))
    assert dry == short.candidate_id
    assert wet == paved.candidate_id


def test_t05_rear_axle_reference_footprint_uses_all_vehicle_dimensions() -> None:
    footprint = _vehicle_footprint((0.0, 0.0), 0.0, _vehicle())
    assert footprint.bounds == pytest.approx((-1.0, -1.0, 4.0, 1.0))


def test_t06_straight_sweep_is_continuous_between_endpoint_poses() -> None:
    primitive = TrajectoryPrimitive("line", (0.0, 0.0), (10.0, 0.0), 0.0, 0.0, 10.0, 0.0)
    swept, _, _ = _primitive_sweep(primitive, _vehicle(), GeometryConfig())
    assert swept.covers(Point(5.0, 0.9))


def test_t07_fillet_obeys_radius_or_reports_insufficient_space() -> None:
    good, failure = _fillet_polyline([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], 2.0)
    assert not failure
    assert max(abs(item.curvature_per_m) for item in good) == pytest.approx(0.5)
    bad, failure = _fillet_polyline([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 5.0)
    assert not bad
    assert failure == ("TURNING_SPACE_INSUFFICIENT",)


def test_t07_end_to_end_geometry_statuses_are_explicit() -> None:
    graph, center, straight, turning = _geometry_graph()
    environment = EnvironmentConfig()
    evaluation = evaluate_factor_model(graph, _vehicle(), FactorModelConfig(), environment)
    valid = build_and_validate_trajectory(
        straight,
        graph,
        evaluation,
        _vehicle(),
        environment,
        GeometryConfig(),
    )
    assert valid.status == "valid"
    assert valid.length_m > 0.0
    assert valid.environment_distance_m["0"] == pytest.approx(valid.length_m)
    assert valid.swept_dependency_cells

    missing = build_and_validate_trajectory(
        straight,
        graph,
        evaluation,
        replace(_vehicle(), width_m=None),
        environment,
        GeometryConfig(),
    )
    assert missing.status == "not_evaluated"
    assert missing.failure_reasons == ("MISSING_VEHICLE_GEOMETRY",)

    blocked_nodes = dict(evaluation.node_metrics)
    blocked_nodes[center] = replace(blocked_nodes[center], is_passable=False)
    blocked_evaluation = replace(evaluation, node_metrics=blocked_nodes)
    collision = build_and_validate_trajectory(
        straight,
        graph,
        blocked_evaluation,
        _vehicle(),
        environment,
        GeometryConfig(),
    )
    assert collision.status == "invalid"
    assert "COLLISION" in collision.failure_reasons

    exhausted = build_and_validate_trajectory(
        turning,
        graph,
        evaluation,
        _vehicle(),
        environment,
        GeometryConfig(max_arc_segments=1),
    )
    assert exhausted.status == "incomplete"
    assert exhausted.failure_reasons == ("RESOURCE_EXHAUSTED",)


def test_trajectory_geometry_helpers_cover_degenerate_and_unknown_cases() -> None:
    assert _simplify_points([(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)], 0.1) == [
        (0.0, 0.0),
        (1.0, 0.0),
    ]
    assert _fillet_polyline([], 1.0) == ((), ("DATA_INSUFFICIENT",))
    assert _fillet_polyline([(0.0, 0.0)], 1.0) == ((), ())
    assert _fillet_polyline([(0.0, 0.0), (1.0, 0.0), (0.0, 0.0)], 1.0)[1] == (
        "TURNING_SPACE_INSUFFICIENT",
    )
    projection = _LocalProjection(32.0, 119.0)
    point = projection.forward(32.001, 119.001)
    assert projection.inverse(point) == pytest.approx((119.001, 32.001))
    with pytest.raises(AssertionError):
        _required_geometry(None)

    graph = H3Graph(cells={"a": _cell("a")})
    polygon = _vehicle_footprint((100.0, 100.0), 0.0, _vehicle())
    totals, unknown = _continuous_environment_metrics(
        [(0.0, 0.0), (10.0, 0.0)],
        10.0,
        ("a",),
        graph,
        {"a": polygon},
        EnvironmentConfig(),
    )
    assert totals["0"] == pytest.approx(10.0)
    assert unknown == pytest.approx(10.0)
    assert _continuous_environment_metrics([], 0.0, (), graph, {}, EnvironmentConfig())[1] == 0.0
    assert (
        _continuous_environment_metrics(
            [(0.0, 0.0), (0.0, 0.0)], 1.0, (), graph, {}, EnvironmentConfig()
        )[1]
        == 0.0
    )
    assert _unknown_h3_length(("a",), graph, EnvironmentConfig()) == 0.0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TrajectoryPrimitive("bad", (0, 0), (1, 0), 0, 0, 1, 0),
        lambda: TrajectoryPrimitive("line", (0, 0), (1, 0), 0, 0, -1, 0),
        lambda: TrajectoryPrimitive("arc", (0, 0), (1, 0), 0, 1, 1, 0),
        lambda: TrajectoryResult("id", "bad", (), (), (), 0, {}, None, 0, 0, 0, ()),
        lambda: TrajectoryResult("id", "valid", (), (), (), -1, {}, None, 0, 0, 0, ()),
    ],
)
def test_trajectory_value_objects_reject_invalid_states(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_t08_static_mode_preserves_water_depth_and_rowspacing() -> None:
    water = _cell("a", landcover_code=5, landcover_type="water", depth=0.1)
    forest = _cell("b", landcover_code=2, landcover_type="forest", rowspacing=0.1)
    graph = H3Graph(
        cells={"a": water, "b": forest},
        edges={("a", "b"): H3Edge("a", "b", 1.0, 0, 0)},
    )
    strict = evaluate_factor_model(graph, _vehicle(), FactorModelConfig(), EnvironmentConfig())
    legacy = evaluate_factor_model(graph, _vehicle(), FactorModelConfig())
    # Under M1 fix: neither static nor legacy bypasses rowspacing or shallow water passability
    assert strict.node_metrics["a"].is_passable is True
    assert "ROWSPACING_BLOCKED" in strict.node_metrics["b"].reason_codes
    assert strict.node_metrics["b"].is_passable is False
    assert legacy.node_metrics["a"].is_passable is True
    assert legacy.node_metrics["b"].is_passable is False


def test_t09_environment_multiplier_uses_surface_and_drainage_not_travel_cost() -> None:
    unpaved = _cell(
        "a",
        soil_code=49,
        drainage_sensitivity=0.5,
        drainage_valid=True,
        surface_response=1.0,
    )
    paved = replace(unpaved, h3index="b", surface_response=0.0)
    config = EnvironmentConfig(shared_sensitivity=1.0)
    assert environment_multiplier(unpaved, 1.0, config) == pytest.approx((2.5, False))
    assert environment_multiplier(paved, 1.0, config) == pytest.approx((1.0, False))
    boundary = replace(unpaved, drainage_boundary_affected=True)
    assert environment_multiplier(boundary, 1.0, config) == pytest.approx((3.0, True))


def test_t10_detour_budget_excludes_overlong_candidate() -> None:
    short = _candidate("short", 100.0, {"1": 200.0})
    overlong = _candidate("overlong", 116.0, {"1": 116.0})
    output, selected, stats, _ = select_robust_candidates(
        (short, overlong), DecisionConfig(), request_pressures=(1.0,)
    )
    assert selected == short.candidate_id
    assert [item.candidate_id for item in output] == [short.candidate_id]
    assert stats["length_budget_m"] == pytest.approx(115.0)


def test_t11_hysteresis_retains_small_gain_but_invalid_old_route_switches() -> None:
    old = _candidate("old", 100.0, {"1": 100.0})
    new = _candidate("new", 100.0, {"1": 96.0})
    _, retained, stats, _ = select_robust_candidates(
        (old, new), DecisionConfig(), old.candidate_id, (1.0,)
    )
    assert retained == old.candidate_id
    assert stats["switch_reason"] == "retained_by_hysteresis"
    invalid_old = _candidate("old", 100.0, {"1": 100.0}, status="invalid")
    _, switched, _, _ = select_robust_candidates(
        (invalid_old, new), DecisionConfig(), invalid_old.candidate_id, (1.0,)
    )
    assert switched == new.candidate_id


def test_robust_selection_reports_conditional_and_all_switch_reasons() -> None:
    invalid = tuple(
        _candidate(f"invalid-{index}", 100.0 + index, {"1": 100.0}, status="invalid")
        for index in range(7)
    )
    invalid = (replace(invalid[0], is_recommended=True), *invalid[1:])
    output, selected, _, warnings = select_robust_candidates(invalid, DecisionConfig())
    assert len(output) == 5
    assert selected == invalid[0].candidate_id
    assert warnings == ("NO_GEOMETRY_VALID_CANDIDATE",)

    old = _candidate("old-clearance", 100.0, {"1": 110.0}, clearance=0.1)
    clear = _candidate("clear", 100.0, {"1": 120.0}, clearance=1.0)
    _, selected, stats, _ = select_robust_candidates(
        (old, clear),
        DecisionConfig(clearance_target_m=1.0),
        old.candidate_id,
        (1.0,),
    )
    assert selected == clear.candidate_id
    assert stats["switch_reason"] == "clearance_level_improved"

    improved = _candidate("improved", 100.0, {"1": 90.0})
    conditional = replace(
        improved,
        trajectory={**dict(improved.trajectory), "unknown_coverage_m": 1.0},
    )
    _, selected, stats, warnings = select_robust_candidates(
        (old, conditional), DecisionConfig(), old.candidate_id, (1.0,)
    )
    assert selected == conditional.candidate_id
    assert stats["switch_reason"] == "environment_improvement_exceeded_threshold"
    assert warnings == ("CONDITIONAL_ENVIRONMENT_EVIDENCE",)

    malformed = replace(improved, trajectory={**dict(improved.trajectory), "length_m": True})
    with pytest.raises(ValueError, match="finite numeric"):
        select_robust_candidates((malformed,), DecisionConfig())
    nonmapping = replace(
        improved, trajectory={**dict(improved.trajectory), "environment_distance_m": 1}
    )
    assert _worst_environment_distance(nonmapping) == 100.0
    assert len(_truncate_candidate_pool(invalid, invalid[0].candidate_id, 3)) == 3


def test_t12_projected_static_raster_is_sampled_from_wgs84_centers(tmp_path: Path) -> None:
    path = tmp_path / "projected.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_bounds(-10.0, -10.0, 10.0, 10.0, 1, 1),
    ) as dst:
        dst.write(np.array([[0.75]], dtype=np.float32), 1)
    layer = GISPreprocessor().load_soil(str(path))
    assert layer is not None
    assert _sample_raster_values(layer, pd.DataFrame([{"lng": 0.0, "lat": 0.0}])) == [0.75]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[bad", "invalid planner YAML"),
        ("- item\n", "must contain a mapping"),
        ("global_planner: DeterministicParetoPlanner\nextra: 1\n", "unsupported fields"),
        ("global_planner: Other\n", "requires global_planner"),
    ],
)
def test_route_plan_planner_config_is_strict(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "planner.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _validate_route_plan_planner(str(path))
    with pytest.raises(ValueError, match="does not exist"):
        _validate_route_plan_planner(str(tmp_path / "missing.yaml"))
    path.write_text("global_planner: DeterministicParetoPlanner\n", encoding="utf-8")
    _validate_route_plan_planner(str(path))


def test_route_plan_snap_and_static_authority_branches() -> None:
    graph, _, straight, _ = _geometry_graph()
    evaluation = evaluate_factor_model(graph, _vehicle(), FactorModelConfig())
    lat, lng = h3.cell_to_latlng(straight[0])
    endpoint = RouteEndpoint("start", lat, lng)
    with pytest.raises(ValueError, match="positive"):
        _snap_evaluated(graph, evaluation, endpoint, 0.0)
    assert _snap_evaluated(graph, evaluation, endpoint, 1.0) == straight[0]
    with pytest.raises(ValueError, match="exceeds max snap distance"):
        _snap_evaluated(graph, evaluation, RouteEndpoint("start", 0.0, 0.0), 1.0)
    blocked_nodes = {
        cell_id: replace(node, is_passable=False)
        for cell_id, node in evaluation.node_metrics.items()
    }
    with pytest.raises(ValueError, match="no passable cell"):
        _snap_evaluated(
            graph,
            replace(evaluation, node_metrics=blocked_nodes),
            endpoint,
            1.0,
        )

    graph.cells[straight[0]].is_passable = False
    _restore_static_authority(graph, {"tile_fact_authority": "vehicle_independent"})
    assert graph.cells[straight[0]].is_passable is False
    graph.cells[straight[0]].lc_factor = 1.0
    graph.cells[straight[0]].landcover_type = "road"
    graph.cells[straight[1]].landcover_type = "water"
    _restore_static_authority(graph, {})
    assert graph.cells[straight[0]].is_passable is True
    assert graph.cells[straight[1]].is_passable is False


def test_route_candidate_keeps_h3_guide_separate_from_trajectory_geometry() -> None:
    candidate = _candidate("route", 10.0, {"0": 10.0})
    no_line = TrajectoryResult(
        "t0", "not_evaluated", (), ((0.0, 0.0),), (), 10.0, {}, None, 0.0, 1.0, 0.0, ()
    )
    unchanged = _with_trajectory(candidate, no_line)
    assert unchanged.geojson == candidate.geojson
    line = TrajectoryResult(
        "t1",
        "valid",
        (),
        ((119.0, 32.0), (119.001, 32.001)),
        (),
        10.0,
        {"0": 10.0},
        1.0,
        0.0,
        1.0,
        0.0,
        (),
    )
    updated = _with_trajectory(candidate, line)
    assert updated.h3_path == candidate.h3_path
    assert updated.geojson["properties"] == {
        "h3_path": list(candidate.h3_path),
        "trajectory_id": "t1",
    }
