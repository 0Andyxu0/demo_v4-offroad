"""Tests for provisional soil USCS mapping."""

from __future__ import annotations

import pytest

from h3_offroad_planner.preprocessing.gis_preprocessor import _profile_from_soil_code


def test_paddy_soil_gets_provisional_cl_mapping() -> None:
    profile = _profile_from_soil_code(44, "水稻土")

    assert profile.soil_texture == "ClLo"
    assert profile.uscs == "CL"
    assert profile.bekker_soil == "clayloam"
    assert profile.soil_moisture is None


def test_brown_red_soil_gets_provisional_cl_mapping() -> None:
    profile = _profile_from_soil_code(49, "黄褐土")

    assert profile.soil_texture == "Lo"
    assert profile.uscs == "CL"
    assert profile.bekker_soil == "loam"
    assert profile.soil_moisture is None


def test_water_and_urban_codes_remain_without_uscs() -> None:
    water = _profile_from_soil_code(18, "湖泊及水")
    urban = _profile_from_soil_code(84, "城区")

    assert water.uscs is None
    assert urban.uscs is None


def test_water_urban_and_marsh_are_non_passable() -> None:
    water = _profile_from_soil_code(18, "湖泊及水")
    urban = _profile_from_soil_code(84, "城区")
    marsh = _profile_from_soil_code(17, "沼泽土")

    assert water.is_passable is False
    assert urban.is_passable is False
    assert marsh.is_passable is False


def test_unknown_soil_name_falls_back_to_sand_mapping() -> None:
    profile = _profile_from_soil_code(999, "砂质土")

    assert profile.soil_texture == "SaLo"
    assert profile.uscs == "SM"
    assert profile.is_passable is True


def test_unknown_soil_name_falls_back_to_clay_mapping() -> None:
    profile = _profile_from_soil_code(999, "粘质红土")

    assert profile.soil_texture == "ClLo"
    assert profile.uscs == "CL"
    assert profile.is_passable is True


def test_unknown_soil_name_uses_conservative_loam_default() -> None:
    profile = _profile_from_soil_code(999, "未知土壤")

    assert profile.soil_texture == "Lo"
    assert profile.uscs == "CL"
    assert profile.is_passable is True


def test_static_soil_catalog_leaves_moisture_to_runtime() -> None:
    """Static catalog must keep soil_moisture as None; moisture belongs to runtime environment."""
    passable = _profile_from_soil_code(49, "黄褐土")
    impassable = _profile_from_soil_code(18, "湖泊及水")

    assert passable.soil_moisture is None
    assert impassable.soil_moisture is None


def test_runtime_environment_resolves_dynamic_moisture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dynamic moisture is injected and resolved at the runtime environment layer."""
    from h3_offroad_planner import environment as env_mod
    from h3_offroad_planner.environment import EnvironmentSnapshot
    from h3_offroad_planner.factor_model import EnvironmentConfig, WeatherConfig

    class _FakeProvider:
        def __init__(self, snapshot: EnvironmentSnapshot) -> None:
            self._snapshot = snapshot

        def fetch(self, _lat: float, _lon: float) -> EnvironmentSnapshot:
            return self._snapshot

    snapshot = EnvironmentSnapshot(
        provider="open-meteo",
        model="best_match",
        requested_at="2026-09-17T00:00:00+00:00",
        valid_at="2026-09-17T00:00:00+00:00",
        latitude=31.99,
        longitude=118.99,
        precipitation_24h_mm=0.0,
        soil_moisture_surface_m3_m3=0.30,
        et0_24h_mm=1.0,
        age_s=60.0,
        degraded=False,
    )
    monkeypatch.setattr(env_mod, "_provider", lambda _cfg: _FakeProvider(snapshot))

    resolved, payload, _, warnings = env_mod.resolve_request_environment(
        EnvironmentConfig(),
        WeatherConfig(enabled=True, theta_dry=0.10, theta_wet=0.50),
        31.99,
        118.99,
    )
    assert payload["derived_pressure"] == pytest.approx(0.5)
    assert resolved.pressure_basis == "model_snapshot_v1"
    assert resolved.request_pressures == (pytest.approx(0.5),)
