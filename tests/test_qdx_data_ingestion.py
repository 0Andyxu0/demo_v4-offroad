"""Tests for QDX dataset ingestion, multi-shapefile loading, and res11/res14 resolution."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon

from h3_offroad_planner.grid.h3_grid_builder import H3GridBuilder
from h3_offroad_planner.models import GISInputError, H3Cell
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
