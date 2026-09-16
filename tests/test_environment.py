"""Weather snapshot validation, caching, calibration, and fallback tests."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from urllib.error import URLError

import pytest

from h3_offroad_planner import environment as environment_module
from h3_offroad_planner.environment import EnvironmentSnapshot, OpenMeteoProvider
from h3_offroad_planner.factor_model import EnvironmentConfig, WeatherConfig


def _payload(*, moisture: float = 0.3, moisture_unit: str = "m³/m³") -> bytes:
    return json.dumps(
        {
            "hourly_units": {
                "precipitation": "mm",
                "soil_moisture_0_to_1cm": moisture_unit,
                "soil_moisture_1_to_3cm": moisture_unit,
                "soil_moisture_3_to_9cm": moisture_unit,
                "et0_fao_evapotranspiration": "mm",
            },
            "hourly": {
                "time": ["2026-09-15T09:00", "2026-09-16T07:00"],
                "precipitation": [1.5, 2.0],
                "soil_moisture_0_to_1cm": [0.2, moisture],
                "soil_moisture_1_to_3cm": [0.2, moisture],
                "soil_moisture_3_to_9cm": [0.2, moisture],
                "et0_fao_evapotranspiration": [0.1, 0.2],
            },
        }
    ).encode("utf-8")


def test_open_meteo_snapshot_is_validated_and_cached() -> None:
    calls: list[tuple[str, float]] = []
    clock = [10.0]

    def opener(url: str, *, timeout: float) -> io.BytesIO:
        calls.append((url, timeout))
        return io.BytesIO(_payload())

    provider = OpenMeteoProvider(
        WeatherConfig(enabled=True),
        opener=opener,
        now=lambda: datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        clock=lambda: clock[0],
    )

    first = provider.fetch(31.99, 118.99)
    second = provider.fetch(31.99, 118.99)

    assert len(calls) == 1
    assert calls[0][1] == 3.0
    assert first.degraded is False
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.precipitation_24h_mm == pytest.approx(3.5)
    assert first.soil_moisture_surface_m3_m3 == pytest.approx(0.3)
    assert first.et0_24h_mm == pytest.approx(0.3)
    assert first.age_s == pytest.approx(3600.0)


def test_open_meteo_failure_is_degraded_and_failure_cached() -> None:
    calls = 0

    def opener(_url: str, *, timeout: float) -> io.BytesIO:
        nonlocal calls
        calls += 1
        assert timeout == 3.0
        raise URLError("offline")

    provider = OpenMeteoProvider(
        WeatherConfig(enabled=True),
        opener=opener,
        now=lambda: datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        clock=lambda: 10.0,
    )

    first = provider.fetch(31.99, 118.99)
    second = provider.fetch(31.99, 118.99)

    assert calls == 1
    assert first.degraded is True
    assert "offline" in (first.degradation_reason or "")
    assert second.cache_hit is True


def test_open_meteo_rejects_unknown_units() -> None:
    provider = OpenMeteoProvider(
        WeatherConfig(enabled=True),
        opener=lambda *_args, **_kwargs: io.BytesIO(_payload(moisture_unit="percent")),
        now=lambda: datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
    )

    snapshot = provider.fetch(31.99, 118.99)

    assert snapshot.degraded is True
    assert "unit" in (snapshot.degradation_reason or "")


def test_open_meteo_applies_one_wall_clock_deadline() -> None:
    def opener(_url: str, *, timeout: float) -> io.BytesIO:
        Event().wait(timeout * 5.0)
        return io.BytesIO(_payload())

    provider = OpenMeteoProvider(
        WeatherConfig(enabled=True, timeout_s=0.02),
        opener=opener,
        now=lambda: datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
    )

    snapshot = provider.fetch(31.99, 118.99)

    assert snapshot.degraded is True
    assert "deadline" in (snapshot.degradation_reason or "")


@pytest.mark.parametrize(
    ("moisture", "expected"),
    [(0.1, 0.0), (0.3, 0.5), (0.5, 1.0), (0.8, 1.0)],
)
def test_calibrated_moisture_maps_to_bounded_pressure(
    moisture: float,
    expected: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(moisture)
    monkeypatch.setattr(
        environment_module,
        "_provider",
        lambda _config: _FakeProvider(snapshot),
    )

    resolved, payload, snapshot_hash, warnings = (
        environment_module.resolve_request_environment(
            EnvironmentConfig(),
            WeatherConfig(enabled=True, theta_dry=0.1, theta_wet=0.5),
            31.99,
            118.99,
        )
    )

    assert resolved.pressure_basis == "model_snapshot_v1"
    assert resolved.request_pressures == (expected,)
    assert expected in resolved.comparison_pressures
    assert payload["derived_pressure"] == expected
    assert len(snapshot_hash) == 64
    assert warnings == ()


def test_uncalibrated_snapshot_preserves_synthetic_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        environment_module,
        "_provider",
        lambda _config: _FakeProvider(_snapshot(0.3)),
    )
    original = EnvironmentConfig()

    resolved, payload, snapshot_hash, warnings = (
        environment_module.resolve_request_environment(
            original,
            WeatherConfig(enabled=True),
            31.99,
            118.99,
        )
    )

    assert resolved == original
    assert payload["soil_moisture_surface_m3_m3"] == pytest.approx(0.3)
    assert len(snapshot_hash) == 64
    assert warnings == ("ENVIRONMENT_PRESSURE_UNCALIBRATED",)


def test_provisional_calibration_is_explicitly_warned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        environment_module,
        "_provider",
        lambda _config: _FakeProvider(_snapshot(0.3)),
    )
    _, payload, _, warnings = environment_module.resolve_request_environment(
        EnvironmentConfig(),
        WeatherConfig(
            enabled=True,
            theta_dry=0.25,
            theta_wet=0.35,
            calibration_status="provisional_cldas_spatial_20260101",
        ),
        31.99,
        118.99,
    )

    assert payload["derived_pressure"] == pytest.approx(0.5)
    assert payload["calibration_status"] == "provisional_cldas_spatial_20260101"
    assert warnings == ("ENVIRONMENT_PRESSURE_PROVISIONAL",)


def test_saved_route_plan_snapshot_replays_identical_pressure_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        environment_module,
        "_provider",
        lambda _config: _FakeProvider(_snapshot(0.3)),
    )
    policy = WeatherConfig(enabled=True, theta_dry=0.1, theta_wet=0.5)
    original = environment_module.resolve_request_environment(
        EnvironmentConfig(), policy, 31.99, 118.99
    )
    replay = tmp_path / "route_plan.json"
    replay.write_text(
        json.dumps({"aggregation_stats": {"environment_snapshot": original[1]}}),
        encoding="utf-8",
    )

    restored = environment_module.resolve_request_environment(
        EnvironmentConfig(), policy, 31.99, 118.99, replay_path=str(replay)
    )

    assert restored == original
    with pytest.raises(ValueError, match="centroid"):
        environment_module.resolve_request_environment(
            EnvironmentConfig(), policy, 32.0, 118.99, replay_path=str(replay)
        )


def test_degraded_replay_never_applies_saved_moisture(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(0.3).to_dict()
    snapshot.update({"degraded": True, "degradation_reason": "stale weather"})
    replay = tmp_path / "degraded.json"
    replay.write_text(json.dumps(snapshot), encoding="utf-8")

    original = EnvironmentConfig()
    resolved, payload, _, warnings = environment_module.resolve_request_environment(
        original,
        WeatherConfig(theta_dry=0.25, theta_wet=0.35),
        31.99,
        118.99,
        replay_path=str(replay),
    )

    assert resolved == original
    assert "derived_pressure" not in payload
    assert "ENVIRONMENT_DATA_DEGRADED" in warnings


class _FakeProvider:
    def __init__(self, snapshot: EnvironmentSnapshot) -> None:
        self._snapshot = snapshot

    def fetch(self, _latitude: float, _longitude: float) -> EnvironmentSnapshot:
        return self._snapshot


def _snapshot(moisture: float) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        provider="open-meteo",
        model="best_match",
        requested_at="2026-09-16T08:00:00+00:00",
        valid_at="2026-09-16T07:00:00+00:00",
        latitude=31.99,
        longitude=118.99,
        precipitation_24h_mm=3.5,
        soil_moisture_surface_m3_m3=moisture,
        et0_24h_mm=0.3,
        age_s=3600.0,
        degraded=False,
    )
