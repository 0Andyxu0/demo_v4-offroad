"""Validate whether a local raster is usable as a raw elevation DEM.

Usage:
    python scripts/validate_dem_asset.py D:/path/to/dem.tif
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio


def validate_dem_asset(path: Path) -> int:
    with rasterio.open(path) as src:
        print(f"path: {path}")
        print(f"driver: {src.driver}")
        print(f"size: {src.width} x {src.height}")
        print(f"crs: {src.crs}")
        print(f"bounds: {src.bounds}")
        print(f"res: {src.res}")
        print(f"nodata: {src.nodata}")
        print(f"dtype: {src.dtypes[0]}")
        arr = src.read(1, masked=True)
        total = arr.size
        valid = int(arr.count())
        nodata_ratio = 1.0 - valid / total
        finite = np.ma.compressed(arr)
        if finite.size == 0:
            print("ERROR: no valid pixels")
            return 2
        vmin = float(finite.min())
        vmax = float(finite.max())
        vmean = float(finite.mean())
        print(f"valid_pixels: {valid} / {total}")
        print(f"nodata_ratio: {nodata_ratio:.4f}")
        print(f"value_min: {vmin:.6f}")
        print(f"value_max: {vmax:.6f}")
        print(f"value_mean: {vmean:.6f}")

        problems: list[str] = []
        if nodata_ratio > 0.5:
            problems.append(f"nodata_ratio={nodata_ratio:.2%} exceeds 50%")
        if vmax <= 255.0:
            problems.append(
                "value_max<=255 suggests this may be a scaled/visualization raster, "
                "not a raw elevation DEM"
            )
        if src.crs is None:
            problems.append("missing CRS")

        if problems:
            print("DEM_VALIDATION_FAILED:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("DEM_VALIDATION_PASSED")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    return validate_dem_asset(args.path)


if __name__ == "__main__":
    raise SystemExit(main())

