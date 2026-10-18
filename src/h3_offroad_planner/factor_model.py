"""Vehicle-aware physical-margin evaluation and immutable directed-edge metrics."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import atan, degrees, inf, isfinite, log, radians, sin, sqrt, tan
from pathlib import Path
from types import MappingProxyType
from typing import cast

import numpy as np
import yaml  # type: ignore[import-untyped]

from h3_offroad_planner.dynamics.bekker import (
    BekkerChecker,
    _cell_bekker_soil,
)
from h3_offroad_planner.models import (
    AssessmentError,
    ConfigError,
    H3Cell,
    H3Edge,
    H3Graph,
    PlanningInputError,
    VehicleProfile,
)
from h3_offroad_planner.vectorized_soil import (
    vectorized_bekker_sinkage,
    vectorized_cone_index_kpa,
)

__all__ = [
    "DirectedEdgeMetrics",
    "DecisionConfig",
    "EnvironmentConfig",
    "FactorEvaluation",
    "FactorInterval",
    "FactorModelConfig",
    "GeometryConfig",
    "NodeFactorMetrics",
    "PathMetrics",
    "PHYSICAL_EVIDENCE_WARNING",
    "build_directed_edge_cache",
    "canonical_hash",
    "compute_directed_roll_deg",
    "environment_multiplier",
    "evaluate_factor_model",
    "evaluate_path_metrics",
    "graph_topology_hash",
    "load_factor_model",
    "load_static_planning_config",
    "static_input_hash",
    "StaticPlanningConfig",
    "WeatherConfig",
    "write_effective_snapshots",
    "write_static_planning_snapshot",
]

GRAVITY_MPS2: float = 9.81
MODEL_SCHEMA_VERSION: int = 2
PHYSICAL_EVIDENCE_WARNING: str = "PHYSICAL_EVIDENCE_INCOMPLETE"
MISSING_REASON_PREFIX: str = "MISSING_"
_EMPTY_ENV: MappingProxyType[str, float] = MappingProxyType({})
SCHEMA_V2_SECTIONS: frozenset[str] = frozenset(
    {
        "schema_version",
        "uncertainty",
        "speed",
        "hard_constraints",
        "risk",
        "cost",
        "portsmap",
    }
)
SCHEMA_V2_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "uncertainty": frozenset({"missing_speed_interval", "missing_confidence"}),
        "speed": frozenset(
            {
                "landcover_by_code",
                "soil_by_uscs",
                "tri_best",
                "tri_worst",
                "offroad_factor",
                "road_factor",
                "floor_ratio",
                "directed_slope_min_factor",
            }
        ),
        "hard_constraints": frozenset(
            {
                "min_cone_index_kpa",
                "max_sinkage_clearance_ratio",
                "enforce_rowspacing",
                "enforce_water_depth",
                "enforce_soil_physics",
                "enforce_scalar_slope_blocking",
                "use_exact_tangent_roll",
            }
        ),
        "risk": frozenset({"epsilon"}),
        "cost": frozenset({"tri_coefficient", "gravity_coefficient"}),
        "portsmap": frozenset({"max_ports", "max_port_pairs"}),
    }
)
LEGACY_ACTIVE_SECTIONS: frozenset[str] = frozenset(
    {
        "schema_version",
        "benefit",
        "uncertainty",
        "speed",
        "hard_constraints",
        "risk",
        "cost",
        "portsmap",
    }
)
LEGACY_ACTIVE_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "benefit": frozenset({"tri_best", "tri_worst"}),
        "uncertainty": frozenset({"missing_interval", "missing_confidence"}),
        "speed": SCHEMA_V2_FIELDS["speed"] - {"tri_best", "tri_worst"},
        "hard_constraints": SCHEMA_V2_FIELDS["hard_constraints"],
        "risk": SCHEMA_V2_FIELDS["risk"],
        "cost": SCHEMA_V2_FIELDS["cost"],
        "portsmap": SCHEMA_V2_FIELDS["portsmap"],
    }
)


@dataclass(frozen=True, slots=True)
class FactorInterval:
    """Ordered ratio interval on the closed unit range."""

    lower: float
    nominal: float
    upper: float

    def __post_init__(self) -> None:
        values = (self.lower, self.nominal, self.upper)
        if not all(isfinite(value) for value in values):
            raise ValueError("factor interval values must be finite.")
        if not 0.0 <= self.lower <= self.nominal <= self.upper <= 1.0:
            raise ValueError("factor interval must satisfy 0 <= lower <= nominal <= upper <= 1.")


_ROAD_INTERVAL_1_0 = FactorInterval(1.0, 1.0, 1.0)
_OFFROAD_INTERVAL_0_7 = FactorInterval(0.70, 0.70, 0.70)


@dataclass(frozen=True, slots=True)
class NodeFactorMetrics:
    """Frozen speed factors, physical safety margin, and evidence for one node."""

    h3index: str
    slope: FactorInterval
    landcover: FactorInterval
    soil: FactorInterval
    tri: FactorInterval
    road: FactorInterval
    safety_margin: FactorInterval
    speed_lower_mps: float
    speed_nominal_mps: float
    speed_upper_mps: float
    is_passable: bool
    confidence: float
    reason_codes: tuple[str, ...] = ()
    cone_index_kpa: float | None = None
    sinkage_m: float | None = None

    def __post_init__(self) -> None:
        if not self.h3index:
            raise ValueError("h3index must be non-empty.")
        speeds = (self.speed_lower_mps, self.speed_nominal_mps, self.speed_upper_mps)
        if not all(isfinite(value) and value >= 0.0 for value in speeds):
            raise ValueError("node speeds must be finite and non-negative.")
        if not self.speed_lower_mps <= self.speed_nominal_mps <= self.speed_upper_mps:
            raise ValueError("node speed interval must be ordered.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1].")

    @classmethod
    def _fast_create(
        cls,
        h3index: str,
        slope: FactorInterval,
        landcover: FactorInterval,
        soil: FactorInterval,
        tri: FactorInterval,
        road: FactorInterval,
        safety_margin: FactorInterval,
        speed_lower_mps: float,
        speed_nominal_mps: float,
        speed_upper_mps: float,
        is_passable: bool,
        confidence: float,
        reason_codes: tuple[str, ...] = (),
        cone_index_kpa: float | None = None,
        sinkage_m: float | None = None,
    ) -> NodeFactorMetrics:
        obj = object.__new__(cls)
        set_attr = object.__setattr__
        set_attr(obj, "h3index", h3index)
        set_attr(obj, "slope", slope)
        set_attr(obj, "landcover", landcover)
        set_attr(obj, "soil", soil)
        set_attr(obj, "tri", tri)
        set_attr(obj, "road", road)
        set_attr(obj, "safety_margin", safety_margin)
        set_attr(obj, "speed_lower_mps", speed_lower_mps)
        set_attr(obj, "speed_nominal_mps", speed_nominal_mps)
        set_attr(obj, "speed_upper_mps", speed_upper_mps)
        set_attr(obj, "is_passable", is_passable)
        set_attr(obj, "confidence", confidence)
        set_attr(obj, "reason_codes", reason_codes)
        set_attr(obj, "cone_index_kpa", cone_index_kpa)
        set_attr(obj, "sinkage_m", sinkage_m)
        return obj


@dataclass(frozen=True, slots=True)
class DirectedEdgeMetrics:
    """Frozen metrics for one directed graph edge."""

    from_h3: str
    to_h3: str
    distance_m: float
    eta_lower_s: float
    eta_s: float
    eta_upper_s: float | None
    eta_upper_bounded: bool
    terrain_risk: float
    travel_cost: float
    safety_margin_lower: float
    safety_margin_nominal: float
    safety_margin_upper: float
    directed_slope_deg: float
    environment_distance_m: Mapping[str, float] = _EMPTY_ENV

    def __post_init__(self) -> None:
        finite_nonnegative = (
            self.distance_m,
            self.eta_lower_s,
            self.eta_s,
            self.terrain_risk,
            self.travel_cost,
        )
        if not self.from_h3 or not self.to_h3 or self.from_h3 == self.to_h3:
            raise ValueError("directed edge endpoints must be distinct non-empty ids.")
        if not all(isfinite(value) and value >= 0.0 for value in finite_nonnegative):
            raise ValueError("directed edge metrics must be finite and non-negative.")
        if self.distance_m <= 0.0:
            raise ValueError("distance_m must be positive.")
        if self.eta_upper_bounded != (self.eta_upper_s is not None):
            raise ValueError("eta_upper_bounded must match eta_upper_s presence.")
        if self.eta_upper_s is not None and self.eta_upper_s < self.eta_s:
            raise ValueError("eta_upper_s must not be below eta_s.")
        if not (
            0.0
            <= self.safety_margin_lower
            <= self.safety_margin_nominal
            <= self.safety_margin_upper
            <= 1.0
        ):
            raise ValueError("directed edge safety-margin interval must be ordered in [0, 1].")
        if any(
            not isfinite(value) or value < self.distance_m
            for value in self.environment_distance_m.values()
        ):
            raise ValueError("environment edge distances must be finite and >= geometry distance.")
        if not self.environment_distance_m:
            object.__setattr__(self, "environment_distance_m", _EMPTY_ENV)
        else:
            object.__setattr__(
                self,
                "environment_distance_m",
                MappingProxyType(dict(self.environment_distance_m)),
            )

    @classmethod
    def _fast_create(
        cls,
        from_h3: str,
        to_h3: str,
        distance_m: float,
        eta_lower_s: float,
        eta_s: float,
        eta_upper_s: float | None,
        eta_upper_bounded: bool,
        terrain_risk: float,
        travel_cost: float,
        safety_margin_lower: float,
        safety_margin_nominal: float,
        safety_margin_upper: float,
        directed_slope_deg: float,
        environment_distance_m: Mapping[str, float] = _EMPTY_ENV,
    ) -> DirectedEdgeMetrics:
        obj = object.__new__(cls)
        set_attr = object.__setattr__
        set_attr(obj, "from_h3", from_h3)
        set_attr(obj, "to_h3", to_h3)
        set_attr(obj, "distance_m", distance_m)
        set_attr(obj, "eta_lower_s", eta_lower_s)
        set_attr(obj, "eta_s", eta_s)
        set_attr(obj, "eta_upper_s", eta_upper_s)
        set_attr(obj, "eta_upper_bounded", eta_upper_bounded)
        set_attr(obj, "terrain_risk", terrain_risk)
        set_attr(obj, "travel_cost", travel_cost)
        set_attr(obj, "safety_margin_lower", safety_margin_lower)
        set_attr(obj, "safety_margin_nominal", safety_margin_nominal)
        set_attr(obj, "safety_margin_upper", safety_margin_upper)
        set_attr(obj, "directed_slope_deg", directed_slope_deg)
        set_attr(obj, "environment_distance_m", environment_distance_m)
        return obj


@dataclass(frozen=True)
class PathMetrics:
    """Exact path aggregates recomputed from frozen directed-edge metrics."""

    distance_m: float
    eta_lower_s: float
    eta_s: float
    eta_upper_s: float | None
    eta_upper_bounded: bool
    terrain_risk: float
    travel_cost: float
    safety_margin_min: float
    safety_margin_mean: float
    edge_count: int
    environment_distance_m: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        values = (
            self.distance_m,
            self.eta_lower_s,
            self.eta_s,
            self.terrain_risk,
            self.travel_cost,
        )
        if not all(isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("path metrics must be finite and non-negative.")
        if self.edge_count < 0:
            raise ValueError("edge_count must be non-negative.")
        if not 0.0 <= self.safety_margin_min <= self.safety_margin_mean <= 1.0:
            raise ValueError("path safety-margin aggregates must be ordered in [0, 1].")
        if self.eta_upper_bounded != (self.eta_upper_s is not None):
            raise ValueError("eta_upper_bounded must match eta_upper_s presence.")
        if any(
            not isfinite(value) or value < self.distance_m
            for value in self.environment_distance_m.values()
        ):
            raise ValueError("environment path distances must be finite and >= geometry distance.")
        object.__setattr__(
            self,
            "environment_distance_m",
            MappingProxyType(dict(self.environment_distance_m)),
        )

    def to_dict(self) -> dict[str, object]:
        """Return schema-v1 metrics with compatibility names at the output boundary."""
        return {
            "distance_m": self.distance_m,
            "eta_lower_s": self.eta_lower_s,
            "eta_s": self.eta_s,
            "eta_upper_s": self.eta_upper_s,
            "eta_upper_bounded": self.eta_upper_bounded,
            "terrain_risk": self.terrain_risk,
            "travel_cost": self.travel_cost,
            "score_lower_min": self.safety_margin_min,
            "score_nominal_mean": self.safety_margin_mean,
            "edge_count": self.edge_count,
            "environment_distance_m": dict(sorted(self.environment_distance_m.items())),
        }

    def __hash__(self) -> int:
        return hash(
            (
                self.distance_m,
                self.eta_lower_s,
                self.eta_s,
                self.eta_upper_s,
                self.eta_upper_bounded,
                self.terrain_risk,
                self.travel_cost,
                self.safety_margin_min,
                self.safety_margin_mean,
                self.edge_count,
                tuple(sorted(self.environment_distance_m.items())),
            )
        )


@dataclass(frozen=True)
class EnvironmentConfig:
    """Static surface/drainage multiplier policy and request pressure scenarios."""

    comparison_pressures: tuple[float, ...] = (0.0, 0.5, 1.0)
    request_pressures: tuple[float, ...] = (0.5, 1.0)
    unknown_drainage_range: tuple[float, float] = (0.0, 1.0)
    unknown_surface_range: tuple[float, float] = (0.0, 1.0)
    shared_sensitivity: float = 1.0
    model: str = "surface_drainage_multiplier_v1"
    pressure_basis: str = "synthetic_scenario"

    def __post_init__(self) -> None:
        if self.model != "surface_drainage_multiplier_v1":
            raise ConfigError("unsupported environment model version.")
        if self.pressure_basis not in {
            "synthetic_scenario",
            "model_snapshot_v1",
            "precipitation_apiv1",
        }:
            raise ConfigError("unsupported environment pressure_basis.")
        for name, values in (
            ("comparison_pressures", self.comparison_pressures),
            ("request_pressures", self.request_pressures),
        ):
            if not values or len(set(values)) != len(values):
                raise ConfigError(f"{name} must contain unique pressure values.")
            if any(not isfinite(value) or value < 0.0 for value in values):
                raise ConfigError(f"{name} must contain finite non-negative values.")
        if not set(self.request_pressures).issubset(self.comparison_pressures):
            raise ConfigError("request_pressures must be a subset of comparison_pressures.")
        for name, bounds in (
            ("unknown_drainage_range", self.unknown_drainage_range),
            ("unknown_surface_range", self.unknown_surface_range),
        ):
            if len(bounds) != 2 or not 0.0 <= bounds[0] <= bounds[1] <= 1.0:
                raise ConfigError(f"{name} must be an ordered [0, 1] interval.")
        if not isfinite(self.shared_sensitivity) or self.shared_sensitivity < 0.0:
            raise ConfigError("shared_sensitivity must be finite and non-negative.")

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "pressure_basis": self.pressure_basis,
            "comparison_pressures": list(self.comparison_pressures),
            "request_pressures": list(self.request_pressures),
            "unknown_drainage_range": list(self.unknown_drainage_range),
            "unknown_surface_range": list(self.unknown_surface_range),
            "shared_sensitivity": self.shared_sensitivity,
        }


@dataclass(frozen=True)
class WeatherConfig:
    """Bounded request-time weather lookup and optional moisture calibration."""

    enabled: bool = False
    provider: str = "open-meteo"
    endpoint: str = "https://api.open-meteo.com/v1/forecast"
    model: str = "best_match"
    timeout_s: float = 3.0
    ttl_s: float = 1800.0
    failure_ttl_s: float = 60.0
    max_age_s: float = 10800.0
    theta_dry: float | None = None
    theta_wet: float | None = None
    calibration_status: str = "unspecified"
    api_reference_mm: float | None = None

    def __post_init__(self) -> None:
        if self.provider != "open-meteo":
            raise ConfigError("unsupported weather provider.")
        if not self.endpoint.startswith("https://"):
            raise ConfigError("weather endpoint must use https.")
        if not self.model:
            raise ConfigError("weather model must be non-empty.")
        for name in ("timeout_s", "ttl_s", "failure_ttl_s", "max_age_s"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0.0:
                raise ConfigError(f"{name} must be finite and positive.")
        if (self.theta_dry is None) != (self.theta_wet is None):
            raise ConfigError("theta_dry and theta_wet must be provided together.")
        if (
            self.theta_dry is not None
            and self.theta_wet is not None
            and not 0.0 <= self.theta_dry < self.theta_wet <= 1.0
        ):
            raise ConfigError("theta calibration must satisfy 0 <= dry < wet <= 1.")
        if self.api_reference_mm is not None and (
            not isfinite(self.api_reference_mm) or self.api_reference_mm <= 0.0
        ):
            raise ConfigError("api_reference_mm must be finite and positive.")
        if self.calibration_status not in {"unspecified", "field_validated"} and not (
            self.calibration_status.startswith("provisional_")
        ):
            # Any provisional_* anchor (CLDAS spatial, local archive climatology,
            # ...) is accepted and keeps the provisional-pressure warning.
            raise ConfigError("unsupported weather calibration_status.")


@dataclass(frozen=True)
class GeometryConfig:
    """Continuous trajectory construction and validation tolerances."""

    simplify_tolerance_m: float = 0.05
    geometry_tolerance_m: float = 0.01
    map_error_m: float = 0.0
    arc_step_deg: float = 10.0
    max_arc_segments: int = 720

    def __post_init__(self) -> None:
        for name in ("simplify_tolerance_m", "geometry_tolerance_m", "arc_step_deg"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0.0:
                raise ConfigError(f"{name} must be finite and positive.")
        if not isfinite(self.map_error_m) or self.map_error_m < 0.0:
            raise ConfigError("map_error_m must be finite and non-negative.")
        if not isinstance(self.max_arc_segments, int) or self.max_arc_segments <= 0:
            raise ConfigError("max_arc_segments must be a positive integer.")


@dataclass(frozen=True)
class DecisionConfig:
    """Candidate-pool detour budget, robust ordering, and switch hysteresis."""

    detour_ratio: float = 0.15
    clearance_target_m: float = 0.0
    clearance_tolerance_m: float = 0.01
    switch_relative_improvement: float = 0.05
    candidate_limit: int = 24
    display_limit: int = 5
    require_independent_backup: bool = False

    def __post_init__(self) -> None:
        for name in ("detour_ratio", "clearance_target_m", "clearance_tolerance_m"):
            value = getattr(self, name)
            if not isfinite(value) or value < 0.0:
                raise ConfigError(f"{name} must be finite and non-negative.")
        if not 0.0 <= self.switch_relative_improvement < 1.0:
            raise ConfigError("switch_relative_improvement must be in [0, 1).")
        if not 1 <= self.display_limit <= 5:
            raise ConfigError("display_limit must be in [1, 5].")
        if not self.display_limit <= self.candidate_limit <= 24:
            raise ConfigError("candidate_limit must be in [display_limit, 24].")
        if not isinstance(self.require_independent_backup, bool):
            raise ConfigError("require_independent_backup must be a boolean.")


@dataclass(frozen=True)
class StaticPlanningConfig:
    """Versioned request policy for the three static-GIS planning increments."""

    environment: EnvironmentConfig = EnvironmentConfig()
    weather: WeatherConfig = WeatherConfig()
    geometry: GeometryConfig = GeometryConfig()
    decision: DecisionConfig = DecisionConfig()
    soil: Mapping[str, object] = MappingProxyType({})
    hydrology: Mapping[str, object] = MappingProxyType({})
    version: str = "static_gis_route_v2"

    def __post_init__(self) -> None:
        if self.version != "static_gis_route_v2":
            raise ConfigError("unsupported static planning version.")
        object.__setattr__(self, "soil", MappingProxyType(dict(self.soil)))
        object.__setattr__(self, "hydrology", MappingProxyType(dict(self.hydrology)))

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "soil": dict(self.soil),
            "hydrology": dict(self.hydrology),
            "environment": self.environment.to_dict(),
            "weather": asdict(self.weather),
            "geometry": asdict(self.geometry),
            "decision": asdict(self.decision),
        }


def environment_multiplier(
    cell: H3Cell,
    pressure: float,
    config: EnvironmentConfig,
) -> tuple[float, bool]:
    """Return M=1+w*U*S*(1+D) and whether static evidence was unknown."""
    if not isfinite(pressure) or pressure < 0.0:
        raise ValueError("pressure must be finite and non-negative.")
    surface_unknown = cell.surface_response is None
    surface = config.unknown_surface_range[1] if surface_unknown else cell.surface_response
    if surface is None:
        raise AssertionError("surface response fallback must be numeric.")
    drainage_unknown = surface > 0.0 and (
        not cell.drainage_valid
        or cell.drainage_sensitivity is None
        or cell.drainage_boundary_affected
    )
    drainage = (
        config.unknown_drainage_range[1] if drainage_unknown else (cell.drainage_sensitivity or 0.0)
    )
    multiplier = 1.0 + pressure * surface * config.shared_sensitivity * (1.0 + drainage)
    return multiplier, bool(
        surface_unknown or drainage_unknown or (surface > 0 and cell.soil_code is None)
    )


def _pressure_key(pressure: float) -> str:
    return f"{pressure:g}"


@dataclass(frozen=True)
class FactorModelConfig:
    """Validated physical-margin and speed configuration for route evaluation."""

    landcover_speed_by_code: Mapping[int, float] = MappingProxyType({})
    soil_speed_by_uscs: Mapping[str, float] = MappingProxyType({})
    tri_best: float = 0.0
    tri_worst: float = 8.0
    missing_speed_lower: float = 0.25
    missing_speed_nominal: float = 0.60
    missing_speed_upper: float = 0.85
    missing_confidence: float = 0.50
    offroad_speed_factor: float = 0.70
    road_speed_factor: float = 1.0
    speed_floor_ratio: float = 0.05
    directed_slope_speed_min_factor: float = 0.20
    min_cone_index_kpa: float = 185.73
    max_sinkage_clearance_ratio: float = 1.0
    epsilon: float = 1.0e-6
    tri_coefficient: float = 0.1
    gravity_coefficient: float = 5.0
    max_ports: int = 20_000
    max_port_pairs: int = 200_000
    enforce_rowspacing: bool = True
    enforce_water_depth: bool = True
    enforce_soil_physics: bool = True
    enforce_scalar_slope_blocking: bool = False
    use_exact_tangent_roll: bool = True

    def __post_init__(self) -> None:
        if (
            not isfinite(self.tri_best)
            or not isfinite(self.tri_worst)
            or not self.tri_worst > self.tri_best >= 0.0
        ):
            raise ValueError("tri thresholds must satisfy tri_worst > tri_best >= 0.")
        FactorInterval(
            self.missing_speed_lower,
            self.missing_speed_nominal,
            self.missing_speed_upper,
        )
        _require_ratio("missing_confidence", self.missing_confidence)
        _require_ratio("offroad_speed_factor", self.offroad_speed_factor)
        _require_ratio("road_speed_factor", self.road_speed_factor)
        _require_ratio("speed_floor_ratio", self.speed_floor_ratio, allow_zero=True)
        _require_ratio(
            "directed_slope_speed_min_factor",
            self.directed_slope_speed_min_factor,
            allow_zero=True,
        )
        _require_positive("min_cone_index_kpa", self.min_cone_index_kpa)
        _require_positive("max_sinkage_clearance_ratio", self.max_sinkage_clearance_ratio)
        _require_ratio("epsilon", self.epsilon)
        _require_nonnegative("tri_coefficient", self.tri_coefficient)
        _require_nonnegative("gravity_coefficient", self.gravity_coefficient)
        limits = (self.max_ports, self.max_port_pairs)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in limits):
            raise ValueError("PortsMap limits must be integers.")
        if self.max_ports <= 0 or self.max_port_pairs <= 0:
            raise ValueError("PortsMap limits must be positive integers.")
        object.__setattr__(
            self,
            "landcover_speed_by_code",
            MappingProxyType(dict(self.landcover_speed_by_code)),
        )
        object.__setattr__(
            self,
            "soil_speed_by_uscs",
            MappingProxyType(dict(self.soil_speed_by_uscs)),
        )
        for mapping in (self.landcover_speed_by_code, self.soil_speed_by_uscs):
            for value in mapping.values():
                _require_ratio("configured speed factor", value, allow_zero=True)

    def to_dict(self) -> dict[str, object]:
        """Return the complete effective schema-v2 configuration."""
        return {
            "schema_version": MODEL_SCHEMA_VERSION,
            "uncertainty": {
                "missing_speed_interval": [
                    self.missing_speed_lower,
                    self.missing_speed_nominal,
                    self.missing_speed_upper,
                ],
                "missing_confidence": self.missing_confidence,
            },
            "speed": {
                "landcover_by_code": dict(sorted(self.landcover_speed_by_code.items())),
                "soil_by_uscs": dict(sorted(self.soil_speed_by_uscs.items())),
                "tri_best": self.tri_best,
                "tri_worst": self.tri_worst,
                "offroad_factor": self.offroad_speed_factor,
                "road_factor": self.road_speed_factor,
                "floor_ratio": self.speed_floor_ratio,
                "directed_slope_min_factor": self.directed_slope_speed_min_factor,
            },
            "hard_constraints": {
                "min_cone_index_kpa": self.min_cone_index_kpa,
                "max_sinkage_clearance_ratio": self.max_sinkage_clearance_ratio,
                "enforce_rowspacing": self.enforce_rowspacing,
                "enforce_water_depth": self.enforce_water_depth,
                "enforce_soil_physics": self.enforce_soil_physics,
                "enforce_scalar_slope_blocking": self.enforce_scalar_slope_blocking,
                "use_exact_tangent_roll": self.use_exact_tangent_roll,
            },
            "risk": {"epsilon": self.epsilon},
            "cost": {
                "tri_coefficient": self.tri_coefficient,
                "gravity_coefficient": self.gravity_coefficient,
            },
            "portsmap": {
                "max_ports": self.max_ports,
                "max_port_pairs": self.max_port_pairs,
            },
        }


@dataclass(frozen=True)
class FactorEvaluation:
    """Complete immutable route-time evaluation context."""

    node_metrics: Mapping[str, NodeFactorMetrics]
    directed_edges: Mapping[tuple[str, str], DirectedEdgeMetrics]
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str

    def __post_init__(self) -> None:
        hashes = (
            self.vehicle_hash,
            self.factor_model_hash,
            self.static_input_hash,
            self.graph_topology_hash,
        )
        if any(not value for value in hashes):
            raise ValueError("factor evaluation hashes must be non-empty.")
        object.__setattr__(self, "node_metrics", MappingProxyType(dict(self.node_metrics)))
        object.__setattr__(self, "directed_edges", MappingProxyType(dict(self.directed_edges)))

    def directed_adjacency(self) -> Mapping[str, list[str]]:
        """Return cached forward directed adjacency from evaluation.directed_edges."""
        adj = getattr(self, "_directed_adjacency_cache", None)
        if adj is None:
            adj = {}
            for from_h3, to_h3 in self.directed_edges:
                adj.setdefault(from_h3, []).append(to_h3)
            object.__setattr__(self, "_directed_adjacency_cache", adj)
        return adj


def load_factor_model(path: str) -> FactorModelConfig:
    """Load and normalize a physical-margin factor-model YAML file."""
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigError(f"factor model file does not exist: {path}")
    with file_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream)
    if not isinstance(loaded, dict):
        raise ConfigError("factor model file must contain a mapping.")
    return _factor_model_from_mapping(cast(dict[str, object], loaded))


def load_static_planning_config(path: str) -> StaticPlanningConfig:
    """Load the versioned soil/drainage, geometry, and robust decision policy."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(f"static planning file does not exist: {path}")
    with file_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream)
    if not isinstance(loaded, dict):
        raise ConfigError("static planning file must contain a mapping.")
    data = cast(dict[str, object], loaded)
    allowed = {
        "version",
        "soil",
        "hydrology",
        "environment",
        "weather",
        "vehicle_geometry",
        "geometry",
        "decision",
    }
    unknown = sorted(set(data).difference(allowed))
    if unknown:
        raise ConfigError(f"static planning file contains unsupported fields: {unknown}")
    _validate_static_source_sections(data)
    environment_data = _optional_mapping(data, "environment")
    weather_data = _optional_mapping(data, "weather")
    decision_data = _optional_mapping(data, "decision")
    geometry_data = _optional_mapping(data, "geometry")
    environment = EnvironmentConfig(
        model=str(environment_data.get("model", "surface_drainage_multiplier_v1")),
        pressure_basis=str(environment_data.get("pressure_basis", "synthetic_scenario")),
        comparison_pressures=_float_tuple(
            environment_data.get("comparison_pressures", [0.0, 0.5, 1.0]),
            "comparison_pressures",
        ),
        request_pressures=_float_tuple(
            environment_data.get("request_pressures", [0.5, 1.0]),
            "request_pressures",
        ),
        unknown_drainage_range=_float_pair(
            environment_data.get("unknown_drainage_range", [0.0, 1.0]),
            "unknown_drainage_range",
        ),
        unknown_surface_range=_float_pair(
            environment_data.get("unknown_surface_range", [0.0, 1.0]),
            "unknown_surface_range",
        ),
        shared_sensitivity=_mapping_float(
            environment_data,
            "shared_sensitivity",
            _mapping_float(_optional_mapping(data, "soil"), "shared_sensitivity", 1.0),
        ),
    )
    weather = WeatherConfig(
        enabled=_mapping_bool(weather_data, "enabled", False),
        provider=str(weather_data.get("provider", "open-meteo")),
        endpoint=str(
            weather_data.get("endpoint", "https://api.open-meteo.com/v1/forecast")
        ),
        model=str(weather_data.get("model", "best_match")),
        timeout_s=_mapping_float(weather_data, "timeout_s", 3.0),
        ttl_s=_mapping_float(weather_data, "ttl_s", 1800.0),
        failure_ttl_s=_mapping_float(weather_data, "failure_ttl_s", 60.0),
        max_age_s=_mapping_float(weather_data, "max_age_s", 10800.0),
        theta_dry=_mapping_optional_float(weather_data, "theta_dry"),
        theta_wet=_mapping_optional_float(weather_data, "theta_wet"),
        calibration_status=str(weather_data.get("calibration_status", "unspecified")),
        api_reference_mm=_mapping_optional_float(weather_data, "api_reference_mm"),
    )
    geometry = GeometryConfig(
        simplify_tolerance_m=_mapping_float(geometry_data, "simplify_tolerance_m", 0.05),
        geometry_tolerance_m=_mapping_float(geometry_data, "geometry_tolerance_m", 0.01),
        map_error_m=_mapping_float(geometry_data, "map_error_m", 0.0),
        arc_step_deg=_mapping_float(geometry_data, "arc_step_deg", 10.0),
        max_arc_segments=_mapping_int(geometry_data, "max_arc_segments", 720),
    )
    decision = DecisionConfig(
        detour_ratio=_mapping_float(decision_data, "detour_ratio", 0.15),
        clearance_target_m=_mapping_float(decision_data, "clearance_target_m", 0.0),
        clearance_tolerance_m=_mapping_float(decision_data, "clearance_tolerance_m", 0.01),
        switch_relative_improvement=_mapping_float(
            decision_data, "switch_relative_improvement", 0.05
        ),
        candidate_limit=_mapping_int(decision_data, "candidate_limit", 24),
        display_limit=_mapping_int(decision_data, "display_limit", 5),
        require_independent_backup=_mapping_bool(
            decision_data, "require_independent_backup", False
        ),
    )
    return StaticPlanningConfig(
        environment=environment,
        weather=weather,
        geometry=geometry,
        decision=decision,
        soil=_optional_mapping(data, "soil"),
        hydrology=_optional_mapping(data, "hydrology"),
        version=str(data.get("version", "static_gis_route_v2")),
    )


