"""Spec-derived tests for deterministic candidates, role merging, and independence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from h3_offroad_planner.candidate_aggregation import (
    CandidateAggregator,
    _assign_metric_roles,
    _recommendation,
    _same_metrics,
    _truncate_candidates,
)
from h3_offroad_planner.factor_model import (
    PHYSICAL_EVIDENCE_WARNING,
    FactorEvaluation,
    FactorModelConfig,
    PathMetrics,
    evaluate_factor_model,
)
from h3_offroad_planner.models import (
    H3Cell,
    H3Edge,
    H3Graph,
    PlanningFailedError,
    PlanningInputError,
    VehicleProfile,
)
from h3_offroad_planner.planners.deterministic_pareto import (
    DeterministicParetoPlanner,
    GeneratedPath,
    _bounded_candidates,
    _crowding_order,
    _dominates,
    _non_dominated_fronts,
    _robust_scales,
)
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.route_models import RouteCandidate, candidate_id_for_path


def test_cl016_planner_and_aggregator_return_unique_fixed_roles(
    vehicle: VehicleProfile,
) -> None:
    """CL-016: output has one-to-five unique routes and every metric role is precise."""
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    raw = DeterministicParetoPlanner(context, candidate_limit=24).plan("s", "g")
    result = CandidateAggregator(graph, context).aggregate(raw, "fastest", 5)
    assert 1 <= len(result.candidates) <= 5
    assert len({candidate.h3_path for candidate in result.candidates}) == len(result.candidates)
    fastest = next(candidate for candidate in result.candidates if "fastest_eta" in candidate.roles)
    shortest = next(
        candidate for candidate in result.candidates if "shortest_distance" in candidate.roles
    )
    passability = next(
        candidate
        for candidate in result.candidates
        if "max_passability_margin" in candidate.roles
    )
    economy = next(
        candidate for candidate in result.candidates if "minimum_travel_cost" in candidate.roles
    )
    assert fastest.metrics.eta_s == min(candidate.metrics.eta_s for candidate in result.candidates)
    assert shortest.metrics.distance_m == min(
        candidate.metrics.distance_m for candidate in result.candidates
    )
    assert passability.metrics.safety_margin_min == max(
        candidate.metrics.safety_margin_min for candidate in result.candidates
    )
    assert economy.metrics.travel_cost == min(
        candidate.metrics.travel_cost for candidate in result.candidates
    )
    assert result.recommended_candidate_id == fastest.candidate_id


def test_cl017_resilient_route_survives_reference_corridor_failure(
    vehicle: VehicleProfile,
) -> None:
    """CL-017: an independent role is awarded only after masked-corridor survival."""
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    raw = DeterministicParetoPlanner(context).plan("s", "g")
    result = CandidateAggregator(graph, context).aggregate(raw, "resilient", 5)
    independent = next(
        candidate for candidate in result.candidates if "independent_backup" in candidate.roles
    )
    assert independent.independence_evidence["survived_disruption"] is True
    assert result.independence_reference_candidate_id is not None
    assert result.recommended_candidate_id == independent.candidate_id


def test_cl018_no_core_corridor_does_not_fabricate_backup(vehicle: VehicleProfile) -> None:
    """CL-018: a route without a maskable core returns the documented resilient fallback."""
    graph = _direct_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    raw = DeterministicParetoPlanner(context).plan("s", "g")
    result = CandidateAggregator(graph, context).aggregate(raw, "resilient", 5)
    assert all("independent_backup" not in candidate.roles for candidate in result.candidates)
    assert result.warnings == (
        "INDEPENDENT_BACKUP_UNAVAILABLE",
        PHYSICAL_EVIDENCE_WARNING,
    )


def test_cl019_candidate_generation_is_deterministic(vehicle: VehicleProfile) -> None:
    """CL-019: identical graph/config inputs produce identical paths, roles, and ordering."""
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    first_context = PortsMapSearchContext(graph, evaluation)
    second_context = PortsMapSearchContext(graph, evaluation)
    first_raw = DeterministicParetoPlanner(first_context).plan("s", "g")
    second_raw = DeterministicParetoPlanner(second_context).plan("s", "g")
    first = CandidateAggregator(graph, first_context).aggregate(first_raw, "economy", 5)
    second = CandidateAggregator(graph, second_context).aggregate(second_raw, "economy", 5)
    assert [candidate.to_dict() for candidate in first.candidates] == [
        candidate.to_dict() for candidate in second.candidates
    ]


def _generated(
    name: str,
    distance: float,
    eta: float,
    risk: float,
    cost: float,
    margin: float,
    profile: str = "test",
) -> GeneratedPath:
    metrics = PathMetrics(
        distance,
        eta,
        eta,
        eta,
        True,
        risk,
        cost,
        margin,
        margin,
        1,
    )
    return GeneratedPath(("s", name, "g"), metrics, profile, cost)


def test_deterministic_planner_validation_and_empty_scale_guard() -> None:
    """Deterministic planner rejects invalid bounds and normalization without edges."""
    context = object()
    with pytest.raises(ValueError, match="max_paths"):
        DeterministicParetoPlanner(context, max_paths=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="candidate_limit"):
        DeterministicParetoPlanner(  # type: ignore[arg-type]
            context, max_paths=5, candidate_limit=4
        )
    with pytest.raises(ValueError, match="penalty_factor"):
        DeterministicParetoPlanner(context, penalty_factor=-1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attempts_per_profile"):
        DeterministicParetoPlanner(  # type: ignore[arg-type]
            context, attempts_per_profile=0
        )
    valid_metrics = _generated("a", 1, 1, 1, 1, 0.5).metrics
    with pytest.raises(ValueError, match="non-empty"):
        GeneratedPath((), valid_metrics, "x", 1.0)
    with pytest.raises(ValueError, match="finite"):
        GeneratedPath(("a",), valid_metrics, "x", -1.0)
    evaluation = FactorEvaluation({}, {}, "v", "f", "s", "g")
    with pytest.raises(PlanningFailedError, match="passable edges"):
        _robust_scales(evaluation)


def test_fast_five_searches_each_base_profile_once(vehicle: VehicleProfile) -> None:
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    planner = DeterministicParetoPlanner(
        context,
        attempts_per_profile=1,
        environment_pressures=(),
    )

    raw = planner.plan("s", "g")
    result = CandidateAggregator(graph, context).aggregate(raw, "fastest", 5)

    assert planner.profile_search_count == 4
    assert len(raw) <= 5
    assert not any(path.generation_profile.startswith("environment_w") for path in raw)
    assert {
        "fastest_eta",
        "shortest_distance",
        "max_passability_margin",
        "minimum_travel_cost",
        "independent_backup",
    } == {role for candidate in result.candidates for role in candidate.roles}


def test_cl020_pareto_front_crowding_and_widest_preservation() -> None:
    """Front ranking exercises dominance, crowding interiors and widest replacement."""
    dominant = _generated("a", 1, 1, 1, 1, 0.9)
    dominated = _generated("b", 2, 2, 2, 2, 0.8)
    distance = _generated("c", 0.5, 4, 4, 4, 0.4)
    eta = _generated("d", 4, 0.5, 4, 4, 0.4)
    risk = _generated("e", 4, 4, 0.5, 4, 0.4)
    widest = _generated("w", 8, 8, 8, 8, 1.0, "widest_path")
    candidates = [dominant, dominated, distance, eta, risk, widest]

    assert _dominates(dominant, dominated) is True
    assert _dominates(dominated, dominant) is False
    fronts = _non_dominated_fronts(candidates)
    assert dominated in fronts[-1]
    assert set(_crowding_order(fronts[0])) == set(fronts[0])
    selected = _bounded_candidates(candidates, 3)
    assert len(selected) == 3
    assert widest in selected
    assert _bounded_candidates([dominant], 3) == [dominant]


def test_cl021_candidate_aggregator_boundary_and_metric_validation(
    vehicle: VehicleProfile,
) -> None:
    """Aggregation rejects invalid request bounds and stale cached path metrics."""
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    raw = DeterministicParetoPlanner(context).plan("s", "g")
    with pytest.raises(ValueError, match="disruption_radius"):
        CandidateAggregator(graph, context, disruption_radius=-1)
    aggregator = CandidateAggregator(graph, context)
    with pytest.raises(ValueError, match="mission_profile"):
        aggregator.aggregate(raw, "unknown")
    with pytest.raises(ValueError, match="max_candidates"):
        aggregator.aggregate(raw, "fastest", 0)
    with pytest.raises(ValueError, match="raw_candidates"):
        aggregator.aggregate([], "fastest")
    stale = replace(raw[0], metrics=replace(raw[0].metrics, distance_m=999.0))
    with pytest.raises(PlanningInputError, match="do not match"):
        aggregator.aggregate([stale], "fastest")
    duplicates = [
        replace(raw[0], generation_profile="z-profile"),
        replace(raw[0], generation_profile="a-profile"),
    ]
    assert aggregator._validated_unique(duplicates)[raw[0].h3_path].generation_profile == (
        "a-profile"
    )


def test_candidate_aggregation_helper_fallbacks_and_truncation() -> None:
    """Role fallback helpers cover impossible-role and deterministic truncation paths."""
    with pytest.raises(PlanningFailedError, match="no Pareto"):
        _assign_metric_roles({})
    base = _generated("base", 1, 1, 1, 1, 0.8)
    route = RouteCandidate(
        candidate_id=candidate_id_for_path(base.h3_path),
        h3_path=base.h3_path,
        roles=("fastest_eta",),
        is_recommended=True,
        objectives=base.objectives,
        metrics=base.metrics,
        corridor_signature=("p",),
        generation_profile="test",
        replan_profile="eta",
    )
    with pytest.raises(PlanningFailedError, match="required route role"):
        _recommendation("economy", (route,), route.candidate_id)
    recommended, reference, warnings = _recommendation(
        "resilient", (route,), route.candidate_id
    )
    assert (recommended, reference) == (route.candidate_id, route.candidate_id)
    assert warnings == ("INDEPENDENT_BACKUP_UNAVAILABLE",)

    roles = (
        "fastest_eta",
        "shortest_distance",
        "max_passability_margin",
        "minimum_travel_cost",
        "independent_backup",
    )
    routes = []
    for index, role in enumerate(roles):
        generated = _generated(str(index), index + 1, index + 1, 1, index + 1, 0.5)
        routes.append(
            RouteCandidate(
                candidate_id=candidate_id_for_path(generated.h3_path),
                h3_path=generated.h3_path,
                roles=(role,),
                is_recommended=index == 0,
                objectives=generated.objectives,
                metrics=generated.metrics,
                corridor_signature=(str(index),),
                generation_profile="test",
                replan_profile="eta",
            )
        )
    truncated = _truncate_candidates(tuple(routes), routes[0].candidate_id, 3)
    assert len(truncated) == 3
    assert routes[0] in truncated
    assert _same_metrics(base.metrics, replace(base.metrics, distance_m=2.0)) is False


def test_same_metrics_compares_optional_eta_and_mean_margin() -> None:
    base = _generated("base", 1, 1, 1, 1, 0.8).metrics

    assert _same_metrics(base, replace(base)) is True
    assert _same_metrics(base, replace(base, safety_margin_mean=0.9)) is False
    assert _same_metrics(base, replace(base, eta_upper_s=2.0)) is False

    unbounded = replace(base, eta_upper_s=None, eta_upper_bounded=False)
    assert _same_metrics(unbounded, replace(unbounded)) is True
    assert _same_metrics(unbounded, base) is False


def test_independence_mask_can_prove_no_surviving_route(vehicle: VehicleProfile) -> None:
    """A real masked core with no alternate corridor returns no backup, never a fake one."""
    cells = {
        name: H3Cell(
            name,
            0.0,
            float(index),
            0.0,
            0.0,
            0.0,
            1.0,
            parent_h3=parent,
        )
        for index, (name, parent) in enumerate((("s", "ps"), ("a", "pa"), ("g", "pg")))
    }
    graph = H3Graph(
        cells=cells,
        edges={
            ("s", "a"): H3Edge("s", "a", 1.0),
            ("a", "g"): H3Edge("a", "g", 1.0),
        },
    )
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    reference = DeterministicParetoPlanner(context).plan("s", "g")[0]
    aggregator = CandidateAggregator(graph, context, disruption_radius=1)

    independent, evidence = aggregator._independent_backup(
        reference, {reference.h3_path: reference}
    )

    assert independent is None
    assert evidence == {}


def _corridor_graph() -> H3Graph:
    parent_by_cell = {
        "s": "ps",
        "a1": "pa",
        "a2": "pa",
        "b1": "pb",
        "b2": "pb",
        "c1": "pc",
        "c2": "pc",
        "g": "pg",
    }
    cells = {}
    for index, (cell_id, parent) in enumerate(parent_by_cell.items()):
        lc_factor = 1.0
        has_road = cell_id.startswith("a")
        tri = 0.1
        if cell_id.startswith("b"):
            lc_factor = 2.0
            tri = 1.0
        if cell_id.startswith("c"):
            lc_factor = 1.2
            tri = 0.0
        cells[cell_id] = H3Cell(
            h3index=cell_id,
            lat=float(index % 3),
            lng=float(index),
            elevation=0.0,
            slope=0.0,
            tri=tri,
            lc_factor=lc_factor,
            parent_h3=parent,
            has_road=has_road,
            is_passable=True,
        )
    edge_specs = (
        ("s", "a1", 3.0),
        ("a1", "a2", 3.0),
        ("a2", "g", 3.0),
        ("s", "b1", 2.0),
        ("b1", "b2", 2.0),
        ("b2", "g", 2.0),
        ("s", "c1", 4.0),
        ("c1", "c2", 4.0),
        ("c2", "g", 4.0),
    )
    edges = {
        (first, second): H3Edge(first, second, distance)
        for first, second, distance in edge_specs
    }
    parent_children: dict[str, set[str]] = {}
    for cell_id, parent in parent_by_cell.items():
        parent_children.setdefault(parent, set()).add(cell_id)
    return H3Graph(cells=cells, edges=edges, parent_children=parent_children)


def _direct_graph() -> H3Graph:
    graph = _corridor_graph()
    cells = {name: replace(graph.cells[name]) for name in ("s", "g")}
    edge = H3Edge("s", "g", 1.0)
    return H3Graph(cells=cells, edges={("s", "g"): edge})


def test_deterministic_planner_emits_sub_progress(vehicle: VehicleProfile) -> None:
    graph = _corridor_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    events: list[tuple[str, int, str]] = []
    DeterministicParetoPlanner(context).plan(
        "s", "g", progress=lambda mod, pct, msg: events.append((mod, pct, msg))
    )
    assert any("searching profile [1/" in msg for _, _, msg in events)
    assert any(msg == "searching widest bottleneck route" for _, _, msg in events)
