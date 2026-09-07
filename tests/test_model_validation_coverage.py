"""Focused validation cases for public model boundary branches."""

from __future__ import annotations

import pytest

from h3_offroad_planner.models import (
    H3Cell,
    H3Edge,
    Path,
    RouteEndpoint,
    RouteRequest,
    SoilProfile,
    TileBuildRequest,
    VehicleProfile,
)


def _vehicle_kwargs() -> dict[str, object]:
    return {
        "name": "test vehicle",
        "mass_kg": 1000.0,
        "max_climb_angle_deg": 30.0,
        "max_speed_kmh": 40.0,
        "tire_width_m": 0.3,
        "ground_clearance_m": 0.2,
        "max_thrust_n": 5000.0,
        "tire_radius_m": 0.4,
        "min_turn_radius_m": 4.0,
    }


def _route_kwargs() -> dict[str, object]:
    return {
        "input_mode": "coordinates",
        "parquet_path": "outputs/grid.parquet",
        "planner_config_path": "configs/planner.yaml",
        "vehicle_path": "configs/vehicle.yaml",
        "output_dir": "outputs/route",
        "start_lat": 31.9,
        "start_lng": 118.8,
        "goal_lat": 31.91,
        "goal_lng": 118.81,
    }


def _tile_kwargs() -> dict[str, object]:
    return {
        "dem_path": "data/dem.tif",
        "landcover_path": "data/land.tif",
        "roi_layer_path": "data/roi.geojson",
        "output_dir": "outputs/tiles",
    }


def _cell_kwargs() -> dict[str, object]:
    return {
        "h3index": "8928308280fffff",
        "lat": 31.9,
        "lng": 118.8,
        "elevation": 10.0,
        "slope": 2.0,
        "tri": 0.1,
        "lc_factor": 1.0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("mass_kg", 0.0),
        ("max_climb_angle_deg", 91.0),
        ("max_speed_kmh", "fast"),
        ("tire_width_m", -0.1),
        ("ground_clearance_m", 0.0),
        ("max_thrust_n", float("inf")),
        ("tire_radius_m", 0.0),
        ("min_turn_radius_m", -1.0),
    ],
)
def test_vehicle_profile_rejects_each_invalid_field(field: str, value: object) -> None:
    """Every physical boundary is validated independently."""
    kwargs = _vehicle_kwargs()
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError)):
        VehicleProfile(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_mode", "other"),
        ("parquet_path", ""),
        ("res_coarse", -1),
        ("res_fine", 10),
        ("max_snap_distance_m", 0.0),
        ("corridor_buffer_deg", -1.0),
        ("max_estimated_cells", 0),
        ("roi_strategy", "unknown"),
        ("objectives", []),
        ("objectives", ["distance", "distance"]),
        ("objectives", ["unknown"]),
        ("candidate_index", True),
        ("candidate_index", -1),
        ("blocked_cells", ["duplicate", "duplicate"]),
        ("theme_attributes", []),
        ("penalty_factor", -1.0),
        ("penalty_factor", float("inf")),
    ],
)
def test_route_request_rejects_invalid_configuration(field: str, value: object) -> None:
    """Route request validation covers numerical, enum, and collection boundaries."""
    kwargs = _route_kwargs()
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError)):
        RouteRequest(**kwargs)  # type: ignore[arg-type]


def test_route_request_rejects_incomplete_coordinate_or_layer_endpoints() -> None:
    """Both input modes enforce their own endpoint source requirements."""
    coordinate = _route_kwargs()
    coordinate["start_lat"] = None
    with pytest.raises(ValueError, match="coordinate mode"):
        RouteRequest(**coordinate)  # type: ignore[arg-type]

    layer = _route_kwargs()
    layer["input_mode"] = "layer"
    for key in ("start_lat", "start_lng", "goal_lat", "goal_lng"):
        layer.pop(key)
    with pytest.raises(ValueError, match="endpoint_layer_path"):
        RouteRequest(**layer)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("soil_path", "data/soil.tif"),
        ("res_fine", 10),
        ("tile_res", -1),
        ("max_tiles", 0),
        ("max_cells_per_tile", 0),
        ("sampling_mode", "area"),
        ("continue_on_error", 1),
        ("overwrite", "yes"),
    ],
)
def test_tile_request_rejects_invalid_configuration(field: str, value: object) -> None:
    """Tile construction boundaries reject malformed vehicle-independent settings."""
    kwargs = _tile_kwargs()
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError)):
        TileBuildRequest(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("h3index", ""),
        ("lat", 91.0),
        ("lng", 181.0),
        ("elevation", float("nan")),
        ("tri", -1.0),
        ("lc_factor", 0.0),
        ("landcover_code", -1),
        ("soil_code", 0),
        ("soil_moisture", 1.1),
        ("cone_index_kpa", -1.0),
        ("sinkage_m", -1.0),
        ("sinkage_resistance", -1.0),
        ("soil_mobility", 1.1),
        ("score", 1.1),
        ("cost_score", 0.5),
    ],
)
def test_h3_cell_rejects_invalid_assessment_values(field: str, value: object) -> None:
    """Cell score, terrain, and soil fields preserve their documented ranges."""
    kwargs = _cell_kwargs()
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError)):
        H3Cell(**kwargs)  # type: ignore[arg-type]


def test_small_model_types_reject_invalid_identity_and_metrics() -> None:
    """Supplementary model types cover identity, role, and finite-metric branches."""
    with pytest.raises(ValueError, match="positive integer"):
        SoilProfile(0, "soil")
    with pytest.raises(ValueError, match="soil_moisture"):
        SoilProfile(1, "soil", soil_moisture=1.1)
    with pytest.raises(ValueError, match="role"):
        RouteEndpoint("unknown", 31.9, 118.8)
    with pytest.raises(ValueError, match="source_id"):
        RouteEndpoint("start", 31.9, 118.8, source_id=" ")
    assert RouteEndpoint("end", 31.9, 118.8).role == "goal"
    with pytest.raises(ValueError, match="different"):
        H3Edge("same", "same", 1.0)
    with pytest.raises(ValueError, match="non-empty"):
        Path([], 1.0)
    with pytest.raises(ValueError, match="finite"):
        Path(["a"], float("nan"))
    with pytest.raises(ValueError, match="objective"):
        Path(["a"], 1.0, objectives={"distance": -1.0})
