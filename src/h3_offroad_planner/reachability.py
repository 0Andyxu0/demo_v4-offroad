"""Reachability analysis and barrier-aware pre-flight checks."""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

import h3

from h3_offroad_planner.factor_model import FactorEvaluation
from h3_offroad_planner.models import H3Graph, PlanningFailedError

logger = logging.getLogger("h3_offroad_planner.reachability")

ProgressCallback = Callable[[str, int, str], None]


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lng2 - lng1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * r * atan2(sqrt(a), sqrt(1.0 - a))


def _is_valid_h3(cell: str | None) -> bool:
    if not cell:
        return False
    try:
        return bool(h3.is_valid_cell(cell))
    except (ValueError, TypeError):
        return False


def _parent_of_cell(cell: str, cell_obj: object | None, res_coarse: int) -> str:
    parent = getattr(cell_obj, "parent_h3", None)
    if parent:
        return str(parent)
    if _is_valid_h3(cell):
        try:
            return str(h3.cell_to_parent(cell, res_coarse))
        except (ValueError, TypeError):
            pass
    return cell


@dataclass(frozen=True)
class ReachabilityDiagnosis:
    """Detailed structural diagnosis of reachability and barrier boundaries."""

    reachable: bool
    visited_cells: frozenset[str] = frozenset()
    boundary_blockage_cells: frozenset[str] = frozenset()
    bottleneck_parents: tuple[str, ...] = ()
    barrier_reasons: tuple[str, ...] = ()
    component_size: int = 0
    disconnect_reason: str = ""


