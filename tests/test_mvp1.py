"""Spec-derived tests for Phase 3 MVP-1 behavior."""

from __future__ import annotations

from pathlib import Path

import h3
import pytest

from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.dynamics import CostFunction, LOSPathSmoother
from h3_offroad_planner.models import (
    ConfigError,
    H3Cell,
    H3Edge,
    H3Graph,
    PlannerInput,
    PlanningFailedError,
    VehicleProfile,
)
from h3_offroad_planner.models import (
    Path as PlannerPath,
)
from h3_offroad_planner.planners import (
    DStarLiteReplanner,
    H3AStarPlanner,
    LocalReplanner,
    PathPlannerFacade,
    PlannerFactory,
)
from tests.conftest import make_grid_graph


def test_t010_astar_returns_finite_path(vehicle: VehicleProfile) -> None:
    """T-010: A* returns a finite path on a 20x20 in-memory graph."""
    graph = make_grid_graph(20, 20)
    planner = H3AStarPlanner(CostFunction(vehicle))
    result = planner.plan(PlannerInput(graph=graph, start="0,0", goal="19,19", vehicle=vehicle))

    assert result.paths
    assert result.paths[0].total_cost < float("inf")
    assert result.paths[0].cells[0] == "0,0"
    assert result.paths[0].cells[-1] == "19,19"


def test_t013_dstar_initialize_sets_rhs_goal(vehicle: VehicleProfile) -> None:
    """T-013: D* Lite initialization sets rhs[goal] to zero and g to infinity."""
    graph = make_grid_graph(3, 3)
    replanner = DStarLiteReplanner(CostFunction(vehicle))

    replanner.initialize(graph, "0,0", "2,2")

    assert replanner.rhs["2,2"] == 0.0
    assert replanner.g["0,0"] == float("inf")


def test_t014_replan_avoids_blocked_cell(vehicle: VehicleProfile) -> None:
    """T-014: Replan excludes the blocked cell from the new path."""
    graph = make_grid_graph(5, 3)
    current_path = PlannerPath(cells=["0,1", "1,1", "2,1", "3,1", "4,1"], total_cost=4.0)
    replanner = DStarLiteReplanner(CostFunction(vehicle))

    new_path = replanner.replan(graph, {"2,1"}, current_path)

    assert "2,1" not in new_path.cells
    assert new_path.cells[0] == "0,1"
    assert new_path.cells[-1] == "4,1"


class FailingLocalReplanner(LocalReplanner):
    """Test double that forces facade fallback without adding production API."""

    def replan(
        self,
        graph: H3Graph,
        blocked_cells: set[str],
        current_path: PlannerPath,
    ) -> PlannerPath:
        """Always fail local replan to exercise global fallback."""
        del graph, blocked_cells, current_path
        raise PlanningFailedError("forced local failure")


def test_t015_facade_falls_back_to_global(vehicle: VehicleProfile) -> None:
    """T-015: Facade returns a global fallback path when local replan fails."""
    graph = make_grid_graph(5, 3)
    cost = CostFunction(vehicle)
    facade = PathPlannerFacade(H3AStarPlanner(cost), FailingLocalReplanner())
    result = facade.plan(PlannerInput(graph=graph, start="0,1", goal="4,1", vehicle=vehicle))

    fallback = facade.on_blockage(graph, {"2,1"}, result.paths[0])

    assert "2,1" not in fallback.cells
    assert fallback.cells[0] == "0,1"
    assert fallback.cells[-1] == "4,1"


def test_t016_facade_raises_when_global_fallback_has_no_path(vehicle: VehicleProfile) -> None:
    """T-016: Facade raises when local and global fallback cannot find a path."""
    graph = make_grid_graph(3, 1)
    cost = CostFunction(vehicle)
    facade = PathPlannerFacade(H3AStarPlanner(cost), FailingLocalReplanner())
    result = facade.plan(PlannerInput(graph=graph, start="0,0", goal="2,0", vehicle=vehicle))

    with pytest.raises(PlanningFailedError):
        facade.on_blockage(graph, {"1,0"}, result.paths[0])


def test_t017_los_smoothing_shortens_visible_path(vehicle: VehicleProfile) -> None:
    """T-017: LOS smoothing keeps endpoints and does not grow the path."""
    del vehicle
    graph = make_grid_graph(3, 1)
    smoother = LOSPathSmoother(graph)

    smoothed = smoother.smooth(["0,0", "1,0", "2,0"])

    assert smoothed == ["0,0", "2,0"]


def test_t018_los_smoothing_does_not_cross_obstacle(vehicle: VehicleProfile) -> None:
    """T-018: LOS smoothing keeps required nodes when direct LOS is blocked."""
    del vehicle
    graph = make_grid_graph(3, 1)
    graph.cells["1,0"].is_passable = False
    graph.edges.pop(("0,0", "2,0"), None)
    smoother = LOSPathSmoother(graph)

    smoothed = smoother.smooth(["0,0", "1,0", "2,0"])

    assert smoothed == ["0,0", "1,0", "2,0"]


def test_t101_los_smoothing_uses_real_h3_path(vehicle: VehicleProfile) -> None:
    """T-101: Real H3 indexes smooth without integer latitude/longitude assumptions."""
    del vehicle
    start = str(h3.latlng_to_cell(32.0, 118.0, 9))
    goal = next(
        str(cell)
        for cell in h3.grid_disk(start, 2)
        if h3.grid_distance(start, str(cell)) == 2
    )
    raw_path = [str(cell) for cell in h3.grid_path_cells(start, goal)]
    cells = {
        cell_id: _real_h3_cell(cell_id)
        for cell_id in raw_path
    }
    edges = {
        (first, second): H3Edge(first, second, 1.0)
        for first, second in zip(raw_path, raw_path[1:], strict=False)
    }
    graph = H3Graph(resolution_fine=9, resolution_coarse=8, cells=cells, edges=edges)
    smoother = LOSPathSmoother(graph)

    assert smoother.smooth(raw_path) == [start, goal]