def _validate_static_source_sections(data: Mapping[str, object]) -> None:
    soil = _optional_mapping(data, "soil")
    if soil and soil.get("mode", "categorical_drainage") != "categorical_drainage":
        raise ConfigError("soil mode must be 'categorical_drainage'.")
    default_theta_v = soil.get("default_theta_v")
    if default_theta_v is not None and (
        isinstance(default_theta_v, bool)
        or not isinstance(default_theta_v, (int, float))
        or not 0.0 <= float(default_theta_v) <= 1.0
    ):
        raise ConfigError("default_theta_v must be null or a value in [0, 1].")
    hydrology = _optional_mapping(data, "hydrology")
    if hydrology and hydrology.get("backend", "grass_r_watershed") != "grass_r_watershed":
        raise ConfigError("hydrology backend must be 'grass_r_watershed'.")
    mapping_t0 = _mapping_optional_float(hydrology, "mapping_t0")
    mapping_t1 = _mapping_optional_float(hydrology, "mapping_t1")
    if (mapping_t0 is None) != (mapping_t1 is None):
        raise ConfigError("mapping_t0 and mapping_t1 must be provided together.")
    if mapping_t0 is not None and mapping_t1 is not None and mapping_t1 <= mapping_t0:
        raise ConfigError("hydrology mapping must satisfy mapping_t1 > mapping_t0.")
    vehicle = _optional_mapping(data, "vehicle_geometry")
    if vehicle and vehicle.get("reference_point", "rear_axle_center") != "rear_axle_center":
        raise ConfigError("vehicle_geometry reference_point must be rear_axle_center.")


