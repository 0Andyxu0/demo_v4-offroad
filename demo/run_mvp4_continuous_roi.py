"""Build a continuous ROI H3 graph from raw GIS inputs for MVP-4."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
from affine import Affine
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from h3_offroad_planner.assessment import TrafficabilityAssessor
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GISInputError, H3Graph, VehicleProfile
from h3_offroad_planner.preprocessing import GISPreprocessor

DATA_DIR: Path = Path("data")
DEFAULT_OUTPUT_DIR: Path = Path("outputs/mvp4")
OUTPUT_PARQUET_NAME: str = "nanjing_h3_continuous_roi.parquet"
OUTPUT_GPKG_NAME: str = "nanjing_h3_continuous_roi.gpkg"
OUTPUT_MANIFEST_NAME: str = "nanjing_h3_continuous_roi.manifest.json"
SOIL_CATALOG_CANDIDATES: tuple[Path, ...] = (
    DATA_DIR / "Export_Output.txt",
    Path("D:/Download/geosptial/Export_Output.txt"),
)
RES_FINE: int = 9
RES_COARSE: int = 7
MAX_CELLS: int = 2_000
DEFAULT_ROI_HALF_SIZE_DEG: float = 0.02
THEME_ATTRIBUTES: list[str] = ["score", "cost_score", "landcover_type", "soil_type", "slope"]


def run_continuous_roi_build(
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
    res_fine: int = RES_FINE,
    res_coarse: int = RES_COARSE,
    max_cells: int = MAX_CELLS,
    roi_layer_path: str | None = None,
) -> dict[str, object]:
    """Build a continuous H3 graph for a bounded ROI from Nanjing raw GIS data."""
    preprocessor = GISPreprocessor()
    dem, affine, _ = preprocessor.load_dem(str(DATA_DIR / "dem_nanjing.tif"))
    slope = preprocessor.compute_slope(dem, affine)
    tri = preprocessor.compute_tri(dem)
    roi_geometry, roi_source = _load_roi(roi_layer_path, dem.shape, affine)
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse, max_cells=max_cells)
    h3_df = builder.roi_to_h3(dem, slope, tri, affine, roi_geometry)
    landcover = preprocessor.load_landcover(str(DATA_DIR / "land_nanjing.tif"))
    h3_df = builder.attach_landcover(h3_df, landcover)
    soil_catalog = preprocessor.load_soil_catalog(str(_first_existing(SOIL_CATALOG_CANDIDATES)))
    soil = preprocessor.load_soil(str(DATA_DIR / "soil_nanjing.tif"))
    h3_df = builder.attach_soil(h3_df, soil, soil_catalog)
    roads = preprocessor.load_road_network(str(DATA_DIR / "road_nanjing.shp"))
    h3_df = builder.attach_roads(h3_df, roads)
    graph = _assess_graph(builder, h3_df)
    h3_df = _copy_assessment_fields(h3_df, graph)
    outputs = _write_outputs(output_dir, builder, h3_df, graph, roi_source)
    return outputs


def _load_roi(
    roi_layer_path: str | None,
    dem_shape: tuple[int, int],
    affine: Affine,
) -> tuple[BaseGeometry, str]:
    if roi_layer_path is not None:
        gdf = gpd.read_file(roi_layer_path)
        if gdf.empty:
            raise GISInputError(f"ROI layer must not be empty: {roi_layer_path}")
        if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return cast(BaseGeometry, gdf.geometry.union_all()), str(roi_layer_path)
    center_lng, center_lat = affine * (dem_shape[1] / 2.0, dem_shape[0] / 2.0)
    return (
        box(
            center_lng - DEFAULT_ROI_HALF_SIZE_DEG,
            center_lat - DEFAULT_ROI_HALF_SIZE_DEG,
            center_lng + DEFAULT_ROI_HALF_SIZE_DEG,
            center_lat + DEFAULT_ROI_HALF_SIZE_DEG,
        ),
        "auto_dem_center_bbox",
    )


def _assess_graph(builder: H3GridBuilder, h3_df: pd.DataFrame) -> H3Graph:
    graph = builder.build_graph(h3_df)
    vehicle = VehicleProfile(
        name="mvp4_truck",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=8000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )
    return TrafficabilityAssessor(
        vehicle=vehicle,
        weights={"slope": 0.30, "lc_factor": 0.25, "tri": 0.15, "soil": 0.15, "road_bonus": 0.15},
    ).assess(graph)


def _write_outputs(
    output_dir: str,
    builder: H3GridBuilder,
    h3_df: pd.DataFrame,
    graph: H3Graph,
    roi_source: str,
) -> dict[str, object]:
    output_root = Path(output_dir)
    parquet_path = output_root / OUTPUT_PARQUET_NAME
    gpkg_path = output_root / OUTPUT_GPKG_NAME
    manifest_path = output_root / OUTPUT_MANIFEST_NAME
    builder.save_parquet(h3_df, str(parquet_path))
    manifest = _continuous_manifest(builder, graph, roi_source, parquet_path, gpkg_path)
    GISExporter.write_manifest(str(manifest_path), manifest)
    GISExporter.export_graph_gpkg(
        graph,
        str(gpkg_path),
        theme_attributes=THEME_ATTRIBUTES,
        layer_metadata=manifest,
    )
    return manifest | {"output_gpkg": str(gpkg_path), "output_manifest": str(manifest_path)}


def _continuous_manifest(
    builder: H3GridBuilder,
    graph: H3Graph,
    roi_source: str,
    parquet_path: Path,
    gpkg_path: Path,
) -> dict[str, object]:
    return {
        "artifact_kind": "continuous_h3_graph",
        "cells_count": len(graph.cells),
        "coverage_mode": "h3_polyfill_roi",
        "edges_count": len(graph.edges),
        "generator": "demo/run_mvp4_continuous_roi.py",
        "is_continuous_coverage": True,
        "max_cells": builder.max_cells,
        "output_gpkg": str(gpkg_path),
        "output_parquet": str(parquet_path),
        "res_coarse": builder.res_coarse,
        "res_fine": builder.res_fine,
        "roi_source": roi_source,
    }


def _copy_assessment_fields(h3_df: pd.DataFrame, graph: H3Graph) -> pd.DataFrame:
    frame = h3_df.copy()
    for column in (
        "cone_index_kpa",
        "cost_score",
        "is_passable",
        "score",
        "sinkage_m",
        "sinkage_resistance",
        "soil_mobility",
    ):
        frame[column] = [
            getattr(graph.cells[str(row.h3index)], column) for row in frame.itertuples()
        ]
    return frame


def _first_existing(paths: tuple[Path, ...]) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError("No soil catalog file found in configured paths.")


def main() -> None:
    """Run the default bounded MVP-4 continuous ROI build."""
    manifest = run_continuous_roi_build()
    print(
        " ".join(
            [
                f"cells={manifest['cells_count']}",
                f"edges={manifest['edges_count']}",
                f"parquet={manifest['output_parquet']}",
                f"gpkg={manifest['output_gpkg']}",
            ]
        )
    )


if __name__ == "__main__":
    main()
