"""Deterministic multi-objective candidate generation over the exact PortsMap kernel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import inf, isfinite
from statistics import median

from h3_offroad_planner.factor_model import FactorEvaluation, PathMetrics
from h3_offroad_planner.models import PlanningFailedError
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile

__all__ = ["DeterministicParetoPlanner", "GeneratedPath"]

ProgressCallback = Callable[[str, int, str], None]

DEFAULT_MAX_PATHS: int = 5
DEFAULT_CANDIDATE_LIMIT: int = 24
DEFAULT_PENALTY_FACTOR: float = 0.25
EPSILON: float = 1.0e-9
PARETO_NAMES: tuple[str, ...] = (
    "distance",
    "environment_distance",
    "eta",
    "terrain_risk",
    "travel_cost",
    "passability_deficit",
)


@dataclass(frozen=True)
class GeneratedPath:
    """One unique raw path with exact original-unit metrics and its search profile."""

    h3_path: tuple[str, ...]
    metrics: PathMetrics
    generation_profile: str
    scalar_cost: float

    def __post_init__(self) -> None:
        if not self.h3_path or not self.generation_profile:
            raise ValueError("generated path and profile must be non-empty.")
        if not isfinite(self.scalar_cost) or self.scalar_cost < 0.0:
            raise ValueError("generated scalar cost must be finite and non-negative.")

    @property
    def objectives(self) -> dict[str, float]:
        """Return the five raw-unit values used for route-level Pareto comparison."""
        return {
            "distance": self.metrics.distance_m,
            "environment_distance": max(
                self.metrics.environment_distance_m.values(),
                default=self.metrics.distance_m,
            ),
            "eta": self.metrics.eta_s,
            "terrain_risk": self.metrics.terrain_risk,
            "travel_cost": self.metrics.travel_cost,
            "passability_deficit": 1.0 - self.metrics.safety_margin_min,
        }


class DeterministicParetoPlanner:
    """Generate bounded alternatives without genetic populations or generations."""

    def __init__(
        self,
        context: PortsMapSearchContext,
        max_paths: int = DEFAULT_MAX_PATHS,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        penalty_factor: float = DEFAULT_PENALTY_FACTOR,
        include_composite: bool = False,
        environment_pressures: tuple[float, ...] = (),
    ) -> None:
        """Initialize deterministic profile and reuse-penalty candidate generation."""
        if not 1 <= max_paths <= 5:
            raise ValueError("max_paths must be in [1, 5].")
        if not max_paths <= candidate_limit <= 24:
            raise ValueError("candidate_limit must be in [max_paths, 24].")
        if not isfinite(penalty_factor) or penalty_factor < 0.0:
            raise ValueError("penalty_factor must be finite and non-negative.")
        self.context = context
        self.max_paths = max_paths
        self.candidate_limit = candidate_limit
        self.penalty_factor = penalty_factor
        self.include_composite = include_composite
        if len(set(environment_pressures)) != len(environment_pressures) or any(
            not isfinite(value) or value < 0.0 for value in environment_pressures
        ):
            raise ValueError("environment_pressures must be unique finite non-negative values.")
        self.environment_pressures = environment_pressures

    def plan(
        self,
        start: str,
        goal: str,
        blocked: frozenset[str] = frozenset(),
        progress: ProgressCallback | None = None,
    ) -> list[GeneratedPath]:
        """Return at most 24 exact unique raw candidates including a widest anchor."""
        scales = _robust_scales(self.context.evaluation)
        profiles = _fixed_profiles(
            scales,
            include_composite=self.include_composite,
            environment_pressures=self.environment_pressures,
        )
        candidates: dict[tuple[str, ...], GeneratedPath] = {}
        penalties: dict[str, int] = {}
        attempts_per_profile = max(1, min(self.max_paths, 3))
        total_profiles = len(profiles)
        for idx, profile in enumerate(profiles, 1):
            if len(candidates) >= self.candidate_limit:
                break
            for attempt in range(attempts_per_profile):
                if len(candidates) >= self.candidate_limit:
                    break
                if progress is not None:
                    progress(
                        "global_plan",
                        89,
                        f"searching profile [{idx}/{total_profiles}: {profile.name}] "
                        f"(attempt {attempt + 1}/{attempts_per_profile})",
                    )
                result = self.context.search(
                    start,
                    goal,
                    profile,
                    blocked,
                    penalties,
                    self.penalty_factor if attempt > 0 else 0.0,
                )
                generated = GeneratedPath(
                    result.h3_path,
                    result.metrics,
                    profile.name,
                    result.scalar_cost,
                )
                if generated.h3_path not in candidates:
                    candidates[generated.h3_path] = generated
                    _add_reuse_penalties(penalties, generated.h3_path)
                elif attempt > 0:
                    # Deterministic search without new penalties will yield the same path
                    break
        if progress is not None:
            progress("global_plan", 91, "searching widest bottleneck route")
        widest = self.context.search_widest(start, goal, blocked)
        candidates[widest.h3_path] = GeneratedPath(
            widest.h3_path,
            widest.metrics,
            "widest_path",
            widest.scalar_cost,
        )
        if not candidates:
            raise PlanningFailedError(f"no deterministic candidate from {start!r} to {goal!r}.")
        return _bounded_candidates(list(candidates.values()), self.candidate_limit)


def _robust_scales(evaluation: FactorEvaluation) -> dict[str, float]:
    metrics = list(evaluation.directed_edges.values())
    if not metrics:
        raise PlanningFailedError("cannot normalize candidate objectives without passable edges.")
    values = {
        "distance": [edge.distance_m for edge in metrics],
        "eta": [edge.eta_s for edge in metrics],
        "terrain_risk": [edge.terrain_risk for edge in metrics if edge.terrain_risk > 0.0],
        "travel_cost": [edge.travel_cost for edge in metrics],
    }
    scales = {
        name: max(float(median(samples)) if samples else 1.0, EPSILON)
        for name, samples in values.items()
    }
    environment_keys = sorted({key for edge in metrics for key in edge.environment_distance_m})
    for key in environment_keys:
        samples = [edge.environment_distance_m[key] for edge in metrics]
        scales[f"environment:{key}"] = max(float(median(samples)), EPSILON)
    return scales


def _fixed_profiles(
    scales: dict[str, float],
    include_composite: bool = False,
    environment_pressures: tuple[float, ...] = (),
) -> list[ScalarProfile]:
    objective_scales = {
        name: scales[name] for name in ("distance", "eta", "terrain_risk", "travel_cost")
    }
    profiles = [
        ScalarProfile({name: 1.0}, objective_scales, name=name)
        for name in ("distance", "eta", "terrain_risk", "travel_cost")
    ]
    if include_composite:
        profiles.extend(
            [
                ScalarProfile(
                    dict.fromkeys(("distance", "eta", "terrain_risk", "travel_cost"), 0.25),
                    objective_scales,
                    "balanced",
                ),
                ScalarProfile({"distance": 0.4, "eta": 0.6}, objective_scales, "distance_eta"),
                ScalarProfile({"eta": 0.6, "terrain_risk": 0.4}, objective_scales, "eta_risk"),
                ScalarProfile(
                    {"terrain_risk": 0.5, "travel_cost": 0.5}, objective_scales, "risk_cost"
                ),
                ScalarProfile(
                    {"distance": 0.4, "travel_cost": 0.6}, objective_scales, "distance_cost"
                ),
            ]
        )
    for pressure in environment_pressures:
        key = f"{pressure:g}"
        profiles.append(
            ScalarProfile(
                {},
                objective_scales,
                name=f"environment_w{key}",
                environment_pressure=pressure,
                environment_weight=1.0,
                environment_scale=scales.get(f"environment:{key}", 1.0),
            )
        )
    return profiles


def _add_reuse_penalties(penalties: dict[str, int], path: tuple[str, ...]) -> None:
    for cell_id in path[1:-1]:
        penalties[cell_id] = penalties.get(cell_id, 0) + 1


def _bounded_candidates(candidates: list[GeneratedPath], limit: int) -> list[GeneratedPath]:
    if len(candidates) <= limit:
        return sorted(candidates, key=_candidate_tie_key)
    fronts = _non_dominated_fronts(candidates)
    selected: list[GeneratedPath] = []
    for front in fronts:
        ordered = _crowding_order(front)
        if len(selected) + len(ordered) <= limit:
            selected.extend(ordered)
        else:
            selected.extend(ordered[: limit - len(selected)])
            break
    widest = next((path for path in candidates if path.generation_profile == "widest_path"), None)
    if widest is not None and widest not in selected:
        selected[-1] = widest
    return sorted({path.h3_path: path for path in selected}.values(), key=_candidate_tie_key)


def _non_dominated_fronts(candidates: list[GeneratedPath]) -> list[list[GeneratedPath]]:
    remaining = list(candidates)
    fronts: list[list[GeneratedPath]] = []
    while remaining:
        front = [
            candidate
            for candidate in remaining
            if not any(_dominates(other, candidate) for other in remaining)
        ]
        fronts.append(front)
        keys = {path.h3_path for path in front}
        remaining = [path for path in remaining if path.h3_path not in keys]
    return fronts


def _dominates(first: GeneratedPath, second: GeneratedPath) -> bool:
    first_values = first.objectives
    second_values = second.objectives
    return all(
        first_values[name] <= second_values[name] + EPSILON for name in PARETO_NAMES
    ) and any(first_values[name] < second_values[name] - EPSILON for name in PARETO_NAMES)


def _crowding_order(paths: list[GeneratedPath]) -> list[GeneratedPath]:
    crowding = dict.fromkeys((path.h3_path for path in paths), 0.0)
    for name in PARETO_NAMES:
        ordered = sorted(paths, key=lambda path: (path.objectives[name], path.h3_path))
        if len(ordered) <= 2:
            for path in ordered:
                crowding[path.h3_path] = inf
            continue
        crowding[ordered[0].h3_path] = inf
        crowding[ordered[-1].h3_path] = inf
        span = max(ordered[-1].objectives[name] - ordered[0].objectives[name], EPSILON)
        for index in range(1, len(ordered) - 1):
            previous_value = ordered[index - 1].objectives[name]
            next_value = ordered[index + 1].objectives[name]
            crowding[ordered[index].h3_path] += (next_value - previous_value) / span
    return sorted(paths, key=lambda path: (-crowding[path.h3_path], _candidate_tie_key(path)))


def _candidate_tie_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    metrics = path.metrics
    return (
        metrics.travel_cost,
        metrics.eta_s,
        metrics.distance_m,
        metrics.terrain_risk,
        path.h3_path,
    )
