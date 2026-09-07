"""Exact request-scoped hierarchical PortsMap search over frozen directed metrics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import inf, isfinite

from h3_offroad_planner.factor_model import (
    DirectedEdgeMetrics,
    FactorEvaluation,
    PathMetrics,
    canonical_hash,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError

__all__ = [
    "Port",
    "PortPairPath",
    "PortsMapLimitError",
    "PortsMapSearchContext",
    "PortsMapSearchResult",
    "PortsMapTopology",
    "ScalarProfile",
]

EPSILON: float = 1.0e-12
OBJECTIVE_NAMES: tuple[str, ...] = ("distance", "eta", "terrain_risk", "travel_cost")


class PortsMapLimitError(PlanningFailedError):
    """Raised when exact PortsMap construction exceeds configured demo limits."""

    code: str = "PORTS_MAP_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class ScalarProfile:
    """Non-negative additive objective weights and robust normalization scales."""

    weights: Mapping[str, float]
    scales: Mapping[str, float] = field(
        default_factory=lambda: {
            "distance": 1.0,
            "eta": 1.0,
            "terrain_risk": 1.0,
            "travel_cost": 1.0,
        }
    )
    name: str = "custom"

    def __post_init__(self) -> None:
        unknown = set(self.weights).difference(OBJECTIVE_NAMES)
        if unknown:
            raise ValueError(f"unknown scalar objectives: {sorted(unknown)}")
        if not self.weights or sum(self.weights.values()) <= 0.0:
            raise ValueError("scalar profile must contain a positive weight sum.")
        for value in self.weights.values():
            if not isfinite(value) or value < 0.0:
                raise ValueError("scalar weights must be finite and non-negative.")
        if set(self.scales) != set(OBJECTIVE_NAMES):
            raise ValueError("scalar scales must define all four additive objectives.")
        if any(not isfinite(value) or value <= 0.0 for value in self.scales.values()):
            raise ValueError("scalar scales must be finite and positive.")

    @property
    def signature(self) -> str:
        """Return a stable cache signature for this complete scalar profile."""
        return canonical_hash(
            {
                "name": self.name,
                "weights": dict(sorted(self.weights.items())),
                "scales": dict(sorted(self.scales.items())),
            }
        )

    def edge_cost(self, edge: DirectedEdgeMetrics) -> float:
        """Compute normalized additive scalar edge cost."""
        metrics = {
            "distance": edge.distance_m,
            "eta": edge.eta_s,
            "terrain_risk": edge.terrain_risk,
            "travel_cost": edge.travel_cost,
        }
        return sum(
            self.weights.get(name, 0.0) * metrics[name] / self.scales[name]
            for name in OBJECTIVE_NAMES
        )


@dataclass(frozen=True)
class Port:
    """Fine-grid endpoint participating in a parent-level macro graph."""

    h3index: str
    parent_h3: str
    is_temporary: bool = False

    def __post_init__(self) -> None:
        if not self.h3index or not self.parent_h3:
            raise ValueError("Port identifiers must be non-empty.")


@dataclass(frozen=True)
class PortPairPath:
    """Exact directed shortest path between two Ports inside one parent."""

    parent_h3: str
    from_port: str
    to_port: str
    h3_path: tuple[str, ...]
    scalar_cost: float

    def __post_init__(self) -> None:
        if not self.parent_h3 or not self.from_port or not self.to_port:
            raise ValueError("Port-pair identifiers must be non-empty.")
        if len(self.h3_path) < 2:
            raise ValueError("Port-pair path must contain at least two cells.")
        if self.h3_path[0] != self.from_port or self.h3_path[-1] != self.to_port:
            raise ValueError("Port-pair path endpoints must match its Port ids.")
        if not isfinite(self.scalar_cost) or self.scalar_cost < 0.0:
            raise ValueError("Port-pair scalar cost must be finite and non-negative.")


@dataclass(frozen=True)
class PortsMapTopology:
    """Explicit Ports and cross-parent directed edge segments for one request."""

    ports: Mapping[str, Port]
    ports_by_parent: Mapping[str, tuple[str, ...]]
    cross_parent_edges: Mapping[tuple[str, str], tuple[str, ...]]


@dataclass(frozen=True)
class PortsMapSearchResult:
    """Expanded continuous fine-grid route with exact scalar and path metrics."""

    h3_path: tuple[str, ...]
    scalar_cost: float
    metrics: PathMetrics
    ports_count: int
    port_pairs_count: int
    cache_hits: int


class PortsMapSearchContext:
    """Request-scoped exact PortsMap kernel with safe Port-pair reuse."""

    def __init__(
        self,
        graph: H3Graph,
        evaluation: FactorEvaluation,
        max_ports: int = 20_000,
        max_port_pairs: int = 200_000,
    ) -> None:
        """Initialize an immutable base graph/evaluation search context."""
        if set(graph.cells) != set(evaluation.node_metrics):
            raise PlanningInputError("PortsMap graph and factor evaluation cells must match.")
        if max_ports <= 0 or max_port_pairs <= 0:
            raise ValueError("PortsMap resource limits must be positive.")
        self.graph = graph
        self.evaluation = evaluation
        self.max_ports = max_ports
        self.max_port_pairs = max_port_pairs
        self._neighbors = _directed_neighbors(evaluation.directed_edges)
        self._pair_cache: dict[
            tuple[str, str, str, str, str],
            dict[tuple[str, str], PortPairPath],
        ] = {}
        self._cache_hits = 0

    def clear_pair_cache(self) -> None:
        """Release request-local Port-pair paths once callers no longer need them."""
        self._pair_cache.clear()

    def build_topology(
        self,
        start: str,
        goal: str,
        blocked: frozenset[str] = frozenset(),
    ) -> PortsMapTopology:
        """Build explicit boundary and temporary Ports for a request overlay."""
        self._validate_endpoints(start, goal, blocked)
        ports: dict[str, Port] = {}
        cross_edges: dict[tuple[str, str], tuple[str, ...]] = {}
        for from_h3, to_h3 in sorted(self.evaluation.directed_edges):
            if from_h3 in blocked or to_h3 in blocked:
                continue
            parent_from = self._parent(from_h3)
            parent_to = self._parent(to_h3)
            if parent_from == parent_to:
                continue
            ports[from_h3] = Port(from_h3, parent_from)
            ports[to_h3] = Port(to_h3, parent_to)
            cross_edges[(from_h3, to_h3)] = (from_h3, to_h3)
        for endpoint in (start, goal):
            existing = ports.get(endpoint)
            ports[endpoint] = Port(
                endpoint,
                self._parent(endpoint),
                is_temporary=existing is None,
            )
        by_parent: dict[str, list[str]] = {}
        for port in ports.values():
            by_parent.setdefault(port.parent_h3, []).append(port.h3index)
        normalized = {
            parent: tuple(sorted(set(port_ids))) for parent, port_ids in by_parent.items()
        }
        self._enforce_limits(ports, normalized)
        return PortsMapTopology(
            ports=ports,
            ports_by_parent=normalized,
            cross_parent_edges=cross_edges,
        )

    def search(
        self,
        start: str,
        goal: str,
        profile: ScalarProfile,
        blocked: frozenset[str] = frozenset(),
        exploration_penalties: Mapping[str, int] | None = None,
        penalty_factor: float = 0.0,
    ) -> PortsMapSearchResult:
        """Run exact weighted PortsMap search and expand the complete fine path."""
        if not isfinite(penalty_factor) or penalty_factor < 0.0:
            raise ValueError("penalty_factor must be finite and non-negative.")
        penalties = dict(exploration_penalties or {})
        if any(count < 0 for count in penalties.values()):
            raise ValueError("exploration penalty counts must be non-negative.")
        topology = self.build_topology(start, goal, blocked)
        pairs = self._all_port_pairs(topology, profile, blocked, penalties, penalty_factor)
        path, cost = self._macro_search(
            topology,
            pairs,
            start,
            goal,
            profile,
            blocked,
            penalties,
            penalty_factor,
        )
        _validate_continuous_path(path, self.evaluation.directed_edges)
        return PortsMapSearchResult(
            h3_path=path,
            scalar_cost=cost,
            metrics=evaluate_path_metrics(path, self.evaluation),
            ports_count=len(topology.ports),
            port_pairs_count=len(pairs),
            cache_hits=self._cache_hits,
        )

    def search_widest(
        self,
        start: str,
        goal: str,
        blocked: frozenset[str] = frozenset(),
    ) -> PortsMapSearchResult:
        """Find the maximum-minimum passability route with fixed metric tie-breaks."""
        topology = self.build_topology(start, goal, blocked)
        start_score = self.evaluation.node_metrics[start].safety_margin.lower
        start_key = (-start_score, 0.0, 0.0, 0.0, (start,))
        heap: list[tuple[float, float, float, float, tuple[str, ...], str]] = [
            (*start_key, start)
        ]
        best: dict[str, tuple[float, float, float, float, tuple[str, ...]]] = {
            start: start_key
        }
        while heap:
            negative_margin, risk, eta, distance, path, current = heappop(heap)
            key = (negative_margin, risk, eta, distance, path)
            if best.get(current) != key:
                continue
            if current == goal:
                metrics = evaluate_path_metrics(path, self.evaluation)
                return PortsMapSearchResult(
                    h3_path=path,
                    scalar_cost=metrics.terrain_risk,
                    metrics=metrics,
                    ports_count=len(topology.ports),
                    port_pairs_count=0,
                    cache_hits=self._cache_hits,
                )
            current_margin = -negative_margin
            for neighbor in self._neighbors.get(current, ()):
                if neighbor in blocked:
                    continue
                edge = self.evaluation.directed_edges[(current, neighbor)]
                margin = min(current_margin, edge.safety_margin_lower)
                candidate = (
                    -margin,
                    risk + edge.terrain_risk,
                    eta + edge.eta_s,
                    distance + edge.distance_m,
                    (*path, neighbor),
                )
                if candidate < best.get(neighbor, (inf, inf, inf, inf, ("~",))):
                    best[neighbor] = candidate
                    heappush(heap, (*candidate, neighbor))
        raise PlanningFailedError(f"no widest path from {start!r} to {goal!r}.")

    def _all_port_pairs(
        self,
        topology: PortsMapTopology,
        profile: ScalarProfile,
        blocked: frozenset[str],
        penalties: Mapping[str, int],
        penalty_factor: float,
    ) -> dict[tuple[str, str], PortPairPath]:
        all_pairs: dict[tuple[str, str], PortPairPath] = {}
        penalty_hash = canonical_hash(
            {"counts": dict(sorted(penalties.items())), "factor": penalty_factor}
        )
        blocked_hash = canonical_hash(sorted(blocked))
        for parent, port_ids in sorted(topology.ports_by_parent.items()):
            port_hash = canonical_hash(port_ids)
            cache_key = (parent, profile.signature, penalty_hash, blocked_hash, port_hash)
            cached = self._pair_cache.get(cache_key)
            if cached is None:
                cached = self._parent_port_pairs(
                    parent,
                    port_ids,
                    profile,
                    blocked,
                    penalties,
                    penalty_factor,
                )
                self._evict_stale_parent_contexts(parent, cache_key)
                self._pair_cache[cache_key] = cached
            else:
                self._cache_hits += 1
            all_pairs.update(cached)
        return all_pairs

    def _evict_stale_parent_contexts(
        self,
        parent: str,
        active_key: tuple[str, str, str, str, str],
    ) -> None:
        """Bound cache growth while retaining immediate identical-search reuse."""
        stale = [
            key
            for key in self._pair_cache
            if key[0] == parent and key != active_key
        ]
        for key in stale:
            del self._pair_cache[key]

    def _parent_port_pairs(
        self,
        parent: str,
        port_ids: tuple[str, ...],
        profile: ScalarProfile,
        blocked: frozenset[str],
        penalties: Mapping[str, int],
        penalty_factor: float,
    ) -> dict[tuple[str, str], PortPairPath]:
        allowed = {
            cell_id
            for cell_id in self.graph.cells
            if self._parent(cell_id) == parent and cell_id not in blocked
        }
        pairs: dict[tuple[str, str], PortPairPath] = {}
        for source in port_ids:
            best = self._fine_dijkstra(
                source,
                allowed,
                profile,
                penalties,
                penalty_factor,
            )
            for target in port_ids:
                if source == target or target not in best:
                    continue
                cost, path = best[target]
                pairs[(source, target)] = PortPairPath(parent, source, target, path, cost)
        return pairs

    def _fine_dijkstra(
        self,
        source: str,
        allowed: set[str],
        profile: ScalarProfile,
        penalties: Mapping[str, int],
        penalty_factor: float,
    ) -> dict[str, tuple[float, tuple[str, ...]]]:
        if source not in allowed:
            return {}
        heap: list[tuple[float, tuple[str, ...], str]] = [(0.0, (source,), source)]
        best: dict[str, tuple[float, tuple[str, ...]]] = {source: (0.0, (source,))}
        while heap:
            cost, path, current = heappop(heap)
            if best.get(current) != (cost, path):
                continue
            for neighbor in self._neighbors.get(current, ()):
                if neighbor not in allowed:
                    continue
                edge = self.evaluation.directed_edges[(current, neighbor)]
                step = _penalized_cost(edge, profile, neighbor, penalties, penalty_factor)
                candidate = (cost + step, (*path, neighbor))
                if _is_better(candidate, best.get(neighbor)):
                    best[neighbor] = candidate
                    heappush(heap, (candidate[0], candidate[1], neighbor))
        return best

    def _macro_search(
        self,
        topology: PortsMapTopology,
        pairs: Mapping[tuple[str, str], PortPairPath],
        start: str,
        goal: str,
        profile: ScalarProfile,
        blocked: frozenset[str],
        penalties: Mapping[str, int],
        penalty_factor: float,
    ) -> tuple[tuple[str, ...], float]:
        adjacency: dict[str, list[tuple[str, tuple[str, ...], float]]] = {}
        for (source, target), pair in pairs.items():
            adjacency.setdefault(source, []).append((target, pair.h3_path, pair.scalar_cost))
        for source, target in topology.cross_parent_edges:
            if source in blocked or target in blocked:
                continue
            edge = self.evaluation.directed_edges[(source, target)]
            cost = _penalized_cost(edge, profile, target, penalties, penalty_factor)
            adjacency.setdefault(source, []).append((target, (source, target), cost))
        heap: list[tuple[float, tuple[str, ...], str]] = [(0.0, (start,), start)]
        best: dict[str, tuple[float, tuple[str, ...]]] = {start: (0.0, (start,))}
        while heap:
            cost, path, current = heappop(heap)
            if best.get(current) != (cost, path):
                continue
            if current == goal:
                return path, cost
            for neighbor, segment, step in sorted(adjacency.get(current, [])):
                expanded = (*path, *segment[1:])
                candidate = (cost + step, expanded)
                if _is_better(candidate, best.get(neighbor)):
                    best[neighbor] = candidate
                    heappush(heap, (candidate[0], candidate[1], neighbor))
        raise PlanningFailedError(f"no exact PortsMap path from {start!r} to {goal!r}.")

    def _validate_endpoints(
        self,
        start: str,
        goal: str,
        blocked: frozenset[str],
    ) -> None:
        if start not in self.graph.cells or goal not in self.graph.cells:
            raise PlanningInputError("PortsMap endpoints must exist in the graph.")
        if start in blocked or goal in blocked:
            raise PlanningFailedError("PortsMap endpoints must not be blocked.")
        if not self.evaluation.node_metrics[start].is_passable:
            raise PlanningFailedError("PortsMap start is not passable.")
        if not self.evaluation.node_metrics[goal].is_passable:
            raise PlanningFailedError("PortsMap goal is not passable.")

    def _enforce_limits(
        self,
        ports: Mapping[str, Port],
        by_parent: Mapping[str, tuple[str, ...]],
    ) -> None:
        pairs = sum(len(values) * max(len(values) - 1, 0) for values in by_parent.values())
        if len(ports) > self.max_ports or pairs > self.max_port_pairs:
            raise PortsMapLimitError(
                f"PORTS_MAP_LIMIT_EXCEEDED: ports={len(ports)}/{self.max_ports}, "
                f"directed_pairs={pairs}/{self.max_port_pairs}."
            )

    def _parent(self, cell_id: str) -> str:
        parent = self.graph.cells[cell_id].parent_h3
        return parent if parent else cell_id


def _directed_neighbors(
    edges: Mapping[tuple[str, str], DirectedEdgeMetrics],
) -> dict[str, tuple[str, ...]]:
    neighbors: dict[str, list[str]] = {}
    for source, target in edges:
        neighbors.setdefault(source, []).append(target)
    return {source: tuple(sorted(set(values))) for source, values in neighbors.items()}


def _penalized_cost(
    edge: DirectedEdgeMetrics,
    profile: ScalarProfile,
    target: str,
    penalties: Mapping[str, int],
    penalty_factor: float,
) -> float:
    base = profile.edge_cost(edge)
    return max(base, EPSILON) * (1.0 + penalty_factor * penalties.get(target, 0))


def _is_better(
    candidate: tuple[float, tuple[str, ...]],
    current: tuple[float, tuple[str, ...]] | None,
) -> bool:
    if current is None:
        return True
    if candidate[0] < current[0] - EPSILON:
        return True
    return abs(candidate[0] - current[0]) <= EPSILON and candidate[1] < current[1]


def _validate_continuous_path(
    path: tuple[str, ...],
    edges: Mapping[tuple[str, str], DirectedEdgeMetrics],
) -> None:
    if not path:
        raise PlanningFailedError("PortsMap expansion produced an empty path.")
    for source, target in zip(path[:-1], path[1:], strict=True):
        if (source, target) not in edges:
            raise PlanningFailedError(
                f"PortsMap expansion is discontinuous at {source!r}->{target!r}."
            )