def test_t102_dstar_repairs_reverse_values_incrementally(vehicle: VehicleProfile) -> None:
    """T-102: D* Lite repairs g/rhs after a second blockage without global A*."""
    graph = make_grid_graph(5, 3)
    replanner = DStarLiteReplanner(CostFunction(vehicle))
    replanner.initialize(graph, "0,1", "4,1")

    first = replanner.replan(graph, {"2,1"}, PlannerPath(["0,1", "4,1"], 4.0))
    second = replanner.replan(graph, {"2,0"}, PlannerPath(first.cells, first.total_cost))

    assert replanner.g["0,1"] < float("inf")
    assert "2,1" not in second.cells
    assert "2,0" not in second.cells


def _real_h3_cell(cell_id: str) -> H3Cell:
    """Create one passable model cell from a real H3 index for LOS validation."""
    lat, lng = h3.cell_to_latlng(cell_id)
    return H3Cell(
        h3index=cell_id,
        lat=float(lat),
        lng=float(lng),
        elevation=0.0,
        slope=0.0,
        tri=0.0,
        lc_factor=1.0,
        parent_h3=str(h3.cell_to_parent(cell_id, 8)),
    )


def test_t019_factory_rejects_unknown_planner(vehicle: VehicleProfile) -> None:
    """T-019: PlannerFactory rejects unregistered planner names."""
    cfg: dict[str, object] = {
        "_vehicle": vehicle,
        "cost": {},
        "global_planner": "Unknown",
        "local_replanner": "DStarLite",
    }

    with pytest.raises(ConfigError):
        PlannerFactory.from_config(cfg)


def test_t020_load_vehicle_requires_min_turn_radius(tmp_path: Path) -> None:
    """T-020: Vehicle YAML missing min_turn_radius_m is rejected."""
    vehicle_path = tmp_path / "vehicle.yaml"
    vehicle_path.write_text(
        "\n".join(
            [
                "name: truck",
                "mass_kg: 2000",
                "max_climb_angle_deg: 30",
                "max_speed_kmh: 80",
                "tire_width_m: 0.35",
                "ground_clearance_m: 0.4",
                "max_thrust_n: 8000",
                "tire_radius_m: 0.45",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_vehicle(str(vehicle_path))


def test_load_config_accepts_required_yaml(tmp_path: Path) -> None:
    """White-box support: load_config accepts the MVP planner YAML schema."""
    config_path = tmp_path / "planner.yaml"
    config_path.write_text(
        "global_planner: H3AStar\nlocal_replanner: DStarLite\ncost: {}\n",
        encoding="utf-8",
    )

    assert load_config(str(config_path))["global_planner"] == "H3AStar"


def test_load_config_rejects_missing_file() -> None:
    """White-box support: load_config rejects absent YAML paths."""
    with pytest.raises(ConfigError):
        load_config("missing-planner-config.yaml")


def test_factory_rejects_unknown_local_replanner(vehicle: VehicleProfile) -> None:
    """White-box support: PlannerFactory validates local replanner names."""
    cfg: dict[str, object] = {
        "_vehicle": vehicle,
        "cost": {},
        "global_planner": "H3AStar",
        "local_replanner": "Unknown",
    }

    with pytest.raises(ConfigError):
        PlannerFactory.from_config(cfg)


@pytest.mark.parametrize(
    "planner_name",
    ("LegacyDeterministicParetoPlanner", "NSGAIIPlanner", "NSGAII"),
)
def test_factory_rejects_retired_global_planners(
    vehicle: VehicleProfile,
    planner_name: str,
) -> None:
    """Removed Legacy and NSGA-II names fail instead of silently remapping."""
    cfg: dict[str, object] = {
        "_vehicle": vehicle,
        "cost": {},
        "global_planner": planner_name,
        "local_replanner": "DStarLite",
    }

    with pytest.raises(ConfigError, match="retired global planner"):
        PlannerFactory.from_config(cfg)


def test_los_to_latlng_rejects_missing_cell(vehicle: VehicleProfile) -> None:
    """White-box support: LOS coordinate conversion does not fabricate cells."""
    del vehicle
    graph = make_grid_graph(2, 1)
    smoother = LOSPathSmoother(graph)

    with pytest.raises(KeyError):
        smoother.to_latlng(["0,0", "missing"])


def test_t023_missing_edge_returns_infinity(vehicle: VehicleProfile) -> None:
    """T-023: Missing graph edge returns infinity instead of silently succeeding."""
    graph = make_grid_graph(2, 1)
    graph.edges.clear()
    cost = CostFunction(vehicle)

    assert cost.compute(graph, "0,0", "1,0") == float("inf")


def test_t024_directional_slope_over_limit_is_infinite(vehicle: VehicleProfile) -> None:
    """T-024: Directional uphill slope over vehicle limit is impossible."""
    graph = make_grid_graph(2, 1, high_barrier_column=0)
    cost = CostFunction(vehicle)

    assert cost.compute(graph, "0,0", "1,0") == float("inf")


def test_t025_downhill_has_no_uphill_gravity_penalty(vehicle: VehicleProfile) -> None:
    """T-025: Downhill direction does not receive uphill elevation penalty."""
    graph = make_grid_graph(2, 1, high_barrier_column=0)
    cost = CostFunction(vehicle, gravity_coeff=100.0)

    downhill_cost = cost.compute(graph, "1,0", "0,0")

    assert downhill_cost < 10.0
