"""Tests for the DEM asset validation helper."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_dem_asset.py"
_spec = importlib.util.spec_from_file_location("validate_dem_asset", _SCRIPT)
assert _spec is not None
validate_dem_asset = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(validate_dem_asset)

_OUTPUT_DIR = Path(__file__).resolve().parents[1] / ".artifacts" / "dem_validation_tests"


def _write_dem(name: str, values: np.ndarray, nodata: float) -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUTPUT_DIR / f"{name}-{uuid.uuid4().hex}.tif"
    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": values.dtype,
        "crs": "EPSG:4326",
        "transform": from_origin(118.0, 32.0, 0.000277, 0.000277),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values, 1)
    return path


def test_dem_asset_validation_accepts_raw_elevation() -> None:
    path = _write_dem("raw", np.arange(100, 500, dtype=np.int16).reshape(20, 20), -9999)

    assert validate_dem_asset.validate_dem_asset(path) == 0


def test_dem_asset_validation_rejects_visualization_like_raster() -> None:
    path = _write_dem("viz", np.arange(0, 256, dtype=np.uint8).reshape(16, 16), 255)

    assert validate_dem_asset.validate_dem_asset(path) == 1
