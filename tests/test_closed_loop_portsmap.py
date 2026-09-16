"""Spec-derived exactness tests for the request-scoped PortsMap kernel."""

from __future__ import annotations

from collections.abc import Mapping
from heapq import heappop, heappush
from math import inf

import pytest

from h3_offroad_planner.factor_model import (
    DirectedEdgeMetrics,
    FactorModelConfig,
    evaluate_factor_model,
)
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, VehicleProfile
from h3_offroad_planner.portsmap import (
    OBJECTIVE_NAMES,
    PortsMapLimitError,
    PortsMapSearchContext,
    ScalarProfile,
)


@pytest.mark.parametrize("objective", OBJECTIVE_NAMES)
def test_cl012_portsmap_matches_full_graph_dijkstra(
    objective: str,
    vehicle: VehicleProfile,
) -> None:
    """CL-012: exact PortsMap cost equals full directed Dijkstra for every objective."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({objective: 1.0}, name=objective)
    result = PortsMapSearchContext(graph, evaluation).search("a", "f", profile)
    expected = _oracle_cost(evaluation.directed_edges, "a", "f", profile)
    assert result.scalar_cost == pytest.approx(expected)
    assert result.h3_path[0] == "a"
    assert result.h3_path[-1] == "f"
    assert all(
        (first, second) in evaluation.directed_edges
        for first, second in zip(result.h3_path[:-1], result.h3_path[1:], strict=True)
    )


def test_cl013_portsmap_reuses_identical_parent_pair_context(vehicle: VehicleProfile) -> None:
    """CL-013: same endpoints/profile/overlay reuse request-local Port-pair results."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    profile = ScalarProfile({"eta": 1.0}, name="eta")
    first = context.search("a", "f", profile)
    second = context.search("a", "f", profile)
    assert first.h3_path == second.h3_path
    assert second.cache_hits > first.cache_hits
    assert context.fine_search_calls > 0
    assert context.visited_parent_count > 0


def test_cl015_portsmap_cache_keeps_only_latest_context_per_parent(
    vehicle: VehicleProfile,
) -> None:
    """Profile changes cannot accumulate unbounded full Port-pair path sets."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)

    context.search("a", "f", ScalarProfile({"distance": 1.0}, name="distance"))
    context.search("a", "f", ScalarProfile({"eta": 1.0}, name="eta"))

    cached_parents = [key[0] for key in context._pair_cache]
    assert len(cached_parents) == len(set(cached_parents))
    context.clear_pair_cache()
    assert context._pair_cache == {}


def test_base_pair_cache_reuses_only_unmodified_cross_request_searches(
    vehicle: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")
    identity = "test-static-build-and-config"

    first = PortsMapSearchContext(graph, evaluation, base_cache_identity=identity)
    expected = first.search("a", "f", profile)

    warm = PortsMapSearchContext(graph, evaluation, base_cache_identity=identity)

    def unexpected_search(*args: object, **kwargs: object) -> object:
        raise AssertionError("warm base pairs should come from the cross-request cache")

    monkeypatch.setattr(warm, "_fine_tile_search", unexpected_search)
    actual = warm.search("a", "f", profile)

    assert actual.h3_path == expected.h3_path
    assert actual.scalar_cost == expected.scalar_cost
    assert actual.cache_hits > 0
    assert warm.base_cache_hits > 0


@pytest.mark.parametrize(
    ("blocked", "penalties", "penalty_factor"),
    [
        (frozenset({"b"}), {}, 0.0),
        (frozenset(), {"b": 1}, 0.25),
    ],
)
def test_base_pair_cache_excludes_blocked_and_penalized_searches(
    vehicle: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
    blocked: frozenset[str],
    penalties: Mapping[str, int],
    penalty_factor: float,
) -> None:
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")
    context = PortsMapSearchContext(
        graph,
        evaluation,
        base_cache_identity="test-protected-overlay",
    )
    original = context._fine_tile_search
    calls = 0

    def counted_search(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(context, "_fine_tile_search", counted_search)
    context.search(
        "a",
        "f",
        profile,
        blocked=blocked,
        exploration_penalties=penalties,
        penalty_factor=penalty_factor,
    )

    assert calls > 0


def test_base_pair_cache_rejects_a_different_project_identity(
    vehicle: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")
    PortsMapSearchContext(
        graph,
        evaluation,
        base_cache_identity="identity-a",
    ).search("a", "f", profile)
    changed = PortsMapSearchContext(
        graph,
        evaluation,
        base_cache_identity="identity-b",
    )
    original = changed._fine_tile_search
    calls = 0

    def counted_search(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(changed, "_fine_tile_search", counted_search)
    changed.search("a", "f", profile)

    assert calls > 0
    assert changed.base_cache_hits == 0


def test_cl014_portsmap_limit_is_explicit(vehicle: VehicleProfile) -> None:
    """CL-014: exact construction exceeding a limit never returns a corridor approximation."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation, max_ports=1, max_port_pairs=1)
    with pytest.raises(PortsMapLimitError, match="PORTS_MAP_LIMIT_EXCEEDED") as caught:
        context.search("a", "f", ScalarProfile({"distance": 1.0}))
    assert caught.value.code == "PORTS_MAP_LIMIT_EXCEEDED"


