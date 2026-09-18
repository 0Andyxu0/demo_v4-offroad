"""Bounded retry checks for routing-index RoutePlan orchestration."""

from __future__ import annotations

from pathlib import Path

import h3
import pandas as pd
import pytest

from h3_offroad_planner import route_planning
from h3_offroad_planner.factor_model import PathMetrics
from h3_offroad_planner.models import (
    H3Cell,
    H3Graph,
    PlanningFailedError,
    RouteEndpoint,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.reachability import (
    ReachabilityDiagnosis,
    ReachabilityDisconnectionError,
)
from h3_offroad_planner.route_models import candidate_id_for_path
from h3_offroad_planner.routing import _coarse_skeletons
from h3_offroad_planner.routing_index import RoutingIndex


def test_indexed_plan_retries_once_with_two_ring_corridor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls: list[tuple[int, str | None]] = []
    expected = object()

    def run_once(*args: object, **kwargs: object) -> object:
        ring = kwargs["corridor_ring"]
        warning = kwargs.get("extra_warning")
        assert isinstance(ring, int)
        assert warning is None or isinstance(warning, str)
        calls.append((ring, warning))
        if ring == 1:
            raise PlanningFailedError("narrow corridor")
        return expected

    monkeypatch.setattr(route_planning, "_run_route_plan_once", run_once)
    monkeypatch.setattr(route_planning, "_routing_index_available", lambda _path: True)

    assert route_planning.run_route_plan(request) is expected
    assert calls == [(1, None), (2, "CORRIDOR_EXPANDED_TO_2_RING")]


def test_indexed_plan_never_expands_beyond_two_rings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls: list[int] = []

    def fail(*args: object, **kwargs: object) -> object:
        ring = kwargs["corridor_ring"]
        assert isinstance(ring, int)
        calls.append(ring)
        raise PlanningFailedError(f"ring {ring} failed")

    monkeypatch.setattr(route_planning, "_run_route_plan_once", fail)
    monkeypatch.setattr(route_planning, "_routing_index_available", lambda _path: True)

    with pytest.raises(PlanningFailedError, match="ring 2 failed"):
        route_planning.run_route_plan(request)
    assert calls == [1, 2]


def test_coarse_widest_over_detour_limit_is_not_loaded(tmp_path: Path) -> None:
    start = h3.latlng_to_cell(31.99, 118.99, 11)
    goal = h3.latlng_to_cell(32.00, 119.00, 11)
    rows = [
        _coarse_row(start, "short", 0.2),
        _coarse_row("short", goal, 0.2),
        _coarse_row(start, "long-1", 0.9),
        _coarse_row("long-1", "long-2", 0.9),
        _coarse_row("long-2", "long-3", 0.9),
        _coarse_row("long-3", goal, 0.9),
    ]
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    start_lat, start_lng = h3.cell_to_latlng(start)
    goal_lat, goal_lng = h3.cell_to_latlng(goal)

    skeletons, diagnostics = _coarse_skeletons(
        index,
        RouteEndpoint("start", start_lat, start_lng),
        RouteEndpoint("goal", goal_lat, goal_lng),
        max_widest_detour_ratio=0.15,
    )

    assert skeletons["widest"] == []
    assert diagnostics["coarse_widest_included"] is False
    assert diagnostics["coarse_widest_parent_count"] == 5


def test_static_index_binds_current_vehicle_without_rebuild() -> None:
    metadata: dict[str, object] = {
        "artifact_kind": "h3_routing_index",
        "vehicle_hash": "old-vehicle",
        "factor_model_hash": "old-factor",
        "evidence_status": "INCOMPLETE",
        "missing_physical_inputs": [
            "vehicle.width_m",
            "vehicle.wheelbase_m",
            "hydrology.mapping_t0",
            "soil.default_theta_v",
        ],
    }
    evaluation = route_planning.FactorEvaluation(
        node_metrics={},
        directed_edges={},
        vehicle_hash="current-vehicle",
        factor_model_hash="current-factor",
        static_input_hash="static",
        graph_topology_hash="topology",
    )
    vehicle = VehicleProfile(
        name="complete",
        mass_kg=2968.0,
        max_climb_angle_deg=31.0,
        max_speed_kmh=90.0,
        tire_width_m=0.265,
        ground_clearance_m=0.225,
        max_thrust_n=50000.0,
        tire_radius_m=0.43315,
        min_turn_radius_m=5.116,
        width_m=2.056,
        wheelbase_m=3.480,
        front_overhang_m=0.928,
        rear_overhang_m=0.940,
    )

    route_planning._bind_loaded_index_identity(metadata, evaluation, vehicle, None)

    assert metadata["vehicle_hash"] == "current-vehicle"
    assert metadata["factor_model_hash"] == "current-factor"
    assert metadata["missing_physical_inputs"] == ["hydrology.mapping_t0"]
    assert metadata["evidence_status"] == "INCOMPLETE"


def test_environment_snapshot_participates_in_scenario_identity() -> None:
    static = route_planning.StaticPlanningConfig()

    first = route_planning._scenario_hash(static, "snapshot-a")
    second = route_planning._scenario_hash(static, "snapshot-b")

    assert first != second
    assert first == route_planning._scenario_hash(static, "snapshot-a")


def _coarse_row(parent_a: str, parent_b: str, passable: float) -> dict[str, object]:
    return {
        "parent_a": parent_a,
        "parent_b": parent_b,
        "distance_m": 1.0,
        "slope_mean": 0.0,
        "tri_mean": 0.0,
        "road_fraction": 0.0,
        "passable_fraction": passable,
        "environment_proxy": 0.0,
    }


def _request(tmp_path: Path) -> RouteRequest:
    return RouteRequest(
        input_mode="coordinates",
        parquet_path=str(tmp_path / "routing_index" / "current.json"),
        planner_config_path=str(tmp_path / "planner.yaml"),
        vehicle_path=str(tmp_path / "vehicle.yaml"),
        factor_model_path=str(tmp_path / "factor.yaml"),
        output_dir=str(tmp_path / "output"),
        start_lat=31.99,
        start_lng=118.99,
        goal_lat=32.00,
        goal_lng=119.00,
    )


def test_expand_targeted_bottleneck_parents_bounded(tmp_path: Path) -> None:
    from h3_offroad_planner.routing import expand_targeted_bottleneck_parents

    center = h3.latlng_to_cell(32.0, 119.0, 11)
    disk_2 = [str(c) for c in h3.grid_disk(center, 2)]
    rows = []
    for c in disk_2:
        for n in h3.grid_disk(c, 1):
            if str(n) in disk_2 and str(n) > c:
                rows.append(_coarse_row(c, str(n), 1.0))
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    current_active = {str(center)}

    # 1. Expand single bottleneck parent with bound 15
    new_parents = expand_targeted_bottleneck_parents(
        index, current_active, [str(center)], max_additional=15
    )
    assert len(new_parents) == 6
    assert str(center) not in new_parents
    assert new_parents.issubset(set(disk_2))

    # 2. Max additional constraint strictly enforced
    capped = expand_targeted_bottleneck_parents(
        index, current_active, [str(center)], max_additional=3
    )
    assert len(capped) == 3

    # 3. No duplicate additions for already active parents
    empty = expand_targeted_bottleneck_parents(
        index, current_active.union(new_parents), [str(center)]
    )
    assert empty == set()


def test_barrier_aware_coarse_routing_avoids_water_corridor(tmp_path: Path) -> None:
    start = h3.latlng_to_cell(31.99, 118.99, 11)
    goal = h3.latlng_to_cell(32.01, 118.99, 11)

    # Path A: direct (2000m total), but passes through water_mid (passable_fraction = 0.05)
    # Path B: minor detour (2250m total, 12.5% longer), but passable_fraction = 0.95
    rows = [
        {
            "parent_a": start,
            "parent_b": "water_mid",
            "distance_m": 1000.0,
            "slope_mean": 2.0,
            "tri_mean": 0.5,
            "road_fraction": 0.0,
            "passable_fraction": 0.05,
            "risk_proxy": 2.5,
            "environment_proxy": 0.95,
        },
        {
            "parent_a": "water_mid",
            "parent_b": goal,
            "distance_m": 1000.0,
            "slope_mean": 2.0,
            "tri_mean": 0.5,
            "road_fraction": 0.0,
            "passable_fraction": 0.05,
            "risk_proxy": 2.5,
            "environment_proxy": 0.95,
        },
        {
            "parent_a": start,
            "parent_b": "land_1",
            "distance_m": 750.0,
            "slope_mean": 2.0,
            "tri_mean": 0.5,
            "road_fraction": 0.0,
            "passable_fraction": 0.95,
            "risk_proxy": 2.5,
            "environment_proxy": 0.05,
        },
        {
            "parent_a": "land_1",
            "parent_b": "land_2",
            "distance_m": 750.0,
            "slope_mean": 2.0,
            "tri_mean": 0.5,
            "road_fraction": 0.0,
            "passable_fraction": 0.95,
            "risk_proxy": 2.5,
            "environment_proxy": 0.05,
        },
        {
            "parent_a": "land_2",
            "parent_b": goal,
            "distance_m": 750.0,
            "slope_mean": 2.0,
            "tri_mean": 0.5,
            "road_fraction": 0.0,
            "passable_fraction": 0.95,
            "risk_proxy": 2.5,
            "environment_proxy": 0.05,
        },
    ]
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    start_lat, start_lng = h3.cell_to_latlng(start)
    goal_lat, goal_lng = h3.cell_to_latlng(goal)
    skeletons, _ = _coarse_skeletons(
        index,
        RouteEndpoint("start", start_lat, start_lng),
        RouteEndpoint("goal", goal_lat, goal_lng),
    )
    # The barrier-aware coarse routing must guide the skeleton away from water_mid
    # to land corridor across all profiles
    assert "water_mid" not in skeletons["distance"]
    assert skeletons["distance"] == [start, "land_1", "land_2", goal]
    assert "water_mid" not in skeletons["eta_road"]
    assert "water_mid" not in skeletons["terrain_travel"]
    assert "water_mid" not in skeletons["environment"]


def _mock_vehicle_and_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_vehicle = VehicleProfile(
        name="test",
        mass_kg=2968.0,
        max_climb_angle_deg=31.0,
        max_speed_kmh=90.0,
        tire_width_m=0.265,
        ground_clearance_m=0.225,
        max_thrust_n=50000.0,
        tire_radius_m=0.43315,
        min_turn_radius_m=5.116,
    )
    dummy_factor = type("FactorConfig", (), {"max_ports": 2, "max_port_pairs": 2})()
    monkeypatch.setattr(route_planning, "load_vehicle", lambda *args, **kwargs: dummy_vehicle)
    monkeypatch.setattr(route_planning, "load_factor_model", lambda *args, **kwargs: dummy_factor)

    dummy_node = type("NodeMetric", (), {"is_passable": True})()
    dummy_eval = route_planning.FactorEvaluation(
        node_metrics={"c1": dummy_node},  # type: ignore[arg-type]
        directed_edges={},
        vehicle_hash="veh-test",
        factor_model_hash="fac-test",
        static_input_hash="static-test",
        graph_topology_hash="topo-test",
    )
    dummy_index = type("DummyIndex", (), {"manifest": {}, "has_port_pairs": False})()
    monkeypatch.setattr(route_planning, "open_routing_index", lambda path: dummy_index)
    monkeypatch.setattr(route_planning, "evaluate_factor_model", lambda *a, **k: dummy_eval)


def test_targeted_dilation_loop_bounds_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    Path(request.output_dir).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(route_planning, "estimate_h3_cells_for_roi", lambda *args, **kwargs: 100)
    _mock_vehicle_and_factor(monkeypatch)
    Path(request.factor_model_path).write_text("model_version: '3.1'\n", encoding="utf-8")
    Path(request.vehicle_path).write_text("name: test\n", encoding="utf-8")
    Path(request.planner_config_path).write_text(
        "global_planner: DeterministicParetoPlanner\n", encoding="utf-8"
    )

    base_meta = {
        "artifact_kind": "h3_routing_index",
        "build_id": "test-repair",
        "source_manifest": "dummy.json",
        "active_parent_h3": ["p1"],
        "res_fine": 13,
        "res_coarse": 11,
    }
    monkeypatch.setattr(route_planning, "_source_metadata", lambda path: dict(base_meta))

    reachability_attempts = 0
    loaded_extra_parents: list[set[str] | None] = []

    def mock_check(*args: object, **kwargs: object) -> ReachabilityDiagnosis:
        nonlocal reachability_attempts
        reachability_attempts += 1
        if reachability_attempts == 1:
            diag = ReachabilityDiagnosis(
                reachable=False,
                bottleneck_parents=("p1",),
                boundary_blockage_cells=frozenset(["c1"]),
            )
            raise ReachabilityDisconnectionError("Endpoints disconnected", diagnosis=diag)
        return ReachabilityDiagnosis(reachable=True)

    def mock_load(
        req: object, roi: object, meta: dict[str, object], **kwargs: object
    ) -> tuple[H3Graph, dict[str, object]]:
        extra = kwargs.get("extra_parents")
        loaded_extra_parents.append(set(extra) if isinstance(extra, set) else None)
        cell = H3Cell(
            "c1", 32.0, 119.0, 10.0, 1.0, 0.1, 1.0, parent_h3="p1", is_passable=True
        )
        cells = {"c1": cell}
        new_meta = {
            **meta,
            "artifact_kind": "h3_routing_index",
            "active_parent_h3": ["p1"],
            "source_manifest": "dummy.json",
        }
        return H3Graph(cells=cells, edges={}), new_meta

    monkeypatch.setattr(route_planning, "check_route_reachability", mock_check)
    monkeypatch.setattr(route_planning, "_load_route_graph", mock_load)
    monkeypatch.setattr(
        route_planning,
        "expand_targeted_bottleneck_parents",
        lambda idx, active, bottlenecks, max_additional=15: {"p_repaired"},
    )
    monkeypatch.setattr(route_planning, "_snap_evaluated", lambda *args, **kwargs: "c1")
    monkeypatch.setattr(
        route_planning, "_validate_route_plan_planner", lambda *args, **kwargs: None
    )

    cand_path = ("c1",)
    cand_id = candidate_id_for_path(cand_path)
    dummy_candidate = route_planning.RouteCandidate(
        candidate_id=cand_id,
        h3_path=cand_path,
        roles=(
            "fastest_eta",
            "shortest_distance",
            "max_passability_margin",
            "minimum_travel_cost",
        ),
        is_recommended=True,
        objectives={"eta_s": 1.0},
        metrics=PathMetrics(10.0, 1.0, 1.0, 1.0, True, 0.0, 10.0, 0.5, 0.8, 1),
        corridor_signature=("p1",),
    )
    monkeypatch.setattr(
        route_planning,
        "DeterministicParetoPlanner",
        lambda *args, **kwargs: type(
            "Planner",
            (),
            {"plan": lambda self, *a, **k: [dummy_candidate], "profile_search_count": 1},
        )(),
    )
    monkeypatch.setattr(
        route_planning,
        "select_robust_candidates",
        lambda *args, **kwargs: ([dummy_candidate], [], {}),
    )
    monkeypatch.setattr(
        route_planning,
        "CandidateAggregator",
        lambda *args, **kwargs: type(
            "Agg",
            (),
            {
                "aggregate": lambda self, *a, **k: type(
                    "AggResult",
                    (),
                    {
                        "candidates": [dummy_candidate],
                        "recommended_candidate_id": cand_id,
                        "independence_reference_candidate_id": None,
                        "statistics": {},
                        "warnings": [],
                    },
                )()
            },
        )(),
    )
    monkeypatch.setattr(route_planning, "write_effective_snapshots", lambda *args, **kwargs: None)
    monkeypatch.setattr(route_planning, "write_route_plan_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(route_planning, "atomic_write_json", lambda *args, **kwargs: None)

    plan = route_planning._run_route_plan_once(
        request,
        progress=None,
        progress_range=(75, 95),
        corridor_ring=1,
        request_started=0.0,
    )
    assert reachability_attempts == 2
    assert "TARGETED_CORRIDOR_REPAIR_APPLIED" in plan.warnings
    assert loaded_extra_parents[-1] == {"p_repaired"}


def test_targeted_dilation_fails_after_two_attempts_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(route_planning, "estimate_h3_cells_for_roi", lambda *args, **kwargs: 100)
    _mock_vehicle_and_factor(monkeypatch)
    Path(request.factor_model_path).write_text("model_version: '3.1'\n", encoding="utf-8")
    Path(request.vehicle_path).write_text("name: test\n", encoding="utf-8")
    Path(request.planner_config_path).write_text(
        "global_planner: DeterministicParetoPlanner\n", encoding="utf-8"
    )

    base_meta = {
        "artifact_kind": "h3_routing_index",
        "build_id": "test-repair",
        "source_manifest": "dummy.json",
        "active_parent_h3": ["p1"],
        "res_fine": 13,
        "res_coarse": 11,
    }
    monkeypatch.setattr(route_planning, "_source_metadata", lambda path: dict(base_meta))
    attempts = 0

    def mock_fail_check(*args: object, **kwargs: object) -> ReachabilityDiagnosis:
        nonlocal attempts
        attempts += 1
        diag = ReachabilityDiagnosis(
            reachable=False,
            bottleneck_parents=("p1",),
            boundary_blockage_cells=frozenset(["c1"]),
        )
        raise ReachabilityDisconnectionError("Endpoints disconnected", diagnosis=diag)

    def mock_load(
        req: object, roi: object, meta: dict[str, object], **kwargs: object
    ) -> tuple[H3Graph, dict[str, object]]:
        cell = H3Cell(
            "c1", 32.0, 119.0, 10.0, 1.0, 0.1, 1.0, parent_h3="p1", is_passable=True
        )
        cells = {"c1": cell}
        new_meta = {
            **meta,
            "artifact_kind": "h3_routing_index",
            "active_parent_h3": ["p1"],
            "source_manifest": "dummy.json",
        }
        return H3Graph(cells=cells, edges={}), new_meta

    monkeypatch.setattr(route_planning, "check_route_reachability", mock_fail_check)
    monkeypatch.setattr(route_planning, "_load_route_graph", mock_load)
    monkeypatch.setattr(
        route_planning,
        "expand_targeted_bottleneck_parents",
        lambda idx, active, bottlenecks, max_additional=15: {f"p_rep_{attempts}"},
    )
    monkeypatch.setattr(route_planning, "_snap_evaluated", lambda *args, **kwargs: "c1")
    monkeypatch.setattr(
        route_planning, "_validate_route_plan_planner", lambda *args, **kwargs: None
    )

    # After 2 repair attempts (initial check + attempt 1 + attempt 2 = 3 checks), it must raise
    with pytest.raises(ReachabilityDisconnectionError):
        route_planning._run_route_plan_once(
            request,
            progress=None,
            progress_range=(75, 95),
            corridor_ring=1,
            request_started=0.0,
        )
    assert attempts == 3


def test_expand_targeted_bottleneck_parents_prioritizes_primary_bottleneck(
    tmp_path: Path,
) -> None:
    from h3_offroad_planner.routing import expand_targeted_bottleneck_parents

    p1 = h3.latlng_to_cell(32.0, 119.0, 11)
    # Pick p2 far enough so their 1-rings are disjoint
    p2 = h3.latlng_to_cell(32.05, 119.05, 11)
    p1_disk = [str(c) for c in h3.grid_disk(p1, 1)]
    p2_disk = [str(c) for c in h3.grid_disk(p2, 1)]
    all_parents = set(p1_disk).union(p2_disk)

    rows = []
    for c in all_parents:
        for n in h3.grid_disk(c, 1):
            if str(n) in all_parents and str(n) > c:
                rows.append(_coarse_row(c, str(n), 1.0))

    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    current_active = {str(p1), str(p2)}

    # p1 has 6 neighbors outside current_active, p2 has 6 neighbors.
    # When bottleneck_parents = [p1, p2] and max_additional = 8:
    # All 6 neighbors of p1 must be chosen, and only 2 neighbors of p2.
    result = expand_targeted_bottleneck_parents(
        index, current_active, [str(p1), str(p2)], max_additional=8
    )
    assert len(result) == 8
    p1_nbrs = set(p1_disk) - current_active
    assert p1_nbrs.issubset(result)
    p2_nbrs_in_result = result - p1_nbrs
    assert len(p2_nbrs_in_result) == 2


def test_expand_targeted_bottleneck_parents_synthetic_topological_graph(
    tmp_path: Path,
) -> None:
    from h3_offroad_planner.routing import expand_targeted_bottleneck_parents

    rows = [
        _coarse_row("parent_A", "parent_B", 1.0),
        _coarse_row("parent_A", "parent_C", 1.0),
        _coarse_row("parent_B", "parent_D", 1.0),
    ]
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    current = {"parent_A"}
    new_parents = expand_targeted_bottleneck_parents(
        index, current, ["parent_A"], max_additional=15
    )
    assert new_parents == {"parent_B", "parent_C"}


def test_expanded_corridor_parents_synthetic_parents(tmp_path: Path) -> None:
    from h3_offroad_planner.routing import _expanded_corridor_parents

    rows = [
        _coarse_row("syn_1", "syn_2", 1.0),
        _coarse_row("syn_2", "syn_3", 1.0),
    ]
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    skeletons = {"distance": ["syn_1", "syn_2"]}
    active = _expanded_corridor_parents(index, skeletons, ring=1)
    assert active == {"syn_1", "syn_2"}
