"""Bounded retry checks for routing-index RoutePlan orchestration."""

from __future__ import annotations

from pathlib import Path

import h3
import pandas as pd
import pytest

from h3_offroad_planner import route_planning
from h3_offroad_planner.models import PlanningFailedError, RouteEndpoint, RouteRequest
from h3_offroad_planner.routing import _coarse_skeletons
from h3_offroad_planner.routing_index import RoutingIndex


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


def test_coarse_widest_over_detour_limit_is_not_loaded(tmp_path: Path) -> None:
    start = h3.latlng_to_cell(31.99, 118.99, 11)
    goal = h3.latlng_to_cell(32.00, 119.00, 11)
    rows = [
        _coarse_row(start, "short", 0.2),
        _coarse_row("short", goal, 0.2),
        _coarse_row(start, "long-1", 0.9),
        _coarse_row("long-1", "long-2", 0.9),
        _coarse_row("long-2", "long-3", 0.9),
        _coarse_row("long-3", goal, 0.9),
    ]
    index = RoutingIndex(
        pointer_path=tmp_path / "current.json",
        build_dir=tmp_path,
        manifest={"build_id": "test", "res_coarse": 11},
        coarse_graph=pd.DataFrame(rows),
    )
    start_lat, start_lng = h3.cell_to_latlng(start)
    goal_lat, goal_lng = h3.cell_to_latlng(goal)

    skeletons, diagnostics = _coarse_skeletons(
        index,
        RouteEndpoint("start", start_lat, start_lng),
        RouteEndpoint("goal", goal_lat, goal_lng),
        max_widest_detour_ratio=0.15,
    )

    assert skeletons["widest"] == []
    assert diagnostics["coarse_widest_included"] is False
    assert diagnostics["coarse_widest_parent_count"] == 5


def _coarse_row(parent_a: str, parent_b: str, passable: float) -> dict[str, object]:
    return {
        "parent_a": parent_a,
        "parent_b": parent_b,
        "distance_m": 1.0,
        "slope_mean": 0.0,
        "tri_mean": 0.0,
        "road_fraction": 0.0,
        "passable_fraction": passable,
        "environment_proxy": 0.0,
    }


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