def test_portsmap_lazy_evaluation_skips_untouched_parents(vehicle: VehicleProfile) -> None:
    """Lazy evaluation ensures unrelated parent tiles are never computed or added to cache."""
    parents = {
        "a": "p1",
        "b": "p1",
        "c": "p1",
        "d": "p2",
        "e": "p2",
        "f": "p2",
        "x": "p_far",
        "y": "p_far",
    }
    cells = {
        name: H3Cell(
            h3index=name,
            lat=0.0 if parent == "p1" else (1.0 if parent == "p2" else 10.0),
            lng=float(index),
            elevation=float(index),
            slope=0.0,
            tri=0.1 * index,
            lc_factor=1.0 + 0.1 * index,
            parent_h3=parent,
            is_passable=True,
        )
        for index, (name, parent) in enumerate(parents.items())
    }
    specifications = (
        ("a", "b", 2.0),
        ("b", "c", 2.0),
        ("a", "c", 6.0),
        ("b", "d", 4.0),
        ("c", "e", 1.0),
        ("d", "e", 2.0),
        ("d", "f", 6.0),
        ("e", "f", 2.0),
        ("x", "y", 1.5),
    )
    edges = {
        (first, second): H3Edge(
            first,
            second,
            distance,
            slope_a_to_b=0.0,
            slope_b_to_a=0.0,
        )
        for first, second, distance in specifications
    }
    graph = H3Graph(
        cells=cells,
        edges=edges,
        parent_children={
            "p1": {"a", "b", "c"},
            "p2": {"d", "e", "f"},
            "p_far": {"x", "y"},
        },
    )
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    result = context.search("a", "f", profile)

    assert result.h3_path[0] == "a"
    assert result.h3_path[-1] == "f"
    cached_parents = {key[0] for key in context._pair_cache}
    # Touched parents are in cache
    assert "p1" in cached_parents
    assert "p2" in cached_parents
    # Untouched parent tile is NEVER computed or cached
    assert "p_far" not in cached_parents



def _oracle_cost(
    edges: Mapping[tuple[str, str], DirectedEdgeMetrics],
    start: str,
    goal: str,
    profile: ScalarProfile,
) -> float:
    heap = [(0.0, start)]
    best = {start: 0.0}
    while heap:
        cost, current = heappop(heap)
        if current == goal:
            return cost
        if cost != best[current]:
            continue
        for (source, target), edge in edges.items():
            if source != current:
                continue
            candidate = cost + profile.edge_cost(edge)
            if candidate < best.get(target, inf):
                best[target] = candidate
                heappush(heap, (candidate, target))
    return inf


def _ports_graph() -> H3Graph:
    parents = {"a": "p1", "b": "p1", "c": "p1", "d": "p2", "e": "p2", "f": "p2"}
    cells = {
        name: H3Cell(
            h3index=name,
            lat=0.0 if parent == "p1" else 1.0,
            lng=float(index),
            elevation=float(index),
            slope=0.0,
            tri=0.1 * index,
            lc_factor=1.0 + 0.1 * index,
            parent_h3=parent,
            is_passable=True,
        )
        for index, (name, parent) in enumerate(parents.items())
    }
    specifications = (
        ("a", "b", 2.0),
        ("b", "c", 2.0),
        ("a", "c", 6.0),
        ("b", "d", 4.0),
        ("c", "e", 1.0),
        ("d", "e", 2.0),
        ("d", "f", 6.0),
        ("e", "f", 2.0),
    )
    edges = {
        (first, second): H3Edge(
            first,
            second,
            distance,
            slope_a_to_b=2.0,
            slope_b_to_a=-2.0,
        )
        for first, second, distance in specifications
    }
    return H3Graph(
        cells=cells,
        edges=edges,
        parent_children={"p1": {"a", "b", "c"}, "p2": {"d", "e", "f"}},
    )
