"""Regression tests for the softened routing-index role gate."""

from __future__ import annotations

import pytest

from h3_offroad_planner import route_planning
from h3_offroad_planner.models import PlanningFailedError


def test_routing_role_gate_allows_missing_independent_backup_with_warning() -> None:
    assigned = {
        "fastest_eta",
        "shortest_distance",
        "max_passability_margin",
        "minimum_travel_cost",
    }

    warnings = route_planning._routing_role_warnings(assigned)

    assert warnings == ("INDEPENDENT_BACKUP_UNAVAILABLE",)


def test_routing_role_gate_still_rejects_missing_core_role() -> None:
    assigned = {
        "fastest_eta",
        "shortest_distance",
        "max_passability_margin",
    }

    with pytest.raises(PlanningFailedError, match="ROUTING_INDEX_ROLE_COVERAGE_INSUFFICIENT"):
        route_planning._routing_role_warnings(assigned)
