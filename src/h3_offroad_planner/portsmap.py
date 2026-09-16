"""Exact request-scoped hierarchical PortsMap search over frozen directed metrics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from heapq import heappop, heappush, heapreplace
from math import atan2, cos, inf, isfinite, radians, sin, sqrt
from threading import Lock

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
BASE_PAIR_CACHE_LIMIT: int = 8_192
_BASE_PAIR_CACHE: dict[
    tuple[str, str, str, str, str],
    tuple[tuple[str, tuple[str, ...], float], ...],
] = {}
_BASE_PAIR_CACHE_RANKS: list[tuple[int, tuple[str, str, str, str, str]]] = []
_BASE_PAIR_CACHE_LOCK = Lock()


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
    environment_pressure: float | None = None
    environment_weight: float = 0.0
    environment_scale: float = 1.0

    def __post_init__(self) -> None:
        unknown = set(self.weights).difference(OBJECTIVE_NAMES)
        if unknown:
            raise ValueError(f"unknown scalar objectives: {sorted(unknown)}")
        if sum(self.weights.values()) + self.environment_weight <= 0.0:
            raise ValueError("scalar profile must contain a positive weight sum.")
        for value in self.weights.values():
            if not isfinite(value) or value < 0.0:
                raise ValueError("scalar weights must be finite and non-negative.")
        if set(self.scales) != set(OBJECTIVE_NAMES):
            raise ValueError("scalar scales must define all four additive objectives.")
        if any(not isfinite(value) or value <= 0.0 for value in self.scales.values()):
            raise ValueError("scalar scales must be finite and positive.")
        if not isfinite(self.environment_weight) or self.environment_weight < 0.0:
            raise ValueError("environment_weight must be finite and non-negative.")
        if not isfinite(self.environment_scale) or self.environment_scale <= 0.0:
            raise ValueError("environment_scale must be finite and positive.")
        if self.environment_pressure is not None and (
            not isfinite(self.environment_pressure) or self.environment_pressure < 0.0
        ):
            raise ValueError("environment_pressure must be finite and non-negative.")
        if self.environment_weight > 0.0 and self.environment_pressure is None:
            raise ValueError("environment_pressure is required for environment_weight.")
        object.__setattr__(
            self, "_w_dist", self.weights.get("distance", 0.0) / self.scales["distance"]
        )
        object.__setattr__(self, "_w_eta", self.weights.get("eta", 0.0) / self.scales["eta"])
        object.__setattr__(
            self,
            "_w_risk",
            self.weights.get("terrain_risk", 0.0) / self.scales["terrain_risk"],
        )
        object.__setattr__(
            self,
            "_w_cost",
            self.weights.get("travel_cost", 0.0) / self.scales["travel_cost"],
        )

    _w_dist: float = field(init=False, repr=False, default=0.0)
    _w_eta: float = field(init=False, repr=False, default=0.0)
    _w_risk: float = field(init=False, repr=False, default=0.0)
    _w_cost: float = field(init=False, repr=False, default=0.0)

    @property
    def signature(self) -> str:
        """Return a stable cache signature for this complete scalar profile."""
        return canonical_hash(
            {
                "name": self.name,
                "weights": dict(sorted(self.weights.items())),
                "scales": dict(sorted(self.scales.items())),
                "environment_pressure": self.environment_pressure,
                "environment_weight": self.environment_weight,
                "environment_scale": self.environment_scale,
            }
        )

    def edge_cost(self, edge: DirectedEdgeMetrics) -> float:
        """Compute normalized additive scalar edge cost."""
        environment_cost = 0.0
        if self.environment_pressure is not None and self.environment_weight > 0.0:
            key = f"{self.environment_pressure:g}"
            if key not in edge.environment_distance_m:
                raise PlanningInputError(f"edge lacks environment pressure scenario {key}.")
            environment_cost = (
                self.environment_weight * edge.environment_distance_m[key] / self.environment_scale
            )
        return (
            self._w_dist * edge.distance_m
            + self._w_eta * edge.eta_s
            + self._w_risk * edge.terrain_risk
            + self._w_cost * edge.travel_cost
            + environment_cost
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
    port_hashes: Mapping[str, str] = field(default_factory=dict)


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
        base_cache_identity: str | None = None,
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
        self.base_cache_identity = base_cache_identity
        if graph.parent_children:
            self._parent_children = graph.parent_children
        else:
            self._parent_children = {}
            for cell in graph.cells.values():
                parent_id = cell.parent_h3 or cell.h3index
                self._parent_children.setdefault(parent_id, set()).add(cell.h3index)
        self._neighbors = _directed_neighbors(evaluation.directed_edges)
        self._pair_cache: dict[
            tuple[str, str, object, object, str],
            dict[tuple[str, str], PortPairPath],
        ] = {}
        self._computed_sources: dict[
            tuple[str, str, object, object, str],
            set[str],
        ] = {}
        self._cache_hits = 0
        self._base_cache_hits = 0
        self._base_cache_misses = 0
        self._fine_search_calls = 0
        self._visited_parents: set[str] = set()
        coord_scale = 1.0
        if evaluation.directed_edges:
            sample_ratios: list[float] = []
            for (u, v), edge in list(evaluation.directed_edges.items())[:50]:
                cell_u = graph.cells.get(u)
                cell_v = graph.cells.get(v)
                if cell_u is not None and cell_v is not None and edge.distance_m > EPSILON:
                    h_dist = _haversine_m(cell_u.lat, cell_u.lng, cell_v.lat, cell_v.lng)
                    if h_dist > EPSILON:
                        sample_ratios.append(edge.distance_m / h_dist)
            if sample_ratios:
                min_ratio = min(sample_ratios)
                coord_scale = 0.0 if min_ratio < 0.5 else min(1.0, min_ratio)
        self._coord_scale = coord_scale
        self._base_topology_cache: dict[
            frozenset[str],
            tuple[
                dict[str, Port],
                dict[tuple[str, str], tuple[str, ...]],
                dict[str, tuple[str, ...]],
            ],
        ] = {}
        self._parent_keys: dict[str, set[tuple[str, str, object, object, str]]] = {}

    def clear_pair_cache(self) -> None:
        """Release request-local Port-pair paths once callers no longer need them."""
        self._pair_cache.clear()
        self._computed_sources.clear()
        self._base_topology_cache.clear()
        self._parent_keys.clear()

    @property
    def cache_hits(self) -> int:
        """Return all request-local and cross-request Port-pair cache hits."""
        return self._cache_hits

    @property
    def base_cache_hits(self) -> int:
        """Return cross-request immutable base Port-pair cache hits."""
        return self._base_cache_hits

    @property
    def base_cache_size(self) -> int:
        """Return the current bounded cross-request cache entry count."""
        with _BASE_PAIR_CACHE_LOCK:
            return len(_BASE_PAIR_CACHE)

    @property
    def base_cache_misses(self) -> int:
        """Return eligible base searches not served by the cross-request cache."""
        return self._base_cache_misses

    @property
    def fine_search_calls(self) -> int:
        """Return all request-local fine-grid searches, including overlays."""
        return self._fine_search_calls

    @property
    def visited_parent_count(self) -> int:
        """Return unique parents expanded by exact macro searches."""
        return len(self._visited_parents)

    def build_topology(
        self,
        start: str,
        goal: str,
        blocked: frozenset[str] = frozenset(),
    ) -> PortsMapTopology:
        """Build explicit boundary and temporary Ports for a request overlay."""
        self._validate_endpoints(start, goal, blocked)
        base = self._base_topology_cache.get(blocked)
        if base is None:
            base_ports: dict[str, Port] = {}
            base_cross: dict[tuple[str, str], tuple[str, ...]] = {}
            for from_h3, to_h3 in sorted(self.evaluation.directed_edges):
                if from_h3 in blocked or to_h3 in blocked:
                    continue
                parent_from = self._parent(from_h3)
                parent_to = self._parent(to_h3)
                if parent_from == parent_to:
                    continue
                base_ports[from_h3] = Port(from_h3, parent_from)
                base_ports[to_h3] = Port(to_h3, parent_to)
                base_cross[(from_h3, to_h3)] = (from_h3, to_h3)
            base_by_parent: dict[str, list[str]] = {}
            for port in base_ports.values():
                base_by_parent.setdefault(port.parent_h3, []).append(port.h3index)
            base_normalized = {p: tuple(sorted(set(pids))) for p, pids in base_by_parent.items()}
            base = (base_ports, base_cross, base_normalized)
            self._base_topology_cache[blocked] = base

        base_ports, base_cross, base_normalized = base
        ports = dict(base_ports)
        normalized = dict(base_normalized)
        for endpoint in (start, goal):
            if endpoint not in ports:
                parent_ep = self._parent(endpoint)
                ports[endpoint] = Port(endpoint, parent_ep, is_temporary=True)
                current_pids = normalized.get(parent_ep, ())
                if endpoint not in current_pids:
                    normalized[parent_ep] = tuple(sorted((*current_pids, endpoint)))

        self._enforce_limits(ports, normalized)
        port_hashes = {
            parent_id: canonical_hash(port_tuple) for parent_id, port_tuple in normalized.items()
        }
        return PortsMapTopology(
            ports=ports,
            ports_by_parent=normalized,
            cross_parent_edges=base_cross,
            port_hashes=port_hashes,
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
        path, cost, pairs_count = self._macro_search(
            topology,
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
            port_pairs_count=pairs_count,
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
        heap: list[tuple[float, float, float, float, str]] = [(-start_score, 0.0, 0.0, 0.0, start)]
        best: dict[str, tuple[float, float, float, float]] = {start: (-start_score, 0.0, 0.0, 0.0)}
        came_from: dict[str, str] = {}
        while heap:
            negative_margin, risk, eta, distance, current = heappop(heap)
            key = (negative_margin, risk, eta, distance)
            if best.get(current) != key:
                continue
            if current == goal:
                path_rev: list[str] = [goal]
                curr = goal
                while curr in came_from:
                    curr = came_from[curr]
                    path_rev.append(curr)
                path = tuple(reversed(path_rev))
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
                cand_key = (
                    -margin,
                    risk + edge.terrain_risk,
                    eta + edge.eta_s,
                    distance + edge.distance_m,
                )
                if cand_key < best.get(neighbor, (inf, inf, inf, inf)):
                    best[neighbor] = cand_key
                    came_from[neighbor] = current
                    heappush(heap, (*cand_key, neighbor))
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
        penalties_by_parent: dict[str, tuple[tuple[str, int], ...]] = {}
        if penalty_factor > 0.0 and penalties:
            p_map: dict[str, list[tuple[str, int]]] = {}
            for cell_id, count in penalties.items():
                p = self._parent(cell_id)
                p_map.setdefault(p, []).append((cell_id, count))
            penalties_by_parent = {p: tuple(sorted(items)) for p, items in p_map.items()}

        blocked_by_parent: dict[str, tuple[str, ...]] = {}
        if blocked:
            b_map: dict[str, list[str]] = {}
            for cell_id in blocked:
                p = self._parent(cell_id)
                b_map.setdefault(p, []).append(cell_id)
            blocked_by_parent = {p: tuple(sorted(items)) for p, items in b_map.items()}

        for parent, port_ids in sorted(topology.ports_by_parent.items()):
            local_p = penalties_by_parent.get(parent, ())
            local_b = blocked_by_parent.get(parent, ())
            port_hash = topology.port_hashes.get(parent)
            if port_hash is None:
                port_hash = canonical_hash(port_ids)
            for source in port_ids:
                self._get_or_compute_source_pairs(
                    source,
                    parent,
                    port_ids,
                    profile,
                    blocked,
                    penalties,
                    penalty_factor,
                    local_p,
                    local_b,
                    port_hash,
                )
            cache_key = (parent, profile.signature, local_p, local_b, port_hash)
            cached = self._pair_cache.get(cache_key)
            if cached:
                all_pairs.update(cached)
        return all_pairs

    def _evict_stale_parent_contexts(
        self,
        parent: str,
        active_key: tuple[str, str, object, object, str],
    ) -> None:
        """Bound cache growth while retaining immediate identical-search reuse."""
        keys = self._parent_keys.get(parent)
        if keys is not None:
            stale = [k for k in keys if k != active_key]
            for k in stale:
                self._pair_cache.pop(k, None)
                self._computed_sources.pop(k, None)
                keys.remove(k)
        else:
            self._parent_keys[parent] = set()
        self._parent_keys[parent].add(active_key)

    def _get_or_compute_source_pairs(
        self,
        source: str,
        parent: str,
        port_ids: tuple[str, ...],
        profile: ScalarProfile,
        blocked: frozenset[str],
        penalties: Mapping[str, int],
        penalty_factor: float,
        local_penalty_key: tuple[tuple[str, int], ...],
        local_blocked_key: tuple[str, ...],
        port_hash: str,
    ) -> list[tuple[str, tuple[str, ...], float]]:
        if len(port_ids) <= 1:
            return []
        cache_key = (parent, profile.signature, local_penalty_key, local_blocked_key, port_hash)
        cached = self._pair_cache.get(cache_key)
        if cached is None:
            self._evict_stale_parent_contexts(parent, cache_key)
            cached = {}
            self._pair_cache[cache_key] = cached
            self._computed_sources[cache_key] = set()

        sources_done = self._computed_sources[cache_key]
        if source in sources_done:
            self._cache_hits += 1
        else:
            base_key = self._base_pair_key(
                parent,
                profile,
                port_hash,
                source,
                blocked,
                local_penalty_key,
                penalty_factor,
            )
            base_pairs = _base_pair_cache_get(base_key) if base_key is not None else None
            if base_pairs is None:
                if base_key is not None:
                    self._base_cache_misses += 1
                allowed = {
                    cell_id
                    for cell_id in self._parent_children.get(parent, ())
                    if cell_id not in blocked
                }
                targets = set(port_ids)
                targets.discard(source)
                effective_penalties = penalties if local_penalty_key else {}
                effective_penalty_factor = penalty_factor if local_penalty_key else 0.0
                fine_best = self._fine_tile_search(
                    source,
                    allowed,
                    profile,
                    effective_penalties,
                    effective_penalty_factor,
                    targets=targets,
                )
                base_pairs = tuple(
                    (target, fine_best[target][1], fine_best[target][0])
                    for target in port_ids
                    if source != target and target in fine_best
                )
                if base_key is not None:
                    _base_pair_cache_put(base_key, base_pairs)
            else:
                self._cache_hits += 1
                self._base_cache_hits += 1
            for target, path, cost in base_pairs:
                cached[(source, target)] = PortPairPath(parent, source, target, path, cost)
            sources_done.add(source)

        edges: list[tuple[str, tuple[str, ...], float]] = []
        for target in port_ids:
            if target == source:
                continue
            pair = cached.get((source, target))
            if pair is not None:
                edges.append((target, pair.h3_path, pair.scalar_cost))
        return edges

    def _base_pair_key(
        self,
        parent: str,
        profile: ScalarProfile,
        port_hash: str,
        source: str,
        blocked: frozenset[str],
        local_penalty_key: tuple[tuple[str, int], ...],
        penalty_factor: float,
    ) -> tuple[str, str, str, str, str] | None:
        if (
            self.base_cache_identity is None
            or blocked
            or local_penalty_key
            or penalty_factor > 0.0
        ):
            return None
        return (self.base_cache_identity, parent, profile.signature, port_hash, source)

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
            cell_id for cell_id in self._parent_children.get(parent, ()) if cell_id not in blocked
        }
        pairs: dict[tuple[str, str], PortPairPath] = {}
        for source in port_ids:
            targets = set(port_ids)
            targets.discard(source)
            best = self._fine_tile_search(
                source,
                allowed,
                profile,
                penalties,
                penalty_factor,
                targets=targets,
            )
            for target in port_ids:
                if source == target or target not in best:
                    continue
                cost, path = best[target]
                pairs[(source, target)] = PortPairPath(parent, source, target, path, cost)
        return pairs

    def _fine_tile_search(
        self,
        source: str,
        allowed: set[str],
        profile: ScalarProfile,
        penalties: Mapping[str, int],
        penalty_factor: float,
        targets: set[str] | None = None,
    ) -> dict[str, tuple[float, tuple[str, ...]]]:
        self._fine_search_calls += 1
        if source not in allowed:
            return {}
        heap: list[tuple[float, str]] = [(0.0, source)]
        best: dict[str, float] = {source: 0.0}
        came_from: dict[str, str] = {}
        remaining_targets = set(targets) if targets is not None else None

        while heap:
            cost, current = heappop(heap)
            if cost > best.get(current, inf) + EPSILON:
                continue
            if remaining_targets is not None and current in remaining_targets:
                remaining_targets.remove(current)
                if not remaining_targets:
                    break
            for neighbor in self._neighbors.get(current, ()):
                if neighbor not in allowed:
                    continue
                edge = self.evaluation.directed_edges[(current, neighbor)]
                step = _penalized_cost(edge, profile, neighbor, penalties, penalty_factor)
                cand_cost = cost + step
                current_best = best.get(neighbor)
                if current_best is None or cand_cost < current_best - EPSILON:
                    best[neighbor] = cand_cost
                    came_from[neighbor] = current
                    heappush(heap, (cand_cost, neighbor))

        results: dict[str, tuple[float, tuple[str, ...]]] = {}
        query_targets = targets if targets is not None else best.keys()
        for t in query_targets:
            if t not in best:
                continue
            curr = t
            p_rev: list[str] = [t]
            while curr != source and curr in came_from:
                curr = came_from[curr]
                p_rev.append(curr)
            if curr == source:
                results[t] = (best[t], tuple(reversed(p_rev)))
        return results

    _fine_dijkstra = _fine_tile_search

    def _macro_search(
        self,
        topology: PortsMapTopology,
        start: str,
        goal: str,
        profile: ScalarProfile,
        blocked: frozenset[str],
        penalties: Mapping[str, int],
        penalty_factor: float,
        pairs: Mapping[tuple[str, str], PortPairPath] | None = None,
    ) -> tuple[tuple[str, ...], float, int]:
        cross_by_source: dict[str, list[tuple[str, tuple[str, str], float]]] = {}
        for source, target in topology.cross_parent_edges:
            if source in blocked or target in blocked:
                continue
            edge = self.evaluation.directed_edges[(source, target)]
            cost = _penalized_cost(edge, profile, target, penalties, penalty_factor)
            cross_by_source.setdefault(source, []).append((target, (source, target), cost))

        penalties_by_parent: dict[str, tuple[tuple[str, int], ...]] = {}
        if penalty_factor > 0.0 and penalties:
            p_map: dict[str, list[tuple[str, int]]] = {}
            for cell_id, count in penalties.items():
                p = self._parent(cell_id)
                p_map.setdefault(p, []).append((cell_id, count))
            penalties_by_parent = {p: tuple(sorted(items)) for p, items in p_map.items()}

        blocked_by_parent: dict[str, tuple[str, ...]] = {}
        if blocked:
            b_map: dict[str, list[str]] = {}
            for cell_id in blocked:
                p = self._parent(cell_id)
                b_map.setdefault(p, []).append(cell_id)
            blocked_by_parent = {p: tuple(sorted(items)) for p, items in b_map.items()}

        precomputed_adjacency: dict[str, list[tuple[str, tuple[str, ...], float]]] | None = None
        if pairs is not None:
            precomputed_adjacency = {}
            for (source, target), pair in pairs.items():
                precomputed_adjacency.setdefault(source, []).append(
                    (target, pair.h3_path, pair.scalar_cost)
                )

        # Admissible heuristic lower bound (includes travel_cost lower bound of 1.0 m/m)
        w_dist = profile.weights.get("distance", 0.0) / profile.scales["distance"]
        w_eta = profile.weights.get("eta", 0.0) / profile.scales["eta"]
        w_cost = profile.weights.get("travel_cost", 0.0) / profile.scales["travel_cost"]
        w_environment = profile.environment_weight / profile.environment_scale
        max_speed_mps = 200.0 / 3.6
        unit_cost_lower_bound = (
            w_dist + (w_eta / max_speed_mps) + (w_cost * 1.0) + w_environment
        ) * self._coord_scale

        goal_cell = self.graph.cells[goal]
        goal_lat = goal_cell.lat
        goal_lng = goal_cell.lng
        goal_dist_cache: dict[str, float] = {}

        def _h(node: str) -> float:
            if unit_cost_lower_bound <= EPSILON:
                return 0.0
            d = goal_dist_cache.get(node)
            if d is None:
                c = self.graph.cells[node]
                d = _haversine_m(c.lat, c.lng, goal_lat, goal_lng)
                goal_dist_cache[node] = d
            return unit_cost_lower_bound * d

        h_start = _h(start)
        heap: list[tuple[float, float, str]] = [(h_start, 0.0, start)]
        best_cost: dict[str, float] = {start: 0.0}
        came_from: dict[str, tuple[str, tuple[str, ...]]] = {}
        visited_parents: set[str] = set()

        while heap:
            priority, cost, current = heappop(heap)
            if cost > best_cost.get(current, inf) + EPSILON:
                continue
            if current == goal:
                segments_rev: list[tuple[str, ...]] = []
                curr = goal
                while curr != start and curr in came_from:
                    prev, seg = came_from[curr]
                    segments_rev.append(seg)
                    curr = prev

                path_parts: list[str] = [start]
                for seg in reversed(segments_rev):
                    path_parts.extend(seg[1:])
                path = tuple(path_parts)

                active_pairs_count = 0
                if pairs is not None:
                    active_pairs_count = len(pairs)
                else:
                    for vp in visited_parents:
                        v_port_ids = topology.ports_by_parent.get(vp, ())
                        v_port_hash = topology.port_hashes.get(vp)
                        if v_port_hash is None:
                            v_port_hash = canonical_hash(v_port_ids)
                        v_local_p = penalties_by_parent.get(vp, ())
                        v_local_b = blocked_by_parent.get(vp, ())
                        v_cache_key = (
                            vp,
                            profile.signature,
                            v_local_p,
                            v_local_b,
                            v_port_hash,
                        )
                        v_cached = self._pair_cache.get(v_cache_key)
                        if v_cached:
                            active_pairs_count += len(v_cached)
                return path, cost, active_pairs_count

            outgoing: list[tuple[str, tuple[str, ...], float]] = []

            # 1. Cross-parent edges
            if current in cross_by_source:
                outgoing.extend(cross_by_source[current])

            # 2. Internal-parent edges
            parent = self._parent(current)
            visited_parents.add(parent)
            self._visited_parents.add(parent)
            if precomputed_adjacency is not None:
                outgoing.extend(precomputed_adjacency.get(current, []))
            else:
                port_ids = topology.ports_by_parent.get(parent, ())
                local_p = penalties_by_parent.get(parent, ())
                local_b = blocked_by_parent.get(parent, ())
                port_hash = topology.port_hashes.get(parent)
                if port_hash is None:
                    port_hash = canonical_hash(port_ids)
                internal_edges = self._get_or_compute_source_pairs(
                    current,
                    parent,
                    port_ids,
                    profile,
                    blocked,
                    penalties,
                    penalty_factor,
                    local_p,
                    local_b,
                    port_hash,
                )
                outgoing.extend(internal_edges)

            for neighbor, segment, step in sorted(outgoing):
                cand_cost = cost + step
                current_best = best_cost.get(neighbor)
                if current_best is None or cand_cost < current_best - EPSILON:
                    best_cost[neighbor] = cand_cost
                    came_from[neighbor] = (current, segment)
                    cand_priority = cand_cost + _h(neighbor)
                    heappush(heap, (cand_priority, cand_cost, neighbor))

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


def _base_pair_cache_get(
    key: tuple[str, str, str, str, str],
) -> tuple[tuple[str, tuple[str, ...], float], ...] | None:
    with _BASE_PAIR_CACHE_LOCK:
        return _BASE_PAIR_CACHE.get(key)


def _base_pair_cache_put(
    key: tuple[str, str, str, str, str],
    value: tuple[tuple[str, tuple[str, ...], float], ...],
) -> None:
    with _BASE_PAIR_CACHE_LOCK:
        if key in _BASE_PAIR_CACHE:
            _BASE_PAIR_CACHE[key] = value
            return
        rank = -int(canonical_hash(key)[:16], 16)
        if len(_BASE_PAIR_CACHE) < BASE_PAIR_CACHE_LIMIT:
            _BASE_PAIR_CACHE[key] = value
            heappush(_BASE_PAIR_CACHE_RANKS, (rank, key))
            return
        worst_rank, worst_key = _BASE_PAIR_CACHE_RANKS[0]
        if rank <= worst_rank:
            return
        _BASE_PAIR_CACHE.pop(worst_key)
        _BASE_PAIR_CACHE[key] = value
        heapreplace(_BASE_PAIR_CACHE_RANKS, (rank, key))


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


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_m = 6_371_000.0
    delta_lat = radians(lat_b - lat_a)
    delta_lng = radians(lng_b - lng_a)
    first_lat = radians(lat_a)
    second_lat = radians(lat_b)
    root = sin(delta_lat / 2.0) ** 2
    root += cos(first_lat) * cos(second_lat) * sin(delta_lng / 2.0) ** 2
    return 2.0 * earth_radius_m * atan2(sqrt(root), sqrt(max(0.0, 1.0 - root)))
