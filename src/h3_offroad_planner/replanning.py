"""Persistent product-state controller around the in-memory D* Lite algorithm core."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import atan2, cos, inf, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import cast

from h3_offroad_planner.candidate_aggregation import CandidateAggregator
from h3_offroad_planner.factor_model import (
    FactorEvaluation,
    canonical_hash,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError
from h3_offroad_planner.models import Path as PlannerPath
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.planners.dstar_lite import DStarLiteReplanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.route_models import (
    BlockageRecord,
    ReplanRequest,
    ReplanResult,
    RouteSelection,
)
from h3_offroad_planner.route_persistence import (
    atomic_write_json,
    load_route_plan,
    load_route_selection,
    write_active_route_state,
)

__all__ = ["ReplanPolicy", "replan_route"]

EPSILON: float = 1.0e-9


@dataclass(frozen=True)
class ReplanPolicy:
    """Explicit bounded confirmation, timing, and fallback-loop controls."""

    confirmation_threshold: int = 2
    debounce_window_s: float = 1.0
    cooldown_s: float = 2.0
    recent_failed_corridor_ttl_s: float = 120.0
    global_fallback_window_s: float = 300.0
    max_global_fallbacks: int = 3

    def __post_init__(self) -> None:
        if self.confirmation_threshold <= 0 or self.max_global_fallbacks <= 0:
            raise ValueError("replan count thresholds must be positive.")
        values = (
            self.debounce_window_s,
            self.cooldown_s,
            self.recent_failed_corridor_ttl_s,
            self.global_fallback_window_s,
        )
        if any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("replan time windows must be finite and non-negative.")


class _FrozenRoleCost:
    """Read-only role-specific edge-cost adapter consumed by D* Lite."""

    def __init__(
        self,
        evaluation: FactorEvaluation,
        role: str,
        passability_threshold: float,
    ) -> None:
        self.evaluation = evaluation
        self.role = role
        self.passability_threshold = passability_threshold

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Return selected-role movement cost without recalculating any factor."""
        if from_cell not in graph.cells or to_cell not in graph.cells:
            raise KeyError("D* Lite edge endpoint is absent from overlay graph.")
        if not graph.cells[from_cell].is_passable or not graph.cells[to_cell].is_passable:
            return inf
        edge = self.evaluation.directed_edges.get((from_cell, to_cell))
        if edge is None:
            return inf
        if self.role == "max_passability_margin":
            if edge.safety_margin_lower < self.passability_threshold - EPSILON:
                return inf
            return edge.terrain_risk
        if self.role == "shortest_distance":
            return edge.distance_m
        if self.role == "minimum_travel_cost":
            return edge.travel_cost
        return edge.eta_s

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Use a universally admissible zero estimate across heterogeneous role units."""
        if first not in graph.cells or second not in graph.cells:
            raise KeyError("D* Lite heuristic endpoints are absent from overlay graph.")
        return 0.0


def replan_route(
    request: ReplanRequest,
    graph: H3Graph,
    evaluation: FactorEvaluation,
    policy: ReplanPolicy | None = None,
) -> ReplanResult:
    """Apply blockage lifecycle, repair locally, and perform bounded global fallback."""
    effective_policy = policy or ReplanPolicy()
    selection = load_route_selection(request.selection_path)
    _validate_hashes(selection, evaluation)
    output_dir = str(Path(request.selection_path).parent)
    history_path = Path(output_dir) / "replan_history.jsonl"
    history = _load_history(history_path)
    previous_records = _latest_blockages(history)
    records = _merge_blockages(
        previous_records,
        request.blockage_observations,
        request.now_epoch_s,
        effective_policy,
    )
    previous_confirmed = {
        record.h3index for record in previous_records.values() if record.state == "confirmed"
    }
    confirmed = {record.h3index for record in records.values() if record.state == "confirmed"}
    missing_blockages = sorted(confirmed.difference(graph.cells))
    if missing_blockages:
        raise PlanningInputError(
            f"confirmed blockages are absent from the planning graph: {missing_blockages}"
        )
    current = _resolve_current(request, graph, evaluation)
    if current in confirmed:
        raise PlanningInputError("current vehicle cell cannot be a confirmed blockage.")
    goal = selection.active_h3_path[-1]
    unchanged_warning = _unchanged_warning(
        history,
        previous_confirmed,
        confirmed,
        request.now_epoch_s,
        effective_policy,
    )
    if unchanged_warning is not None:
        result = _unchanged_result(selection, unchanged_warning)
        _persist_replan(
            output_dir,
            graph,
            selection,
            result,
            records,
            request.now_epoch_s,
            set(),
            effective_policy,
        )
        return result
    overlay = _overlay_graph(graph)
    cost = _FrozenRoleCost(
        evaluation,
        selection.selected_role,
        selection.active_metrics.safety_margin_min,
    )
    failed_corridor: set[str] = set()
    try:
        repaired = DStarLiteReplanner(cost).replan(
            overlay,
            confirmed,
            PlannerPath([current, goal], 0.0),
        )
        metrics = evaluate_path_metrics(repaired.cells, evaluation)
        updated = replace(
            selection,
            active_h3_path=tuple(repaired.cells),
            active_metrics=metrics,
            state="active",
            replan_version=selection.replan_version + 1,
        )
        result = _result(selection, updated, "DStarLite")
    except PlanningFailedError:
        failed_corridor = set(selection.active_h3_path[1:-1])
        failed_corridor.difference_update({current, goal})
        updated, result = _global_fallback(
            selection,
            graph,
            evaluation,
            confirmed,
            history,
            request.now_epoch_s,
            effective_policy,
            output_dir,
            current,
            failed_corridor,
        )
    _persist_replan(
        output_dir,
        graph,
        updated,
        result,
        records,
        request.now_epoch_s,
        failed_corridor,
        effective_policy,
    )
    return result


def _global_fallback(
    selection: RouteSelection,
    graph: H3Graph,
    evaluation: FactorEvaluation,
    confirmed: set[str],
    history: list[dict[str, object]],
    now_epoch_s: float,
    policy: ReplanPolicy,
    output_dir: str,
    current: str,
    failed_corridor: set[str],
) -> tuple[RouteSelection, ReplanResult]:
    recent = _recent_global_fallbacks(history, now_epoch_s, policy.global_fallback_window_s)
    if recent >= policy.max_global_fallbacks:
        held = replace(selection, state="safe_hold")
        return held, _result(
            selection,
            held,
            "safe_hold",
            warnings=("GLOBAL_FALLBACK_RATE_LIMIT_EXCEEDED",),
        )
    plan = load_route_plan(str(Path(output_dir) / "route_plan.json"))
    context = PortsMapSearchContext(graph, evaluation)
    recent_failed = _recent_failed_cells(
        history,
        now_epoch_s,
        policy.recent_failed_corridor_ttl_s,
    )
    blocked = frozenset(confirmed.union(recent_failed).union(failed_corridor))
    try:
        raw = DeterministicParetoPlanner(context).plan(
            current,
            selection.active_h3_path[-1],
            blocked,
        )
        aggregation = CandidateAggregator(graph, context).aggregate(raw, plan.mission_profile, 5)
        candidate = next(
            item
            for item in aggregation.candidates
            if item.candidate_id == aggregation.recommended_candidate_id
        )
        updated = replace(
            selection,
            candidate_id=candidate.candidate_id,
            active_h3_path=candidate.h3_path,
            active_metrics=candidate.metrics,
            state="active",
            replan_version=selection.replan_version + 1,
        )
        return updated, _result(selection, updated, "global_fallback", aggregation.warnings)
    except PlanningFailedError:
        invalidated = replace(selection, state="invalidated")
        return invalidated, _result(
            selection,
            invalidated,
            "global_fallback",
            warnings=("GLOBAL_ROUTE_UNAVAILABLE",),
            has_new_path=False,
        )


def _merge_blockages(
    previous: dict[str, BlockageRecord],
    observations: tuple[BlockageRecord, ...],
    now_epoch_s: float,
    policy: ReplanPolicy,
) -> dict[str, BlockageRecord]:
    merged = dict(previous)
    for blockage_id, record in list(merged.items()):
        if (
            not record.mission_lifetime
            and record.state in {"tentative", "confirmed"}
            and record.expires_at_epoch_s is not None
            and now_epoch_s >= record.expires_at_epoch_s
        ):
            merged[blockage_id] = replace(record, state="expired")
    for observation in observations:
        current = merged.get(observation.blockage_id)
        if current is not None and current.state in {"cleared", "expired"}:
            continue
        state = observation.state
        if state not in {"cleared", "expired"}:
            count = observation.confirmation_count
            if current is not None:
                count += current.confirmation_count
            confirmed = observation.trusted_source or count >= policy.confirmation_threshold
            if current is not None and current.state == "confirmed":
                confirmed = True
            state = "confirmed" if confirmed else "tentative"
            observation = replace(observation, confirmation_count=count)
        merged[observation.blockage_id] = replace(observation, state=state)
    return merged


def _unchanged_warning(
    history: list[dict[str, object]],
    previous_confirmed: set[str],
    confirmed: set[str],
    now_epoch_s: float,
    policy: ReplanPolicy,
) -> str | None:
    if previous_confirmed != confirmed:
        return None
    latest = _latest_history_epoch(history)
    if latest is not None and now_epoch_s - latest < policy.debounce_window_s:
        return "BLOCKAGE_DEBOUNCE_WINDOW_ACTIVE"
    if latest is not None and now_epoch_s - latest < policy.cooldown_s:
        return "REPLAN_COOLDOWN_ACTIVE"
    return "BLOCKAGE_DEBOUNCED_NO_EDGE_CHANGE"


def _unchanged_result(selection: RouteSelection, warning: str) -> ReplanResult:
    path_hash = canonical_hash(list(selection.active_h3_path))
    return ReplanResult(
        plan_id=selection.plan_id,
        candidate_id=selection.candidate_id,
        algorithm="DStarLite",
        status=selection.state,
        replan_version=selection.replan_version,
        old_path_hash=path_hash,
        new_path_hash=path_hash,
        metrics_before=selection.active_metrics,
        metrics_after=selection.active_metrics,
        warnings=(warning,),
    )


def _result(
    before: RouteSelection,
    after: RouteSelection,
    algorithm: str,
    warnings: tuple[str, ...] = (),
    has_new_path: bool = True,
) -> ReplanResult:
    return ReplanResult(
        plan_id=before.plan_id,
        candidate_id=after.candidate_id,
        algorithm=algorithm,
        status=after.state,
        replan_version=after.replan_version,
        old_path_hash=canonical_hash(list(before.active_h3_path)),
        new_path_hash=canonical_hash(list(after.active_h3_path)) if has_new_path else None,
        metrics_before=before.active_metrics,
        metrics_after=after.active_metrics if has_new_path else None,
        warnings=warnings,
    )


def _persist_replan(
    output_dir: str,
    graph: H3Graph,
    selection: RouteSelection,
    result: ReplanResult,
    blockages: Mapping[str, BlockageRecord],
    now_epoch_s: float,
    failed_corridor: set[str],
    policy: ReplanPolicy,
) -> None:
    atomic_write_json(Path(output_dir) / "route_selection.json", selection.to_dict())
    ordered = tuple(sorted(blockages.values(), key=lambda item: item.blockage_id))
    write_active_route_state(output_dir, selection, graph, ordered)
    event = {
        "schema_version": 1,
        "event_epoch_s": now_epoch_s,
        "plan_id": result.plan_id,
        "candidate_id": result.candidate_id,
        "algorithm": result.algorithm,
        "status": result.status,
        "replan_version": result.replan_version,
        "old_path_hash": result.old_path_hash,
        "new_path_hash": result.new_path_hash,
        "metrics_before": result.metrics_before.to_dict(),
        "metrics_after": None if result.metrics_after is None else result.metrics_after.to_dict(),
        "warnings": list(result.warnings),
        "blockages": [asdict(record) for record in ordered],
        "failed_corridor_cells": sorted(failed_corridor),
        "failed_corridor_expires_at_epoch_s": (
            now_epoch_s + policy.recent_failed_corridor_ttl_s
            if failed_corridor
            else None
        ),
    }
    _append_history_atomic(Path(output_dir) / "replan_history.jsonl", event)


def _overlay_graph(graph: H3Graph) -> H3Graph:
    cells = {cell_id: replace(cell) for cell_id, cell in graph.cells.items()}
    return H3Graph(
        resolution_fine=graph.resolution_fine,
        resolution_coarse=graph.resolution_coarse,
        cells=cells,
        edges=dict(graph.edges),
        parent_children={
            parent: set(children) for parent, children in graph.parent_children.items()
        },
    )


def _resolve_current(
    request: ReplanRequest,
    graph: H3Graph,
    evaluation: FactorEvaluation,
) -> str:
    if request.current_h3 is not None:
        if request.current_h3 not in graph.cells:
            raise PlanningInputError("current_h3 is absent from the planning graph.")
        return request.current_h3
    if request.current_lat is None or request.current_lng is None:
        raise PlanningInputError("current coordinates are incomplete.")
    best_cell = ""
    best_distance = inf
    for cell_id in sorted(graph.cells):
        if not evaluation.node_metrics[cell_id].is_passable:
            continue
        cell = graph.cells[cell_id]
        distance = _haversine_m(request.current_lat, request.current_lng, cell.lat, cell.lng)
        if distance < best_distance:
            best_cell = cell_id
            best_distance = distance
    if not best_cell or best_distance > request.snap_distance_m:
        raise PlanningInputError("current coordinates cannot be snapped within snap_distance_m.")
    return best_cell


def _validate_hashes(selection: RouteSelection, evaluation: FactorEvaluation) -> None:
    pairs = (
        (selection.vehicle_hash, evaluation.vehicle_hash),
        (selection.factor_model_hash, evaluation.factor_model_hash),
        (selection.static_input_hash, evaluation.static_input_hash),
        (selection.graph_topology_hash, evaluation.graph_topology_hash),
    )
    if any(expected != actual for expected, actual in pairs):
        raise PlanningInputError("ROUTE_SELECTION_HASH_MISMATCH_REPLAN_REQUIRED")


def _load_history(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("history event must be an object")
            events.append(cast(dict[str, object], payload))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PlanningInputError("replan history is corrupt.") from exc
    return events


def _latest_blockages(history: list[dict[str, object]]) -> dict[str, BlockageRecord]:
    if not history:
        return {}
    raw = history[-1].get("blockages", [])
    if not isinstance(raw, list):
        raise PlanningInputError("replan history blockages must be an array.")
    result = {}
    for item in raw:
        if not isinstance(item, dict):
            raise PlanningInputError("replan blockage history entries must be objects.")
        record = _blockage_from_mapping(cast(dict[str, object], item))
        result[record.blockage_id] = record
    return result


def _blockage_from_mapping(payload: Mapping[str, object]) -> BlockageRecord:
    expires = payload.get("expires_at_epoch_s")
    return BlockageRecord(
        blockage_id=_string(payload, "blockage_id"),
        h3index=_string(payload, "h3index"),
        state=_string(payload, "state"),
        confirmation_count=_integer(payload, "confirmation_count"),
        trusted_source=_boolean(payload, "trusted_source"),
        observed_at_epoch_s=_number(payload, "observed_at_epoch_s"),
        expires_at_epoch_s=(
            None if expires is None else _number_value(expires, "expires_at_epoch_s")
        ),
        mission_lifetime=_boolean(payload, "mission_lifetime"),
        source=_string(payload, "source"),
    )


def _recent_global_fallbacks(
    history: list[dict[str, object]],
    now_epoch_s: float,
    window_s: float,
) -> int:
    return sum(
        event.get("algorithm") == "global_fallback"
        and now_epoch_s - _event_epoch(event) <= window_s
        for event in history
    )


def _recent_failed_cells(
    history: list[dict[str, object]],
    now_epoch_s: float,
    ttl_s: float,
) -> set[str]:
    cells: set[str] = set()
    for event in history:
        event_epoch = _event_epoch(event)
        if now_epoch_s - event_epoch > ttl_s:
            continue
        expiry = event.get("failed_corridor_expires_at_epoch_s")
        if expiry is not None and now_epoch_s >= _number_value(expiry, "failed corridor expiry"):
            continue
        raw = event.get("failed_corridor_cells", [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise PlanningInputError("failed corridor history must be an array of strings.")
        cells.update(cast(list[str], raw))
    return cells


def _latest_history_epoch(history: list[dict[str, object]]) -> float | None:
    return None if not history else _event_epoch(history[-1])


def _event_epoch(event: Mapping[str, object]) -> float:
    return _number(event, "event_epoch_s")


def _append_history_atomic(path: Path, event: dict[str, object]) -> None:
    lines = [] if not path.exists() else path.read_text(encoding="utf-8").splitlines()
    lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
        stream.write("\n")
    temporary.replace(path)


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_m = 6_371_000.0
    delta_lat = radians(lat_b - lat_a)
    delta_lng = radians(lng_b - lng_a)
    first_lat = radians(lat_a)
    second_lat = radians(lat_b)
    root = sin(delta_lat / 2.0) ** 2
    root += cos(first_lat) * cos(second_lat) * sin(delta_lng / 2.0) ** 2
    return 2.0 * earth_radius_m * atan2(sqrt(root), sqrt(max(0.0, 1.0 - root)))


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PlanningInputError(f"blockage field {key!r} must be a non-empty string.")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"blockage field {key!r} must be an integer.")
    return value


def _boolean(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise PlanningInputError(f"blockage field {key!r} must be boolean.")
    return value


def _number(payload: Mapping[str, object], key: str) -> float:
    if key not in payload:
        raise PlanningInputError(f"blockage field {key!r} is required.")
    return _number_value(payload[key], key)


def _number_value(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"blockage field {key!r} must be numeric.")
    return float(value)
