"""Vehicle-aware physical-margin evaluation and immutable directed-edge metrics."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import inf, isfinite, log, radians, sin
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml  # type: ignore[import-untyped]

from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.models import (
    AssessmentError,
    ConfigError,
    H3Cell,
    H3Edge,
    H3Graph,
    PlanningInputError,
    VehicleProfile,
)

__all__ = [
    "DirectedEdgeMetrics",
    "FactorEvaluation",
    "FactorInterval",
    "FactorModelConfig",
    "NodeFactorMetrics",
    "PathMetrics",
    "PHYSICAL_EVIDENCE_WARNING",
    "build_directed_edge_cache",
    "canonical_hash",
    "evaluate_factor_model",
    "evaluate_path_metrics",
    "graph_topology_hash",
    "load_factor_model",
    "static_input_hash",
    "write_effective_snapshots",
]

GRAVITY_MPS2: float = 9.81
MODEL_SCHEMA_VERSION: int = 2
PHYSICAL_EVIDENCE_WARNING: str = "PHYSICAL_EVIDENCE_INCOMPLETE"
MISSING_REASON_PREFIX: str = "MISSING_"
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
            {"min_cone_index_kpa", "max_sinkage_clearance_ratio"}
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
        }


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


def evaluate_factor_model(
    graph: H3Graph,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> FactorEvaluation:
    """Evaluate physical node evidence once and freeze directed edge metrics."""
    if not graph.cells:
        raise PlanningInputError("factor evaluation requires a non-empty graph.")
    evidence = {
        cell_id: _raw_node_evidence(cell, vehicle, config)
        for cell_id, cell in graph.cells.items()
    }
    nodes = {
        cell_id: _node_metrics(graph.cells[cell_id], evidence[cell_id], vehicle)
        for cell_id in sorted(graph.cells)
    }
    edges = build_directed_edge_cache(graph, nodes, vehicle, config)
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
) -> dict[tuple[str, str], DirectedEdgeMetrics]:
    """Build the authoritative directed metrics used by route searches."""
    if set(node_metrics) != set(graph.cells):
        raise PlanningInputError("node metrics must cover every graph cell exactly once.")
    cache: dict[tuple[str, str], DirectedEdgeMetrics] = {}
    for edge in sorted(graph.edges.values(), key=lambda item: (item.cell_a, item.cell_b)):
        for from_h3, to_h3 in ((edge.cell_a, edge.cell_b), (edge.cell_b, edge.cell_a)):
            metrics = _directed_edge_metrics(
                graph,
                edge,
                from_h3,
                to_h3,
                node_metrics,
                vehicle,
                config,
            )
            if metrics is not None:
                cache[(from_h3, to_h3)] = metrics
    return cache


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
        )
    edges = _path_edges(h3_path, evaluation)
    bounded = all(edge.eta_upper_bounded for edge in edges)
    eta_upper = sum(cast(float, edge.eta_upper_s) for edge in edges) if bounded else None
    weighted_margin = sum(edge.safety_margin_nominal * edge.distance_m for edge in edges)
    total_distance = sum(edge.distance_m for edge in edges)
    return PathMetrics(
        distance_m=total_distance,
        eta_lower_s=sum(edge.eta_lower_s for edge in edges),
        eta_s=sum(edge.eta_s for edge in edges),
        eta_upper_s=eta_upper,
        eta_upper_bounded=bounded,
        terrain_risk=sum(edge.terrain_risk for edge in edges),
        travel_cost=sum(edge.travel_cost for edge in edges),
        safety_margin_min=min(edge.safety_margin_lower for edge in edges),
        safety_margin_mean=weighted_margin / total_distance,
        edge_count=len(edges),
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
                "has_road": cell.has_road,
                "static_passable": cell.is_passable,
            }
        )
    return canonical_hash(rows)


def graph_topology_hash(graph: H3Graph) -> str:
    """Hash graph resolutions and deterministic undirected topology."""
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
    return canonical_hash(
        {
            "resolution_fine": graph.resolution_fine,
            "resolution_coarse": graph.resolution_coarse,
            "cells": sorted(graph.cells),
            "edges": edges,
        }
    )


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
    landcover = _landcover_speed_interval(cell, config, missing, reasons)
    soil, cone_index, sinkage = _soil_speed_interval(cell, vehicle, config, missing, reasons)
    tri = _floor_interval(
        _known_interval(_tri_speed_factor(cell.tri, config)),
        config.speed_floor_ratio,
    )
    road = _known_interval(
        config.road_speed_factor if cell.has_road else config.offroad_speed_factor
    )
    passable = _hard_constraints(cell, vehicle, config, cone_index, sinkage, reasons)
    margin = _node_safety_margin(cell, vehicle, config, cone_index, sinkage, passable)
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
    config: FactorModelConfig,
    missing: FactorInterval,
    reasons: list[str],
) -> FactorInterval:
    if cell.landcover_code is None and cell.landcover_type is None:
        reasons.append("MISSING_LANDCOVER")
        return _floor_interval(missing, config.speed_floor_ratio)
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


def _soil_speed_interval(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    missing: FactorInterval,
    reasons: list[str],
) -> tuple[FactorInterval, float | None, float | None]:
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
    clone = replace(cell)
    try:
        BekkerChecker().enrich_cell(clone, vehicle)
    except AssessmentError:
        reasons.extend(("MISSING_SOIL_EVIDENCE", "SOIL_MODEL_FALLBACK"))
        return _floor_interval(missing, config.speed_floor_ratio), None, None
    cone_index = clone.cone_index_kpa
    sinkage = clone.sinkage_m
    configured = config.soil_speed_by_uscs.get(cell.uscs)
    if configured is not None:
        value = configured
    elif clone.soil_mobility is not None:
        value = max(0.0, min(1.0, clone.soil_mobility))
    elif sinkage is not None:
        value = max(0.0, 1.0 - sinkage / vehicle.ground_clearance_m)
    else:
        reasons.extend(("MISSING_SOIL_EVIDENCE", "SOIL_MODEL_PARTIAL"))
        return _floor_interval(missing, config.speed_floor_ratio), cone_index, sinkage
    interval = _known_interval(value)
    if configured is None:
        interval = _floor_interval(interval, config.speed_floor_ratio)
    return interval, cone_index, sinkage


def _hard_constraints(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    cone_index: float | None,
    sinkage: float | None,
    reasons: list[str],
) -> bool:
    if not cell.is_passable:
        reasons.append("STATIC_BLOCKED")
    if (
        cell.lc_factor == inf
        or (cell.landcover_type or "").lower() == "water"
        or cell.landcover_code == 5
    ):
        reasons.append("WATER")
    if (
        (cell.landcover_type or "").lower() == "building"
        or cell.landcover_code == 6
    ):
        reasons.append("BUILDING")
    if abs(cell.slope) > vehicle.max_climb_angle_deg:
        reasons.append("SLOPE_LIMIT")
    if cone_index is not None and cone_index < config.min_cone_index_kpa:
        reasons.append("CONE_INDEX_INSUFFICIENT")
    clearance_limit = vehicle.ground_clearance_m * config.max_sinkage_clearance_ratio
    if sinkage is not None and sinkage >= clearance_limit:
        reasons.append("SINKAGE_CLEARANCE_EXCEEDED")
    hard_codes = {
        "STATIC_BLOCKED",
        "WATER",
        "BUILDING",
        "SLOPE_LIMIT",
        "CONE_INDEX_INSUFFICIENT",
        "SINKAGE_CLEARANCE_EXCEEDED",
    }
    return not hard_codes.intersection(reasons)


def _node_safety_margin(
    cell: H3Cell,
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    cone_index: float | None,
    sinkage: float | None,
    passable: bool,
) -> float:
    if not passable:
        return 0.0
    margins = [_slope_margin(cell.slope, vehicle)]
    if cone_index is not None:
        margins.append(1.0 - config.min_cone_index_kpa / cone_index)
    if sinkage is not None:
        clearance = vehicle.ground_clearance_m * config.max_sinkage_clearance_ratio
        margins.append(1.0 - sinkage / clearance)
    return _clamp_ratio(min(margins))


def _node_metrics(
    cell: H3Cell,
    evidence: _RawNodeEvidence,
    vehicle: VehicleProfile,
) -> NodeFactorMetrics:
    maximum = vehicle.max_speed_kmh / 3.6
    speeds = _node_speed_interval(evidence, maximum)
    factors = evidence.speed_factors
    return NodeFactorMetrics(
        h3index=cell.h3index,
        slope=factors[0],
        landcover=factors[1],
        soil=factors[2],
        tri=factors[3],
        road=factors[4],
        safety_margin=evidence.safety_margin,
        speed_lower_mps=speeds[0],
        speed_nominal_mps=speeds[1],
        speed_upper_mps=speeds[2],
        is_passable=evidence.passable,
        confidence=evidence.confidence,
        reason_codes=evidence.reasons,
        cone_index_kpa=evidence.cone_index_kpa,
        sinkage_m=evidence.sinkage_m,
    )


def _node_speed_interval(
    evidence: _RawNodeEvidence,
    maximum_mps: float,
) -> tuple[float, float, float]:
    if not evidence.passable:
        return (0.0, 0.0, 0.0)
    factors = evidence.speed_factors
    bounds = (
        tuple(interval.lower for interval in factors),
        tuple(interval.nominal for interval in factors),
        tuple(interval.upper for interval in factors),
    )
    return (
        min(maximum_mps, maximum_mps * _product(bounds[0])),
        min(maximum_mps, maximum_mps * _product(bounds[1])),
        min(maximum_mps, maximum_mps * _product(bounds[2])),
    )


def _directed_edge_metrics(
    graph: H3Graph,
    edge: H3Edge,
    from_h3: str,
    to_h3: str,
    nodes: Mapping[str, NodeFactorMetrics],
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> DirectedEdgeMetrics | None:
    first = nodes[from_h3]
    second = nodes[to_h3]
    if not first.is_passable or not second.is_passable:
        return None
    slope = _directional_slope(edge, from_h3, to_h3)
    grade_force = _grade_force_n(slope, vehicle)
    if abs(slope) > vehicle.max_climb_angle_deg or grade_force > vehicle.max_thrust_n:
        return None
    directed = _directed_slope_factor(slope, vehicle, config)
    speeds = _edge_speed_interval(first, second, directed)
    speed_lower, speed_nominal, speed_upper = speeds
    if speed_nominal <= 0.0 or speed_upper <= 0.0:
        return None
    margin = _edge_safety_margin(first, second, slope, grade_force, vehicle)
    source_cell = graph.cells[from_h3]
    target_cell = graph.cells[to_h3]
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
) -> float:
    return _clamp_ratio(
        min(
            first.safety_margin.lower,
            second.safety_margin.lower,
            _slope_margin(slope_deg, vehicle),
            1.0 - grade_force_n / vehicle.max_thrust_n,
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
        "missing_speed_interval"
        if schema_version == MODEL_SCHEMA_VERSION
        else "missing_interval"
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
            raise ConfigError(
                f"factor model field {key!r} must map integers to numbers."
            ) from exc
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
            raise ConfigError(
                f"factor model field {key!r} must map strings to numbers."
            ) from exc
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
