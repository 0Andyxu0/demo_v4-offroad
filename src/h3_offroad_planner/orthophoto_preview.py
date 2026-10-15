"""Create bounded WGS84 previews of local orthophoto rasters for desktop display.

The preview is strictly a visual verification aid.  It is not sampled by the
trafficability model and is deliberately kept outside the planning payload.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

__all__ = ["OrthophotoPreview", "create_orthophoto_preview"]


@dataclass(frozen=True)
class OrthophotoPreview:
    """Metadata required to draw a generated PNG preview as a Leaflet overlay."""

    source_path: str
    preview_path: str
    bounds_wgs84: list[list[float]]
    source_crs: str
    source_window: list[int]
    output_shape: list[int]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable metadata without reading any raster samples."""
        return asdict(self)


def create_orthophoto_preview(
    source_path: str | Path,
    preview_path: str | Path,
    study_bounds_wgs84: tuple[float, float, float, float],
    *,
    max_dimension: int = 2048,
) -> OrthophotoPreview:
    """Crop a local RGB orthophoto to the study area and save a PNG preview.

    ``study_bounds_wgs84`` is ordered as west, south, east, north.  The output
    contains at most ``max_dimension`` pixels along its longest side and carries
    the exact WGS84 bounds of the sampled source window for display only.
    """
    if max_dimension <= 0:
        raise ValueError("max_dimension must be positive.")
    source = Path(source_path)
    destination = Path(preview_path)
    if not source.is_file():
        raise FileNotFoundError(f"orthophoto raster does not exist: {source}")
    west, south, east, north = study_bounds_wgs84
    if not west < east or not south < north:
        raise ValueError("study bounds must be ordered west, south, east, north.")

    with rasterio.open(source) as dataset:
        if dataset.crs is None:
            raise ValueError("orthophoto raster has no CRS.")
        if dataset.count < 1:
            raise ValueError("orthophoto raster has no raster bands.")
        projected_bounds = transform_bounds(
            "EPSG:4326", dataset.crs, west, south, east, north, densify_pts=21
        )
        left = max(projected_bounds[0], dataset.bounds.left)
        bottom = max(projected_bounds[1], dataset.bounds.bottom)
        right = min(projected_bounds[2], dataset.bounds.right)
        top = min(projected_bounds[3], dataset.bounds.top)
        if not left < right or not bottom < top:
            raise ValueError("study area does not overlap the orthophoto raster.")
        source_window = from_bounds(left, bottom, right, top, dataset.transform)
        source_window = source_window.round_offsets().round_lengths()
        source_window = _clip_window(source_window, dataset.width, dataset.height)
        if source_window.width <= 0 or source_window.height <= 0:
            raise ValueError("orthophoto crop is empty after pixel alignment.")
        scale = min(1.0, max_dimension / max(source_window.width, source_window.height))
        output_width = max(1, round(source_window.width * scale))
        output_height = max(1, round(source_window.height * scale))
        indexes = tuple(range(1, min(dataset.count, 3) + 1))
        raster = dataset.read(
            indexes=indexes,
            window=source_window,
            out_shape=(len(indexes), output_height, output_width),
            resampling=Resampling.bilinear,
        )
        rgb = _rgb_uint8(raster)
        crop_bounds = rasterio.windows.bounds(source_window, dataset.transform)
        west_south_east_north = transform_bounds(
            dataset.crs, "EPSG:4326", *crop_bounds, densify_pts=21
        )
        source_crs = str(dataset.crs)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(
            destination,
            "w",
            driver="PNG",
            width=output_width,
            height=output_height,
            count=3,
            dtype="uint8",
        ) as output:
            output.write(rgb)
    overlay_bounds = [
        [west_south_east_north[1], west_south_east_north[0]],
        [west_south_east_north[3], west_south_east_north[2]],
    ]
    return OrthophotoPreview(
        source_path=str(source),
        preview_path=str(destination),
        bounds_wgs84=overlay_bounds,
        source_crs=source_crs,
        source_window=[
            int(source_window.col_off),
            int(source_window.row_off),
            int(source_window.width),
            int(source_window.height),
        ],
        output_shape=[output_height, output_width],
    )


def _clip_window(window: Window, width: int, height: int) -> Window:
    """Intersect a pixel window with a raster extent."""
    col_start = max(0, int(window.col_off))
    row_start = max(0, int(window.row_off))
    col_stop = min(width, int(window.col_off) + int(window.width))
    row_stop = min(height, int(window.row_off) + int(window.height))
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def _rgb_uint8(raster: np.ndarray) -> np.ndarray:
    """Return a three-band uint8 image without applying classification semantics."""
    if raster.ndim != 3 or raster.shape[0] == 0:
        raise ValueError("orthophoto sample must have at least one raster band.")
    if raster.shape[0] == 1:
        raster = np.repeat(raster, 3, axis=0)
    elif raster.shape[0] == 2:
        raster = np.concatenate((raster, raster[1:2]), axis=0)
    if raster.dtype == np.uint8:
        return raster[:3]
    converted = raster[:3].astype(np.float32, copy=False)
    finite = converted[np.isfinite(converted)]
    if finite.size == 0:
        return np.zeros(converted.shape, dtype=np.uint8)
    low, high = np.percentile(finite, (1.0, 99.0))
    if high <= low:
        high = low + 1.0
    return np.clip((converted - low) * (255.0 / (high - low)), 0.0, 255.0).astype(np.uint8)
