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
    logger, while a clean and concise '起终点无连通性' error is reported to the UI.
    """
    if start not in evaluation.node_metrics:
        logger.error("[DIAG] 起点 %s 不在评价网格中", start)
        _fail_reachability(progress, "起终点无连通性")

    if goal not in evaluation.node_metrics:
        logger.error("[DIAG] 终点 %s 不在评价网格中", goal)
        _fail_reachability(progress, "起终点无连通性")

    start_node = evaluation.node_metrics[start]
    if not start_node.is_passable:
        logger.error(
            "[DIAG] 起点 %s 自身不可通行！硬阻断原因: %s",
            start,
            list(start_node.reason_codes),
        )
        _fail_reachability(progress, "起终点无连通性")

    goal_node = evaluation.node_metrics[goal]
    if not goal_node.is_passable:
        logger.error(
            "[DIAG] 终点 %s 自身不可通行！硬阻断原因: %s",
            goal,
            list(goal_node.reason_codes),
        )
        _fail_reachability(progress, "起终点无连通性")

    if start == goal:
        logger.info("[REACHABILITY] 起终点为同一网格，连通性门检通过")
        return

    # Build passable directed adjacency from evaluation.directed_edges
    adj: dict[str, list[str]] = {}
    for from_h3, to_h3 in evaluation.directed_edges:
        adj.setdefault(from_h3, []).append(to_h3)

    if start not in adj:
        logger.error("[DIAG] 起点 %s 没有向外的可行边，处于完全孤立状态", start)
        _fail_reachability(progress, "起终点无连通性")

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

        logger.error("[DIAG] 起终点物理不连通！")
        logger.error(
            "[DIAG] 起点 %s 所在连通块大小: %d 网格，外围阻断主要原因: %s",
            start,
            len(visited),
            sorted(barrier_reasons) if barrier_reasons else "走廊几何边界或微观坡度阻断",
        )
        _fail_reachability(progress, "起终点无连通性")

    logger.info(
        "[REACHABILITY] 起终点连通性门检通过 (start=%s, goal=%s, 探索网格数=%d)",
        start,
        goal,
        len(visited),
    )


def _fail_reachability(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        with contextlib.suppress(Exception):
            progress("reachability", 0, message)
    raise PlanningFailedError(message)
