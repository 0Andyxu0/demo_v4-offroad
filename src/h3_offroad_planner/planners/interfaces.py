"""Planner interface contracts for global and local planning."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3_offroad_planner.models import H3Graph, Path, PlannerInput, PlannerOutput

__all__ = ["GlobalPlanner", "LocalReplanner"]


class GlobalPlanner(ABC):
    """Abstract global planner interface."""

    @abstractmethod
    def plan(self, inp: PlannerInput) -> PlannerOutput:
        """Plan one or more paths for a validated planner input."""


class LocalReplanner(ABC):
    """Abstract local replanner interface."""

    @abstractmethod
    def replan(
        self,
        graph: H3Graph,
        blocked_cells: set[str],
        current_path: Path,
    ) -> Path:
        """Replan around the currently confirmed impassable cells."""

