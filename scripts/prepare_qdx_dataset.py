"""Audit, validate, and optionally merge QDX vector shapefiles for H3 planning."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import rasterio

TARGET_CRS: str = "EPSG:4326"
LANDCOVER_FILES: tuple[str, ...] = (
    "water.shp",
    "forest.shp",
    "grass.shp",
    "plowland.shp",
    "shrubwood.shp",
    "building.shp",
    "wasteland.shp",
)


@dataclass(frozen=True)
class QDXValidationReport:
    """Structured validation report for the raw QDX GIS dataset."""

    dem_shape: list[int]
    dem_bounds: list[float]
    bound_features: int
    bound_bounds: list[float]
    road_features: int
    landcover_layer_count: int


def validate_qdx_dataset(base_dir: Path) -> QDXValidationReport:
    """Validate all QDX GIS sources and return structured metadata."""
    dem_path = base_dir / "DEM-DSM" / "DEM_CGCS2000.tif"
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM raster missing: {dem_path}")
    with rasterio.open(dem_path) as src:
        dem_shape = [src.height, src.width]
        dem_bounds = [float(val) for val in src.bounds]

    bound_path = base_dir / "矢量数据" / "bound.shp"
    if not bound_path.exists():
        raise FileNotFoundError(f"ROI bound vector missing: {bound_path}")
    bound_gdf = gpd.read_file(bound_path)
    bound_features = len(bound_gdf)
    bound_bounds = [float(val) for val in bound_gdf.total_bounds]

    road_path = base_dir / "road" / "road_fina.shp"
    if not road_path.exists():
        raise FileNotFoundError(f"Road network missing: {road_path}")
    road_gdf = gpd.read_file(road_path)
    road_features = len(road_gdf)

    vec_dir = base_dir / "矢量数据"
    layer_count = 0
    for filename in LANDCOVER_FILES:
        shp_file = vec_dir / filename
        if not shp_file.exists():
            raise FileNotFoundError(f"Landcover layer missing: {shp_file}")
        layer_count += 1

    return QDXValidationReport(
        dem_shape=dem_shape,
        dem_bounds=dem_bounds,
        bound_features=bound_features,
        bound_bounds=bound_bounds,
        road_features=road_features,
        landcover_layer_count=layer_count,
    )


def merge_landcover_layers(base_dir: Path, output_path: Path) -> gpd.GeoDataFrame:
    """Merge separate landcover shapefiles into a unified WGS84 GeoDataFrame."""
    vec_dir = base_dir / "矢量数据"
    frames: list[gpd.GeoDataFrame] = []
    for filename in LANDCOVER_FILES:
        shp_file = vec_dir / filename
        gdf = gpd.read_file(shp_file)
        if gdf.crs is not None and gdf.crs.to_string() != TARGET_CRS:
            gdf = gdf.to_crs(TARGET_CRS)
        frames.append(gdf)
    merged = pd.concat(frames, ignore_index=True)
    unified = gpd.GeoDataFrame(merged, crs=TARGET_CRS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".geojson":
        unified.to_file(output_path, driver="GeoJSON")
    else:
        unified.to_file(output_path)
    return cast(gpd.GeoDataFrame, unified)


def main() -> int:
    """Parse CLI arguments and run QDX validation and merging."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qdx-dir",
        default=r"D:\Workspace\qdx数据",
        help="Path to QDX raw data root directory",
    )
    parser.add_argument(
        "--merge-out",
        default=None,
        help="Optional path to write merged landcover shapefile or GeoJSON",
    )
    args = parser.parse_args()
    qdx_root = Path(args.qdx_dir)
    print(f"Validating QDX dataset at: {qdx_root}...")
    report = validate_qdx_dataset(qdx_root)
    print("Validation SUCCESS:")
    print(f"  DEM: {report.dem_shape}, bounds={report.dem_bounds}")
    print(f"  Bound: {report.bound_features} polygon, bounds={report.bound_bounds}")
    print(f"  Road: {report.road_features} lines")
    print(f"  Landcover layers: {report.landcover_layer_count} layers loaded")

    if args.merge_out:
        out_path = Path(args.merge_out)
        print(f"Merging landcover layers into: {out_path}...")
        merged_gdf = merge_landcover_layers(qdx_root, out_path)
        print(f"Merged {len(merged_gdf)} landcover features successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
