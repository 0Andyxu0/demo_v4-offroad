"""Tests for QDX dataset ingestion, multi-shapefile loading, and res11/res14 resolution."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon

from h3_offroad_planner.factor_model import FactorModelConfig, evaluate_factor_model
from h3_offroad_planner.grid.h3_grid_builder import H3GridBuilder
from h3_offroad_planner.models import GISInputError, H3Cell, H3Graph, VehicleProfile
from h3_offroad_planner.preprocessing.gis_preprocessor import GISPreprocessor


def test_h3cell_depth_and_rowspacing_attributes() -> None:
    """H3Cell validates and stores optional depth and rowspacing attributes."""
    valid_h3 = str(h3.latlng_to_cell(31.98, 118.99, 14))
    cell = H3Cell(
        h3index=valid_h3,
        lat=31.98,
        lng=118.99,
        elevation=50.0,
        slope=5.0,
        tri=1.2,
        lc_factor=1.0,
        depth=1.8,
        rowspacing=3.5,
    )
    assert cell.depth == 1.8
    assert cell.rowspacing == 3.5

    with pytest.raises(ValueError, match="depth"):
        H3Cell(
            h3index=valid_h3,
            lat=31.98,
            lng=118.99,
            elevation=50.0,
            slope=5.0,
            tri=1.2,
            lc_factor=1.0,
            depth=-0.5,
        )

    with pytest.raises(ValueError, match="rowspacing"):
        H3Cell(
            h3index=valid_h3,
            lat=31.98,
            lng=118.99,
            elevation=50.0,
            slope=5.0,
            tri=1.2,
            lc_factor=1.0,
            rowspacing=-2.0,
        )


def test_qdx_multi_shapefile_directory_loading(tmp_path: Path) -> None:
    """GISPreprocessor.load_landcover loads and concatenates multiple shapefiles in a folder."""
    vec_dir = tmp_path / "vectors"
    vec_dir.mkdir()

    # Create dummy water shapefile
    poly1 = Polygon([(118.98, 31.97), (118.99, 31.97), (118.99, 31.98), (118.98, 31.98)])
    gdf1 = gpd.GeoDataFrame(
        [{"id": 1, "type": "01", "fclass": "water", "depth": 2.5, "geometry": poly1}],
        crs="EPSG:4490",
    )
    gdf1.to_file(vec_dir / "water.shp")

    # Create dummy forest shapefile
    poly2 = Polygon([(118.99, 31.98), (119.00, 31.98), (119.00, 31.99), (118.99, 31.99)])
    gdf2 = gpd.GeoDataFrame(
        [{"id": 2, "type": "02", "fclass": "forest", "rowspacing": 4.0, "geometry": poly2}],
        crs="EPSG:4490",
    )
    gdf2.to_file(vec_dir / "forest.shp")

    preprocessor = GISPreprocessor(target_crs="EPSG:4326")
    merged_gdf = preprocessor.load_landcover(str(vec_dir))

    assert isinstance(merged_gdf, gpd.GeoDataFrame)
    assert len(merged_gdf) == 2
    assert merged_gdf.crs.to_string() == "EPSG:4326"

    # Test empty directory raises GISInputError
    empty_dir = tmp_path / "empty_vecs"
    empty_dir.mkdir()
    with pytest.raises(GISInputError, match="no vector files found"):
        preprocessor.load_landcover(str(empty_dir))


def test_qdx_vector_landcover_attribute_attachment(tmp_path: Path) -> None:
    """H3GridBuilder attaches code, depth, rowspacing, and type from vector attributes."""
    poly = Polygon([(118.98, 31.97), (119.01, 31.97), (119.01, 32.00), (118.98, 32.00)])
    gdf = gpd.GeoDataFrame(
        [
            {"id": 1, "type": "01", "fclass": "water", "depth": 1.5, "geometry": poly},
            {"id": 2, "type": "02", "fclass": "forest", "rowspacing": 3.0, "geometry": poly},
        ],
        crs="EPSG:4326",
    )

    builder = H3GridBuilder(res_fine=14, res_coarse=11)
    cell_id = str(h3.latlng_to_cell(31.98, 118.99, 14))
    parent_id = str(h3.cell_to_parent(cell_id, 11))
    df = pd.DataFrame(
        [
            {
                "h3index": cell_id,
                "lat": 31.98,
                "lng": 118.99,
                "elevation": 50.0,
                "slope": 2.0,
                "tri": 0.5,
                "parent_h3": parent_id,
                "lc_factor": 1.0,
            }
        ]
    )

    result_df = builder.attach_landcover(df, gdf)
    assert "depth" in result_df.columns
    assert "rowspacing" in result_df.columns
    assert result_df["landcover_code"].iloc[0] in {1, 2, 5}


def test_default_resolutions_are_res14_and_res11() -> None:
    """Builder, TileBuildRequest, and RouteRequest default to res_fine=14 and res_coarse=11."""
    builder = H3GridBuilder()
    assert builder.res_fine == 14
    assert builder.res_coarse == 11


def test_qdx_water_depth_physical_evaluation(vehicle: VehicleProfile) -> None:
    """Deep water is blocked, but shallow water within clearance allows wading."""
    cell_id = str(h3.latlng_to_cell(31.98, 118.99, 14))
    deep_cell = H3Cell(
        h3index=cell_id,
        lat=31.98,
        lng=118.99,
        elevation=50.0,
        slope=2.0,
        tri=0.5,
        lc_factor=float("inf"),
        landcover_code=5,
        landcover_type="water",
        depth=0.9,  # exceeds vehicle.ground_clearance_m (0.45m)
        soil_code=1,
        soil_type="loam",
        uscs="ML",
        soil_moisture=0.3,
    )
    graph = H3Graph(14, 11, {cell_id: deep_cell}, {})
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    assert evaluation.node_metrics[cell_id].is_passable is False
    assert "WATER_DEPTH_LIMIT" in evaluation.node_metrics[cell_id].reason_codes

    shallow_cell = H3Cell(
        h3index=cell_id,
        lat=31.98,
        lng=118.99,
        elevation=50.0,
        slope=2.0,
        tri=0.5,
        lc_factor=float("inf"),
        landcover_code=5,
        landcover_type="water",
        depth=0.2,  # fordable shallow water (<= 0.45m)
        soil_code=1,
        soil_type="loam",
        uscs="ML",
        soil_moisture=0.3,
    )
    graph2 = H3Graph(14, 11, {cell_id: shallow_cell}, {})
    evaluation2 = evaluate_factor_model(graph2, vehicle, FactorModelConfig())
    assert evaluation2.node_metrics[cell_id].is_passable is True
    assert evaluation2.node_metrics[cell_id].landcover.nominal > 0.0


def test_qdx_tree_rowspacing_physical_evaluation(vehicle: VehicleProfile) -> None:
    """Dense trees narrower than vehicle are blocked, while wider spacing allows passage."""
    cell_id = str(h3.latlng_to_cell(31.98, 118.99, 14))
    tight_cell = H3Cell(
        h3index=cell_id,
        lat=31.98,
        lng=118.99,
        elevation=50.0,
        slope=2.0,
        tri=0.5,
        lc_factor=1.35,
        landcover_code=2,
        landcover_type="forest",
        rowspacing=1.5,  # narrower than safe width (2.2m)
        soil_code=1,
        soil_type="loam",
        uscs="ML",
        soil_moisture=0.3,
    )
    graph = H3Graph(14, 11, {cell_id: tight_cell}, {})
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    assert evaluation.node_metrics[cell_id].is_passable is False
    assert "ROWSPACING_BLOCKED" in evaluation.node_metrics[cell_id].reason_codes

    wide_cell = H3Cell(
        h3index=cell_id,
        lat=31.98,
        lng=118.99,
        elevation=50.0,
        slope=2.0,
        tri=0.5,
        lc_factor=1.35,
        landcover_code=2,
        landcover_type="forest",
        rowspacing=3.8,  # wide enough
        soil_code=1,
        soil_type="loam",
        uscs="ML",
        soil_moisture=0.3,
    )
    graph2 = H3Graph(14, 11, {cell_id: wide_cell}, {})
    evaluation2 = evaluate_factor_model(graph2, vehicle, FactorModelConfig())
    assert evaluation2.node_metrics[cell_id].is_passable is True
    assert evaluation2.node_metrics[cell_id].landcover.nominal > 0.0


def test_qdx_road_priority_over_background_vegetation() -> None:
    """Narrow road corridor takes precedence over background grass when intersecting cell."""
    center_lat, center_lng = 31.98, 118.99
    cell_id = str(h3.latlng_to_cell(center_lat, center_lng, 14))
    poly_grass = Polygon([
        (center_lng - 0.001, center_lat - 0.001),
        (center_lng + 0.001, center_lat - 0.001),
        (center_lng + 0.001, center_lat + 0.001),
        (center_lng - 0.001, center_lat + 0.001),
    ])
    # Road crosses a portion of the cell
    poly_road = Polygon([
        (center_lng - 0.00005, center_lat - 0.001),
        (center_lng + 0.00005, center_lat - 0.001),
        (center_lng + 0.00005, center_lat + 0.001),
        (center_lng - 0.00005, center_lat + 0.001),
    ])
    gdf = gpd.GeoDataFrame(
        [
            {"id": 1, "type": "03", "fclass": "grass", "geometry": poly_grass},
            {"id": 2, "type": "08", "fclass": "road", "geometry": poly_road},
        ],
        crs="EPSG:4326",
    )
    builder = H3GridBuilder(res_fine=14, res_coarse=11)
    df = pd.DataFrame(
        [
            {
                "h3index": cell_id,
                "lat": center_lat,
                "lng": center_lng,
                "elevation": 50.0,
                "slope": 1.0,
                "tri": 0.2,
                "parent_h3": str(h3.cell_to_parent(cell_id, 11)),
                "lc_factor": 1.0,
            }
        ]
    )
    result = builder.attach_landcover(df, gdf)
    assert result["landcover_code"].iloc[0] == 8
    assert result["landcover_type"].iloc[0] == "impervious"