def _optional_mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"static planning field {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _float_tuple(value: object, name: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in value
    ):
        raise ConfigError(f"{name} must be a numeric sequence.")
    return tuple(float(cast(float, item)) for item in value)


def _float_pair(value: object, name: str) -> tuple[float, float]:
    values = _float_tuple(value, name)
    if len(values) != 2:
        raise ConfigError(f"{name} must contain exactly two values.")
    return (values[0], values[1])


def _mapping_float(data: Mapping[str, object], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"static planning field {key!r} must be numeric.")
    return float(value)


def _mapping_optional_float(data: Mapping[str, object], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"static planning field {key!r} must be numeric or null.")
    numeric = float(value)
    if not isfinite(numeric):
        raise ConfigError(f"static planning field {key!r} must be finite.")
    return numeric


def _mapping_bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"static planning field {key!r} must be boolean.")
    return value


def _mapping_int(data: Mapping[str, object], name: str, default: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"static planning field {name!r} must be an integer.")
    return value


def evaluate_factor_model(
    graph: H3Graph,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    environment: EnvironmentConfig | None = None,
) -> FactorEvaluation:
    """Evaluate physical node evidence once and freeze directed edge metrics."""
    if not graph.cells:
        raise PlanningInputError("factor evaluation requires a non-empty graph.")
    soil_cells = [
        cell
        for cell in graph.cells.values()
        if cell.uscs is not None and cell.soil_moisture is not None
    ]
    soil_cone_cache: dict[str, float] = {}
    soil_sinkage_cache: dict[str, tuple[float, float]] = {}
    if soil_cells:
        uscs_array = np.array([str(cell.uscs) for cell in soil_cells], dtype=np.str_)
        moisture_array = np.array(
            [float(cast(float, cell.soil_moisture)) for cell in soil_cells],
            dtype=np.float64,
        )
        cone_values = vectorized_cone_index_kpa(uscs_array, moisture_array)
        soil_cone_cache = {
            cell.h3index: float(value)
            for cell, value in zip(soil_cells, cone_values, strict=True)
            if np.isfinite(value)
        }
        bekker_soils = np.array(
            [_cell_bekker_soil(cell) or "" for cell in soil_cells], dtype=np.str_
        )
        sinkage_m, resistance_n = vectorized_bekker_sinkage(
            bekker_soils, moisture_array, vehicle
        )
        soil_sinkage_cache = {
            cell.h3index: (float(s), float(r))
            for cell, s, r in zip(soil_cells, sinkage_m, resistance_n, strict=True)
            if np.isfinite(s) and np.isfinite(r)
        }
    strict_static_mode = False
    nodes = {
        cell_id: _node_metrics(
            cell,
            _raw_node_evidence(
                cell,
                vehicle,
                config,
                strict_static_mode=strict_static_mode,
                soil_cone_cache=soil_cone_cache,
                soil_sinkage_cache=soil_sinkage_cache,
            ),
            vehicle,
        )
        for cell_id, cell in sorted(graph.cells.items())
    }
    edges = build_directed_edge_cache(graph, nodes, vehicle, config, environment)
    return FactorEvaluation(
        node_metrics=nodes,
        directed_edges=edges,
        vehicle_hash=canonical_hash(_vehicle_payload(vehicle)),
        factor_model_hash=canonical_hash(config.to_dict()),
        static_input_hash=static_input_hash(graph),
        graph_topology_hash=graph_topology_hash(graph),
    )


