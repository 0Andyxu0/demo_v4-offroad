"""Tests for provisional soil USCS mapping."""

from __future__ import annotations

from h3_offroad_planner.preprocessing.gis_preprocessor import _profile_from_soil_code


def test_paddy_soil_gets_provisional_cl_mapping() -> None:
    profile = _profile_from_soil_code(44, "水稻土")

    assert profile.soil_texture == "ClLo"
    assert profile.uscs == "CL"
    assert profile.bekker_soil == "clayloam"


def test_brown_red_soil_gets_provisional_cl_mapping() -> None:
    profile = _profile_from_soil_code(49, "黄褐土")

    assert profile.soil_texture == "Lo"
    assert profile.uscs == "CL"
    assert profile.bekker_soil == "loam"


def test_water_and_urban_codes_remain_without_uscs() -> None:
    water = _profile_from_soil_code(18, "湖泊及水")
    urban = _profile_from_soil_code(84, "城区")

    assert water.uscs is None
    assert urban.uscs is None
