"""Tests for precipitation-based environment pressure fallback."""

from __future__ import annotations

import pytest

from h3_offroad_planner import environment as environment_module
from h3_offroad_planner.environment import EnvironmentSnapshot
from h3_offroad_planner.factor_model import EnvironmentConfig, WeatherConfig
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


class _FakeProvider:
    def __init__(self, snapshot: EnvironmentSnapshot) -> None:
        self._snapshot = snapshot

    def fetch(self, _latitude: float, _longitude: float) -> EnvironmentSnapshot:
        return self._snapshot


def test_resolve_request_environment_uses_precipitation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = EnvironmentSnapshot(
        provider="open-meteo",
        model="best_match",
        requested_at="2026-09-17T00:00:00+00:00",
        valid_at="2026-09-17T00:00:00+00:00",
        latitude=31.99,
        longitude=118.99,
        precipitation_24h_mm=5.0,
        soil_moisture_surface_m3_m3=None,
        et0_24h_mm=1.0,
        age_s=60.0,
        degraded=False,
    )
    monkeypatch.setattr(environment_module, "_provider", lambda _config: _FakeProvider(snapshot))

    resolved, payload, _, warnings = environment_module.resolve_request_environment(
        EnvironmentConfig(),
        WeatherConfig(enabled=True, api_reference_mm=10.0),
        31.99,
        118.99,
    )

    assert payload["derived_pressure"] == pytest.approx(0.5)
    assert resolved.pressure_basis == "precipitation_apiv1"
    assert resolved.request_pressures == (0.5,)
    assert "ENVIRONMENT_PRESSURE_PRECIPITATION_PROVISIONAL" in warnings
