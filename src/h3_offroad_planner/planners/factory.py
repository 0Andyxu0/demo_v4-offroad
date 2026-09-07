"""Configuration-driven planner factory for MVP-1."""

from __future__ import annotations

from typing import cast

from h3_offroad_planner.dynamics.cost_function import CostFunction
from h3_offroad_planner.models import ConfigError, VehicleProfile
from h3_offroad_planner.planners.dstar_lite import DStarLiteReplanner
from h3_offroad_planner.planners.facade import PathPlannerFacade
from h3_offroad_planner.planners.h3_astar import H3AStarPlanner

__all__ = ["PlannerFactory"]

GLOBAL_PLANNERS: frozenset[str] = frozenset({"H3AStar"})
RETIRED_GLOBAL_PLANNERS: frozenset[str] = frozenset(
    {"LegacyDeterministicParetoPlanner", "NSGAIIPlanner", "NSGAII"}
)
LOCAL_REPLANNERS: frozenset[str] = frozenset({"DStarLite"})


class PlannerFactory:
    """Build a `PathPlannerFacade` from validated configuration."""

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> PathPlannerFacade:
        """Create the configured global/local planner pair.

        Args:
            cfg: Configuration mapping with planner names, cost mapping, and `_vehicle`.

        Returns:
            Configured facade.

        Raises:
            ConfigError: If a planner name is unknown or `_vehicle` is missing.
        """
        vehicle = _vehicle_from_config(cfg)
        cost_cfg = _cost_mapping(cfg)
        cost_function = CostFunction(
            vehicle=vehicle,
            k_r=_float_from_mapping(cost_cfg, "tri_coefficient", 0.1),
            gravity_coeff=_float_from_mapping(cost_cfg, "gravity_coefficient", 5.0),
            score_coefficient=_float_from_mapping(cost_cfg, "score_coefficient", 0.0),
        )
        global_planner = _build_global(str(cfg["global_planner"]), cost_function)
        local_replanner = _build_local(str(cfg["local_replanner"]), cost_function)
        return PathPlannerFacade(global_planner, local_replanner)


def _vehicle_from_config(cfg: dict[str, object]) -> VehicleProfile:
    vehicle = cfg.get("_vehicle")
    if not isinstance(vehicle, VehicleProfile):
        raise ConfigError("configuration must include '_vehicle' as a VehicleProfile.")
    return vehicle


def _cost_mapping(cfg: dict[str, object]) -> dict[str, object]:
    cost_cfg = cfg.get("cost")
    if not isinstance(cost_cfg, dict):
        raise ConfigError("configuration key 'cost' must be a mapping.")
    return cast(dict[str, object], cost_cfg)


def _float_from_mapping(
    mapping: dict[str, object],
    key: str,
    default: float,
    label: str = "cost",
) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{label}.{key} must be numeric, got {type(value).__name__}.")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{label}.{key} must be numeric, got {value!r}.") from exc


def _build_global(
    name: str,
    cost_function: CostFunction,
) -> H3AStarPlanner:
    if name in RETIRED_GLOBAL_PLANNERS:
        raise ConfigError(
            f"retired global planner {name!r} is unsupported; "
            "use the RoutePlan DeterministicParetoPlanner entrypoint"
        )
    if name not in GLOBAL_PLANNERS:
        raise ConfigError(f"unknown global planner: {name}")
    return H3AStarPlanner(cost_function)


def _build_local(name: str, cost_function: CostFunction) -> DStarLiteReplanner:
    if name not in LOCAL_REPLANNERS:
        raise ConfigError(f"unknown local replanner: {name}")
    return DStarLiteReplanner(cost_function)
