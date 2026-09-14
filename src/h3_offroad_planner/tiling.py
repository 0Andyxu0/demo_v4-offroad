"""Tile-based H3 cache construction for MVP-4.1."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import cast

import geopandas as gpd
import h3
import numpy as np
import numpy.typing as npt
import pandas as pd
from affine import Affine
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.factor_model import canonical_hash, static_input_hash
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import (
    GISInputError,
    GridBuildError,
    H3Graph,
    SoilProfile,
    TileBuildRequest,
)
from h3_offroad_planner.preprocessing import GISPreprocessor, RasterLayer, RasterQuality

__all__ = ["build_h3_tile_cache"]

CRS_WGS84: str = "EPSG:4326"
TILE_MANIFEST_NAME: str = "tile_manifest.json"
TILE_CACHE_KIND: str = "tile_h3_cache"
TILE_COVERAGE_MODE: str = "h3_polyfill_tile_cache"
TerrainLayers = tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    Affine,
]


ProgressCallback = Callable[[str, int, str], None]


def build_h3_tile_cache(
    request: TileBuildRequest,
    progress: ProgressCallback | None = None,
    progress_range: tuple[int, int] = (10, 50),
) -> dict[str, object]:
    """Build a resumable H3 tile cache from raw GIS inputs.

    Args:
        request: Valid tile build request. Unit: file paths and H3 resolutions.
        progress: Optional callback for real-time tile build status updates.
        progress_range: Bounded percentage interval (start, end) for progress mapping.

    Returns:
        JSON-serializable tile manifest.

    Raises:
        FileNotFoundError: If any required source path is missing.
        GridBuildError: If ROI tiling exceeds limits or a tile fails while
            `continue_on_error=False`.
        GISInputError: If GIS source layers cannot be read.
    """
    preprocessor = GISPreprocessor()
    dem_quality = preprocessor.inspect_raster(request.dem_path)
    roi_geometry = _load_roi_geometry(request.roi_layer_path)
    tile_ids = _tile_ids_for_roi(roi_geometry, request.tile_res, request.max_tiles)
    dem, affine, _ = preprocessor.load_dem(request.dem_path)
    slope = preprocessor.compute_slope(dem, affine)
    tri = preprocessor.compute_tri(dem)
    landcover = preprocessor.load_landcover(request.landcover_path)
    soil = preprocessor.load_soil(request.soil_path)
    soil_catalog = _load_soil_catalog(preprocessor, request)
    roads = preprocessor.load_road_network(request.road_path)
    drainage = preprocessor.load_soil(request.drainage_path)
    twi = preprocessor.load_soil(request.twi_path)
    drainage_validity = preprocessor.load_soil(request.drainage_validity_path)
    drainage_boundary = preprocessor.load_soil(request.drainage_boundary_path)
    tile_records = []
    total_tiles = len(tile_ids)
    start_pct, end_pct = progress_range
    pct_span = max(0, end_pct - start_pct)
    stride = max(1, total_tiles // 100) if total_tiles > 50 else 1
    for idx, tile_id in enumerate(tile_ids, 1):
        tile_records.append(
            _build_tile_record(
                request,
                tile_id,
                roi_geometry,
                (dem, slope, tri, affine),
                landcover,
                soil,
                soil_catalog,
                roads,
                drainage,
                twi,
                drainage_validity,
                drainage_boundary,
            )
        )
        if progress is not None and (idx % stride == 0 or idx == total_tiles):
            pct = start_pct + int(pct_span * (idx / total_tiles))
            progress("build_map", pct, f"building tile cache: [{idx}/{total_tiles}]")
    manifest = _tile_manifest(request, tile_records, dem_quality)
    GISExporter.write_manifest(str(Path(request.output_dir) / TILE_MANIFEST_NAME), manifest)
    return manifest


def _load_roi_geometry(path: str) -> BaseGeometry:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(path)
    try:
        gdf = gpd.read_file(input_path)
    except (OSError, ValueError) as exc:
        raise GISInputError(f"failed to read ROI layer: {path}") from exc
    if gdf.empty:
        raise GISInputError(f"ROI layer must not be empty: {path}")
    if gdf.crs is not None and gdf.crs.to_string() != CRS_WGS84:
        gdf = gdf.to_crs(CRS_WGS84)
    geometry = cast(BaseGeometry, gdf.geometry.union_all())
    if geometry.is_empty or geometry.area <= 0.0:
        raise GridBuildError("ROI geometry must be non-empty with positive area.")
    return geometry


def _tile_ids_for_roi(roi_geometry: BaseGeometry, tile_res: int, max_tiles: int) -> list[str]:
    candidates = _polygon_cells(roi_geometry, tile_res)
    candidates.update(_boundary_tile_candidates(roi_geometry, tile_res))
    tiles = sorted(
        tile_id for tile_id in candidates if _h3_polygon(tile_id).intersects(roi_geometry)
    )
    if not tiles:
        raise GridBuildError("ROI tile split produced no parent H3 tiles.")
    if len(tiles) > max_tiles:
        raise GridBuildError(
            f"ROI parent tile count {len(tiles)} exceeds max_tiles={max_tiles}; "
            "shrink ROI, increase tile_res only for smaller jobs, or split the request."
        )
    return tiles


def _build_tile_record(
    request: TileBuildRequest,
    tile_id: str,
    roi_geometry: BaseGeometry,
    terrain: TerrainLayers,
    landcover: RasterLayer | gpd.GeoDataFrame,
    soil: RasterLayer | None,
    soil_catalog: dict[int, SoilProfile],
    roads: gpd.GeoDataFrame | None,
    drainage: RasterLayer | None,
    twi: RasterLayer | None,
    drainage_validity: RasterLayer | None,
    drainage_boundary: RasterLayer | None,
) -> dict[str, object]:
    output_path = _tile_output_path(request.output_dir, request.tile_res, tile_id)
    try:
        if output_path.exists() and not request.overwrite:
            return _skipped_tile_record(request, tile_id, output_path)
        record = _completed_tile_record(
            request,
            tile_id,
            roi_geometry,
            terrain,
            landcover,
            soil,
            soil_catalog,
            roads,
            drainage,
            twi,
            drainage_validity,
            drainage_boundary,
            output_path,
        )
    except (GISInputError, GridBuildError, OSError, ValueError) as exc:
        if isinstance(exc, GridBuildError) and _is_empty_tile_error(exc):
            return _empty_tile_record(tile_id, str(exc))
        if not request.continue_on_error:
            raise GridBuildError(f"tile {tile_id} failed: {exc}") from exc
        record = _failed_tile_record(tile_id, str(exc))
    return record


def _completed_tile_record(
    request: TileBuildRequest,
    tile_id: str,
    roi_geometry: BaseGeometry,
    terrain: TerrainLayers,
    landcover: RasterLayer | gpd.GeoDataFrame,
    soil: RasterLayer | None,
    soil_catalog: dict[int, SoilProfile],
    roads: gpd.GeoDataFrame | None,
    drainage: RasterLayer | None,
    twi: RasterLayer | None,
    drainage_validity: RasterLayer | None,
    drainage_boundary: RasterLayer | None,
    output_path: Path,
) -> dict[str, object]:
    dem, slope, tri, affine = terrain
    tile_roi = roi_geometry.intersection(_h3_polygon(tile_id))
    builder = H3GridBuilder(
        res_fine=request.res_fine,
        res_coarse=request.tile_res,
        max_cells=request.max_cells_per_tile,
    )
    h3_df = builder.tile_to_h3(dem, slope, tri, affine, tile_id, roi_geometry)
    h3_df = builder.attach_landcover(h3_df, landcover)
    h3_df = builder.attach_soil(h3_df, soil, soil_catalog)
    h3_df = builder.attach_roads(h3_df, roads)
    h3_df = builder.attach_drainage(
        h3_df,
        drainage,
        twi,
        drainage_validity,
        drainage_boundary,
    )
    graph = builder.build_graph(h3_df)
    static_hash = static_input_hash(graph)
    static_frame = _static_fact_frame(h3_df, graph, request.sampling_mode, static_hash)
    builder.save_parquet(static_frame, str(output_path))
    return _tile_record(
        tile_id=tile_id,
        status="completed",
        path=str(output_path),
        cells_count=len(graph.cells),
        edges_count=len(graph.edges),
        bounds=_bounds_tuple(tile_roi.bounds),
        static_hash=static_hash,
        statistics=_static_statistics(static_frame),
    )


def _skipped_tile_record(
    request: TileBuildRequest,
    tile_id: str,
    output_path: Path,
) -> dict[str, object]:
    builder = H3GridBuilder(res_fine=request.res_fine, res_coarse=request.tile_res)
    frame = builder.load_parquet(str(output_path))
    graph = builder.build_graph(frame)
    static_hash = static_input_hash(graph)
    return _tile_record(
        tile_id=tile_id,
        status="skipped",
        path=str(output_path),
        cells_count=len(graph.cells),
        edges_count=len(graph.edges),
        bounds=_bounds_tuple(_h3_polygon(tile_id).bounds),
        static_hash=static_hash,
        statistics=_static_statistics(
            _static_fact_frame(frame, graph, request.sampling_mode, static_hash)
        ),
    )


def _failed_tile_record(tile_id: str, error: str) -> dict[str, object]:
    return _tile_record(
        tile_id=tile_id,
        status="failed",
        path=None,
        cells_count=0,
        edges_count=0,
        bounds=_bounds_tuple(_h3_polygon(tile_id).bounds),
        error=error,
    )


def _empty_tile_record(tile_id: str, error: str) -> dict[str, object]:
    return _tile_record(
        tile_id=tile_id,
        status="empty",
        path=None,
        cells_count=0,
        edges_count=0,
        bounds=_bounds_tuple(_h3_polygon(tile_id).bounds),
        error=error,
    )


def _is_empty_tile_error(exc: GridBuildError) -> bool:
    message = str(exc)
    return (
        "polyfill produced no cells" in message
        or "must be non-empty with positive area" in message
        or "outside valid DEM terrain" in message
        or "tile contains no cells on valid DEM terrain" in message
    )


def _tile_record(
    tile_id: str,
    status: str,
    path: str | None,
    cells_count: int,
    edges_count: int,
    bounds: tuple[float, float, float, float],
    error: str | None = None,
    static_hash: str | None = None,
    statistics: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "bounds": list(bounds),
        "cells_count": cells_count,
        "edges_count": edges_count,
        "error": error,
        "parent_h3": tile_id,
        "path": path,
        "static_input_hash": static_hash,
        "statistics": statistics or {},
        "status": status,
    }


def _bounds_tuple(bounds: tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(bounds) != 4:
        raise GridBuildError(f"expected 4 geometry bounds, got {len(bounds)}.")
    return (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))


def _static_fact_frame(
    h3_df: pd.DataFrame,
    graph: H3Graph,
    sampling_mode: str,
    static_hash: str,
) -> pd.DataFrame:
    """Return vehicle-neutral facts with explicit exact adjacency metadata."""
    frame = h3_df.copy()
    vehicle_columns = (
        "cone_index_kpa",
        "cost_score",
        "score",
        "sinkage_m",
        "sinkage_resistance",
        "soil_mobility",
    )
    frame = frame.drop(columns=[column for column in vehicle_columns if column in frame.columns])
    adjacency: dict[str, dict[str, float]] = {cell_id: {} for cell_id in graph.cells}
    for edge in graph.edges.values():
        adjacency[edge.cell_a][edge.cell_b] = edge.geo_distance
        adjacency[edge.cell_b][edge.cell_a] = edge.geo_distance
    frame["adjacency_json"] = frame["h3index"].map(
        lambda cell_id: json.dumps(adjacency[str(cell_id)], sort_keys=True, separators=(",", ":"))
    )
    frame["edge_length_m"] = frame["h3index"].map(
        lambda cell_id: _mean_edge_length(adjacency[str(cell_id)])
    )
    frame["nodata"] = frame[["elevation", "slope", "tri", "landcover_code"]].isna().any(axis=1)
    frame["sampling_mode"] = sampling_mode
    frame["static_input_hash"] = static_hash
    return frame


def _mean_edge_length(neighbors: dict[str, float]) -> float | None:
    return sum(neighbors.values()) / len(neighbors) if neighbors else None


def _static_statistics(frame: pd.DataFrame) -> dict[str, object]:
    """Return deterministic robust statistics and missing ratios for one Tile."""
    statistics: dict[str, object] = {}
    for column in ("elevation", "slope", "tri"):
        values = pd.to_numeric(frame[column], errors="coerce")
        statistics[column] = {
            "q50": float(values.quantile(0.50)),
            "q90": float(values.quantile(0.90)),
            "missing_ratio": float(values.isna().mean()),
        }
    for column in (
        "landcover_code",
        "soil_code",
        "soil_moisture",
        "twi",
        "drainage_sensitivity",
        "surface_response",
    ):
        if column in frame.columns:
            statistics[column] = {"missing_ratio": float(frame[column].isna().mean())}
    return statistics


def _tile_manifest(
    request: TileBuildRequest,
    tile_records: list[dict[str, object]],
    dem_quality: RasterQuality,
) -> dict[str, object]:
    statuses = Counter(str(record["status"]) for record in tile_records)
    return {
        "artifact_kind": TILE_CACHE_KIND,
        "cells_count": sum(_record_int(record, "cells_count") for record in tile_records),
        "coverage_mode": TILE_COVERAGE_MODE,
        "dem_quality": _quality_payload(dem_quality),
        "edges_count": sum(_record_int(record, "edges_count") for record in tile_records),
        "is_continuous_coverage": True,
        "max_cells_per_tile": request.max_cells_per_tile,
        "max_tiles": request.max_tiles,
        "output_dir": request.output_dir,
        "res_fine": request.res_fine,
        "sampling_mode": request.sampling_mode,
        "static_sources": {
            "dem": request.dem_path,
            "landcover": request.landcover_path,
            "road": request.road_path,
            "soil": request.soil_path,
            "soil_catalog": request.soil_catalog_path,
            "twi": request.twi_path,
            "drainage": request.drainage_path,
            "drainage_validity": request.drainage_validity_path,
            "drainage_boundary": request.drainage_boundary_path,
        },
        "schema_version": 2,
        "tile_fact_authority": "vehicle_independent",
        "authority_for_new_routing": {
            "score": False,
            "cost_score": False,
            "sinkage_m": False,
            "is_passable": "physical_static_only",
        },
        "static_input_hash": canonical_hash(
            [
                record.get("static_input_hash")
                for record in tile_records
                if record.get("static_input_hash") is not None
            ]
        ),
        "status_counts": dict(statuses),
        "tile_res": request.tile_res,
        "tiles": tile_records,
    }


def _quality_payload(quality: RasterQuality) -> dict[str, object]:
    """Return JSON-safe quality fields without coupling manifests to raster classes."""
    return {
        "crs": quality.crs,
        "finite_max": quality.finite_max,
        "finite_min": quality.finite_min,
        "height": quality.height,
        "nodata_ratio": quality.nodata_ratio,
        "width": quality.width,
    }


def _record_int(record: dict[str, object], key: str) -> int:
    value = record[key]
    if isinstance(value, bool):
        raise GridBuildError(f"manifest field must be an integer: {key}")
    if isinstance(value, int):
        return value
    raise GridBuildError(f"manifest field must be an integer: {key}")


def _load_soil_catalog(
    preprocessor: GISPreprocessor,
    request: TileBuildRequest,
) -> dict[int, SoilProfile]:
    if request.soil_catalog_path is None:
        return {}
    return preprocessor.load_soil_catalog(request.soil_catalog_path)


def _tile_output_path(output_dir: str, tile_res: int, tile_id: str) -> Path:
    return Path(output_dir) / "tiles" / f"parent_res={tile_res}" / f"parent_h3={tile_id}.parquet"


def _polygon_cells(roi_geometry: BaseGeometry, resolution: int) -> set[str]:
    if isinstance(roi_geometry, Polygon):
        return _single_polygon_cells(roi_geometry, resolution)
    if isinstance(roi_geometry, MultiPolygon):
        cells: set[str] = set()
        for polygon in roi_geometry.geoms:
            cells.update(_single_polygon_cells(polygon, resolution))
        return cells
    raise GridBuildError("ROI geometry must be a Polygon or MultiPolygon.")


def _single_polygon_cells(polygon: Polygon, resolution: int) -> set[str]:
    outer = [(lat, lng) for lng, lat in polygon.exterior.coords]
    holes = [[(lat, lng) for lng, lat in ring.coords] for ring in polygon.interiors]
    return {str(cell) for cell in h3.polygon_to_cells(h3.LatLngPoly(outer, *holes), resolution)}


def _boundary_tile_candidates(roi_geometry: BaseGeometry, tile_res: int) -> set[str]:
    candidates: set[str] = set()
    for lng, lat in _geometry_sample_points(roi_geometry):
        cell_id = str(h3.latlng_to_cell(float(lat), float(lng), tile_res))
        candidates.update(str(cell) for cell in h3.grid_disk(cell_id, 1))
    return candidates


def _geometry_sample_points(geometry: BaseGeometry) -> list[tuple[float, float]]:
    points = [(geometry.representative_point().x, geometry.representative_point().y)]
    if isinstance(geometry, Polygon):
        points.extend(list(geometry.exterior.coords))
    elif isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            points.append((polygon.representative_point().x, polygon.representative_point().y))
            points.extend(list(polygon.exterior.coords))
    return [(float(lng), float(lat)) for lng, lat in points]


def _h3_polygon(h3index: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3index)])
