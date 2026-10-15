"""Unit and regression tests for StaticScene and prepare_static_scene (M0 normalization)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, LineString, Polygon

from h3_offroad_planner.scene import (
    DemReference,
    HydrologyReference,
    LandcoverAttributeAudit,
    LandcoverReference,
    MoistureReference,
    OrthophotoReference,
    RoadReference,
    SoilReference,
    StaticScene,
    StudyArea,
    WeatherSnapshotReference,
    load_static_scene,
    prepare_static_scene,
)

ROOT = Path(__file__).resolve().parents[1]


def test_static_scene_roundtrip_serialization(tmp_path: Path) -> None:
    study_area = StudyArea(
        source_layer="/path/to/bound.shp",
        source_crs="EPSG:4490",
        bounds_wgs84=[118.98, 31.96, 119.02, 32.00],
        bounds_metric=[40403000.0, 3538000.0, 40407000.0, 3543000.0],
        metric_crs="EPSG:4528",
        selection_basis="Overlapping test area",
    )
    dem = DemReference(
        path="/path/to/dem.tif",
        crs="EPSG:4490",
        native_resolution=[0.00002, 0.00002],
        horizontal_unit="degree",
        elevation_unit="meter",
        bounds=[118.98, 31.96, 119.02, 32.00],
    )
    landcover = LandcoverReference(
        source_directory="/path/to/landcover",
        crs="EPSG:4490",
        layers=["forest.shp", "water.shp"],
        attribute_checks=[
            LandcoverAttributeAudit(
                layer="forest.shp",
                field="rowspacing",
                features_in_study_area=10,
                non_null=10,
                sample_raw_values=["2.5", "3.0"],
                numeric_min=2.0,
                numeric_max=5.0,
                semantic_status="raw source field audited",
            )
        ],
    )
    road = RoadReference(
        path="/path/to/road.shp",
        crs="EPSG:4490",
        width_field="Width",
        feature_count=15,
        sample_widths=[30.0, 30.0],
    )
    orthophoto = OrthophotoReference(
        source_path="/path/to/T.tif",
        crs="EPSG:4528",
        native_resolution_m=0.5,
        bounds_wgs84=[[31.95, 118.93], [32.01, 119.06]],
    )
    soil = SoilReference(
        raster_path="/path/to/soil.tif",
        catalog_path="/path/to/soil.dbf",
        crs="EPSG:4326",
        native_resolution=[0.0003, 0.0003],
        class_count=27,
    )
    moisture = MoistureReference(
        paths=["/path/to/cldas.nc"],
        unit="m3/m3",
        depth_layers=["0-5cm"],
    )
    hydrology = HydrologyReference(
        upstream_layers={"twi": "/path/to/twi.tif"},
        crs="EPSG:32650",
    )
    weather = WeatherSnapshotReference(
        snapshot_path="/path/to/weather.json",
        provider="open-meteo",
        valid_at="2026-10-15T08:00:00+00:00",
        precipitation_24h_mm=0.3,
        soil_moisture_surface_m3_m3=0.25,
        degraded=False,
    )

    scene = StaticScene(
        scene_id="test-scene-001",
        metric_crs="EPSG:4528",
        study_area=study_area,
        dem=dem,
        landcover=landcover,
        road=road,
        orthophoto=orthophoto,
        soil=soil,
        moisture=moisture,
        hydrology=hydrology,
        weather=weather,
        mapping_time="2026-10-15T08:00:00+00:00",
        field_mapping={"forest.shp": {"rowspacing": "rowspacing"}},
        primary_od={"id": "od-001", "start_wgs84": [31.99, 118.99], "goal_wgs84": [31.993, 118.989]},
    )

    out_file = tmp_path / "scene.json"
    scene.save_json(out_file)
    assert out_file.is_file()

    reloaded = load_static_scene(out_file)
    assert reloaded.scene_id == "test-scene-001"
    assert reloaded.metric_crs == "EPSG:4528"
    assert reloaded.study_area.bounds_wgs84 == [118.98, 31.96, 119.02, 32.00]
    assert reloaded.dem.horizontal_unit == "degree"
    assert reloaded.dem.elevation_unit == "meter"
    assert len(reloaded.landcover.attribute_checks) == 1
    assert reloaded.landcover.attribute_checks[0].field == "rowspacing"
    assert reloaded.road.feature_count == 15
    assert reloaded.road.sample_widths == [30.0, 30.0]
    assert reloaded.orthophoto.native_resolution_m == 0.5
    assert reloaded.soil.class_count == 27
    assert reloaded.weather.degraded is False
    assert reloaded.primary_od is not None
    assert reloaded.primary_od["id"] == "od-001"


def test_prepare_static_scene_with_synthetic_fixtures(tmp_path: Path) -> None:
    # 1. Create synthetic DEM (EPSG:4326)
    dem_path = tmp_path / "dem.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(118.98, 32.00, 0.002, 0.002),
    ) as ds:
        ds.write(np.full((10, 10), 50.0, dtype=np.float32), 1)

    # 2. Create synthetic ROI (EPSG:4326)
    roi_path = tmp_path / "bound.shp"
    roi_poly = box(118.982, 31.982, 118.998, 31.998)
    roi_gdf = gpd.GeoDataFrame({"geometry": [roi_poly]}, crs="EPSG:4326")
    roi_gdf.to_file(roi_path)

    # 3. Create synthetic Road shapefile
    road_path = tmp_path / "road.shp"
    road_line = LineString([(118.985, 31.985), (118.995, 31.995)])
    road_gdf = gpd.GeoDataFrame({"geometry": [road_line], "Width": [30.0]}, crs="EPSG:4326")
    road_gdf.to_file(road_path)

    # 4. Create synthetic Landcover directory with forest.shp and water.shp
    lc_dir = tmp_path / "landcover"
    lc_dir.mkdir()
    forest_poly = box(118.983, 31.983, 118.990, 31.990)
    forest_gdf = gpd.GeoDataFrame({"geometry": [forest_poly], "rowspacing": [3.5]}, crs="EPSG:4326")
    forest_gdf.to_file(lc_dir / "forest.shp")

    water_poly = box(118.991, 31.983, 118.997, 31.990)
    water_gdf = gpd.GeoDataFrame({"geometry": [water_poly], "depth": [1.2]}, crs="EPSG:4326")
    water_gdf.to_file(lc_dir / "water.shp")

    # 5. Create synthetic Orthophoto (EPSG:3857)
    ortho_path = tmp_path / "ortho.tif"
    with rasterio.open(
        ortho_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(13245000.0, 3762000.0, 1.0, 1.0),
    ) as ds:
        for b in range(1, 4):
            ds.write(np.full((10, 10), 128, dtype=np.uint8), b)

    # 6. Create synthetic Soil raster and catalog DBF
    soil_path = tmp_path / "soil.tif"
    with rasterio.open(
        soil_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(118.98, 32.00, 0.002, 0.002),
    ) as ds:
        ds.write(np.ones((10, 10), dtype=np.uint8), 1)

    catalog_path = tmp_path / "soil.dbf"
    cat_gdf = gpd.GeoDataFrame({"VALUE": [1], "geometry": [None]}, crs="EPSG:4326")
    cat_gdf.to_file(catalog_path)

    # 7. Create synthetic frozen weather snapshot
    weather_path = tmp_path / "weather.json"
    weather_path.write_text(
        json.dumps(
            {
                "provider": "open-meteo",
                "valid_at": "2026-10-15T08:00:00+00:00",
                "precipitation_24h_mm": 0.5,
                "soil_moisture_surface_m3_m3": 0.22,
                "degraded": False,
            }
        ),
        encoding="utf-8",
    )

    inputs = {
        "dem": str(dem_path),
        "orthophoto": str(ortho_path),
        "landcover_directory": str(lc_dir),
        "road": str(road_path),
        "roi": str(roi_path),
        "soil": str(soil_path),
        "soil_catalog": str(catalog_path),
    }

    scene = prepare_static_scene(
        inputs=inputs,
        weather_snapshot=weather_path,
        build_config={"scene_id": "synthetic-001", "metric_crs": "EPSG:3857"},
    )

    assert scene.scene_id == "synthetic-001"
    assert scene.metric_crs == "EPSG:3857"
    assert scene.dem.crs == "EPSG:4326"
    assert scene.dem.horizontal_unit == "degree"
    assert scene.study_area.bounds_wgs84[0] < scene.study_area.bounds_wgs84[2]
    assert scene.road.feature_count == 1
    assert scene.road.sample_widths == [30.0]
    assert len(scene.landcover.attribute_checks) == 3
    rowspacing_check = next(c for c in scene.landcover.attribute_checks if c.field == "rowspacing")
    assert rowspacing_check.features_in_study_area == 1
    assert rowspacing_check.numeric_min == 3.5
    assert scene.weather.degraded is False
    assert scene.weather.precipitation_24h_mm == 0.5


def test_prepare_static_scene_rejects_degraded_weather(tmp_path: Path) -> None:
    weather_path = tmp_path / "degraded_weather.json"
    weather_path.write_text(
        json.dumps(
            {
                "provider": "open-meteo",
                "valid_at": "2026-10-15T08:00:00+00:00",
                "degraded": True,
                "degradation_reason": "API timeout fallback used",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Weather snapshot is marked degraded"):
        prepare_static_scene(
            inputs={"dem": "none"},
            weather_snapshot=weather_path,
        )


def test_prepare_static_scene_rejects_missing_inputs(tmp_path: Path) -> None:
    weather_path = tmp_path / "weather.json"
    weather_path.write_text(
        json.dumps({"valid_at": "2026-10-15", "degraded": False}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Missing required GIS input paths"):
        prepare_static_scene(
            inputs={},
            weather_snapshot=weather_path,
        )


def test_load_existing_m0_qdx_scene() -> None:
    scene_file = ROOT / "configs" / "scenes" / "m0_qdx_scene.json"
    assert scene_file.is_file()
    scene = load_static_scene(scene_file)
    assert scene.scene_id == "qdx-dem-coverage-001"
    assert scene.metric_crs == "EPSG:4528"
    assert scene.model_version == "m0_static_scene_v1"
    assert scene.baseline_source_commit == "986bd58"
    assert scene.dem.crs == "EPSG:4490"
    assert scene.study_area.source_crs == "EPSG:4490"
    assert scene.orthophoto.crs == "EPSG:4528"
    assert scene.orthophoto.native_resolution_m == 0.5
    assert scene.weather.valid_at == "2026-10-15T08:00:00+00:00"
    assert scene.weather.degraded is False
    assert len(scene.landcover.attribute_checks) == 3
    assert scene.primary_od is not None
    assert scene.vehicle is not None


def test_prepare_static_scene_qdx_live_if_present() -> None:
    request_path = ROOT / "configs" / "manned_offroad_m0.yaml"
    weather_path = ROOT / "configs" / "scenes" / "baseline_986bd58_weather.json"
    assets_path = ROOT / "configs" / "manned_assets.private.yaml"
    if not request_path.is_file() or not assets_path.is_file() or not weather_path.is_file():
        pytest.skip("Local QDX private assets not present.")

    scene = prepare_static_scene(
        inputs=request_path,
        weather_snapshot=weather_path,
        build_config={"assets_config_path": assets_path},
    )
    assert scene.scene_id == "qdx-dem-coverage-001"
    assert scene.dem.native_resolution[0] > 0
    assert scene.road.feature_count == 124
    assert len(scene.landcover.attribute_checks) == 3
