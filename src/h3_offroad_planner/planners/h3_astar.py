"""Hierarchical PortsMap and A* planner for in-memory H3-style graphs."""

from __future__ import annotations

from heapq import heappop, heappush
from math import inf, isfinite, sqrt

from h3_offroad_planner.dynamics.cost_function import CostFunction
from h3_offroad_planner.models import (
    H3Graph,
    Path,
    PlannerInput,
    PlannerOutput,
    PlanningFailedError,
)
from h3_offroad_planner.planners.interfaces import GlobalPlanner

__all__ = ["H3AStarPlanner"]


class H3AStarPlanner(GlobalPlanner):
    """Plan through a parent-cell corridor before running fine-cell A*."""

    def __init__(self, cost_function: CostFunction) -> None:
        """Initialize the planner with a physical edge-cost function."""
        self.cost_function = cost_function

    def plan(self, inp: PlannerInput) -> PlannerOutput:
        """Plan a single finite-cost path from `inp.start` to `inp.goal`."""
        ports_map = self._build_ports_map(inp.graph)
        macro_route = self._macro_astar(ports_map, inp.graph, inp.start, inp.goal)
        corridor = self._extract_corridor(inp.graph, macro_route)
        path = self._corridor_astar(inp.graph, corridor, inp.start, inp.goal)
        return PlannerOutput(
            paths=[path],
            metadata={"ports_count": len(ports_map), "corridor_size": len(corridor)},
        )

    def _build_ports_map(self, graph: H3Graph) -> dict[str, dict[str, float]]:
        """Build directional parent adjacency weighted by physical boundary traversal."""
        if not graph.cells:
            raise PlanningFailedError("graph has no cells.")
        ports_map: dict[str, dict[str, float]] = {
            self._parent_id(graph, cell_id): {}
            for cell_id, cell in graph.cells.items()
            if cell.is_passable
        }
        for edge in graph.edges.values():
            if not self._edge_is_passable(graph, edge.cell_a, edge.cell_b):
                continue
            parent_a = self._parent_id(graph, edge.cell_a)
            parent_b = self._parent_id(graph, edge.cell_b)
            if parent_a != parent_b:
                self._record_boundary_cost(
                    ports_map, graph, parent_a, parent_b, edge.cell_a, edge.cell_b
                )
                self._record_boundary_cost(
                    ports_map, graph, parent_b, parent_a, edge.cell_b, edge.cell_a
                )
        return ports_map

    def _macro_astar(
        self,
        ports_map: dict[str, dict[str, float]],
        graph: H3Graph,
        start: str,
        goal: str,
    ) -> list[str]:
        """Find a finite parent-cell route and attach endpoint cells by parent."""
        if start not in graph.cells or goal not in graph.cells:
            raise PlanningFailedError("start or goal is not present in graph.")
        if not graph.cells[start].is_passable:
            raise PlanningFailedError(f"start={start!r} is not passable.")
        if not graph.cells[goal].is_passable:
            raise PlanningFailedError(f"goal={goal!r} is not passable.")
        start_parent = self._parent_id(graph, start)
        goal_parent = self._parent_id(graph, goal)
        if start_parent not in ports_map or goal_parent not in ports_map:
            raise PlanningFailedError("start or goal parent has no passable cells.")
        if start_parent == goal_parent:
            return [start_parent]
        return self._search_parent_graph(ports_map, start_parent, goal_parent)

    def _extract_corridor(
        self,
        graph: H3Graph,
        macro_route: list[str],
        dilation: int = 1,
    ) -> set[str]:
        """Return passable cells in the parent route plus a parent-neighbor shell."""
        if dilation < 0:
            raise ValueError("dilation must be non-negative.")
        if not macro_route:
            raise PlanningFailedError("macro_route must be non-empty.")
        parent_route = self._normalize_parent_route(graph, macro_route)
        allowed_parents = self._dilate_parent_route(graph, parent_route, dilation)
        corridor = {
            cell_id
            for cell_id, cell in graph.cells.items()
            if cell.is_passable and self._parent_id(graph, cell_id) in allowed_parents
        }
        if not corridor:
            raise PlanningFailedError("macro route produced an empty passable corridor.")
        return corridor

    def _corridor_astar(
        self,
        graph: H3Graph,
        corridor: set[str],
        start: str,
        goal: str,
    ) -> Path:
        if start not in corridor or goal not in corridor:
            raise PlanningFailedError("start and goal must be inside the corridor.")
        came_from, g_score = self._search(graph, corridor, start, goal)
        if goal not in g_score or not isfinite(g_score[goal]):
            raise PlanningFailedError(f"no finite path from {start!r} to {goal!r}.")
        return Path(cells=_reconstruct_path(came_from, start, goal), total_cost=g_score[goal])

    def _search(
        self,
        graph: H3Graph,
        corridor: set[str],
        start: str,
        goal: str,
    ) -> tuple[dict[str, str], dict[str, float]]:
        open_heap: list[tuple[float, str]] = [(self._heuristic(graph, start, goal), start)]
        came_from: dict[str, str] = {}
        g_score: dict[str, float] = {start: 0.0}
        while open_heap:
            _, current = heappop(open_heap)
            if current == goal:
                return came_from, g_score
            self._expand_node(graph, corridor, goal, current, came_from, g_score, open_heap)
        return came_from, g_score

    def _expand_node(
        self,
        graph: H3Graph,
        corridor: set[str],
        goal: str,
        current: str,
        came_from: dict[str, str],
        g_score: dict[str, float],
        open_heap: list[tuple[float, str]],
    ) -> None:
        for neighbor in self._neighbors(graph, current):
            if neighbor not in corridor:
                continue
            step_cost = self.cost_function.compute(graph, current, neighbor)
            tentative = g_score[current] + step_cost
            if not isfinite(step_cost) or tentative >= g_score.get(neighbor, inf):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            heappush(open_heap, (tentative + self._heuristic(graph, neighbor, goal), neighbor))

    def _neighbors(self, graph: H3Graph, cell_id: str) -> list[str]:
        """Return deterministic fine-cell neighbors present in graph edges."""
        neighbors: list[str] = []
        for edge_key in graph.edges:
            if edge_key[0] == cell_id:
                neighbors.append(edge_key[1])
            elif edge_key[1] == cell_id:
                neighbors.append(edge_key[0])
        return sorted(set(neighbors))

    def _parent_id(self, graph: H3Graph, cell_id: str) -> str:
        """Return a cell parent, preserving compatibility with synthetic graphs."""
        parent_h3 = graph.cells[cell_id].parent_h3
        return parent_h3 if parent_h3 else cell_id

    def _edge_is_passable(self, graph: H3Graph, cell_a: str, cell_b: str) -> bool:
        """Check that both endpoints of a candidate Port edge are passable."""
        return graph.cells[cell_a].is_passable and graph.cells[cell_b].is_passable

    def _search_parent_graph(
        self,
        ports_map: dict[str, dict[str, float]],
        start_parent: str,
        goal_parent: str,
    ) -> list[str]:
        """Run deterministic Dijkstra search over accumulated parent-edge weights."""
        open_heap: list[tuple[float, str]] = [(0.0, start_parent)]
        came_from: dict[str, str] = {}
        g_score: dict[str, float] = {start_parent: 0.0}
        while open_heap:
            current_cost, current = heappop(open_heap)
            if current_cost != g_score.get(current):
                continue
            if current == goal_parent:
                return _reconstruct_path(came_from, start_parent, goal_parent)
            for neighbor, edge_cost in sorted(ports_map[current].items()):
                tentative = current_cost + edge_cost
                if tentative >= g_score.get(neighbor, inf):
                    continue
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                heappush(open_heap, (tentative, neighbor))
        raise PlanningFailedError(
            f"no passable parent route from {start_parent!r} to {goal_parent!r}."
        )

    def _normalize_parent_route(self, graph: H3Graph, macro_route: list[str]) -> set[str]:
        """Normalize old fine-cell route inputs and new parent-route inputs."""
        return {
            self._parent_id(graph, route_node) if route_node in graph.cells else route_node
            for route_node in macro_route
        }

    def _dilate_parent_route(
        self,
        graph: H3Graph,
        parent_route: set[str],
        dilation: int,
    ) -> set[str]:
        """Expand a parent route by graph-derived parent adjacency rings."""
        allowed_parents = set(parent_route)
        frontier = set(parent_route)
        ports_map = self._build_ports_map(graph)
        for _ in range(dilation):
            frontier = {
                neighbor
                for parent in frontier
                for neighbor in ports_map.get(parent, {})
                if neighbor not in allowed_parents
            }
            if not frontier:
                break
            allowed_parents.update(frontier)
        return allowed_parents

    def _record_boundary_cost(
        self,
        ports_map: dict[str, dict[str, float]],
        graph: H3Graph,
        source_parent: str,
        target_parent: str,
        source_cell: str,
        target_cell: str,
    ) -> None:
        """Keep the lowest finite directional cost among parent-boundary crossings."""
        cost = self.cost_function.compute(graph, source_cell, target_cell)
        if not isfinite(cost):
            return
        previous = ports_map[source_parent].get(target_parent, inf)
        ports_map[source_parent][target_parent] = min(previous, cost)

    def _heuristic(self, graph: H3Graph, cell_a: str, cell_b: str) -> float:
        first = graph.cells[cell_a]
        second = graph.cells[cell_b]
        return sqrt((first.lat - second.lat) ** 2 + (first.lng - second.lng) ** 2)


def _reconstruct_path(came_from: dict[str, str], start: str, goal: str) -> list[str]:
    current = goal
    path = [current]
    while current != start:
        if current not in came_from:
            raise PlanningFailedError(f"cannot reconstruct path from {start!r} to {goal!r}.")
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