def build_directed_edge_cache(
    graph: H3Graph,
    node_metrics: Mapping[str, NodeFactorMetrics],
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    environment: EnvironmentConfig | None = None,
) -> dict[tuple[str, str], DirectedEdgeMetrics]:
    """Build the authoritative directed metrics used by route searches."""
    if set(node_metrics) != set(graph.cells):
        raise PlanningInputError("node metrics must cover every graph cell exactly once.")
    from h3_offroad_planner.vectorized_factor import evaluate_directed_edges_vectorized

    return evaluate_directed_edges_vectorized(
        graph,
        node_metrics,
        vehicle,
        config,
        environment,
    )


def evaluate_path_metrics(
    h3_path: list[str] | tuple[str, ...],
    evaluation: FactorEvaluation,
) -> PathMetrics:
    """Recompute exact path aggregates from the frozen directed-edge cache."""
    if not h3_path:
        raise PlanningInputError("h3_path must contain at least one cell.")
    if any(cell_id not in evaluation.node_metrics for cell_id in h3_path):
        raise PlanningInputError("h3_path references a cell absent from factor evaluation.")
    if len(h3_path) == 1:
        margin = evaluation.node_metrics[h3_path[0]].safety_margin
        return PathMetrics(
            0.0,
            0.0,
            0.0,
            0.0,
            True,
            0.0,
            0.0,
            margin.lower,
            margin.nominal,
            0,
            {},
        )
    edges = _path_edges(h3_path, evaluation)
    bounded = all(edge.eta_upper_bounded for edge in edges)
    eta_upper = sum(cast(float, edge.eta_upper_s) for edge in edges) if bounded else None
    weighted_margin = sum(edge.safety_margin_nominal * edge.distance_m for edge in edges)
    total_distance = sum(edge.distance_m for edge in edges)
    margin_min = max(0.0, min(1.0, min(edge.safety_margin_lower for edge in edges)))
    margin_mean = max(margin_min, min(1.0, max(0.0, weighted_margin / total_distance)))
    return PathMetrics(
        distance_m=total_distance,
        eta_lower_s=sum(edge.eta_lower_s for edge in edges),
        eta_s=sum(edge.eta_s for edge in edges),
        eta_upper_s=eta_upper,
        eta_upper_bounded=bounded,
        terrain_risk=sum(edge.terrain_risk for edge in edges),
        travel_cost=sum(edge.travel_cost for edge in edges),
        safety_margin_min=margin_min,
        safety_margin_mean=margin_mean,
        edge_count=len(edges),
        environment_distance_m={
            key: sum(edge.environment_distance_m[key] for edge in edges)
            for key in edges[0].environment_distance_m
        },
    )


