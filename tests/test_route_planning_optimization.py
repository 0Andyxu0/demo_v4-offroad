"""Bounded retry checks for routing-index RoutePlan orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from h3_offroad_planner import route_planning
from h3_offroad_planner.models import PlanningFailedError, RouteRequest


def test_indexed_plan_retries_once_with_two_ring_corridor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls: list[tuple[int, str | None]] = []
    expected = object()

    def run_once(*args: object, **kwargs: object) -> object:
        ring = kwargs["corridor_ring"]
        warning = kwargs.get("extra_warning")
        assert isinstance(ring, int)
        assert warning is None or isinstance(warning, str)
        calls.append((ring, warning))
        if ring == 1:
            raise PlanningFailedError("narrow corridor")
        return expected

    monkeypatch.setattr(route_planning, "_run_route_plan_once", run_once)
    monkeypatch.setattr(route_planning, "_routing_index_available", lambda _path: True)

    assert route_planning.run_route_plan(request) is expected
    assert calls == [(1, None), (2, "CORRIDOR_EXPANDED_TO_2_RING")]


def test_indexed_plan_never_expands_beyond_two_rings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls: list[int] = []

    def fail(*args: object, **kwargs: object) -> object:
        ring = kwargs["corridor_ring"]
        assert isinstance(ring, int)
        calls.append(ring)
        raise PlanningFailedError(f"ring {ring} failed")

    monkeypatch.setattr(route_planning, "_run_route_plan_once", fail)
    monkeypatch.setattr(route_planning, "_routing_index_available", lambda _path: True)

    with pytest.raises(PlanningFailedError, match="ring 2 failed"):
        route_planning.run_route_plan(request)
    assert calls == [1, 2]


def _request(tmp_path: Path) -> RouteRequest:
    return RouteRequest(
        input_mode="coordinates",
        parquet_path=str(tmp_path / "routing_index" / "current.json"),
        planner_config_path=str(tmp_path / "planner.yaml"),
        vehicle_path=str(tmp_path / "vehicle.yaml"),
        factor_model_path=str(tmp_path / "factor.yaml"),
        output_dir=str(tmp_path / "output"),
        start_lat=31.99,
        start_lng=118.99,
        goal_lat=32.00,
        goal_lng=119.00,
    )
