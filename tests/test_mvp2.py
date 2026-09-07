"""Spec-derived tests for MVP-2 GIS and H3 graph ingestion."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from shapely.geometry import Polygon

from h3_offroad_planner.assessment import TrafficabilityAssessor
from h3_offroad_planner.dynamics.bekker import LEGACY_SOIL_PARAMS, BekkerChecker
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.grid.h3_grid_builder import _safe_neighbors
from h3_offroad_planner.models import (
    GridBuildError,
    H3Cell,
    H3Graph,
    SoilProfile,
    VehicleProfile,
)
from h3_offroad_planner.preprocessing import GISPreprocessor, RasterLayer


def test_t001_load_dem_rejects_missing_file() -> None:
    """T-001: load_dem rejects missing files."""
    preprocessor = GISPreprocessor()

    with pytest.raises(FileNotFoundError):
        preprocessor.load_dem("missing-dem.tif")


def test_t002_compute_slope_rejects_empty_dem() -> None:
    """T-002: compute_slope rejects empty DEM arrays."""
    preprocessor = GISPreprocessor()

    with pytest.raises(ValueError):
        preprocessor.compute_slope(np.array([], dtype=np.float64), Affine.identity())


def test_t003_grid_builder_rejects_invalid_resolution() -> None:
    """T-003: H3GridBuilder rejects invalid resolution ordering."""
    with pytest.raises(ValueError):
        H3GridBuilder(res_fine=7, res_coarse=7)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_stride": 0}, "sample_stride"),
        ({"max_cells": 0}, "max_cells"),
        ({"road_buffer_deg": 0.0}, "road_buffer_deg"),
    ],
)
def test_grid_builder_rejects_invalid_sampling_controls(
    kwargs: dict[str, float | int],
    message: str,
) -> None:
    """White-box support: sampling controls are defensively validated."""
    with pytest.raises(ValueError, match=message):
        H3GridBuilder(res_fine=7, res_coarse=5, **kwargs)


def test_t004_raster_to_h3_rejects_shape_mismatch() -> None:
    """T-004: raster_to_h3 rejects DEM/slope/TRI shape mismatch."""
    builder = H3GridBuilder(res_fine=7, res_coarse=5)

    with pytest.raises(GridBuildError):
        builder.raster_to_h3(
            np.ones((2, 2), dtype=np.float64),
            np.ones((2, 3), dtype=np.float64),
            np.ones((2, 2), dtype=np.float64),
            Affine.translation(118.0, 32.0) * Affine.scale(0.001, -0.001),
        )


def test_raster_to_h3_rejects_all_invalid_samples() -> None:
    """White-box support: raster_to_h3 rejects all-NaN sampled input."""
    builder = H3GridBuilder(res_fine=7, res_coarse=5)
    invalid = np.array([[np.nan]], dtype=np.float64)

    with pytest.raises(GridBuildError):
        builder.raster_to_h3(invalid, invalid, invalid, Affine.identity())


def test_t006_build_graph_creates_directional_slopes() -> None:
    """T-006: build_graph creates directional edge slopes."""
    graph = _tiny_realistic_graph()

    assert graph.edges
    edge = next(iter(graph.edges.values()))
    assert edge.slope_a_to_b != edge.slope_b_to_a


def test_t007_assessor_marks_over_slope_unpassable(vehicle: VehicleProfile) -> None:
    """T-007: trafficability assessment rejects over-slope cells."""
    graph = H3Graph(
        resolution_fine=9,
        resolution_coarse=7,
        cells={
            "cell": H3Cell(
                h3index="cell",
                lat=32.0,
                lng=118.0,
                elevation=10.0,
                slope=vehicle.max_climb_angle_deg + 1.0,
                tri=0.0,
                lc_factor=1.0,
            )
        },
    )

    TrafficabilityAssessor(vehicle, _weights()).assess(graph)

    assert not graph.cells["cell"].is_passable


def test_t008_assessor_scores_normal_cell(vehicle: VehicleProfile) -> None:
    """T-008: trafficability assessment keeps scores in [0, 1]."""
    graph = _tiny_realistic_graph()

    assessed = TrafficabilityAssessor(vehicle, _weights()).assess(graph)

    assert all(0.0 <= cell.score <= 1.0 for cell in assessed.cells.values())


def test_assessor_rejects_invalid_weights_and_empty_graph(vehicle: VehicleProfile) -> None:
    """White-box support: assessor validates weights and non-empty graphs."""
    with pytest.raises(ValueError):
        TrafficabilityAssessor(vehicle, {"unsupported": 1.0})
    with pytest.raises(ValueError):
        TrafficabilityAssessor(vehicle, {"slope": -1.0})
    with pytest.raises(ValueError):
        TrafficabilityAssessor(vehicle, {"slope": 0.0})
    with pytest.raises(Exception, match="graph must contain"):
        TrafficabilityAssessor(vehicle, _weights()).assess(H3Graph())


def test_assessor_has_no_placeholder_evaluation_entrypoint() -> None:
    """White-box support: the legacy assessor exposes only its implemented entrypoint."""
    public_assessors = {
        name for name in vars(TrafficabilityAssessor) if name.startswith("assess")
    }
    assert public_assessors == {"assess"}


def test_t009_bekker_rejects_heavy_vehicle_on_wet_clay(vehicle: VehicleProfile) -> None:
    """T-009: Bekker check rejects a low-clearance heavy vehicle on wet clay."""
    heavy_vehicle = VehicleProfile(
        name="heavy",
        mass_kg=20_000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=50.0,
        tire_width_m=0.2,
        ground_clearance_m=0.05,
        max_thrust_n=40_000.0,
        tire_radius_m=0.4,
        min_turn_radius_m=8.0,
    )
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        soil_type="clay_wet",
    )

    assert not BekkerChecker().check(cell, heavy_vehicle)


def test_t088_bekker_legacy_light_vehicle_can_pass_dry_sand() -> None:
    """T-088: legacy Bekker units allow plausible light-vehicle passage."""
    light_vehicle = VehicleProfile(
        name="light",
        mass_kg=1200.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.3,
        ground_clearance_m=0.35,
        max_thrust_n=6000.0,
        tire_radius_m=0.35,
        min_turn_radius_m=5.0,
    )
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        soil_type="sand_dry",
    )
    checker = BekkerChecker()

    sinkage_m = checker._legacy_sinkage_m(light_vehicle, LEGACY_SOIL_PARAMS["sand_dry"])

    assert sinkage_m < light_vehicle.ground_clearance_m
    assert checker.check(cell, light_vehicle)


def test_bekker_speed_cap_uses_passability_and_score(vehicle: VehicleProfile) -> None:
    """White-box support: Bekker speed cap is zero only for impassable cells."""
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        is_passable=False,
    )
    checker = BekkerChecker()

    assert checker.compute_max_speed(cell, vehicle) == 0.0
    cell.is_passable = True
    cell.score = 0.5
    assert checker.compute_max_speed(cell, vehicle) > 0.0


def test_t091_bekker_speed_cap_uses_configured_score_floor(
    vehicle: VehicleProfile,
) -> None:
    """T-091: Bekker speed floor is configurable and bounded."""
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        score=0.0,
    )
    checker = BekkerChecker(speed_score_floor=0.6)

    assert checker.compute_max_speed(cell, vehicle) == pytest.approx(
        vehicle.max_speed_kmh / 3.6 * 0.6
    )
    with pytest.raises(ValueError, match="speed_score_floor"):
        BekkerChecker(speed_score_floor=1.1)


def test_t026_load_soil_catalog_parses_nanjing_codes_when_present() -> None:
    """T-026: Export_Output.txt maps Nanjing soil codes to Chinese names."""
    catalog_path = Path("D:/Download/geosptial/Export_Output.txt")
    if not catalog_path.exists():
        pytest.skip("Nanjing soil catalog is not available in this workspace.")

    catalog = GISPreprocessor().load_soil_catalog(str(catalog_path))

    assert len(catalog) == 27
    assert catalog[44].name_zh == "水稻土"
    assert catalog[85].name_zh == "江及河"


def test_t027_t028_attach_soil_uses_area_dominance(tmp_path: Path) -> None:
    """T-027/T-028: attach_soil assigns dominant soil code and profile fields."""
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    layer = _soil_raster_for_cell(tmp_path / "soil.tif", center, center_code=18, outer_code=44)
    h3_df = _single_cell_frame(center)

    result = H3GridBuilder(res_fine=9, res_coarse=7).attach_soil(h3_df, layer, _soil_catalog())

    row = result.iloc[0]
    assert row.soil_code == 44
    assert row.soil_type == "水稻土"
    assert row.soil_texture == "ClLo"
    assert row.uscs == "CL"


def test_t029_water_soil_code_marks_cell_unpassable(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """T-029: water soil codes are hard-blocked before trafficability scoring."""
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    layer = _soil_raster_for_cell(tmp_path / "water.tif", center, center_code=18, outer_code=18)
    builder = H3GridBuilder(res_fine=9, res_coarse=7)
    h3_df = builder.attach_soil(_single_cell_frame(center), layer, _soil_catalog())
    graph = builder.build_graph(h3_df)

    TrafficabilityAssessor(vehicle, _weights()).assess(graph)

    assert not graph.cells[str(center)].is_passable


@pytest.mark.parametrize("uscs", ["CL", "ML", "SM"])
def test_t030_bekker_computes_finite_cone_index(uscs: str) -> None:
    """T-030: CL/ML/SM have finite CI under default soil moisture."""
    ci_kpa = BekkerChecker().compute_cone_index_kpa(uscs, 0.20)

    assert np.isfinite(ci_kpa)
    assert ci_kpa > 0.0


@pytest.mark.parametrize(("soil_texture", "uscs"), [("ClLo", "CL"), ("Lo", "CL")])
def test_t031_bekker_computes_finite_sinkage(
    vehicle: VehicleProfile,
    soil_texture: str,
    uscs: str,
) -> None:
    """T-031: clayloam/loam produce finite Bekker parameters and sinkage."""
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        soil_texture=soil_texture,
        uscs=uscs,
        soil_moisture=0.20,
    )

    result = BekkerChecker().compute_sinkage(cell, vehicle)

    assert {"n", "k_c", "k_phi", "sinkage_m"}.issubset(result)
    assert all(np.isfinite(value) and value > 0.0 for value in result.values())


def test_t032_bekker_rejects_low_cone_index(vehicle: VehicleProfile) -> None:
    """T-032: CI below threshold makes the cell fail Bekker check."""
    cell = H3Cell(
        h3index="cell",
        lat=32.0,
        lng=118.0,
        elevation=10.0,
        slope=1.0,
        tri=0.0,
        lc_factor=1.0,
        soil_texture="ClLo",
        uscs="CL",
        soil_moisture=1.0,
    )

    assert not BekkerChecker().check(cell, vehicle)


def test_preprocessor_rejects_empty_target_crs_and_none_optional_loaders() -> None:
    """White-box support: preprocessor handles invalid and optional inputs."""
    with pytest.raises(ValueError):
        GISPreprocessor("")
    preprocessor = GISPreprocessor()
    assert preprocessor.load_soil(None) is None
    assert preprocessor.load_road_network(None) is None


def test_real_nanjing_sample_builds_h3_table_when_data_is_present(tmp_path: Path) -> None:
    """Real-data smoke: sampled Nanjing rasters produce an H3 table."""
    data_dir = Path("data")
    dem_path = data_dir / "dem_nanjing.tif"
    if not dem_path.exists():
        pytest.skip("Nanjing real GIS data is not available in this workspace.")
    preprocessor = GISPreprocessor()
    dem, affine, _ = preprocessor.load_dem(str(dem_path))
    slope = preprocessor.compute_slope(dem, affine)
    tri = preprocessor.compute_tri(dem)
    landcover = preprocessor.load_landcover(str(data_dir / "land_nanjing.tif"))
    soil = preprocessor.load_soil(str(data_dir / "soil_nanjing.tif"))
    catalog_path = Path("D:/Download/geosptial/Export_Output.txt")
    soil_catalog = (
        preprocessor.load_soil_catalog(str(catalog_path)) if catalog_path.exists() else None
    )
    roads = preprocessor.load_road_network(str(data_dir / "road_nanjing.shp"))
    builder = H3GridBuilder(res_fine=7, res_coarse=5, sample_stride=120, max_cells=800)

    h3_df = builder.raster_to_h3(dem, slope, tri, affine)
    h3_df = builder.attach_landcover(h3_df, landcover)
    h3_df = builder.attach_soil(h3_df, soil, soil_catalog)
    h3_df = builder.attach_roads(h3_df, roads)
    graph = builder.build_graph(h3_df)
    output_path = tmp_path / "sample.parquet"
    builder.save_parquet(h3_df, str(output_path))

    assert not h3_df.empty
    assert {"h3index", "elevation", "slope", "tri"}.issubset(h3_df.columns)
    assert h3_df["soil_code"].notna().any()
    assert graph.cells
    assert graph.edges
    assert output_path.exists()


def test_t089_attach_landcover_uses_vector_largest_overlap() -> None:
    """T-089: vector landcover assigns code/type/factor instead of being ignored."""
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    landcover = gpd.GeoDataFrame(
        {"landcover_code": [5]},
        geometry=[_h3_polygon(center)],
        crs="EPSG:4326",
    )

    result = H3GridBuilder(res_fine=9, res_coarse=7).attach_landcover(
        _single_cell_frame(center),
        landcover,
    )
    row = result.iloc[0]

    assert row.landcover_code == 5
    assert row.landcover_type == "water"
    assert row.lc_factor == np.inf
    assert not row.is_passable


def test_t090_landcover_factors_are_configurable_for_vector_inputs() -> None:
    """T-090: custom and default landcover factors are constructor-configurable."""
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    landcover = gpd.GeoDataFrame(
        {"code": [42]},
        geometry=[_h3_polygon(center)],
        crs="EPSG:4326",
    )
    custom_builder = H3GridBuilder(
        res_fine=9,
        res_coarse=7,
        land_cover_factors={42: 2.5},
        default_landcover_factor=1.7,
    )
    default_builder = H3GridBuilder(
        res_fine=9,
        res_coarse=7,
        default_landcover_factor=1.7,
    )

    custom = custom_builder.attach_landcover(_single_cell_frame(center), landcover)
    fallback = default_builder.attach_landcover(_single_cell_frame(center), landcover)

    assert custom.iloc[0].lc_factor == 2.5
    assert fallback.iloc[0].lc_factor == 1.7
    with pytest.raises(ValueError, match="land_cover_factors"):
        H3GridBuilder(res_fine=9, res_coarse=7, land_cover_factors={1: 0.0})


def test_t092_safe_neighbors_returns_deterministic_pentagon_neighbors() -> None:
    """T-092: pentagon neighbor handling is deterministic and complete."""
    pentagon = str(next(iter(h3.get_pentagons(5))))

    first = _safe_neighbors(pentagon)
    second = _safe_neighbors(pentagon)

    assert first == second
    assert len(first) == 5
    assert len(set(first)) == 5


def _weights() -> dict[str, float]:
    return {"slope": 0.3, "lc_factor": 0.25, "tri": 0.15, "soil": 0.15, "road_bonus": 0.15}


def _tiny_realistic_graph() -> H3Graph:
    center = h3.latlng_to_cell(32.0, 118.0, 9)
    neighbor = next(cell for cell in h3.grid_disk(center, 1) if cell != center)
    lat_a, lng_a = h3.cell_to_latlng(center)
    lat_b, lng_b = h3.cell_to_latlng(neighbor)
    builder = H3GridBuilder(res_fine=9, res_coarse=7)
    h3_df = pd.DataFrame(
        [
            {
                "h3index": str(center),
                "lat": lat_a,
                "lng": lng_a,
                "elevation": 10.0,
                "slope": 0.0,
                "tri": 0.0,
                "parent_h3": str(h3.cell_to_parent(center, 7)),
                "lc_factor": 1.0,
                "soil_type": None,
                "has_road": False,
                "is_passable": True,
            },
            {
                "h3index": str(neighbor),
                "lat": lat_b,
                "lng": lng_b,
                "elevation": 20.0,
                "slope": 1.0,
                "tri": 0.0,
                "parent_h3": str(h3.cell_to_parent(neighbor, 7)),
                "lc_factor": 1.0,
                "soil_type": None,
                "has_road": False,
                "is_passable": True,
            },
        ]
    )
    return builder.build_graph(h3_df)


def _soil_catalog() -> dict[int, SoilProfile]:
    return {
        18: SoilProfile(code=18, name_zh="湖泊及水", is_passable=False),
        44: SoilProfile(
            code=44,
            name_zh="水稻土",
            soil_texture="ClLo",
            uscs="CL",
            bekker_soil="clayloam",
            soil_moisture=0.20,
        ),
    }


def _single_cell_frame(h3index: str) -> pd.DataFrame:
    lat, lng = h3.cell_to_latlng(h3index)
    return pd.DataFrame(
        [
            {
                "h3index": str(h3index),
                "lat": lat,
                "lng": lng,
                "elevation": 10.0,
                "slope": 0.0,
                "tri": 0.0,
                "parent_h3": str(h3.cell_to_parent(h3index, 7)),
                "lc_factor": 1.0,
                "has_road": False,
                "is_passable": True,
            }
        ]
    )


def _soil_raster_for_cell(
    path: Path,
    h3index: str,
    center_code: int,
    outer_code: int,
) -> RasterLayer:
    boundary = h3.cell_to_boundary(h3index)
    lngs = [lng for _, lng in boundary]
    lats = [lat for lat, _ in boundary]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    width = height = 3
    transform = Affine.translation(min_lng, max_lat) * Affine.scale(
        (max_lng - min_lng) / width,
        -(max_lat - min_lat) / height,
    )
    data = np.full((height, width), outer_code, dtype=np.uint8)
    data[1, 1] = center_code
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs=CRS.from_epsg(4326),
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)
    layer = GISPreprocessor().load_soil(str(path))
    assert layer is not None
    return layer


def _h3_polygon(h3index: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3index)])
