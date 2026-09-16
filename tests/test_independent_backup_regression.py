"""Regression tests for short-corridor independence and endpoint-parent blocking.

These tests cover two real defects found during the audit:

1. ``CandidateAggregator._corridor_signature`` returns an empty corridor for
   paths that cross two or fewer parent cells.  The old ``_independent_backup``
   therefore returned ``None`` unconditionally for short routes even when a
   fine-grained alternate H3 path existed.

2. ``_independent_backup`` could block the start/goal parent cells when parent
   dilation touched them, making it impossible for the search to leave the
   start cell through an alternate corridor.
"""

from __future__ import annotations

from h3_offroad_planner.candidate_aggregation import CandidateAggregator
from h3_offroad_planner.factor_model import (
    FactorModelConfig,
    PathMetrics,
    evaluate_factor_model,
)
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, VehicleProfile
from h3_offroad_planner.planners.deterministic_pareto import GeneratedPath
from h3_offroad_planner.portsmap import PortsMapSearchContext


def _metrics(distance: float) -> PathMetrics:
    return PathMetrics(
        distance_m=distance,
        eta_s=distance,
        eta_upper_s=distance,
        eta_lower_s=distance,
        eta_upper_bounded=True,
        terrain_risk=0.0,
        travel_cost=distance,
        safety_margin_min=1.0,
        safety_margin_mean=1.0,
        edge_count=1,
    )


def _cell(name: str, parent: str, index: int) -> H3Cell:
    return H3Cell(
        h3index=name,
        lat=float(index % 3),
        lng=float(index),
        elevation=0.0,
        slope=0.0,
        tri=0.0,
        lc_factor=1.0,
        parent_h3=parent,
        has_road=False,
        is_passable=True,
    )


def _edge(first: str, second: str, distance: float) -> H3Edge:
    return H3Edge(cell_a=first, cell_b=second, geo_distance=distance)


def _aggregator(graph: H3Graph, vehicle: VehicleProfile) -> CandidateAggregator:
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    return CandidateAggregator(graph, context)


def test_short_two_parent_path_uses_fine_cell_backup(
    vehicle: VehicleProfile,
) -> None:
    """A path crossing only two parent cells can still get an alternate route."""
    cells = {
        "s": _cell("s", "ps", 0),
        "a1": _cell("a1", "pg", 1),
        "b1": _cell("b1", "pg", 2),
        "g": _cell("g", "pg", 3),
    }
    edges = {
        ("s", "a1"): _edge("s", "a1", 1.0),
        ("a1", "g"): _edge("a1", "g", 1.0),
        ("s", "b1"): _edge("s", "b1", 2.0),
        ("b1", "g"): _edge("b1", "g", 2.0),
    }
    graph = H3Graph(cells=cells, edges=edges)
    aggregator = _aggregator(graph, vehicle)

    reference = GeneratedPath(("s", "a1", "g"), _metrics(2.0), "reference", 2.0)
    alternate = GeneratedPath(("s", "b1", "g"), _metrics(4.0), "alternate", 4.0)
    independent, evidence = aggregator._independent_backup(
        reference, {reference.h3_path: reference, alternate.h3_path: alternate}
    )

    assert independent is not None
    assert independent.h3_path == ("s", "b1", "g")
    assert evidence["core_kind"] == "fine"
    assert evidence["blocked_core_cells"] == ["a1"]


def test_endpoint_parent_cells_are_not_blocked_by_dilation(
    vehicle: VehicleProfile,
) -> None:
    """Parent dilation must never block start/goal parent cells as a whole."""
    cells = {
        "s": _cell("s", "ps", 0),
        "s2": _cell("s2", "ps", 1),
        "a1": _cell("a1", "pa", 2),
        "g": _cell("g", "pg", 3),
        "b1": _cell("b1", "pb", 4),
        "b2": _cell("b2", "pb", 5),
    }
    edges = {
        ("s", "a1"): _edge("s", "a1", 3.0),
        ("a1", "g"): _edge("a1", "g", 3.0),
        ("s", "s2"): _edge("s", "s2", 1.0),
        ("s2", "b1"): _edge("s2", "b1", 1.0),
        ("b1", "b2"): _edge("b1", "b2", 1.0),
        ("b2", "g"): _edge("b2", "g", 1.0),
    }
    graph = H3Graph(cells=cells, edges=edges)
    aggregator = _aggregator(graph, vehicle)

    reference = GeneratedPath(("s", "a1", "g"), _metrics(6.0), "reference", 6.0)
    alternate = GeneratedPath(
        ("s", "s2", "b1", "b2", "g"), _metrics(4.0), "alternate", 4.0
    )
    independent, evidence = aggregator._independent_backup(
        reference, {reference.h3_path: reference, alternate.h3_path: alternate}
    )

    assert independent is not None
    assert independent.h3_path == ("s", "s2", "b1", "b2", "g")
    assert evidence["core_kind"] == "parent"
    # ps/pg are endpoint parents and must not appear in the masked parent set.
    assert "ps" not in evidence["masked_parents"]
    assert "pg" not in evidence["masked_parents"]

