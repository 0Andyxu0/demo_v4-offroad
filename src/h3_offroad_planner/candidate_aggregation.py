"""Candidate validation, Pareto filtering, corridor roles, and disruption survival."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isclose, isfinite

from h3_offroad_planner.factor_model import (
    PHYSICAL_EVIDENCE_WARNING,
    DecisionConfig,
    PathMetrics,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError
from h3_offroad_planner.planners.deterministic_pareto import GeneratedPath
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile
from h3_offroad_planner.route_models import (
    MISSION_PROFILES,
    PATH_ROLES,
    RouteCandidate,
    candidate_id_for_path,
)

__all__ = ["AggregationResult", "CandidateAggregator", "select_robust_candidates"]

EPSILON: float = 1.0e-9
MISSION_ROLE: dict[str, str] = {
    "fastest": "fastest_eta",
    "shortest": "shortest_distance",
    "passability": "max_passability_margin",
    "economy": "minimum_travel_cost",
    "resilient": "independent_backup",
}
REPLAN_PROFILE: dict[str, str] = {
    "fastest_eta": "eta",
    "shortest_distance": "distance",
    "max_passability_margin": "passability_then_terrain_risk",
    "minimum_travel_cost": "travel_cost",
    "independent_backup": "resilient_eta",
}


@dataclass(frozen=True)
class AggregationResult:
    """Unique role candidates or a bounded pre-display candidate pool."""

    candidates: tuple[RouteCandidate, ...]
    recommended_candidate_id: str
    independence_reference_candidate_id: str | None
    warnings: tuple[str, ...]
    statistics: dict[str, object]


class CandidateAggregator:
    """Aggregate raw deterministic paths into five fixed product roles."""

    def __init__(
        self,
        graph: H3Graph,
        context: PortsMapSearchContext,
        disruption_radius: int = 0,
    ) -> None:
        """Initialize corridor and disruption analysis for one immutable graph."""
        if disruption_radius < 0:
            raise ValueError("disruption_radius must be non-negative.")
        self.graph = graph
        self.context = context
        self.disruption_radius = disruption_radius

    def aggregate(
        self,
        raw_candidates: list[GeneratedPath],
        mission_profile: str,
        max_candidates: int = 5,
        *,
        preserve_pool: bool = False,
    ) -> AggregationResult:
        """Return exact unique candidates, merged roles, and mission recommendation."""
        if mission_profile not in MISSION_PROFILES:
            raise ValueError(f"mission_profile must be one of {MISSION_PROFILES!r}.")
        if not 1 <= max_candidates <= 5:
            raise ValueError("max_candidates must be in [1, 5].")
        if not 1 <= len(raw_candidates) <= 24:
            raise ValueError("raw_candidates must contain between 1 and 24 paths.")
        validated = self._validated_unique(raw_candidates)
        pareto = _pareto_candidates(validated)
        representatives = (
            dict(validated) if preserve_pool else self._cluster_representatives(pareto)
        )
        roles = _assign_metric_roles(representatives)
        fastest_path = next(
            path for path, assigned_roles in roles.items() if "fastest_eta" in assigned_roles
        )
        fastest = representatives[fastest_path]
        independent, evidence = self._independent_backup(fastest, validated)
        if independent is not None:
            representatives[independent.h3_path] = independent
            roles.setdefault(independent.h3_path, []).append("independent_backup")
        candidates = self._route_candidates(
            representatives,
            roles,
            evidence,
            include_unassigned=preserve_pool,
        )
        recommended, reference, warnings = _recommendation(
            mission_profile,
            candidates,
            candidate_id_for_path(fastest.h3_path),
        )
        warnings = (*warnings, *self._evidence_warnings(candidates))
        candidates = tuple(
            replace(candidate, is_recommended=candidate.candidate_id == recommended)
            for candidate in candidates
        )
        if preserve_pool:
            candidates = _truncate_candidate_pool(candidates, recommended, 24)
        else:
            candidates = _truncate_candidates(candidates, recommended, max_candidates)
        if recommended not in {candidate.candidate_id for candidate in candidates}:
            raise PlanningFailedError("candidate truncation removed the recommended route.")
        return AggregationResult(
            candidates=candidates,
            recommended_candidate_id=recommended,
            independence_reference_candidate_id=reference,
            warnings=warnings,
            statistics={
                "raw_count": len(raw_candidates),
                "unique_count": len(validated),
                "pareto_count": len(pareto),
                "cluster_representative_count": len(representatives),
                "returned_count": len(candidates),
                "independent_backup_available": independent is not None,
            },
        )

    def _evidence_warnings(
        self,
        candidates: tuple[RouteCandidate, ...],
    ) -> tuple[str, ...]:
        incomplete = any(
            self.context.evaluation.node_metrics[cell_id].confidence < 1.0
            for candidate in candidates
            for cell_id in candidate.h3_path
        )
        return (PHYSICAL_EVIDENCE_WARNING,) if incomplete else ()

    def _validated_unique(
        self,
        raw_candidates: list[GeneratedPath],
    ) -> dict[tuple[str, ...], GeneratedPath]:
        unique: dict[tuple[str, ...], GeneratedPath] = {}
        for candidate in raw_candidates:
            exact = evaluate_path_metrics(candidate.h3_path, self.context.evaluation)
            if not _same_metrics(candidate.metrics, exact):
                raise PlanningInputError("candidate metrics do not match its expanded H3 path.")
            previous = unique.get(candidate.h3_path)
            if previous is None or candidate.generation_profile < previous.generation_profile:
                unique[candidate.h3_path] = candidate
        return unique

    def _cluster_representatives(
        self,
        candidates: dict[tuple[str, ...], GeneratedPath],
    ) -> dict[tuple[str, ...], GeneratedPath]:
        clusters: dict[tuple[object, ...], list[GeneratedPath]] = {}
        for candidate in candidates.values():
            signature = self._corridor_signature(candidate.h3_path)
            metric_bucket = (
                round(candidate.metrics.eta_s, 3),
                round(candidate.metrics.distance_m, 3),
                round(candidate.metrics.safety_margin_min, 6),
            )
            clusters.setdefault((signature, *metric_bucket), []).append(candidate)
        representatives: dict[tuple[str, ...], GeneratedPath] = {}
        for cluster in clusters.values():
            representative = min(cluster, key=_balanced_tie_key)
            representatives[representative.h3_path] = representative
        return representatives

    def _independent_backup(
        self,
        reference: GeneratedPath,
        existing: dict[tuple[str, ...], GeneratedPath],
    ) -> tuple[GeneratedPath | None, dict[str, object]]:
        core = set(self._corridor_signature(reference.h3_path))
        if not core:
            return None, {}
        masked_parents = self._dilated_parents(core)
        endpoints = {reference.h3_path[0], reference.h3_path[-1]}
        blocked = frozenset(
            cell_id
            for cell_id in self.graph.cells
            if self._parent(cell_id) in masked_parents and cell_id not in endpoints
        )
        survivors = [
            candidate
            for candidate in existing.values()
            if candidate.h3_path != reference.h3_path
            and not blocked.intersection(candidate.h3_path)
        ]
        try:
            result = self.context.search(
                reference.h3_path[0],
                reference.h3_path[-1],
                ScalarProfile({"eta": 1.0}, name="independent_disruption_eta"),
                blocked,
            )
            survivors.append(
                GeneratedPath(
                    result.h3_path,
                    result.metrics,
                    "independent_disruption",
                    result.scalar_cost,
                )
            )
        except PlanningFailedError:
            pass
        survivors = [
            candidate for candidate in survivors if not blocked.intersection(candidate.h3_path)
        ]
        if not survivors:
            return None, {}
        independent = max(
            {candidate.h3_path: candidate for candidate in survivors}.values(),
            key=lambda candidate: self._independence_key(reference, candidate),
        )
        evidence = {
            "reference_candidate_id": candidate_id_for_path(reference.h3_path),
            "blocked_core_parents": sorted(core),
            "masked_parents": sorted(masked_parents),
            "blocked_cells_count": len(blocked),
            "survived_disruption": True,
            "candidate_corridor": list(self._corridor_signature(independent.h3_path)),
        }
        return independent, evidence

    def _independence_key(
        self,
        reference: GeneratedPath,
        candidate: GeneratedPath,
    ) -> tuple[int, int, float, float, float, tuple[int, ...]]:
        reference_corridor = set(self._corridor_signature(reference.h3_path))
        candidate_corridor = set(self._corridor_signature(candidate.h3_path))
        difference = len(reference_corridor.symmetric_difference(candidate_corridor))
        overlap = len(reference_corridor.intersection(candidate_corridor))
        return (
            difference,
            -overlap,
            -candidate.metrics.terrain_risk,
            -candidate.metrics.eta_s,
            -candidate.metrics.distance_m,
            tuple(-ord(char) for char in "|".join(candidate.h3_path)),
        )

    def _route_candidates(
        self,
        representatives: dict[tuple[str, ...], GeneratedPath],
        roles: dict[tuple[str, ...], list[str]],
        evidence: dict[str, object],
        *,
        include_unassigned: bool = False,
    ) -> tuple[RouteCandidate, ...]:
        candidates = []
        paths = representatives if include_unassigned else roles
        for path in paths:
            assigned_roles = roles.get(path, [])
            generated = representatives[path]
            ordered_roles = tuple(role for role in PATH_ROLES if role in assigned_roles)
            candidate_evidence = evidence if "independent_backup" in ordered_roles else {}
            candidates.append(
                RouteCandidate(
                    candidate_id=candidate_id_for_path(path),
                    h3_path=path,
                    roles=ordered_roles,
                    is_recommended=False,
                    objectives=generated.objectives,
                    metrics=generated.metrics,
                    corridor_signature=self._corridor_signature(path),
                    independence_evidence=candidate_evidence,
                    geojson=self._route_geojson(path),
                    generation_profile=generated.generation_profile,
                    replan_profile=(REPLAN_PROFILE[ordered_roles[0]] if ordered_roles else "eta"),
                )
            )
        return tuple(sorted(candidates, key=_route_candidate_sort_key))

    def _route_geojson(self, path: tuple[str, ...]) -> dict[str, object]:
        coordinates = [
            [self.graph.cells[cell_id].lng, self.graph.cells[cell_id].lat] for cell_id in path
        ]
        return {
            "type": "Feature",
            "properties": {"h3_path": list(path)},
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }

    def _corridor_signature(self, path: tuple[str, ...]) -> tuple[str, ...]:
        parent_sequence: list[str] = []
        for cell_id in path:
            parent = self._parent(cell_id)
            if not parent_sequence or parent_sequence[-1] != parent:
                parent_sequence.append(parent)
        if len(parent_sequence) <= 2:
            return ()
        return tuple(parent_sequence[1:-1])

    def _dilated_parents(self, parents: set[str]) -> set[str]:
        adjacency: dict[str, set[str]] = {}
        for edge in self.graph.edges.values():
            first = self._parent(edge.cell_a)
            second = self._parent(edge.cell_b)
            if first != second:
                adjacency.setdefault(first, set()).add(second)
                adjacency.setdefault(second, set()).add(first)
        allowed = set(parents)
        frontier = set(parents)
        for _ in range(self.disruption_radius):
            frontier = {
                neighbor
                for parent in frontier
                for neighbor in adjacency.get(parent, set())
                if neighbor not in allowed
            }
            allowed.update(frontier)
        return allowed

    def _parent(self, cell_id: str) -> str:
        return self.graph.cells[cell_id].parent_h3 or cell_id


def select_robust_candidates(
    candidates: tuple[RouteCandidate, ...],
    policy: DecisionConfig,
    current_candidate_id: str | None = None,
    request_pressures: tuple[float, ...] = (),
) -> tuple[tuple[RouteCandidate, ...], str, dict[str, object], tuple[str, ...]]:
    """Apply the candidate-pool detour budget, robust order, and optional hysteresis."""
    valid = [candidate for candidate in candidates if candidate.trajectory.get("status") == "valid"]
    if not valid:
        fallback = next(
            (candidate for candidate in candidates if candidate.is_recommended), candidates[0]
        )
        output = _truncate_candidate_pool(candidates, fallback.candidate_id, policy.display_limit)
        return (
            output,
            fallback.candidate_id,
            {
                "length_reference_scope": "candidate_pool",
                "length_reference_m": None,
                "geometry_valid_count": 0,
            },
            ("NO_GEOMETRY_VALID_CANDIDATE",),
        )
    length_reference = min(_trajectory_number(candidate, "length_m") for candidate in valid)
    limit = (1.0 + policy.detour_ratio) * length_reference
    budgeted = [
        candidate
        for candidate in valid
        if _trajectory_number(candidate, "length_m") <= limit + EPSILON
    ]
    selected = min(
        budgeted,
        key=lambda candidate: _robust_key(candidate, policy, request_pressures),
    )
    switch_reason = "initial_robust_selection"
    current: RouteCandidate | None = next(
        (candidate for candidate in budgeted if candidate.candidate_id == current_candidate_id),
        None,
    )
    if current is not None and current.candidate_id != selected.candidate_id:
        current_clearance = _clearance_bucket(current, policy)
        selected_clearance = _clearance_bucket(selected, policy)
        current_j = _worst_environment_distance(current, request_pressures)
        selected_j = _worst_environment_distance(selected, request_pressures)
        improvement = (
            1.0
            if current_j <= EPSILON and selected_j < current_j
            else 0.0
            if current_j <= EPSILON
            else (current_j - selected_j) / current_j
        )
        if (
            selected_clearance <= current_clearance
            and improvement <= policy.switch_relative_improvement
        ):
            selected = current
            switch_reason = "retained_by_hysteresis"
        elif selected_clearance > current_clearance:
            switch_reason = "clearance_level_improved"
        else:
            switch_reason = "environment_improvement_exceeded_threshold"
    output = tuple(
        replace(candidate, is_recommended=candidate.candidate_id == selected.candidate_id)
        for candidate in sorted(
            budgeted,
            key=lambda candidate: _robust_key(candidate, policy, request_pressures),
        )[: policy.display_limit]
    )
    if selected.candidate_id not in {candidate.candidate_id for candidate in output}:
        output = (replace(selected, is_recommended=True), *output[:-1])
        output = tuple(
            replace(candidate, is_recommended=candidate.candidate_id == selected.candidate_id)
            for candidate in output
        )
    conditional = any(
        _trajectory_number(candidate, "unknown_coverage_m") > 0.0 for candidate in output
    )
    warnings = ("CONDITIONAL_ENVIRONMENT_EVIDENCE",) if conditional else ()
    return (
        output,
        selected.candidate_id,
        {
            "length_reference_scope": "candidate_pool",
            "length_reference_m": length_reference,
            "detour_ratio": policy.detour_ratio,
            "length_budget_m": limit,
            "geometry_valid_count": len(valid),
            "budget_candidate_count": len(budgeted),
            "clearance_target_m": policy.clearance_target_m,
            "switch_reason": switch_reason,
            "previous_candidate_id": current_candidate_id,
            "request_pressures": list(request_pressures),
        },
        warnings,
    )


def _robust_key(
    candidate: RouteCandidate,
    policy: DecisionConfig,
    request_pressures: tuple[float, ...] = (),
) -> tuple[float, float, float, str]:
    return (
        -float(_clearance_bucket(candidate, policy)),
        _worst_environment_distance(candidate, request_pressures),
        _trajectory_number(candidate, "length_m"),
        candidate.candidate_id,
    )


def _clearance_bucket(candidate: RouteCandidate, policy: DecisionConfig) -> int:
    raw = candidate.trajectory.get("min_clearance_m")
    clearance = 0.0 if not isinstance(raw, (int, float)) else float(raw)
    capped = min(clearance, policy.clearance_target_m)
    tolerance = max(policy.clearance_tolerance_m, EPSILON)
    return int((capped + tolerance / 2.0) / tolerance)


def _worst_environment_distance(
    candidate: RouteCandidate,
    request_pressures: tuple[float, ...] = (),
) -> float:
    raw = candidate.trajectory.get("environment_distance_m", {})
    if not isinstance(raw, dict):
        return _trajectory_number(candidate, "length_m")
    requested_keys = {_pressure_key(pressure) for pressure in request_pressures}
    values = [
        float(value)
        for key, value in raw.items()
        if isinstance(value, (int, float)) and (not requested_keys or key in requested_keys)
    ]
    return max(values, default=_trajectory_number(candidate, "length_m"))


def _pressure_key(pressure_kpa: float) -> str:
    return f"{pressure_kpa:.6f}".rstrip("0").rstrip(".")


def _trajectory_number(candidate: RouteCandidate, field: str) -> float:
    value = candidate.trajectory.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise PlanningInputError(f"candidate trajectory field {field!r} must be finite numeric.")
    return float(value)


def _pareto_candidates(
    candidates: dict[tuple[str, ...], GeneratedPath],
) -> dict[tuple[str, ...], GeneratedPath]:
    return {
        path: candidate
        for path, candidate in candidates.items()
        if not any(
            other_path != path and _dominates(other, candidate)
            for other_path, other in candidates.items()
        )
    }


def _dominates(first: GeneratedPath, second: GeneratedPath) -> bool:
    first_values = tuple(first.objectives.values())
    second_values = tuple(second.objectives.values())
    return all(a <= b + EPSILON for a, b in zip(first_values, second_values, strict=True)) and any(
        a < b - EPSILON for a, b in zip(first_values, second_values, strict=True)
    )


def _assign_metric_roles(
    candidates: dict[tuple[str, ...], GeneratedPath],
) -> dict[tuple[str, ...], list[str]]:
    values = list(candidates.values())
    if not values:
        raise PlanningFailedError("candidate aggregation has no Pareto representatives.")
    selections = {
        "fastest_eta": min(values, key=_fastest_key),
        "shortest_distance": min(values, key=_shortest_key),
        "max_passability_margin": min(values, key=_passability_key),
        "minimum_travel_cost": min(values, key=_travel_cost_key),
    }
    roles: dict[tuple[str, ...], list[str]] = {}
    for role in PATH_ROLES[:-1]:
        roles.setdefault(selections[role].h3_path, []).append(role)
    return roles


def _recommendation(
    mission_profile: str,
    candidates: tuple[RouteCandidate, ...],
    fastest_candidate_id: str,
) -> tuple[str, str | None, tuple[str, ...]]:
    desired = MISSION_ROLE[mission_profile]
    selected = next((candidate for candidate in candidates if desired in candidate.roles), None)
    if selected is not None:
        reference = fastest_candidate_id if mission_profile == "resilient" else None
        return selected.candidate_id, reference, ()
    if mission_profile == "resilient":
        return fastest_candidate_id, fastest_candidate_id, ("INDEPENDENT_BACKUP_UNAVAILABLE",)
    raise PlanningFailedError(f"required route role is unavailable: {desired}")


def _truncate_candidates(
    candidates: tuple[RouteCandidate, ...],
    recommended: str,
    limit: int,
) -> tuple[RouteCandidate, ...]:
    if len(candidates) <= limit:
        return candidates
    recommended_candidate = next(
        candidate for candidate in candidates if candidate.candidate_id == recommended
    )
    selected = [recommended_candidate]
    for role in PATH_ROLES:
        for candidate in candidates:
            if role in candidate.roles and candidate not in selected:
                selected.append(candidate)
                if len(selected) == limit:
                    return tuple(sorted(selected, key=_route_candidate_sort_key))
    return tuple(sorted(selected[:limit], key=_route_candidate_sort_key))


def _same_metrics(first: PathMetrics, second: PathMetrics) -> bool:
    names = (
        "distance_m",
        "eta_lower_s",
        "eta_s",
        "terrain_risk",
        "travel_cost",
        "safety_margin_mean",
    )
    if any(
        not isclose(float(getattr(first, name)), float(getattr(second, name)), rel_tol=1.0e-9)
        for name in names
    ):
        return False
    first_upper = first.eta_upper_s
    second_upper = second.eta_upper_s
    if (first_upper is None) != (second_upper is None):
        return False
    if (
        first_upper is not None
        and second_upper is not None
        and not isclose(first_upper, second_upper, rel_tol=1.0e-9)
    ):
        return False
    return (
        first.eta_upper_bounded == second.eta_upper_bounded
        and first.edge_count == second.edge_count
        and isclose(first.safety_margin_min, second.safety_margin_min, rel_tol=1.0e-9)
    )


def _balanced_tie_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    return (
        path.metrics.travel_cost,
        path.metrics.eta_s,
        path.metrics.distance_m,
        path.metrics.terrain_risk,
        path.h3_path,
    )


def _fastest_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    return (path.metrics.eta_s, path.metrics.distance_m, path.metrics.terrain_risk, path.h3_path)


def _shortest_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    return (path.metrics.distance_m, path.metrics.eta_s, path.metrics.terrain_risk, path.h3_path)


def _passability_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    return (
        -path.metrics.safety_margin_min,
        path.metrics.terrain_risk,
        path.metrics.eta_s,
        path.metrics.distance_m,
        path.h3_path,
    )


def _travel_cost_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    return (
        path.metrics.travel_cost,
        path.metrics.eta_s,
        path.metrics.distance_m,
        path.h3_path,
    )


def _route_candidate_sort_key(
    candidate: RouteCandidate,
) -> tuple[int, float, float, tuple[str, ...]]:
    role_index = min(
        (PATH_ROLES.index(role) for role in candidate.roles),
        default=len(PATH_ROLES),
    )
    return (role_index, candidate.metrics.eta_s, candidate.metrics.distance_m, candidate.h3_path)


def _truncate_candidate_pool(
    candidates: tuple[RouteCandidate, ...],
    recommended: str,
    limit: int,
) -> tuple[RouteCandidate, ...]:
    """Bound an internal pool while preserving its selected candidate."""
    if len(candidates) <= limit:
        return candidates
    selected = next(candidate for candidate in candidates if candidate.candidate_id == recommended)
    remainder = [candidate for candidate in candidates if candidate.candidate_id != recommended]
    return (selected, *remainder[: limit - 1])
