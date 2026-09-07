"""Public immutable RoutePlan, selection, blockage, and replanning domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from math import isfinite
from types import MappingProxyType

from h3_offroad_planner.factor_model import PathMetrics, canonical_hash

__all__ = [
    "BlockageRecord",
    "MISSION_PROFILES",
    "PATH_ROLES",
    "ReplanRequest",
    "ReplanResult",
    "RouteCandidate",
    "RoutePlan",
    "RouteSelection",
    "candidate_id_for_path",
    "plan_id_for_payload",
]

PATH_ROLES: tuple[str, ...] = (
    "fastest_eta",
    "shortest_distance",
    "max_passability_margin",
    "minimum_travel_cost",
    "independent_backup",
)
MISSION_PROFILES: tuple[str, ...] = (
    "fastest",
    "shortest",
    "passability",
    "economy",
    "resilient",
)
ROUTE_STATES: frozenset[str] = frozenset(
    {"active", "safe_hold", "superseded", "invalidated"}
)
BLOCKAGE_STATES: frozenset[str] = frozenset(
    {"tentative", "confirmed", "cleared", "expired"}
)


@dataclass(frozen=True)
class RouteCandidate:
    """One unique fine-grid route with zero or more deterministic product roles."""

    candidate_id: str
    h3_path: tuple[str, ...]
    roles: tuple[str, ...]
    is_recommended: bool
    objectives: Mapping[str, float]
    metrics: PathMetrics
    corridor_signature: tuple[str, ...]
    independence_evidence: Mapping[str, object] = field(default_factory=dict)
    geojson: Mapping[str, object] = field(default_factory=dict)
    generation_profile: str = "unknown"
    replan_profile: str = "eta"

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.h3_path:
            raise ValueError("candidate_id and h3_path must be non-empty.")
        if self.candidate_id != candidate_id_for_path(self.h3_path):
            raise ValueError("candidate_id must equal the stable H3 path hash.")
        if len(set(self.roles)) != len(self.roles) or set(self.roles).difference(PATH_ROLES):
            raise ValueError("candidate roles must be unique known role names.")
        if any(not isfinite(value) or value < 0.0 for value in self.objectives.values()):
            raise ValueError("candidate objectives must be finite and non-negative.")
        if not self.generation_profile or not self.replan_profile:
            raise ValueError("candidate profiles must be non-empty.")
        object.__setattr__(self, "objectives", MappingProxyType(dict(self.objectives)))
        object.__setattr__(
            self,
            "independence_evidence",
            MappingProxyType(dict(self.independence_evidence)),
        )
        object.__setattr__(self, "geojson", MappingProxyType(dict(self.geojson)))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping in canonical field order."""
        return {
            "candidate_id": self.candidate_id,
            "h3_path": list(self.h3_path),
            "roles": list(self.roles),
            "is_recommended": self.is_recommended,
            "objectives": dict(sorted(self.objectives.items())),
            "metrics": self.metrics.to_dict(),
            "corridor_signature": list(self.corridor_signature),
            "independence_evidence": dict(self.independence_evidence),
            "geojson": dict(self.geojson),
            "generation_profile": self.generation_profile,
            "replan_profile": self.replan_profile,
        }