def _path_edges(
    h3_path: list[str] | tuple[str, ...],
    evaluation: FactorEvaluation,
) -> list[DirectedEdgeMetrics]:
    edges: list[DirectedEdgeMetrics] = []
    for first, second in zip(h3_path[:-1], h3_path[1:], strict=True):
        metric = evaluation.directed_edges.get((first, second))
        if metric is None:
            raise PlanningInputError(
                f"path contains missing or impassable edge {first!r}->{second!r}."
            )
        edges.append(metric)
    return edges


def canonical_hash(payload: object) -> str:
    """Return SHA-256 for canonical UTF-8 JSON serialization."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def static_input_hash(graph: H3Graph) -> str:
    """Hash vehicle-independent facts only, excluding route-time score fields."""
    cached = getattr(graph, "_cached_static_input_hash", None)
    if cached is not None and getattr(graph, "_cached_cell_count", None) == len(graph.cells):
        return str(cached)

    rows = []
    for cell_id in sorted(graph.cells):
        cell = graph.cells[cell_id]
        rows.append(
            {
                "h3index": cell.h3index,
                "parent_h3": cell.parent_h3,
                "lat": cell.lat,
                "lng": cell.lng,
                "elevation": cell.elevation,
                "slope": cell.slope,
                "tri": cell.tri,
                "lc_factor": cell.lc_factor if isfinite(cell.lc_factor) else "inf",
                "landcover_code": cell.landcover_code,
                "landcover_type": cell.landcover_type,
                "soil_code": cell.soil_code,
                "soil_type": cell.soil_type,
                "soil_texture": cell.soil_texture,
                "uscs": cell.uscs,
                "soil_moisture": cell.soil_moisture,
                "depth": cell.depth,
                "rowspacing": cell.rowspacing,
                "soil_source": cell.soil_source,
                "source_support_m": cell.source_support_m,
                "twi": cell.twi,
                "drainage_sensitivity": cell.drainage_sensitivity,
                "drainage_valid": cell.drainage_valid,
                "drainage_boundary_affected": cell.drainage_boundary_affected,
                "surface_response": cell.surface_response,
                "surface_evidence": cell.surface_evidence,
                "has_road": cell.has_road,
                "static_passable": cell.is_passable,
            }
        )
    h = canonical_hash(rows)
    try:
        graph._cached_static_input_hash = h  # type: ignore[attr-defined]
        graph._cached_cell_count = len(graph.cells)  # type: ignore[attr-defined]
    except Exception:
        pass
    return h


def graph_topology_hash(graph: H3Graph) -> str:
    """Hash graph resolutions and deterministic undirected topology."""
    cached = getattr(graph, "_cached_topology_hash", None)
    if cached is not None and getattr(graph, "_cached_edge_count", None) == len(graph.edges):
        return str(cached)

    edges = [
        {
            "a": edge.cell_a,
            "b": edge.cell_b,
            "distance_m": edge.geo_distance,
            "slope_a_to_b": edge.slope_a_to_b,
            "slope_b_to_a": edge.slope_b_to_a,
        }
        for edge in sorted(graph.edges.values(), key=lambda item: (item.cell_a, item.cell_b))
    ]
    h = canonical_hash(
        {
            "resolution_fine": graph.resolution_fine,
            "resolution_coarse": graph.resolution_coarse,
            "cells": sorted(graph.cells),
            "edges": edges,
        }
    )
    try:
        graph._cached_topology_hash = h  # type: ignore[attr-defined]
        graph._cached_edge_count = len(graph.edges)  # type: ignore[attr-defined]
    except Exception:
        pass
    return h


def write_effective_snapshots(
    output_dir: str,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> tuple[str, str]:
    """Write normalized vehicle and factor-model YAML snapshots."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    vehicle_path = directory / "effective_vehicle.yaml"
    factor_path = directory / "effective_factor_model.yaml"
    _atomic_yaml_write(vehicle_path, _vehicle_payload(vehicle))
    _atomic_yaml_write(factor_path, config.to_dict())
    return str(vehicle_path), str(factor_path)


def write_static_planning_snapshot(
    output_dir: str,
    config: StaticPlanningConfig,
) -> str:
    """Write the effective static-planning policy needed by replanning."""
    path = Path(output_dir) / "effective_static_planning.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_yaml_write(path, config.to_dict())
    return str(path)


@dataclass(frozen=True)
class _RawNodeEvidence:
    speed_factors: tuple[FactorInterval, ...]
    safety_margin: FactorInterval
    passable: bool
    confidence: float
    reasons: tuple[str, ...]
    cone_index_kpa: float | None
    sinkage_m: float | None


