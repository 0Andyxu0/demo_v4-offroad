"""Merge and crop Copernicus 30m DEM tiles for QDX upstream analysis.

Usage:
    python scripts/prepare_copernicus_dem.py \
        --input data/dem_copernicus_30m \
        --output data/dem_copernicus_30m/qdx_upstream_30m.tif \
        --bounds 118.85 31.85 119.15 32.15
"""

from __future__ import annotations

import argparse
from pathlib import Path

import rasterio
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.windows import from_bounds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bounds", type=float, nargs=4, required=True,
                        help="west south east north")
    args = parser.parse_args()

    paths = sorted(args.input.glob("*.tif"))
    if not paths:
        raise SystemExit(f"no GeoTIFF files found in {args.input}")

    mosaic, transform = merge(paths)
    west, south, east, north = args.bounds
    window = from_bounds(west, south, east, north, transform)
    window = window.round_lengths().round_offsets()
    row_start = int(window.row_off)
    row_end = int(window.row_off + window.height)
    col_start = int(window.col_off)
    col_end = int(window.col_off + window.width)
    cropped = mosaic[0, row_start:row_end, col_start:col_end]
    ul_x, ul_y = rasterio.transform.xy(
        transform, int(window.row_off), int(window.col_off), offset="ul"
    )
    out_transform = from_origin(ul_x, ul_y, abs(transform.a), abs(transform.e))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": cropped.shape[0],
        "width": cropped.shape[1],
        "count": 1,
        "dtype": cropped.dtype,
        "crs": "EPSG:4326",
        "transform": out_transform,
        "compress": "deflate",
    }
    with rasterio.open(args.output, "w", **profile) as dst:
        dst.write(cropped, 1)
    print(f"wrote {args.output} {cropped.shape[1]}x{cropped.shape[0]}")

    with rasterio.open(args.output) as src:
        arr = src.read(1, masked=True)
        print(f"bounds: {src.bounds}")
        print(f"res: {src.res}")
        print(f"valid: {arr.count()} / {arr.size}")
        print(f"min/max/mean: {arr.min():.3f} / {arr.max():.3f} / {arr.mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

