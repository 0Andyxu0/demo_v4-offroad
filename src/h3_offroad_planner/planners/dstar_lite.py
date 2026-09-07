"""Incremental D* Lite local replanning for in-memory H3-style graphs."""

from __future__ import annotations

from heapq import heappop, heappush
from math import inf, isfinite
from typing import Protocol

from h3_offroad_planner.models import H3Graph, Path, PlanningFailedError
from h3_offroad_planner.planners.interfaces import LocalReplanner

__all__ = ["DStarLiteReplanner", "MovementCost"]

Key = tuple[float, float]


class MovementCost(Protocol):
    """Minimal directed movement-cost interface required by D* Lite."""

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Return finite non-negative cost or infinity for an unavailable edge."""

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Return a finite admissible estimate in the same unit as movement cost."""


class DStarLiteReplanner(LocalReplanner):
    """Incrementally repair a reverse shortest-path tree after cell blockages."""

    def __init__(self, cost_function: MovementCost) -> None:
        """Initialize an empty D* Lite state for one compatible graph and goal."""
        self.cost_function = cost_function
        self._g: dict[str, float] = {}
        self._rhs: dict[str, float] = {}
        self._queue: list[tuple[float, float, str]] = []
        self._queued_keys: dict[str, Key] = {}
        self._start: str | None = None
        self._goal: str | None = None
        self._km: float = 0.0

    @property
    def rhs(self) -> dict[str, float]:
        """Expose a copy of reverse one-step values for validation."""
        return dict(self._rhs)

    @property
    def g(self) -> dict[str, float]:
        """Expose a copy of reverse path values for validation."""
        return dict(self._g)

    def initialize(self, graph: H3Graph, start: str, goal: str) -> None:
        """Initialize reverse D* Lite state with `rhs[goal] == 0`.

        Raises:
            PlanningFailedError: If either endpoint is absent from the graph.
        """
        if start not in graph.cells or goal not in graph.cells:
            raise PlanningFailedError("start and goal must exist before D* Lite initialization.")
        self._start = start
        self._goal = goal
        self._g = dict.fromkeys(graph.cells, inf)
        self._rhs = dict.fromkeys(graph.cells, inf)
        self._rhs[goal] = 0.0
        self._queue = []
        self._queued_keys = {}
        self._km = 0.0
        self._push(goal, graph)

    def replan(
        self,
        graph: H3Graph,
        blocked_cells: set[str],
        current_path: Path,
    ) -> Path:
        """Incrementally repair the path after newly blocked cells.

        The lifecycle controller resolves timestamps and confirmation state before this
        call; the graph-level planner receives only confirmed impassable cell ids.
        """
        if not current_path.cells:
            raise PlanningFailedError("current_path must be non-empty.")
        start, goal = current_path.cells[0], current_path.cells[-1]
        if self._goal != goal or self._start is None or set(self._g) != set(graph.cells):
            self.initialize(graph, start, goal)
        else:
            self._move_start(graph, start)
        affected = _mark_unpassable(graph, blocked_cells)
        self._repair_affected_vertices(graph, affected)
        self._compute_shortest_path(graph)
        return self._extract_path(graph)

    def _move_start(self, graph: H3Graph, start: str) -> None:
        """Apply D* Lite's key shift when the vehicle advances along a path."""
        if self._start is None:
            raise PlanningFailedError("D* Lite start is not initialized.")
        self._km += self.cost_function.heuristic(graph, self._start, start)
        self._start = start

    def _repair_affected_vertices(self, graph: H3Graph, affected: set[str]) -> None:
        """Update changed cells and predecessors after obstacle-state changes."""
        for cell_id in affected:
            self._update_vertex(graph, cell_id)
            for neighbor in _neighbors(graph, cell_id):
                self._update_vertex(graph, neighbor)

    def _compute_shortest_path(self, graph: H3Graph) -> None:
        """Repair inconsistent reverse values until the current start is consistent."""
        if self._start is None:
            raise PlanningFailedError("D* Lite start is not initialized.")
        while self._top_key() < self._calculate_key(graph, self._start) or (
            self._rhs[self._start] != self._g[self._start]
        ):
            popped = self._pop()
            if popped is None:
                break
            old_key, cell_id = popped
            new_key = self._calculate_key(graph, cell_id)
            if old_key < new_key:
                self._push(cell_id, graph)
            elif self._g[cell_id] > self._rhs[cell_id]:
                self._g[cell_id] = self._rhs[cell_id]
                for predecessor in _neighbors(graph, cell_id):
                    self._update_vertex(graph, predecessor)
            else:
                self._g[cell_id] = inf
                self._update_vertex(graph, cell_id)
                for predecessor in _neighbors(graph, cell_id):
                    self._update_vertex(graph, predecessor)

    def _update_vertex(self, graph: H3Graph, cell_id: str) -> None:
        """Refresh one reverse one-step value and its lazy priority-queue entry."""
        if cell_id not in graph.cells:
            raise PlanningFailedError(f"cell={cell_id!r} is not present in graph.")
        if cell_id != self._goal:
            self._rhs[cell_id] = min(
                (
                    self.cost_function.compute(graph, cell_id, neighbor) + self._g[neighbor]
                    for neighbor in _neighbors(graph, cell_id)
                ),
                default=inf,
            )
        self._queued_keys.pop(cell_id, None)
        if self._g[cell_id] != self._rhs[cell_id]:
            self._push(cell_id, graph)

    def _extract_path(self, graph: H3Graph) -> Path:
        """Follow minimum `cost + g` successors from the current start to the goal."""
        if self._start is None or self._goal is None or not isfinite(self._g[self._start]):
            raise PlanningFailedError("no finite local D* Lite path exists.")
        cells = [self._start]
        total_cost = 0.0
        while cells[-1] != self._goal:
            current = cells[-1]
            options = [
                (self.cost_function.compute(graph, current, neighbor) + self._g[neighbor], neighbor)
                for neighbor in _neighbors(graph, current)
            ]
            finite_options = [(cost, neighbor) for cost, neighbor in options if isfinite(cost)]
            if not finite_options:
                raise PlanningFailedError("D* Lite cannot extract a finite successor.")
            step_value, next_cell = min(finite_options)
            if next_cell in cells:
                raise PlanningFailedError("D* Lite extraction encountered a cycle.")
            total_cost += self.cost_function.compute(graph, current, next_cell)
            cells.append(next_cell)
            if len(cells) > len(graph.cells):
                raise PlanningFailedError("D* Lite extraction exceeded graph cell count.")
        return Path(cells=cells, total_cost=total_cost)

    def _calculate_key(self, graph: H3Graph, cell_id: str) -> Key:
        """Compute the lexicographic D* Lite key for one graph cell."""
        if self._start is None:
            raise PlanningFailedError("D* Lite start is not initialized.")
        value = min(self._g[cell_id], self._rhs[cell_id])
        heuristic = self.cost_function.heuristic(graph, self._start, cell_id)
        return (value + heuristic + self._km, value)

    def _push(self, cell_id: str, graph: H3Graph) -> None:
        """Add or replace a lazy priority-queue entry for one inconsistent cell."""
        key = self._calculate_key(graph, cell_id)
        self._queued_keys[cell_id] = key
        heappush(self._queue, (key[0], key[1], cell_id))

    def _pop(self) -> tuple[Key, str] | None:
        """Pop the next non-stale D* Lite queue entry."""
        while self._queue:
            first, second, cell_id = heappop(self._queue)
            key = (first, second)
            if self._queued_keys.get(cell_id) == key:
                del self._queued_keys[cell_id]
                return key, cell_id
        return None

    def _top_key(self) -> Key:
        """Return the next non-stale key without removing its valid entry."""
        while self._queue:
            first, second, cell_id = self._queue[0]
            if self._queued_keys.get(cell_id) == (first, second):
                return first, second
            heappop(self._queue)
        return inf, inf


def _mark_unpassable(graph: H3Graph, blocked: set[str]) -> set[str]:
    """Mark known obstacle cells impassable and return their changed identifiers."""
    changed: set[str] = set()
    for cell_id in blocked:
        if cell_id in graph.cells and graph.cells[cell_id].is_passable:
            graph.cells[cell_id].is_passable = False
            changed.add(cell_id)
    return changed


def _neighbors(graph: H3Graph, cell_id: str) -> list[str]:
    """Return deterministic graph neighbors for reverse D* Lite updates."""
    neighbors = [
        edge.cell_b if edge.cell_a == cell_id else edge.cell_a
        for edge in graph.edges.values()
        if edge.cell_a == cell_id or edge.cell_b == cell_id
    ]
    return sorted(set(neighbors))
