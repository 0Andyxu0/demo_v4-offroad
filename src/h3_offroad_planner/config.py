"""Configuration loading helpers for MVP-1 planner wiring."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from h3_offroad_planner.models import ConfigError, VehicleProfile

__all__ = ["load_config", "load_vehicle"]

REQUIRED_CONFIG_KEYS: frozenset[str] = frozenset({"cost", "global_planner", "local_replanner"})
REQUIRED_VEHICLE_KEYS: frozenset[str] = frozenset(
    {
        "ground_clearance_m",
        "mass_kg",
        "max_climb_angle_deg",
        "max_speed_kmh",
        "max_thrust_n",
        "min_turn_radius_m",
        "name",
        "tire_radius_m",
        "tire_width_m",
    }
)


def _load_yaml_mapping(path: str) -> dict[str, object]:
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigError(f"configuration file does not exist: {path}")
    with file_path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream)
    if not isinstance(loaded, dict):
        raise ConfigError(f"configuration file must contain a mapping: {path}")
    return cast(dict[str, object], loaded)


def load_config(path: str) -> dict[str, object]:
    """Load and validate planner configuration from a YAML file.

    Args:
        path: YAML file path. Unit: filesystem path. Must exist and contain a mapping
            with `global_planner`, `local_replanner`, and `cost`.

    Returns:
        Validated configuration dictionary.

    Raises:
        ConfigError: If the file is missing, malformed, or lacks required keys.
    """
    data = _load_yaml_mapping(path)
    missing = REQUIRED_CONFIG_KEYS.difference(data)
    if missing:
        raise ConfigError(f"configuration is missing required keys: {sorted(missing)}")
    if not isinstance(data["cost"], dict):
        raise ConfigError("configuration key 'cost' must be a mapping.")
    return data


def load_vehicle(path: str) -> VehicleProfile:
    """Load and validate a vehicle profile from a YAML file.

    Args:
        path: YAML file path. Unit: filesystem path. Must contain all
            `VehicleProfile` fields.

    Returns:
        Validated vehicle profile.

    Raises:
        ConfigError: If the file is missing, malformed, or lacks vehicle fields.
        ValueError: If vehicle physical ranges are invalid.
    """
    data = _load_yaml_mapping(path)
    missing = REQUIRED_VEHICLE_KEYS.difference(data)
    if missing:
        raise ConfigError(f"vehicle profile is missing required keys: {sorted(missing)}")
    return VehicleProfile(
        name=str(data["name"]),
        mass_kg=float(cast(float, data["mass_kg"])),
        max_climb_angle_deg=float(cast(float, data["max_climb_angle_deg"])),
        max_speed_kmh=float(cast(float, data["max_speed_kmh"])),
        tire_width_m=float(cast(float, data["tire_width_m"])),
        ground_clearance_m=float(cast(float, data["ground_clearance_m"])),
        max_thrust_n=float(cast(float, data["max_thrust_n"])),
        tire_radius_m=float(cast(float, data["tire_radius_m"])),
        min_turn_radius_m=float(cast(float, data["min_turn_radius_m"])),
    )