class ReachabilityDisconnectionError(PlanningFailedError):
    """Raised when reachability pre-check fails, carrying diagnostic barrier details."""

    def __init__(
        self,
        message: str = "Endpoints disconnected",
        diagnosis: ReachabilityDiagnosis | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnosis = diagnosis


def diagnose_route_reachability(
    graph: H3Graph,
    evaluation: FactorEvaluation,
    start: str,
    goal: str,
    res_coarse: int | None = None,
) -> ReachabilityDiagnosis:
    """Analyze reachability between start and goal and diagnose bottleneck barriers."""
    if start not in evaluation.node_metrics:
        logger.error("[DIAG] Start cell %s is missing from evaluation grid", start)
        return ReachabilityDiagnosis(
            reachable=False,
            disconnect_reason=f"Start cell {start} missing from evaluation grid",
        )

    if goal not in evaluation.node_metrics:
        logger.error("[DIAG] Goal cell %s is missing from evaluation grid", goal)
        return ReachabilityDiagnosis(
            reachable=False,
            disconnect_reason=f"Goal cell {goal} missing from evaluation grid",
        )

    start_node = evaluation.node_metrics[start]
    if not start_node.is_passable:
        reasons = tuple(sorted(start_node.reason_codes))
        logger.error(
            "[DIAG] Start cell %s is physically impassable! Reasons: %s",
            start,
            list(reasons),
        )
        return ReachabilityDiagnosis(
            reachable=False,
            barrier_reasons=reasons,
            disconnect_reason=f"Start cell {start} is physically impassable",
        )

    goal_node = evaluation.node_metrics[goal]
    if not goal_node.is_passable:
        reasons = tuple(sorted(goal_node.reason_codes))
        logger.error(
            "[DIAG] Goal cell %s is physically impassable! Reasons: %s",
            goal,
            list(reasons),
        )
        return ReachabilityDiagnosis(
            reachable=False,
            barrier_reasons=reasons,
            disconnect_reason=f"Goal cell {goal} is physically impassable",
        )

    if start == goal:
        return ReachabilityDiagnosis(
            reachable=True,
            visited_cells=frozenset([start]),
            component_size=1,
        )

    # Determine coarse resolution if not supplied
    if res_coarse is None:
        res_coarse = getattr(graph, "resolution_coarse", None)
    if res_coarse is None:
        start_cell = graph.cells.get(start)
        if start_cell and _is_valid_h3(start_cell.parent_h3):
            with contextlib.suppress(ValueError, TypeError):
                res_coarse = h3.get_resolution(start_cell.parent_h3)
    if res_coarse is None and _is_valid_h3(start):
        with contextlib.suppress(ValueError, TypeError):
            res_coarse = max(0, h3.get_resolution(start) - 2)
    if res_coarse is None:
        res_coarse = 11

    # Directed adjacency
    adj = (
        evaluation.directed_adjacency()
        if hasattr(evaluation, "directed_adjacency")
        else {}
    )
    if not adj and evaluation.directed_edges:
        adj = {}
        for from_h3, to_h3 in evaluation.directed_edges:
            adj.setdefault(from_h3, []).append(to_h3)

    if start not in adj:
        logger.error("[DIAG] Start cell %s has no passable outgoing edges; isolated", start)
        start_cell = graph.cells.get(start)
        parent = _parent_of_cell(start, start_cell, res_coarse)
        return ReachabilityDiagnosis(
            reachable=False,
            visited_cells=frozenset([start]),
            boundary_blockage_cells=frozenset([start]),
            bottleneck_parents=(parent,),
            component_size=1,
            disconnect_reason=f"Start cell {start} has no outgoing edges",
        )

    # Forward BFS from start
    visited_start: set[str] = {start}
    queue_start: deque[str] = deque([start])
    reachable = False

    while queue_start:
        curr = queue_start.popleft()
        if curr == goal:
            reachable = True
            break
        for nxt in adj.get(curr, ()):
            if nxt not in visited_start:
                visited_start.add(nxt)
                queue_start.append(nxt)

    if reachable:
        return ReachabilityDiagnosis(
            reachable=True,
            visited_cells=frozenset(visited_start),
            component_size=len(visited_start),
        )

    # Backward BFS from goal (to identify goal-side island if available)
    rev_adj: dict[str, list[str]] = {}
    for from_h3, to_h3 in evaluation.directed_edges:
        rev_adj.setdefault(to_h3, []).append(from_h3)

    visited_goal: set[str] = set()
    if goal in evaluation.node_metrics and evaluation.node_metrics[goal].is_passable:
        visited_goal.add(goal)
        queue_goal: deque[str] = deque([goal])
        while queue_goal:
            curr = queue_goal.popleft()
            for prev in rev_adj.get(curr, ()):
                if prev not in visited_goal:
                    visited_goal.add(prev)
                    queue_goal.append(prev)

    # Build undirected graph adjacency for boundary / neighbor detection
    graph_neighbors: dict[str, set[str]] = {}
    for edge in graph.edges.values():
        graph_neighbors.setdefault(edge.cell_a, set()).add(edge.cell_b)
        graph_neighbors.setdefault(edge.cell_b, set()).add(edge.cell_a)

    barrier_reasons: set[str] = set()
    boundary_blockage_cells: set[str] = set()

    goal_cell = graph.cells.get(goal)
    goal_lat: float | None = None
    goal_lng: float | None = None
    if goal_cell is not None:
        goal_lat, goal_lng = goal_cell.lat, goal_cell.lng
    elif _is_valid_h3(goal):
        try:
            goal_lat, goal_lng = h3.cell_to_latlng(goal)
        except (ValueError, TypeError):
            goal_lat, goal_lng = None, None

    start_cell = graph.cells.get(start)
    start_lat: float | None = None
    start_lng: float | None = None
    if start_cell is not None:
        start_lat, start_lng = start_cell.lat, start_cell.lng
    elif _is_valid_h3(start):
        try:
            start_lat, start_lng = h3.cell_to_latlng(start)
        except (ValueError, TypeError):
            start_lat, start_lng = None, None

    # Collect start-side boundary cells and bottleneck parents
    start_parent_min_dist: dict[str, float] = {}

    for cell in visited_start:
        c_obj = graph.cells.get(cell)
        c_lat: float | None = None
        c_lng: float | None = None
        if c_obj is not None:
            c_lat, c_lng = c_obj.lat, c_obj.lng
        elif _is_valid_h3(cell):
            try:
                c_lat, c_lng = h3.cell_to_latlng(cell)
            except (ValueError, TypeError):
                c_lat, c_lng = None, None

        dist_to_goal = (
            _haversine_m(c_lat, c_lng, goal_lat, goal_lng)
            if (
                c_lat is not None
                and c_lng is not None
                and goal_lat is not None
                and goal_lng is not None
            )
            else 0.0
        )
        c_parent = _parent_of_cell(cell, c_obj, res_coarse)

        is_boundary = False
        # 1. Neighbor cells in graph not in visited_start
        for neighbor in graph_neighbors.get(cell, ()):
            if neighbor not in visited_start:
                is_boundary = True
                n_node = evaluation.node_metrics.get(neighbor)
                if n_node is not None and not n_node.is_passable:
                    barrier_reasons.update(n_node.reason_codes)
                n_obj = graph.cells.get(neighbor)
                n_parent = _parent_of_cell(neighbor, n_obj, res_coarse)
                start_parent_min_dist[n_parent] = min(
                    start_parent_min_dist.get(n_parent, float("inf")), dist_to_goal
                )

        # 2. Disk neighbors outside loaded graph (corridor boundary)
        if _is_valid_h3(cell):
            try:
                nbrs = [str(n) for n in h3.grid_disk(cell, 1)]
            except (ValueError, TypeError):
                nbrs = []
            for nbr_str in nbrs:
                if nbr_str not in graph.cells:
                    is_boundary = True
                    break

        if is_boundary:
            boundary_blockage_cells.add(cell)
            start_parent_min_dist[c_parent] = min(
                start_parent_min_dist.get(c_parent, float("inf")), dist_to_goal
            )

    # Collect goal-side boundary parents
    goal_parent_min_dist: dict[str, float] = {}
    for cell in visited_goal:
        c_obj = graph.cells.get(cell)
        c_lat = None
        c_lng = None
        if c_obj is not None:
            c_lat, c_lng = c_obj.lat, c_obj.lng
        elif _is_valid_h3(cell):
            try:
                c_lat, c_lng = h3.cell_to_latlng(cell)
            except (ValueError, TypeError):
                c_lat, c_lng = None, None

        dist_to_start = (
            _haversine_m(c_lat, c_lng, start_lat, start_lng)
            if (
                c_lat is not None
                and c_lng is not None
                and start_lat is not None
                and start_lng is not None
            )
            else 0.0
        )
        c_parent = _parent_of_cell(cell, c_obj, res_coarse)
        is_boundary = False
        for neighbor in graph_neighbors.get(cell, ()):
            if neighbor not in visited_goal:
                is_boundary = True
                n_obj = graph.cells.get(neighbor)
                n_parent = _parent_of_cell(neighbor, n_obj, res_coarse)
                goal_parent_min_dist[n_parent] = min(
                    goal_parent_min_dist.get(n_parent, float("inf")), dist_to_start
                )
        if _is_valid_h3(cell):
            try:
                nbrs = [str(n) for n in h3.grid_disk(cell, 1)]
            except (ValueError, TypeError):
                nbrs = []
            for nbr_str in nbrs:
                if nbr_str not in graph.cells:
                    is_boundary = True
                    break
        if is_boundary:
            goal_parent_min_dist[c_parent] = min(
                goal_parent_min_dist.get(c_parent, float("inf")), dist_to_start
            )

    # Rank and select bottleneck parents (3 ~ 8 parents)
    sorted_start_parents = sorted(
        start_parent_min_dist.keys(), key=lambda p: start_parent_min_dist[p]
    )
    sorted_goal_parents = sorted(
        goal_parent_min_dist.keys(), key=lambda p: goal_parent_min_dist[p]
    )

    bottleneck_list: list[str] = []
    seen: set[str] = set()

    # Interleave closest start-side and goal-side bottleneck parents
    max_side = max(len(sorted_start_parents), len(sorted_goal_parents))
    for i in range(max_side):
        if i < len(sorted_start_parents):
            sp = sorted_start_parents[i]
            if sp not in seen:
                seen.add(sp)
                bottleneck_list.append(sp)
        if len(bottleneck_list) >= 8:
            break
        if i < len(sorted_goal_parents):
            gp = sorted_goal_parents[i]
            if gp not in seen:
                seen.add(gp)
                bottleneck_list.append(gp)
        if len(bottleneck_list) >= 8:
            break

    # If goal side has no parents, fill with start parents up to 8
    if len(bottleneck_list) < 3:
        for sp in sorted_start_parents:
            if sp not in seen:
                seen.add(sp)
                bottleneck_list.append(sp)
            if len(bottleneck_list) >= 8:
                break

    if not bottleneck_list:
        sp = _parent_of_cell(start, graph.cells.get(start), res_coarse)
        gp = _parent_of_cell(goal, graph.cells.get(goal), res_coarse)
        bottleneck_list = [sp] if sp == gp else [sp, gp]

    return ReachabilityDiagnosis(
        reachable=False,
        visited_cells=frozenset(visited_start),
        boundary_blockage_cells=frozenset(boundary_blockage_cells),
        bottleneck_parents=tuple(bottleneck_list),
        barrier_reasons=tuple(sorted(barrier_reasons)),
        component_size=len(visited_start),
        disconnect_reason="Endpoints disconnected",
    )


def check_route_reachability(
    graph: H3Graph,
    evaluation: FactorEvaluation,
    start: str,
    goal: str,
    progress: ProgressCallback | None = None,
    res_coarse: int | None = None,
) -> ReachabilityDiagnosis:
    """Pre-flight reachability gate.

    Verifies that the start and goal endpoints are physically passable and mutually
    reachable via directed passable edges before entering heavy Pareto search.

    If disconnected, raises ReachabilityDisconnectionError carrying detailed
    barrier and bottleneck parent diagnosis for targeted repair.
    """
    diagnosis = diagnose_route_reachability(
        graph, evaluation, start, goal, res_coarse=res_coarse
    )
    if not diagnosis.reachable:
        logger.error("[DIAG] Endpoints physically disconnected!")
        blocked_by = (
            sorted(diagnosis.barrier_reasons)
            if diagnosis.barrier_reasons
            else "corridor boundary or slope"
        )
        logger.error(
            "[DIAG] Start cell %s reachable component size: %d cells; "
            "boundary blocked by: %s; bottleneck parents: %s",
            start,
            diagnosis.component_size,
            blocked_by,
            diagnosis.bottleneck_parents,
        )
        if progress is not None:
            with contextlib.suppress(Exception):
                progress("reachability", 0, "Endpoints disconnected")
        raise ReachabilityDisconnectionError("Endpoints disconnected", diagnosis=diagnosis)

    logger.info(
        "[REACHABILITY] Reachability gate passed (start=%s, goal=%s, explored_cells=%d)",
        start,
        goal,
        diagnosis.component_size,
    )
    return diagnosis