@dataclass(frozen=True)
class RoutePlan:
    """Stable planning result written before any user route is activated."""

    plan_id: str
    mission_profile: str
    recommended_candidate_id: str
    independence_reference_candidate_id: str | None
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str
    candidates: tuple[RouteCandidate, ...]
    aggregation_stats: Mapping[str, object] = field(default_factory=dict)
    output_files: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    planner_name: str = "DeterministicParetoPlanner"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.mission_profile not in MISSION_PROFILES:
            raise ValueError(f"mission_profile must be one of {MISSION_PROFILES!r}.")
        if not 1 <= len(self.candidates) <= 5:
            raise ValueError("RoutePlan must contain one to five candidates.")
        identifiers = [candidate.candidate_id for candidate in self.candidates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("RoutePlan candidates must be unique.")
        if self.recommended_candidate_id not in identifiers:
            raise ValueError("recommended_candidate_id must identify a candidate.")
        if sum(candidate.is_recommended for candidate in self.candidates) != 1:
            raise ValueError("RoutePlan must mark exactly one recommended candidate.")
        if self.planner_name != "DeterministicParetoPlanner":
            raise ValueError("new RoutePlan outputs must use DeterministicParetoPlanner.")
        if self.plan_id != plan_id_for_payload(self.identity_payload()):
            raise ValueError("plan_id does not match the canonical plan identity payload.")
        object.__setattr__(
            self,
            "aggregation_stats",
            MappingProxyType(dict(self.aggregation_stats)),
        )
        object.__setattr__(self, "output_files", MappingProxyType(dict(self.output_files)))

    def identity_payload(self) -> dict[str, object]:
        """Return deterministic fields participating in stable plan identity."""
        return {
            "schema_version": self.schema_version,
            "mission_profile": self.mission_profile,
            "recommended_candidate_id": self.recommended_candidate_id,
            "independence_reference_candidate_id": self.independence_reference_candidate_id,
            "vehicle_hash": self.vehicle_hash,
            "factor_model_hash": self.factor_model_hash,
            "static_input_hash": self.static_input_hash,
            "graph_topology_hash": self.graph_topology_hash,
            "candidate_ids": [candidate.candidate_id for candidate in self.candidates],
            "candidate_roles": [list(candidate.roles) for candidate in self.candidates],
        }

    def to_dict(self) -> dict[str, object]:
        """Return the complete JSON-compatible public plan contract."""
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "planner_name": self.planner_name,
            "mission_profile": self.mission_profile,
            "recommended_candidate_id": self.recommended_candidate_id,
            "independence_reference_candidate_id": self.independence_reference_candidate_id,
            "vehicle_hash": self.vehicle_hash,
            "factor_model_hash": self.factor_model_hash,
            "static_input_hash": self.static_input_hash,
            "graph_topology_hash": self.graph_topology_hash,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "aggregation_stats": dict(self.aggregation_stats),
            "output_files": dict(self.output_files),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RouteSelection:
    """Persisted explicit user activation and current active-route state."""

    plan_id: str
    candidate_id: str
    selected_role: str
    active_h3_path: tuple[str, ...]
    active_metrics: PathMetrics
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str
    state: str = "active"
    replan_version: int = 0
    selection_version: int = 1

    def __post_init__(self) -> None:
        if not self.plan_id or not self.candidate_id or not self.active_h3_path:
            raise ValueError("selection identifiers and active path must be non-empty.")
        if self.selected_role not in PATH_ROLES:
            raise ValueError("selected_role must be a known path role.")
        if self.state not in ROUTE_STATES:
            raise ValueError(f"selection state must be one of {sorted(ROUTE_STATES)}.")
        if self.replan_version < 0 or self.selection_version <= 0:
            raise ValueError("selection versions are outside their valid ranges.")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible persisted selection mapping."""
        payload = asdict(self)
        payload["active_h3_path"] = list(self.active_h3_path)
        payload["active_metrics"] = self.active_metrics.to_dict()
        return payload


@dataclass(frozen=True)
class BlockageRecord:
    """Persistable blockage observation lifecycle record."""

    blockage_id: str
    h3index: str
    state: str
    confirmation_count: int
    trusted_source: bool
    observed_at_epoch_s: float
    expires_at_epoch_s: float | None = None
    mission_lifetime: bool = False
    source: str = "user"

    def __post_init__(self) -> None:
        if not self.blockage_id or not self.h3index or not self.source:
            raise ValueError("blockage identifiers and source must be non-empty.")
        if self.state not in BLOCKAGE_STATES:
            raise ValueError(f"blockage state must be one of {sorted(BLOCKAGE_STATES)}.")
        if self.confirmation_count <= 0:
            raise ValueError("confirmation_count must be positive.")
        if not isfinite(self.observed_at_epoch_s) or self.observed_at_epoch_s < 0.0:
            raise ValueError("observed_at_epoch_s must be finite and non-negative.")
        if self.expires_at_epoch_s is not None:
            if not isfinite(self.expires_at_epoch_s):
                raise ValueError("expires_at_epoch_s must be finite when provided.")
            if self.expires_at_epoch_s <= self.observed_at_epoch_s:
                raise ValueError("expires_at_epoch_s must follow observed_at_epoch_s.")


@dataclass(frozen=True)
class ReplanRequest:
    """Explicit local-replan input; current position is never inferred."""

    selection_path: str
    blockage_observations: tuple[BlockageRecord, ...]
    current_h3: str | None = None
    current_lat: float | None = None
    current_lng: float | None = None
    snap_distance_m: float = 20_000.0
    now_epoch_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.selection_path:
            raise ValueError("selection_path must be non-empty.")
        has_h3 = self.current_h3 is not None
        has_coordinates = self.current_lat is not None and self.current_lng is not None
        if has_h3 == has_coordinates:
            raise ValueError("provide exactly one of current_h3 or current_lat/current_lng.")
        if (self.current_lat is None) != (self.current_lng is None):
            raise ValueError("current_lat and current_lng must be provided together.")
        if self.current_lat is not None and not -90.0 <= self.current_lat <= 90.0:
            raise ValueError("current_lat must be in [-90, 90] degrees.")
        if self.current_lng is not None and not -180.0 <= self.current_lng <= 180.0:
            raise ValueError("current_lng must be in [-180, 180] degrees.")
        if not isfinite(self.snap_distance_m) or self.snap_distance_m <= 0.0:
            raise ValueError("snap_distance_m must be finite and positive.")
        if not isfinite(self.now_epoch_s) or self.now_epoch_s < 0.0:
            raise ValueError("now_epoch_s must be finite and non-negative.")


@dataclass(frozen=True)
class ReplanResult:
    """Product-level result of one local repair or global fallback attempt."""

    plan_id: str
    candidate_id: str
    algorithm: str
    status: str
    replan_version: int
    old_path_hash: str
    new_path_hash: str | None
    metrics_before: PathMetrics
    metrics_after: PathMetrics | None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ROUTE_STATES:
            raise ValueError("replan status is invalid.")
        if self.algorithm not in {"DStarLite", "global_fallback", "safe_hold"}:
            raise ValueError("replan algorithm is invalid.")
        if self.replan_version < 0:
            raise ValueError("replan_version must be non-negative.")


def candidate_id_for_path(h3_path: tuple[str, ...] | list[str]) -> str:
    """Return stable candidate id from the complete ordered H3 sequence."""
    if not h3_path:
        raise ValueError("h3_path must be non-empty.")
    return f"route-{canonical_hash(list(h3_path))[:16]}"


def plan_id_for_payload(payload: Mapping[str, object]) -> str:
    """Return stable plan id from a canonical identity payload."""
    return f"plan-{canonical_hash(dict(payload))[:20]}"
