import contextlib
import logging
from collections import deque
from collections.abc import Callable

from h3_offroad_planner.factor_model import FactorEvaluation
from h3_offroad_planner.models import H3Graph, PlanningFailedError

logger = logging.getLogger("h3_offroad_planner.reachability")

ProgressCallback = Callable[[str, int, str], None]


def check_route_reachability(
    graph: H3Graph,
    evaluation: FactorEvaluation,
    start: str,
    goal: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Pre-flight reachability gate.

    Verifies that the start and goal endpoints are physically passable and mutually
    reachable via directed passable edges before entering heavy Pareto search.

    Detailed topological and obstacle diagnoses are logged to the IDE / system process
    logger, while a clean and concise 'Endpoints disconnected' error is reported to the UI.
    """
    if start not in evaluation.node_metrics:
        logger.error("[DIAG] Start cell %s is missing from evaluation grid", start)
        _fail_reachability(progress, "Endpoints disconnected")

    if goal not in evaluation.node_metrics:
        logger.error("[DIAG] Goal cell %s is missing from evaluation grid", goal)
        _fail_reachability(progress, "Endpoints disconnected")

    start_node = evaluation.node_metrics[start]
    if not start_node.is_passable:
        logger.error(
            "[DIAG] Start cell %s is physically impassable! Reasons: %s",
            start,
            list(start_node.reason_codes),
        )
        _fail_reachability(progress, "Endpoints disconnected")

    goal_node = evaluation.node_metrics[goal]
    if not goal_node.is_passable:
        logger.error(
            "[DIAG] Goal cell %s is physically impassable! Reasons: %s",
            goal,
            list(goal_node.reason_codes),
        )
        _fail_reachability(progress, "Endpoints disconnected")

    if start == goal:
        logger.info("[REACHABILITY] Start and goal are identical; reachability gate passed")
        return

    # Build passable directed adjacency from evaluation.directed_edges
    adj: dict[str, list[str]] = {}
    for from_h3, to_h3 in evaluation.directed_edges:
        adj.setdefault(from_h3, []).append(to_h3)

    if start not in adj:
        logger.error("[DIAG] Start cell %s has no passable outgoing edges; isolated", start)
        _fail_reachability(progress, "Endpoints disconnected")

    # Fast Breadth-First Search on passable subgraph
    visited: set[str] = {start}
    queue: deque[str] = deque([start])
    reachable = False

    while queue:
        curr = queue.popleft()
        if curr == goal:
            reachable = True
            break
        for nxt in adj.get(curr, ()):
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)

    if not reachable:
        # Collect diagnosis on the barrier surrounding the visited island
        barrier_reasons: set[str] = set()
        graph_neighbors: dict[str, set[str]] = {}
        for edge in graph.edges.values():
            graph_neighbors.setdefault(edge.cell_a, set()).add(edge.cell_b)
            graph_neighbors.setdefault(edge.cell_b, set()).add(edge.cell_a)

        for cell in visited:
            for neighbor in graph_neighbors.get(cell, ()):
                if neighbor not in visited:
                    n_node = evaluation.node_metrics.get(neighbor)
                    if n_node is not None and not n_node.is_passable:
                        barrier_reasons.update(n_node.reason_codes)

        logger.error("[DIAG] Endpoints physically disconnected!")
        logger.error(
            "[DIAG] Start cell %s reachable component size: %d cells; boundary blocked by: %s",
            start,
            len(visited),
            sorted(barrier_reasons) if barrier_reasons else "corridor boundary or slope",
        )
        _fail_reachability(progress, "Endpoints disconnected")

    logger.info(
        "[REACHABILITY] Reachability gate passed (start=%s, goal=%s, explored_cells=%d)",
        start,
        goal,
        len(visited),
    )


def _fail_reachability(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        with contextlib.suppress(Exception):
            progress("reachability", 0, message)
    raise PlanningFailedError(message)
