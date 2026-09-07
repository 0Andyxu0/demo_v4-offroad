"""Spec-derived persistent D* Lite blockage and recovery state-flow tests."""

from __future__ import annotations

from dataclasses import replace
from math import inf
from pathlib import Path

import pytest

from h3_offroad_planner.factor_model import (
    FactorEvaluation,
    FactorModelConfig,
    evaluate_factor_model,
)
from h3_offroad_planner.models import PlanningInputError, VehicleProfile
from h3_offroad_planner.replanning import (
    ReplanPolicy,
    _FrozenRoleCost,
    _global_fallback,
    replan_route,
)
from h3_offroad_planner.route_models import BlockageRecord, ReplanRequest
from h3_offroad_planner.route_persistence import (
    load_route_graph_snapshot,
    load_route_selection,
    select_route,
    write_route_plan_outputs,
)
from tests.test_closed_loop_persistence import _plan_fixture


def test_cl028_confirmed_blockage_repairs_overlay_without_mutating_base(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-028: confirmed blockage changes the active route on a cloned overlay only."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    blocked_cell = selection.active_h3_path[1]
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    result = replan_route(
        ReplanRequest(
            selection_path=str(tmp_path / "route_selection.json"),
            current_h3=selection.active_h3_path[0],
            blockage_observations=(
                _blockage("block-1", blocked_cell, "tentative", 1.0, trusted=True),
            ),
            now_epoch_s=1.0,
        ),
        graph,
        evaluation,
    )
    updated = load_route_selection(str(tmp_path / "route_selection.json"))
    assert result.algorithm == "DStarLite"
    assert updated.replan_version == 1
    assert blocked_cell not in updated.active_h3_path
    assert graph.cells[blocked_cell].is_passable is True


def test_cl029_cleared_and_expired_blockages_restore_edges(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-029: cleared and TTL-expired records rebuild from the unmodified base graph."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    original = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    blocked_cell = original.active_h3_path[1]
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    confirmed = _blockage(
        "block-ttl",
        blocked_cell,
        "tentative",
        1.0,
        trusted=True,
        expires=4.0,
    )
    replan_route(
        ReplanRequest(
            str(tmp_path / "route_selection.json"),
            (confirmed,),
            current_h3=original.active_h3_path[0],
            now_epoch_s=1.0,
        ),
        graph,
        evaluation,
    )
    replan_route(
        ReplanRequest(
            str(tmp_path / "route_selection.json"),
            (),
            current_h3=original.active_h3_path[0],
            now_epoch_s=5.0,
        ),
        graph,
        evaluation,
    )
    restored = load_route_selection(str(tmp_path / "route_selection.json"))
    assert restored.active_h3_path == original.active_h3_path
    assert restored.replan_version == 2


def test_cl030_tentative_observation_is_debounced_without_path_version(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-030: an unconfirmed observation persists but does not trigger edge repair."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    result = replan_route(
        ReplanRequest(
            str(tmp_path / "route_selection.json"),
            (_blockage("tentative", selection.active_h3_path[1], "tentative", 1.0),),
            current_h3=selection.active_h3_path[0],
            now_epoch_s=1.0,
        ),
        graph,
        evaluation,
    )
    assert result.replan_version == 0
    assert result.warnings == ("BLOCKAGE_DEBOUNCED_NO_EDGE_CHANGE",)


def test_cl031_restart_snapshot_and_hash_mismatch_guard(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-031: restart restores graph state; vehicle/hash changes reject local repair."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    restored_graph = load_route_graph_snapshot(str(tmp_path / "route_manifest.json"))
    restored_evaluation = evaluate_factor_model(restored_graph, vehicle, FactorModelConfig())
    result = replan_route(
        ReplanRequest(
            str(tmp_path / "route_selection.json"),
            (),
            current_h3=selection.active_h3_path[0],
            now_epoch_s=1.0,
        ),
        restored_graph,
        restored_evaluation,
    )
    assert result.status == "active"
    changed_vehicle = replace(vehicle, max_speed_kmh=vehicle.max_speed_kmh + 1.0)
    changed = evaluate_factor_model(restored_graph, changed_vehicle, FactorModelConfig())
    with pytest.raises(PlanningInputError, match="HASH_MISMATCH"):
        replan_route(
            ReplanRequest(
                str(tmp_path / "route_selection.json"),
                (),
                current_h3=selection.active_h3_path[0],
                now_epoch_s=10.0,
            ),
            restored_graph,
            changed,
        )
    changed_model = evaluate_factor_model(
        restored_graph,
        vehicle,
        FactorModelConfig(epsilon=0.01),
    )
    assert changed_model.factor_model_hash != restored_evaluation.factor_model_hash
    with pytest.raises(
        PlanningInputError,
        match="ROUTE_SELECTION_HASH_MISMATCH_REPLAN_REQUIRED",
    ):
        replan_route(
            ReplanRequest(
                str(tmp_path / "route_selection.json"),
                (),
                current_h3=selection.active_h3_path[0],
                now_epoch_s=11.0,
            ),
            restored_graph,
            changed_model,
        )


def test_cl032_confirmation_count_promotes_tentative_record(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-032: repeated untrusted observations cross the configured confirmation count."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    cell_id = selection.active_h3_path[1]
    policy = ReplanPolicy(confirmation_threshold=2, cooldown_s=0.0, debounce_window_s=0.0)
    first = ReplanRequest(
        str(tmp_path / "route_selection.json"),
        (_blockage("repeat", cell_id, "tentative", 1.0),),
        current_h3=selection.active_h3_path[0],
        now_epoch_s=1.0,
    )
    replan_route(first, graph, evaluation, policy)
    second = ReplanRequest(
        str(tmp_path / "route_selection.json"),
        (_blockage("repeat", cell_id, "tentative", 2.0),),
        current_h3=selection.active_h3_path[0],
        now_epoch_s=2.0,
    )
    result = replan_route(second, graph, evaluation, policy)
    assert result.replan_version == 1
    persisted = load_route_selection(str(tmp_path / "route_selection.json"))
    assert cell_id not in persisted.active_h3_path


@pytest.mark.parametrize(
    "changes",
    (
        {"confirmation_threshold": 0},
        {"max_global_fallbacks": 0},
        {"debounce_window_s": -1.0},
        {"cooldown_s": float("nan")},
    ),
)
def test_replan_policy_rejects_unbounded_or_invalid_controls(changes: dict[str, object]) -> None:
    """All lifecycle and loop-protection controls have finite explicit bounds."""
    with pytest.raises(ValueError):
        ReplanPolicy(**changes)  # type: ignore[arg-type]


def test_cl034_role_cost_reads_only_frozen_edge_metrics(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Every selected role maps to its frozen edge metric or passability threshold."""
    graph, _ = _plan_fixture(tmp_path, vehicle)
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    first, second = next(iter(evaluation.directed_edges))
    edge = evaluation.directed_edges[(first, second)]

    assert _FrozenRoleCost(evaluation, "shortest_distance", 0.0).compute(
        graph, first, second
    ) == edge.distance_m
    assert _FrozenRoleCost(evaluation, "minimum_travel_cost", 0.0).compute(
        graph, first, second
    ) == edge.travel_cost
    assert _FrozenRoleCost(evaluation, "fastest_eta", 0.0).compute(
        graph, first, second
    ) == edge.eta_s
    assert _FrozenRoleCost(evaluation, "max_passability_margin", 0.0).compute(
        graph, first, second
    ) == edge.terrain_risk
    assert _FrozenRoleCost(evaluation, "max_passability_margin", 1.1).compute(
        graph, first, second
    ) == inf

    lower_edge = replace(
        edge,
        safety_margin_lower=0.4,
        safety_margin_nominal=0.4,
        safety_margin_upper=0.4,
    )
    directional = dict(evaluation.directed_edges)
    directional[(first, second)] = lower_edge
    directional_evaluation = FactorEvaluation(
        evaluation.node_metrics,
        directional,
        evaluation.vehicle_hash,
        evaluation.factor_model_hash,
        evaluation.static_input_hash,
        evaluation.graph_topology_hash,
    )
    assert evaluation.node_metrics[second].safety_margin.lower > 0.5
    assert _FrozenRoleCost(
        directional_evaluation,
        "max_passability_margin",
        0.5,
    ).compute(graph, first, second) == inf

    graph.cells[second].is_passable = False
    assert _FrozenRoleCost(evaluation, "fastest_eta", 0.0).compute(
        graph, first, second
    ) == inf
    graph.cells[second].is_passable = True
    missing_pair = next(
        (a, b)
        for a in graph.cells
        for b in graph.cells
        if a != b and (a, b) not in evaluation.directed_edges
    )
    assert _FrozenRoleCost(evaluation, "fastest_eta", 0.0).compute(
        graph, *missing_pair
    ) == inf
    with pytest.raises(KeyError, match="absent"):
        _FrozenRoleCost(evaluation, "fastest_eta", 0.0).compute(graph, "missing", second)
    role_cost = _FrozenRoleCost(evaluation, "fastest_eta", 0.0)
    assert role_cost.heuristic(graph, first, second) == 0.0
    with pytest.raises(KeyError, match="absent"):
        role_cost.heuristic(graph, first, "missing")


def test_cl035_global_fallback_rate_limit_and_no_route_states(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Bounded fallback enters safe_hold, while a proven no-route state invalidates selection."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    held, held_result = _global_fallback(
        selection,
        graph,
        evaluation,
        set(),
        [{"algorithm": "global_fallback", "event_epoch_s": 1.0}],
        2.0,
        ReplanPolicy(max_global_fallbacks=1),
        str(tmp_path),
        selection.active_h3_path[0],
        set(),
    )
    assert held.state == "safe_hold"
    assert held_result.algorithm == "safe_hold"
    assert held_result.warnings == ("GLOBAL_FALLBACK_RATE_LIMIT_EXCEEDED",)

    invalidated, invalid_result = _global_fallback(
        selection,
        graph,
        evaluation,
        {selection.active_h3_path[-1]},
        [],
        2.0,
        ReplanPolicy(),
        str(tmp_path),
        selection.active_h3_path[0],
        set(selection.active_h3_path[1:-1]),
    )
    assert invalidated.state == "invalidated"
    assert invalid_result.new_path_hash is None
    assert invalid_result.metrics_after is None
    assert invalid_result.warnings == ("GLOBAL_ROUTE_UNAVAILABLE",)


def _blockage(
    blockage_id: str,
    h3index: str,
    state: str,
    observed: float,
    trusted: bool = False,
    expires: float | None = None,
) -> BlockageRecord:
    return BlockageRecord(
        blockage_id=blockage_id,
        h3index=h3index,
        state=state,
        confirmation_count=1,
        trusted_source=trusted,
        observed_at_epoch_s=observed,
        expires_at_epoch_s=expires,
        source="test",
    )
