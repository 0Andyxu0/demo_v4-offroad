"""Facade orchestration for global planning and local replan fallback."""

from __future__ import annotations

from h3_offroad_planner.models import (
    H3Graph,
    Path,
    PlannerInput,
    PlannerOutput,
    PlanningFailedError,
)
from h3_offroad_planner.planners.interfaces import GlobalPlanner, LocalReplanner

__all__ = ["PathPlannerFacade"]


class PathPlannerFacade:
    """Orchestrate global planning and local blockage handling."""

    def __init__(self, global_planner: GlobalPlanner, local_replanner: LocalReplanner) -> None:
        """Initialize the facade with decoupled planner implementations."""
        self._global = global_planner
        self._local = local_replanner
        self._last_input: PlannerInput | None = None

    def plan(self, inp: PlannerInput) -> PlannerOutput:
        """Run global planning and cache the request for future fallback."""
        self._last_input = inp
        return self._global.plan(inp)

    def on_blockage(
        self,
        graph: H3Graph,
        blocked_cells: set[str],
        current_path: Path,
    ) -> Path:
        """Handle sudden blockage by local replan, then global fallback."""
        try:
            return self._local.replan(graph, blocked_cells, current_path)
        except PlanningFailedError:
            return self._global_fallback(graph, blocked_cells, current_path)

    def _global_fallback(
        self,
        graph: H3Graph,
        blocked_cells: set[str],
        current_path: Path,
    ) -> Path:
        if self._last_input is None:
            raise PlanningFailedError("no cached global planning input is available for fallback.")
        for cell_id in blocked_cells:
            if cell_id in graph.cells:
                graph.cells[cell_id].is_passable = False
        fallback_input = PlannerInput(
            graph=graph,
            start=current_path.cells[0],
            goal=self._last_input.goal,
            vehicle=self._last_input.vehicle,
            objectives=self._last_input.objectives,
        )
        result = self._global.plan(fallback_input)
        if not result.paths:
            raise PlanningFailedError("global fallback produced no path.")
        return result.paths[0]
