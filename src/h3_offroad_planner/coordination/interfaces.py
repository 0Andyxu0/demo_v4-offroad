"""Future fleet-coordination interface without any implemented multi-vehicle behavior."""

from __future__ import annotations

from typing import Protocol

from h3_offroad_planner.models import FleetPlan, FleetPlanningInput

__all__ = ["FleetCoordinator"]


class FleetCoordinator(Protocol):
    """Abstract boundary reserved for a future multi-vehicle coordinator."""

    def coordinate(self, planning_input: FleetPlanningInput) -> FleetPlan:
        """Coordinate fleet tasks; no concrete implementation ships in this release."""
