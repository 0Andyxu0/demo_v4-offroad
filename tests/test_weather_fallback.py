"""Tests for precipitation-based environment pressure fallback."""

from __future__ import annotations

import pytest

from h3_offroad_planner.weather_fallback import (
    precipitation_pressure,
    resolve_precipitation_fallback,
)


def test_precipitation_pressure_clamps_to_one() -> None:
    assert precipitation_pressure(10.0, 5.0) == 1.0
    assert precipitation_pressure(0.0, 5.0) == 0.0
    assert precipitation_pressure(2.5, 10.0) == pytest.approx(0.25)


def test_resolve_precipitation_fallback_returns_pressure_and_basis() -> None:
    pressure, basis, warnings = resolve_precipitation_fallback(
        {"degraded": False, "precipitation_24h_mm": 5.0}, 10.0
    )

    assert pressure == 0.5
    assert basis == "precipitation_apiv1"
    assert warnings == ("ENVIRONMENT_PRESSURE_PRECIPITATION_PROVISIONAL",)


def test_resolve_precipitation_fallback_handles_degraded_snapshot() -> None:
    pressure, basis, warnings = resolve_precipitation_fallback(
        {"degraded": True, "precipitation_24h_mm": 5.0}, 10.0
    )

    assert pressure is None
    assert basis is None
    assert warnings == ("ENVIRONMENT_DATA_DEGRADED",)


def test_resolve_precipitation_fallback_requires_reference() -> None:
    pressure, basis, warnings = resolve_precipitation_fallback(
        {"degraded": False, "precipitation_24h_mm": 5.0}, None
    )

    assert pressure is None
    assert basis is None
    assert warnings == ("ENVIRONMENT_PRESSURE_UNCALIBRATED",)
