"""GIS preprocessing for raster/vector normalization and terrain derivatives."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from math import cos, radians
from pathlib import Path
from typing import cast

import geopandas as gpd
import numpy as np
import numpy.typing as npt
import pandas as pd
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

from h3_offroad_planner.models import GISInputError, SoilProfile

__all__ = ["GISPreprocessor", "RasterLayer", "RasterQuality"]

DEGREES_TO_METERS: float = 111_320.0
TARGET_CRS: str = "EPSG:4326"
DEFAULT_SOIL_MOISTURE: float = 0.20
WATER_SOIL_CODES: frozenset[int] = frozenset({18, 85})
URBAN_SOIL_CODES: frozenset[int] = frozenset({84})
PADDY_SOIL_CODES: frozenset[int] = frozenset({44, 55, 64, 80, 82, 90})
ALLUVIAL_SOIL_CODES: frozenset[int] = frozenset({26, 27, 72})
BROWN_RED_SOIL_CODES: frozenset[int] = frozenset({14, 22, 48, 49, 50, 58, 73, 74, 92, 184})
LITHIC_SOIL_CODES: frozenset[int] = frozenset({38, 47, 53, 96})
MARSH_SOIL_CODES: frozenset[int] = frozenset({17})


@dataclass(frozen=True)
class RasterLayer:
    """Lazy raster descriptor used for large GIS layers.

    Attributes:
        path: Raster file path. Unit: filesystem path.
        crs: Coordinate reference system string.
        width: Raster width. Unit: pixels.
        height: Raster height. Unit: pixels.
        bounds: Raster bounds as `(left, bottom, right, top)`.
        nodata: Optional nodata value.
        dtype: First-band data type.
    """

    path: Path
    crs: str
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    nodata: float | None
    dtype: str


@dataclass(frozen=True)
class RasterQuality:
    """Finite-value and metadata summary for one raster source."""

    crs: str
    finite_max: float | None
    finite_min: float | None
    height: int
    nodata_ratio: float
    width: int


class GISPreprocessor:
    """Load and normalize GIS sources for the H3 graph builder."""

    def __init__(self, target_crs: str = TARGET_CRS) -> None:
        """Initialize the preprocessor with a target CRS string."""
        if not target_crs:
            raise ValueError("target_crs must be a non-empty CRS string.")
        self.target_crs = target_crs

    def load_dem(self, path: str) -> tuple[npt.NDArray[np.float64], Affine, CRS]:
        """Load a DEM raster into memory and normalize it to the target CRS."""
        file_path = _require_existing_path(path)
        with rasterio.open(file_path) as src:
            if src.crs is None:
                raise GISInputError(f"DEM raster has no CRS: {path}")
            masked = src.read(1, masked=True).astype(np.float64)
            data = cast(npt.NDArray[np.float64], masked.filled(np.nan))
            if not np.isfinite(data).any():
                raise GISInputError(f"DEM raster has no finite terrain values: {path}")
            if src.crs.to_string() == self.target_crs:
                return data, src.transform, src.crs
            return self._reproject_dem(data, src, path)

    def inspect_raster(self, path: str) -> RasterQuality:
        """Summarize raster CRS, dimensions, finite range, and nodata ratio."""
        file_path = _require_existing_path(path)
        with rasterio.open(file_path) as src:
            if src.crs is None:
                raise GISInputError(f"raster has no CRS: {path}")
            data = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            finite = np.isfinite(data)
            finite_count = int(finite.sum())
            if finite_count == 0:
                raise GISInputError(f"raster has no finite values: {path}")
            return RasterQuality(
                crs=src.crs.to_string(),
                finite_max=float(np.nanmax(data)),
                finite_min=float(np.nanmin(data)),
                height=src.height,
                nodata_ratio=1.0 - finite_count / data.size,
                width=src.width,
            )

    def load_landcover(self, path: str) -> RasterLayer | gpd.GeoDataFrame:
        """Load landcover as a lazy raster layer or WGS84 vector GeoDataFrame.

        Args:
            path: Raster file path, single vector file path, or directory containing shapefiles.
                Unit: filesystem path. Must exist.

        Returns:
            RasterLayer for TIF rasters or GeoDataFrame for normalized WGS84 vectors.

        Raises:
            FileNotFoundError: If the path does not exist.
            GISInputError: If vectors have no CRS or directory contains no vector files.
        """
        file_path = _require_existing_path(path)
        if file_path.is_dir():
            return self._vector_directory(file_path)
        if file_path.suffix.lower() in {".tif", ".tiff"}:
            return self._raster_layer(file_path)
        return self._vector_layer(file_path)

    def load_soil(self, path: str | None) -> RasterLayer | None:
        """Load optional soil raster metadata without reading the full raster."""
        if path is None:
            return None
        return self._raster_layer(_require_existing_path(path))

    def load_soil_catalog(self, path: str) -> dict[int, SoilProfile]:
        """Load a soil code catalog from `Export_Output.txt` style CSV data."""
        rows = _read_soil_catalog_rows(_require_existing_path(path))
        catalog: dict[int, SoilProfile] = {}
        for row in rows:
            code, name_zh = _parse_soil_catalog_row(row)
            if code in catalog:
                raise GISInputError(f"duplicate soil code in catalog: {code}")
            catalog[code] = _profile_from_soil_code(code, name_zh)
        if not catalog:
            raise GISInputError(f"soil catalog is empty: {path}")
        return catalog

    def load_road_network(self, path: str | None) -> gpd.GeoDataFrame | None:
        """Load optional road network vectors into the target CRS."""
        if path is None:
            return None
        return self._vector_layer(_require_existing_path(path))

    def compute_slope(
        self,
        dem: npt.NDArray[np.float64],
        affine: Affine,
    ) -> npt.NDArray[np.float64]:
        """Compute slope in degrees from a DEM matrix."""
        _require_non_empty_matrix("dem", dem)
        center_lat = _center_latitude(dem, affine)
        meters_per_degree_lng = DEGREES_TO_METERS * max(cos(radians(center_lat)), 0.01)
        x_res_m = max(abs(float(affine.a)) * meters_per_degree_lng, 1.0)
        y_res_m = max(abs(float(affine.e)) * DEGREES_TO_METERS, 1.0)
        grad_y, grad_x = np.gradient(np.nan_to_num(dem, nan=0.0), y_res_m, x_res_m)
        slope = np.degrees(np.arctan(np.hypot(grad_x, grad_y)))
        return cast(npt.NDArray[np.float64], slope)

    def compute_tri(self, dem: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Compute terrain ruggedness index as mean absolute neighbor difference."""
        _require_non_empty_matrix("dem", dem)
        filled = np.nan_to_num(dem, nan=0.0)
        tri_sum = np.zeros_like(filled, dtype=np.float64)
        counts = np.zeros_like(filled, dtype=np.float64)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx != 0 or dy != 0:
                    _accumulate_neighbor_difference(filled, tri_sum, counts, dy, dx)
        return cast(npt.NDArray[np.float64], np.divide(tri_sum, counts, where=counts > 0))

    def _raster_layer(self, path: Path) -> RasterLayer:
        with rasterio.open(path) as src:
            if src.crs is None:
                raise GISInputError(f"raster has no CRS: {path}")
            if src.crs.to_string() != self.target_crs:
                raise GISInputError(
                    f"large raster must be pre-projected to {self.target_crs}: {path}"
                )
            bounds = (
                float(src.bounds.left),
                float(src.bounds.bottom),
                float(src.bounds.right),
                float(src.bounds.top),
            )
            nodata = None if src.nodata is None else float(src.nodata)
            return RasterLayer(
                path=path,
                crs=src.crs.to_string(),
                width=src.width,
                height=src.height,
                bounds=bounds,
                nodata=nodata,
                dtype=src.dtypes[0],
            )

    def _vector_layer(self, path: Path) -> gpd.GeoDataFrame:
        try:
            gdf = gpd.read_file(path, layer=path.stem)
        except Exception:
            gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise GISInputError(f"vector layer has no CRS: {path}")
        if gdf.crs.to_string() != self.target_crs:
            gdf = gdf.to_crs(self.target_crs)
        return cast(gpd.GeoDataFrame, gdf)

    def _vector_directory(self, path: Path) -> gpd.GeoDataFrame:
        vector_files = sorted(
            [
                item
                for item in path.iterdir()
                if item.is_file()
                and item.suffix.lower() in {".shp", ".geojson"}
                and item.stem.lower() != "bound"
            ]
        )
        if not vector_files:
            raise GISInputError(f"no vector files found in landcover directory: {path}")
        frames: list[gpd.GeoDataFrame] = []
        for file_item in vector_files:
            frames.append(self._vector_layer(file_item))
        merged = pd.concat(frames, ignore_index=True)
        return cast(gpd.GeoDataFrame, gpd.GeoDataFrame(merged, crs=self.target_crs))

    def _reproject_dem(
        self,
        data: npt.NDArray[np.float64],
        src: rasterio.io.DatasetReader,
        path: str,
    ) -> tuple[npt.NDArray[np.float64], Affine, CRS]:
        dst_crs = CRS.from_string(self.target_crs)
        transform, width, height = calculate_default_transform(
            src.crs,
            dst_crs,
            src.width,
            src.height,
            *src.bounds,
        )
        destination = np.empty((height, width), dtype=np.float64)
        reproject(
            source=data,
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
        if destination.size == 0:
            raise GISInputError(f"DEM reprojection produced an empty raster: {path}")
        return cast(npt.NDArray[np.float64], destination), transform, dst_crs


def _require_existing_path(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(path)
    return file_path


def _read_soil_catalog_rows(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as file_obj:
                return list(csv.DictReader(file_obj))
        except UnicodeDecodeError:
            continue
    raise GISInputError(f"soil catalog encoding is not supported: {path}")


def _parse_soil_catalog_row(row: dict[str, str]) -> tuple[int, str]:
    code_text = row.get("VALUE", "").strip()
    name_zh = row.get("亚类名", "").strip()
    if not code_text or not name_zh:
        raise GISInputError(f"soil catalog row is missing VALUE or 亚类名: {row!r}")
    try:
        return int(code_text), name_zh
    except ValueError as exc:
        raise GISInputError(f"soil catalog VALUE is not an integer: {code_text!r}") from exc


def _profile_from_soil_code(code: int, name_zh: str) -> SoilProfile:
    texture, uscs, bekker_soil = _soil_texture_mapping(code)
    return SoilProfile(
        code=code,
        name_zh=name_zh,
        soil_texture=texture,
        uscs=uscs,
        bekker_soil=bekker_soil,
        soil_moisture=(
            None if code in WATER_SOIL_CODES | URBAN_SOIL_CODES else DEFAULT_SOIL_MOISTURE
        ),
        is_passable=code not in WATER_SOIL_CODES,
    )


def _soil_texture_mapping(code: int) -> tuple[str | None, str | None, str | None]:
    if code in WATER_SOIL_CODES | URBAN_SOIL_CODES:
        return None, None, None
    if code in PADDY_SOIL_CODES | MARSH_SOIL_CODES or code == 92:
        return "ClLo", "CL", "clayloam"
    if code in ALLUVIAL_SOIL_CODES:
        return "SiLo", "ML", "loam"
    if code in LITHIC_SOIL_CODES:
        return "SaLo", "SM", "loam"
    if code in BROWN_RED_SOIL_CODES:
        return "Lo", "CL", "loam"
    return None, None, None


def _require_non_empty_matrix(name: str, matrix: npt.NDArray[np.float64]) -> None:
    if matrix.ndim != 2 or matrix.size == 0:
        raise ValueError(f"{name} must be a non-empty 2D matrix.")


def _center_latitude(matrix: npt.NDArray[np.float64], affine: Affine) -> float:
    _, latitude = affine * (matrix.shape[1] / 2.0, matrix.shape[0] / 2.0)
    return float(latitude)


def _accumulate_neighbor_difference(
    dem: npt.NDArray[np.float64],
    tri_sum: npt.NDArray[np.float64],
    counts: npt.NDArray[np.float64],
    dy: int,
    dx: int,
) -> None:
    src_y = slice(max(0, -dy), dem.shape[0] - max(0, dy))
    src_x = slice(max(0, -dx), dem.shape[1] - max(0, dx))
    dst_y = slice(max(0, dy), dem.shape[0] - max(0, -dy))
    dst_x = slice(max(0, dx), dem.shape[1] - max(0, -dx))
    tri_sum[dst_y, dst_x] += np.abs(dem[dst_y, dst_x] - dem[src_y, src_x])
    counts[dst_y, dst_x] += 1.0