def _raw_node_evidence(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    strict_static_mode: bool = False,
    soil_cone_cache: Mapping[str, float] | None = None,
    soil_sinkage_cache: Mapping[str, tuple[float, float]] | None = None,
) -> _RawNodeEvidence:
    reasons: list[str] = []
    missing = FactorInterval(
        config.missing_speed_lower,
        config.missing_speed_nominal,
        config.missing_speed_upper,
    )
    slope = _floor_interval(
        _known_interval(_slope_margin(cell.slope, vehicle)),
        config.speed_floor_ratio,
    )
    landcover = _landcover_speed_interval(
        cell, vehicle, config, missing, reasons, strict_static_mode
    )
    soil, cone_index, sinkage = _soil_speed_interval(
        cell,
        vehicle,
        config,
        missing,
        reasons,
        soil_cone_cache=soil_cone_cache,
        soil_sinkage_cache=soil_sinkage_cache,
    )
    tri = _floor_interval(
        _known_interval(_tri_speed_factor(cell.tri, config)),
        config.speed_floor_ratio,
    )
    if cell.has_road and config.road_speed_factor == 1.0:
        road = _ROAD_INTERVAL_1_0
    elif not cell.has_road and config.offroad_speed_factor == 0.70:
        road = _OFFROAD_INTERVAL_0_7
    else:
        road = _known_interval(
            config.road_speed_factor if cell.has_road else config.offroad_speed_factor
        )
    passable = _hard_constraints(
        cell,
        vehicle,
        config,
        cone_index,
        sinkage,
        reasons,
        strict_static_mode,
    )
    margin = _node_safety_margin(
        cell,
        vehicle,
        config,
        cone_index,
        sinkage,
        passable,
        strict_static_mode,
    )
    confidence = (
        config.missing_confidence
        if any(reason.startswith(MISSING_REASON_PREFIX) for reason in reasons)
        else 1.0
    )
    return _RawNodeEvidence(
        speed_factors=(slope, landcover, soil, tri, road),
        safety_margin=_known_interval(margin),
        passable=passable,
        confidence=confidence,
        reasons=tuple(sorted(set(reasons))),
        cone_index_kpa=cone_index,
        sinkage_m=sinkage,
    )


def _landcover_speed_interval(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    missing: FactorInterval,
    reasons: list[str],
    strict_static_mode: bool,
) -> FactorInterval:
    if cell.landcover_code is None and cell.landcover_type is None:
        reasons.append("MISSING_LANDCOVER")
        return _floor_interval(missing, config.speed_floor_ratio)

    is_water = cell.landcover_code == 5 or (cell.landcover_type or "").lower() == "water"
    if (
        is_water
        and cell.depth is not None
        and cell.depth <= vehicle.ground_clearance_m
    ):
        wading_speed = max(
            config.speed_floor_ratio,
            0.50 * (1.0 - cell.depth / max(vehicle.ground_clearance_m, 0.01)),
        )
        return _known_interval(wading_speed)

    if (
        cell.rowspacing is not None
        and (cell.landcover_code == 2 or (cell.landcover_type or "").lower() == "forest")
    ):
        safe_width = vehicle.width_m or 2.2
        if cell.rowspacing >= safe_width:
            base_speed = config.landcover_speed_by_code.get(cell.landcover_code or -1, 0.40)
            clearance_factor = min(
                1.0,
                max(0.5, (cell.rowspacing - safe_width) / max(safe_width, 0.01) + 0.5),
            )
            return _known_interval(max(config.speed_floor_ratio, base_speed * clearance_factor))

    landcover_code = -1 if cell.landcover_code is None else cell.landcover_code
    configured = config.landcover_speed_by_code.get(landcover_code)

    if configured is not None:
        return _known_interval(configured)
    if isfinite(cell.lc_factor):
        return _floor_interval(
            _known_interval(min(1.0, 1.0 / max(cell.lc_factor, 1.0))),
            config.speed_floor_ratio,
        )
    return _known_interval(0.0)


_DEFAULT_BEKKER = BekkerChecker()
_ORIGINAL_BEKKER_ENRICH_CELL = BekkerChecker.enrich_cell


def _soil_speed_interval(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    missing: FactorInterval,
    reasons: list[str],
    *,
    soil_cone_cache: Mapping[str, float] | None = None,
    soil_sinkage_cache: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[FactorInterval, float | None, float | None]:
    if cell.has_road:
        # Paved / road surface: Bekker sinkage, cone index and soil mobility do
        # not apply, so the soil speed factor is neutral (1.0) and no soil
        # reason codes or soil safety margins are emitted for road cells.
        return _known_interval(1.0), None, None

    if not config.enforce_soil_physics:
        configured = config.soil_speed_by_uscs.get(cell.uscs or "")
        return (
            _known_interval(configured)
            if configured is not None
            else _floor_interval(missing, config.speed_floor_ratio),
            None,
            None,
        )

    if cell.uscs is None or cell.soil_moisture is None:
        reasons.append("MISSING_SOIL")
        configured = config.soil_speed_by_uscs.get(cell.uscs or "")
        return (
            _known_interval(configured)
            if configured is not None
            else _floor_interval(missing, config.speed_floor_ratio),
            None,
            None,
        )

    cone_index: float | None = None
    sinkage: float | None = None
    soil_mobility: float | None = cell.soil_mobility
    fast_path = False

    if (
        BekkerChecker.enrich_cell is _ORIGINAL_BEKKER_ENRICH_CELL
        and soil_cone_cache is not None
        and cell.h3index in soil_cone_cache
    ):
        cone_index = soil_cone_cache[cell.h3index]
        if cone_index < config.min_cone_index_kpa:
            soil_mobility = 0.0
            sinkage = None
            fast_path = True
        elif soil_sinkage_cache is not None and cell.h3index in soil_sinkage_cache:
            sinkage = soil_sinkage_cache[cell.h3index][0]
            fast_path = True
        elif cell.sinkage_m is not None:
            sinkage = cell.sinkage_m
            fast_path = True
        elif _cell_bekker_soil(cell) is None or (soil_sinkage_cache is not None and cell.h3index not in soil_sinkage_cache):
            sinkage = None
            fast_path = True

    if not fast_path:
        clone = replace(cell)
        if soil_cone_cache is not None and cell.h3index in soil_cone_cache:
            clone.cone_index_kpa = soil_cone_cache[cell.h3index]
        if (
            soil_sinkage_cache is not None
            and cell.h3index in soil_sinkage_cache
            and (clone.cone_index_kpa is None or clone.cone_index_kpa >= config.min_cone_index_kpa)
        ):
            clone.sinkage_m, clone.sinkage_resistance = soil_sinkage_cache[cell.h3index]
        try:
            BekkerChecker(ci_threshold_kpa=config.min_cone_index_kpa).enrich_cell(clone, vehicle)
        except AssessmentError:
            pass
        cone_index = clone.cone_index_kpa
        sinkage = clone.sinkage_m
        soil_mobility = clone.soil_mobility

    configured = config.soil_speed_by_uscs.get(cell.uscs)
    clearance_limit = vehicle.ground_clearance_m * config.max_sinkage_clearance_ratio
    sinkage_factor: float | None = None
    if sinkage is not None and isfinite(sinkage):
        sinkage_factor = max(config.speed_floor_ratio, 1.0 - sinkage / clearance_limit)
    elif sinkage is not None and not isfinite(sinkage):
        sinkage_factor = config.speed_floor_ratio

    if configured is not None:
        if sinkage_factor is not None:
            value = configured * sinkage_factor
        elif soil_mobility is not None:
            value = configured * max(config.speed_floor_ratio, min(1.0, soil_mobility))
        else:
            value = configured
    elif soil_mobility is not None:
        value = max(0.0, min(1.0, soil_mobility))
    elif sinkage_factor is not None:
        value = sinkage_factor
    else:
        reasons.extend(("MISSING_SOIL_EVIDENCE", "SOIL_MODEL_PARTIAL"))
        return _floor_interval(missing, config.speed_floor_ratio), cone_index, sinkage
    interval = _known_interval(value)
    interval = _floor_interval(interval, config.speed_floor_ratio)
    return interval, cone_index, sinkage


def _hard_constraints(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    cone_index: float | None,
    sinkage: float | None,
    reasons: list[str],
    strict_static_mode: bool,
) -> bool:
    if not cell.is_passable:
        reasons.append("STATIC_BLOCKED")
    is_water = cell.landcover_code == 5 or (cell.landcover_type or "").lower() == "water"
    if is_water:
        if config.enforce_water_depth:
            if cell.depth is None:
                reasons.append("WATER")
            elif cell.depth > vehicle.ground_clearance_m:
                reasons.append("WATER_DEPTH_LIMIT")
    if config.enforce_rowspacing and cell.rowspacing is not None:
        safe_width = vehicle.width_m or 2.2
        if cell.rowspacing < safe_width:
            reasons.append("ROWSPACING_BLOCKED")
    if (cell.landcover_type or "").lower() == "building" or cell.landcover_code in {0, 6}:
        reasons.append("BUILDING")
    if abs(cell.slope) > vehicle.max_climb_angle_deg:
        reasons.append("STEEP_SLOPE")
    if config.enforce_soil_physics:
        if cone_index is not None and cone_index < config.min_cone_index_kpa:
            reasons.append("CONE_INDEX_INSUFFICIENT")
        clearance_limit = vehicle.ground_clearance_m * config.max_sinkage_clearance_ratio
        if sinkage is not None and (sinkage >= clearance_limit or not isfinite(sinkage)):
            reasons.append("SINKAGE_CLEARANCE_EXCEEDED")
    hard_codes = {
        "STATIC_BLOCKED",
        "WATER",
        "WATER_DEPTH_LIMIT",
        "BUILDING",
        "ROWSPACING_BLOCKED",
        "CONE_INDEX_INSUFFICIENT",
        "SINKAGE_CLEARANCE_EXCEEDED",
    }
    if config.enforce_scalar_slope_blocking:
        hard_codes.add("STEEP_SLOPE")
    return not hard_codes.intersection(reasons)


def _node_safety_margin(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    cone_index: float | None,
    sinkage: float | None,
    passable: bool,
    strict_static_mode: bool,
) -> float:
    if not passable:
        return 0.0
    margins: list[float] = []
    if abs(cell.slope) <= vehicle.max_climb_angle_deg:
        margins.append(max(0.05, _slope_margin(cell.slope, vehicle)))
    else:
        margins.append(0.05)
    if cone_index is not None:
        margins.append(1.0 - config.min_cone_index_kpa / cone_index)
    if sinkage is not None:
        clearance = vehicle.ground_clearance_m * config.max_sinkage_clearance_ratio
        margins.append(1.0 - sinkage / clearance if isfinite(sinkage) else 0.0)
    if cell.depth is not None and cell.depth <= vehicle.ground_clearance_m:
        margins.append(1.0 - cell.depth / max(vehicle.ground_clearance_m, 0.01))
    if cell.rowspacing is not None:
        safe_width = vehicle.width_m or 2.2
        if cell.rowspacing >= safe_width:
            margins.append(min(1.0, (cell.rowspacing - safe_width) / max(safe_width, 0.01)))
    return _clamp_ratio(min(margins) if margins else 1.0)


def _node_metrics(
    cell: H3Cell,
    evidence: _RawNodeEvidence,
    vehicle: VehicleProfile,
) -> NodeFactorMetrics:
    maximum = vehicle.max_speed_kmh / 3.6
    speeds = _node_speed_interval(evidence, maximum)
    factors = evidence.speed_factors
    return NodeFactorMetrics._fast_create(
        cell.h3index,
        factors[0],
        factors[1],
        factors[2],
        factors[3],
        factors[4],
        evidence.safety_margin,
        speeds[0],
        speeds[1],
        speeds[2],
        evidence.passable,
        evidence.confidence,
        evidence.reasons,
        evidence.cone_index_kpa,
        evidence.sinkage_m,
    )


def _node_speed_interval(
    evidence: _RawNodeEvidence,
    maximum_mps: float,
) -> tuple[float, float, float]:
    if not evidence.passable:
        return (0.0, 0.0, 0.0)
    f0, f1, f2, f3, f4 = evidence.speed_factors
    p_lower = f0.lower * f1.lower * f2.lower * f3.lower * f4.lower
    p_nominal = f0.nominal * f1.nominal * f2.nominal * f3.nominal * f4.nominal
    p_upper = f0.upper * f1.upper * f2.upper * f3.upper * f4.upper
    return (
        min(maximum_mps, maximum_mps * p_lower),
        min(maximum_mps, maximum_mps * p_nominal),
        min(maximum_mps, maximum_mps * p_upper),
    )


def compute_directed_roll_deg(terrain_slope_deg: float, pitch_deg: float) -> float:
    """Exact tangent decomposition of terrain slope into directed pitch and roll angles.

    tan(theta_roll) = sqrt(max(0, tan^2(theta_terrain) - tan^2(theta_pitch)))
    theta_roll = degrees(arctan(tan(theta_roll)))

    Note on discrete terrain slope: at the discrete cell level, terrain_slope uses a cell-level
    proxy max(slope_u, slope_v); true continuous DEM gradient projection along
    polyline micro-segments belongs to M2.
    """
    t_terrain = tan(radians(max(0.0, terrain_slope_deg)))
    t_pitch = tan(radians(abs(pitch_deg)))
    t_roll_sq = max(0.0, t_terrain * t_terrain - t_pitch * t_pitch)
    return float(degrees(atan(sqrt(t_roll_sq))))


def _directed_edge_metrics(
    graph: H3Graph,
    edge: H3Edge,
    from_h3: str,
    to_h3: str,
    nodes: Mapping[str, NodeFactorMetrics],
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    environment: EnvironmentConfig | None,
) -> DirectedEdgeMetrics | None:
    first = nodes[from_h3]
    second = nodes[to_h3]
    if not first.is_passable or not second.is_passable:
        return None
    slope = _directional_slope(edge, from_h3, to_h3)
    grade_force = _grade_force_n(slope, vehicle)
    source_cell = graph.cells[from_h3]
    target_cell = graph.cells[to_h3]
    terrain_slope = max(source_cell.slope, target_cell.slope)
    if config.use_exact_tangent_roll:
        roll_deg = compute_directed_roll_deg(terrain_slope, slope)
    else:
        roll_deg = float(sqrt(max(0.0, terrain_slope * terrain_slope - slope * slope)))
    max_roll = getattr(vehicle, "effective_max_roll_angle_deg", 25.0)
    if abs(slope) > vehicle.max_climb_angle_deg or grade_force > vehicle.max_thrust_n or roll_deg > max_roll:
        return None
    directed = _directed_slope_factor(slope, vehicle, config)
    speeds = _edge_speed_interval(first, second, directed)
    speed_lower, speed_nominal, speed_upper = speeds
    if speed_nominal <= 0.0 or speed_upper <= 0.0:
        return None
    margin = _edge_safety_margin(first, second, slope, grade_force, vehicle, roll_deg=roll_deg)
    travel_cost = _travel_cost(edge, source_cell, target_cell, slope, vehicle, config)
    if not isfinite(travel_cost):
        return None
    severity = -log(max(margin, config.epsilon))
    return DirectedEdgeMetrics(
        from_h3=from_h3,
        to_h3=to_h3,
        distance_m=edge.geo_distance,
        eta_lower_s=edge.geo_distance / speed_upper,
        eta_s=edge.geo_distance / speed_nominal,
        eta_upper_s=None if speed_lower <= 0.0 else edge.geo_distance / speed_lower,
        eta_upper_bounded=speed_lower > 0.0,
        terrain_risk=edge.geo_distance * severity,
        travel_cost=travel_cost,
        safety_margin_lower=margin,
        safety_margin_nominal=margin,
        safety_margin_upper=margin,
        directed_slope_deg=slope,
        environment_distance_m=(
            {}
            if environment is None
            else {
                _pressure_key(pressure): edge.geo_distance
                * (
                    environment_multiplier(source_cell, pressure, environment)[0]
                    + environment_multiplier(target_cell, pressure, environment)[0]
                )
                / 2.0
                for pressure in environment.comparison_pressures
            }
        ),
    )


def _edge_speed_interval(
    first: NodeFactorMetrics,
    second: NodeFactorMetrics,
    directed: FactorInterval,
) -> tuple[float, float, float]:
    return (
        min(first.speed_lower_mps, second.speed_lower_mps) * directed.lower,
        min(first.speed_nominal_mps, second.speed_nominal_mps) * directed.nominal,
        min(first.speed_upper_mps, second.speed_upper_mps) * directed.upper,
    )


def _edge_safety_margin(
    first: NodeFactorMetrics,
    second: NodeFactorMetrics,
    slope_deg: float,
    grade_force_n: float,
    vehicle: VehicleProfile,
    roll_deg: float = 0.0,
) -> float:
    max_roll = getattr(vehicle, "effective_max_roll_angle_deg", 25.0)
    return _clamp_ratio(
        min(
            first.safety_margin.lower,
            second.safety_margin.lower,
            _slope_margin(slope_deg, vehicle),
            1.0 - grade_force_n / vehicle.max_thrust_n,
            1.0 - roll_deg / max_roll,
        )
    )


def _travel_cost(
    edge: H3Edge,
    source_cell: H3Cell,
    target_cell: H3Cell,
    slope_deg: float,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> float:
    landcover_cost = target_cell.lc_factor if isfinite(target_cell.lc_factor) else inf
    slope_utilization = abs(slope_deg) / vehicle.max_climb_angle_deg
    terrain_factor = 1.0 + slope_utilization**2 + config.tri_coefficient * target_cell.tri
    elevation_gain = max(target_cell.elevation - source_cell.elevation, 0.0)
    return (
        edge.geo_distance * landcover_cost * terrain_factor
        + config.gravity_coefficient * elevation_gain
    )


def _directed_slope_factor(
    slope_deg: float,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> FactorInterval:
    divisor = vehicle.max_climb_angle_deg if slope_deg >= 0.0 else 2.0 * vehicle.max_climb_angle_deg
    nominal = max(config.directed_slope_speed_min_factor, 1.0 - abs(slope_deg) / divisor)
    spread = (1.0 - config.missing_confidence) * 0.1
    return FactorInterval(max(0.0, nominal - spread), nominal, min(1.0, nominal + spread))


def _slope_margin(slope_deg: float, vehicle: VehicleProfile) -> float:
    return _clamp_ratio(1.0 - abs(slope_deg) / vehicle.max_climb_angle_deg)


def _grade_force_n(slope_deg: float, vehicle: VehicleProfile) -> float:
    uphill_component = max(sin(radians(slope_deg)), 0.0)
    return vehicle.mass_kg * GRAVITY_MPS2 * uphill_component


def _tri_speed_factor(tri: float, config: FactorModelConfig) -> float:
    position = (tri - config.tri_best) / (config.tri_worst - config.tri_best)
    return 1.0 - min(max(position, 0.0), 1.0)


def _directional_slope(edge: H3Edge, from_h3: str, to_h3: str) -> float:
    if edge.cell_a == from_h3 and edge.cell_b == to_h3:
        return edge.slope_a_to_b
    if edge.cell_b == from_h3 and edge.cell_a == to_h3:
        return edge.slope_b_to_a
    raise PlanningInputError("directed edge endpoints do not match graph edge.")


def _factor_model_from_mapping(data: dict[str, object]) -> FactorModelConfig:
    schema_version = _schema_version(data)
    if schema_version == MODEL_SCHEMA_VERSION:
        _validate_schema_v2(data)
    elif schema_version == 1:
        _warn_unused_legacy_fields(data)
    else:
        raise ConfigError(f"unsupported factor model schema_version: {schema_version}")
    uncertainty = _mapping(data, "uncertainty")
    speed = _mapping(data, "speed")
    hard = _mapping(data, "hard_constraints")
    risk = _mapping(data, "risk")
    cost = _mapping(data, "cost")
    portsmap = _mapping(data, "portsmap")
    legacy_calibration = _mapping(data, "benefit") if schema_version == 1 else {}
    missing_key = (
        "missing_speed_interval" if schema_version == MODEL_SCHEMA_VERSION else "missing_interval"
    )
    missing = _sequence(uncertainty, missing_key, [0.25, 0.60, 0.85])
    if len(missing) != 3:
        raise ConfigError(f"uncertainty.{missing_key} must contain three values.")
    tri_source = speed if schema_version == MODEL_SCHEMA_VERSION else legacy_calibration
    return FactorModelConfig(
        landcover_speed_by_code=_int_float_mapping(speed, "landcover_by_code"),
        soil_speed_by_uscs=_str_float_mapping(speed, "soil_by_uscs"),
        tri_best=_float(tri_source, "tri_best", 0.0),
        tri_worst=_float(tri_source, "tri_worst", 8.0),
        missing_speed_lower=_sequence_float(missing, 0, missing_key),
        missing_speed_nominal=_sequence_float(missing, 1, missing_key),
        missing_speed_upper=_sequence_float(missing, 2, missing_key),
        missing_confidence=_float(uncertainty, "missing_confidence", 0.5),
        offroad_speed_factor=_float(speed, "offroad_factor", 0.7),
        road_speed_factor=_float(speed, "road_factor", 1.0),
        speed_floor_ratio=_float(speed, "floor_ratio", 0.05),
        directed_slope_speed_min_factor=_float(speed, "directed_slope_min_factor", 0.2),
        min_cone_index_kpa=_float(hard, "min_cone_index_kpa", 185.73),
        max_sinkage_clearance_ratio=_float(hard, "max_sinkage_clearance_ratio", 1.0),
        epsilon=_float(risk, "epsilon", 1.0e-6),
        tri_coefficient=_float(cost, "tri_coefficient", 0.1),
        gravity_coefficient=_float(cost, "gravity_coefficient", 5.0),
        max_ports=_int(portsmap, "max_ports", 20_000),
        max_port_pairs=_int(portsmap, "max_port_pairs", 200_000),
        enforce_rowspacing=_bool(hard, "enforce_rowspacing", True),
        enforce_water_depth=_bool(hard, "enforce_water_depth", True),
        enforce_soil_physics=_bool(hard, "enforce_soil_physics", True),
        enforce_scalar_slope_blocking=_bool(hard, "enforce_scalar_slope_blocking", False),
        use_exact_tangent_roll=_bool(hard, "use_exact_tangent_roll", True),
    )


def _schema_version(data: Mapping[str, object]) -> int:
    value = data.get("schema_version", 1)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError("factor model schema_version must be an integer.")
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError("factor model schema_version must be an integer.") from exc


def _validate_schema_v2(data: Mapping[str, object]) -> None:
    _reject_unknown_fields(data, SCHEMA_V2_SECTIONS, "factor model")
    for section, allowed in SCHEMA_V2_FIELDS.items():
        _reject_unknown_fields(_mapping(data, section), allowed, f"factor model {section}")


def _warn_unused_legacy_fields(data: Mapping[str, object]) -> None:
    ignored = [f"section:{name}" for name in sorted(set(data) - LEGACY_ACTIVE_SECTIONS)]
    for section, allowed in LEGACY_ACTIVE_FIELDS.items():
        raw = _mapping(data, section)
        ignored.extend(f"{section}.{name}" for name in sorted(set(raw) - allowed))
    if ignored:
        warnings.warn(
            f"unused factor model fields ignored: {', '.join(ignored)}",
            UserWarning,
            stacklevel=3,
        )


def _reject_unknown_fields(
    data: Mapping[str, object],
    allowed: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{label} contains unknown fields: {unknown}")


def _mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"factor model section {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _sequence(
    data: Mapping[str, object],
    key: str,
    default: object,
) -> list[object] | tuple[object, ...]:
    value = data.get(key, default)
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"factor model field {key!r} must be a sequence.")
    return cast(list[object] | tuple[object, ...], value)


def _sequence_float(values: list[object] | tuple[object, ...], index: int, key: str) -> float:
    value = values[index]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"factor model field {key!r} must contain numbers.")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"factor model field {key!r} must contain numbers.") from exc


def _float(data: Mapping[str, object], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"factor model field {key!r} must be numeric.")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"factor model field {key!r} must be numeric.") from exc


def _int(data: Mapping[str, object], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"factor model field {key!r} must be an integer.")
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"factor model field {key!r} must be an integer.") from exc


def _bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"true", "1", "yes"}:
            return True
        if value.lower() in {"false", "0", "no"}:
            return False
    raise ConfigError(f"factor model field {key!r} must be a boolean.")


def _int_float_mapping(data: Mapping[str, object], key: str) -> dict[int, float]:
    raw = _mapping(data, key)
    result: dict[int, float] = {}
    for name, value in raw.items():
        if isinstance(name, bool) or not isinstance(name, (int, str)):
            raise ConfigError(f"factor model field {key!r} must use integer keys.")
        try:
            normalized = int(name)
        except ValueError as exc:
            raise ConfigError(f"factor model field {key!r} must use integer keys.") from exc
        if normalized in result:
            raise ConfigError(
                f"factor model field {key!r} contains duplicate normalized key {normalized}."
            )
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ConfigError(f"factor model field {key!r} must map integers to numbers.")
        try:
            result[normalized] = float(value)
        except ValueError as exc:
            raise ConfigError(f"factor model field {key!r} must map integers to numbers.") from exc
    return result


def _str_float_mapping(data: Mapping[str, object], key: str) -> dict[str, float]:
    raw = _mapping(data, key)
    result: dict[str, float] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"factor model field {key!r} must use non-empty string keys.")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ConfigError(f"factor model field {key!r} must map strings to numbers.")
        try:
            result[name] = float(value)
        except ValueError as exc:
            raise ConfigError(f"factor model field {key!r} must map strings to numbers.") from exc
    return result


def _known_interval(value: float | None) -> FactorInterval:
    if value is None:
        raise ValueError("known interval value must not be None.")
    bounded = _clamp_ratio(value)
    return FactorInterval(bounded, bounded, bounded)


def _floor_interval(interval: FactorInterval, floor: float) -> FactorInterval:
    return FactorInterval(
        max(floor, interval.lower),
        max(floor, interval.nominal),
        max(floor, interval.upper),
    )


def _clamp_ratio(value: float) -> float:
    return min(1.0, max(0.0, value))


def _product(values: tuple[float, ...]) -> float:
    product = 1.0
    for value in values:
        product *= value
    return product


def _require_ratio(name: str, value: float, allow_zero: bool = False) -> None:
    lower_valid = value >= 0.0 if allow_zero else value > 0.0
    if not isfinite(value) or not lower_valid or value > 1.0:
        bracket = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be finite and in {bracket}.")


def _require_positive(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive.")


def _require_nonnegative(name: str, value: float) -> None:
    if not isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative.")


def _vehicle_payload(vehicle: VehicleProfile) -> dict[str, object]:
    return dict(asdict(vehicle))


def _atomic_yaml_write(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=True)
    temporary.replace(path)

