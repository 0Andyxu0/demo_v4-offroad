"""Sampled H3 graph construction from real GIS rasters and vectors."""

from __future__ import annotations

import logging
from math import atan2, cos, degrees, inf, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import Protocol, cast

import geopandas as gpd
import h3
import numpy as np
import numpy.typing as npt
import pandas as pd
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as transform_coordinates
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

from h3_offroad_planner.models import GridBuildError, H3Cell, H3Edge, H3Graph, SoilProfile
from h3_offroad_planner.preprocessing import RasterLayer

__all__ = ["H3GridBuilder"]

EARTH_RADIUS_M: float = 6_371_000.0
DEFAULT_ROAD_BUFFER_DEG: float = 0.001
AREA_DOMINANCE_MAX_PIXELS: int = 250_000
LOGGER = logging.getLogger(__name__)
CRS_WGS84: str = "EPSG:4326"
LANDCOVER_CODE_COLUMNS: tuple[str, ...] = (
    "fclass",
    "FCLASS",
    "landcover_code",
    "lc_code",
    "code",
    "value",
    "DN",
    "gridcode",
    "type",
    "Type",
)
FCLASS_CODE_MAPPING: dict[str, int] = {
    "water": 5,
    "01": 5,
    "forest": 2,
    "02": 2,
    "grass": 3,
    "grassland": 3,
    "03": 3,
    "plowland": 1,
    "cropland": 1,
    "04": 1,
    "shrubwood": 4,
    "shrubland": 4,
    "05": 4,
    "building": 6,
    "06": 6,
    "wasteland": 7,
    "barren": 7,
    "07": 7,
    "road": 8,
}
LAND_COVER_FACTORS: dict[int, float] = {
    0: inf,
    1: 1.20,
    2: 1.35,
    3: 1.30,
    4: 1.10,
    5: inf,
    6: inf,
    7: 1.50,
    8: 0.85,
    9: 1.60,
}
LAND_COVER_TYPES: dict[int, str] = {
    0: "unclassified",
    1: "cropland",
    2: "forest",
    3: "grassland",
    4: "shrubland",
    5: "water",
    6: "building",
    7: "barren",
    8: "impervious",
    9: "other",
}


class _SpatialIndex(Protocol):
    def query(self, geometry: object, predicate: str | None = None) -> npt.NDArray[np.intp]:
        """Return spatial index matches for a geometry."""


class H3GridBuilder:
    """Build sampled or ROI-continuous H3 graphs from normalized GIS layers."""

    COMPACT: bool = False

    def __init__(
        self,
        res_fine: int = 14,
        res_coarse: int = 11,
        sample_stride: int = 1,
        max_cells: int | None = None,
        road_buffer_deg: float = DEFAULT_ROAD_BUFFER_DEG,
        land_cover_factors: dict[int, float] | None = None,
        default_landcover_factor: float = 1.40,
    ) -> None:
        """Initialize a sampled H3 grid builder."""
        if res_coarse < 0 or res_fine <= res_coarse:
            raise ValueError("res_fine must be greater than res_coarse >= 0.")
        if sample_stride <= 0:
            raise ValueError("sample_stride must be positive.")
        if max_cells is not None and max_cells <= 0:
            raise ValueError("max_cells must be positive when provided.")
        if road_buffer_deg <= 0.0:
            raise ValueError("road_buffer_deg must be positive.")
        if not isfinite(default_landcover_factor) or default_landcover_factor <= 0.0:
            raise ValueError("default_landcover_factor must be finite and positive.")
        self.res_fine = res_fine
        self.res_coarse = res_coarse
        self.sample_stride = sample_stride
        self.max_cells = max_cells
        self.road_buffer_deg = road_buffer_deg
        self.land_cover_factors = _landcover_factors(land_cover_factors)
        self.default_landcover_factor = default_landcover_factor

    def raster_to_h3(
        self,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
    ) -> pd.DataFrame:
        """Convert sampled DEM-derived matrices into a fine-resolution H3 table."""
        if dem.shape != slope.shape or dem.shape != tri.shape:
            raise GridBuildError("dem, slope, and tri matrices must have the same shape.")
        records = self._sample_dem_records(dem, slope, tri, affine)
        if not records:
            raise GridBuildError("raster sampling produced no valid H3 cells.")
        return _h3_frame_from_records(records)

    def roi_to_h3(
        self,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
        roi_geometry: BaseGeometry,
        *,
        allow_uncovered: bool = False,
    ) -> pd.DataFrame:
        """Convert a WGS84 ROI polygon into a continuous fine-resolution H3 table."""
        if dem.shape != slope.shape or dem.shape != tri.shape:
            raise GridBuildError("dem, slope, and tri matrices must have the same shape.")
        cell_ids = _roi_polyfill_cells(roi_geometry, self.res_fine, self.max_cells)
        records = [
            self._record_from_cell_center(cell_id, dem, slope, tri, affine) for cell_id in cell_ids
        ]
        valid_records = [record for record in records if record is not None]
        if not allow_uncovered and len(valid_records) < len(records):
            missing = len(records) - len(valid_records)
            raise GridBuildError(
                f"ROI contains {missing} H3 cells outside valid DEM terrain; "
                "shrink ROI, repair DEM, or use tiled construction."
            )
        if not valid_records:
            raise GridBuildError("ROI polyfill produced no cells on valid DEM terrain.")
        return _h3_frame_from_records(valid_records)

    def tile_to_h3(
        self,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
        tile_id: str,
        roi_geometry: BaseGeometry | None = None,
    ) -> pd.DataFrame:
        """Convert a parent H3 tile into a fine-resolution H3 table using exact hierarchy."""
        if dem.shape != slope.shape or dem.shape != tri.shape:
            raise GridBuildError("dem, slope, and tri matrices must have the same shape.")
        cell_ids = sorted(h3.cell_to_children(tile_id, self.res_fine))
        if roi_geometry is not None:
            cell_ids = [
                c
                for c in cell_ids
                if roi_geometry.intersects(Point(h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]))
                or roi_geometry.intersects(_h3_polygon(c))
            ]
        records = [
            self._record_from_cell_center(cell_id, dem, slope, tri, affine) for cell_id in cell_ids
        ]
        valid_records = [record for record in records if record is not None]
        if not valid_records:
            raise GridBuildError("tile contains no cells on valid DEM terrain.")
        return _h3_frame_from_records(valid_records)

    def attach_landcover(
        self,
        h3_df: pd.DataFrame,
        landcover: RasterLayer | gpd.GeoDataFrame,
    ) -> pd.DataFrame:
        """Attach landcover resistance factors to an H3 table."""
        frame = _require_h3_frame(h3_df)
        if isinstance(landcover, RasterLayer):
            values = _sample_raster_values(landcover, frame)
            codes = [_landcover_code(value, landcover.nodata) for value in values]
            factors = [
                _landcover_factor_for_code(
                    code,
                    self.land_cover_factors,
                    self.default_landcover_factor,
                )
                for code in codes
            ]
            frame["landcover_code"] = codes
            frame["landcover_type"] = [_landcover_type(code) for code in codes]
            frame["lc_factor"] = factors
            frame["is_passable"] = [
                bool(row.is_passable) and factor != inf
                for row, factor in zip(frame.itertuples(index=False), factors, strict=True)
            ]
            return _attach_surface_response(frame)
        return _attach_surface_response(
            _attach_vector_landcover(
                frame,
                landcover,
                self.land_cover_factors,
                self.default_landcover_factor,
            )
        )

    def attach_soil(
        self,
        h3_df: pd.DataFrame,
        soil: RasterLayer | None,
        soil_catalog: dict[int, SoilProfile] | None = None,
    ) -> pd.DataFrame:
        """Attach optional soil type codes to an H3 table."""
        frame = _require_h3_frame(h3_df)
        if soil is None:
            return _attach_empty_soil_columns(frame)
        codes = _dominant_soil_codes_or_fallback(soil, frame)
        frame = _apply_soil_catalog(frame, codes, soil_catalog or {})
        frame["soil_source"] = str(soil.path)
        frame["source_support_m"] = _raster_support_m(soil, frame)
        return frame

    def attach_drainage(
        self,
        h3_df: pd.DataFrame,
        drainage: RasterLayer | None,
        twi: RasterLayer | None = None,
        validity: RasterLayer | None = None,
        boundary: RasterLayer | None = None,
    ) -> pd.DataFrame:
        """Attach cached static TWI/D evidence without a request pressure scenario."""
        frame = _require_h3_frame(h3_df)
        if drainage is None and twi is None and validity is None and boundary is None:
            return frame
        drainage_values = (
            _sample_raster_values(drainage, frame)
            if drainage is not None
            else [float("nan")] * len(frame)
        )
        valid_values = (
            _sample_raster_values(validity, frame) if validity is not None else [1.0] * len(frame)
        )
        boundary_values = (
            _sample_raster_values(boundary, frame) if boundary is not None else [0.0] * len(frame)
        )
        twi_values = (
            _sample_raster_values(twi, frame) if twi is not None else [float("nan")] * len(frame)
        )
        sensitivities: list[float | None] = []
        twi_output: list[float | None] = []
        valid_output: list[bool] = []
        for d_value, twi_value, valid_value in zip(
            drainage_values, twi_values, valid_values, strict=True
        ):
            evidence_valid = isfinite(valid_value) and valid_value > 0.0
            valid_cell = evidence_valid and isfinite(d_value)
            if valid_cell and not 0.0 <= d_value <= 1.0:
                raise GridBuildError("drainage sensitivity raster values must be in [0, 1].")
            valid_output.append(valid_cell)
            sensitivities.append(float(d_value) if valid_cell else None)
            twi_output.append(float(twi_value) if evidence_valid and isfinite(twi_value) else None)
        frame["twi"] = twi_output
        frame["drainage_sensitivity"] = sensitivities
        frame["drainage_valid"] = valid_output
        frame["drainage_boundary_affected"] = [
            bool(isfinite(value) and value > 0.0) for value in boundary_values
        ]
        return frame

    def attach_roads(self, h3_df: pd.DataFrame, roads: gpd.GeoDataFrame | None) -> pd.DataFrame:
        """Mark sampled cells that intersect a road proximity buffer."""
        frame = _require_h3_frame(h3_df)
        if roads is None or roads.empty:
            frame["has_road"] = False
            return frame
        roads_wgs84 = (
            roads
            if roads.crs and roads.crs.to_string() == "EPSG:4326"
            else roads.to_crs("EPSG:4326")
        )
        spatial_index = cast(_SpatialIndex, roads_wgs84.sindex)
        frame["has_road"] = [
            _point_near_road(
                Point(row.lng, row.lat),
                roads_wgs84,
                spatial_index,
                self.road_buffer_deg,
            )
            for row in frame.itertuples(index=False)
        ]
        return frame

    def build_graph(self, h3_df: pd.DataFrame) -> H3Graph:
        """Build an H3Graph with directional-slope edges from an H3 table."""
        frame = _require_h3_frame(h3_df)
        cells = _cells_from_frame(frame)
        if not cells:
            raise GridBuildError("cannot build a graph with zero cells.")
        edges = self._edges_from_cells(cells)
        parent_children = _parent_children(cells)
        return H3Graph(
            resolution_fine=self.res_fine,
            resolution_coarse=self.res_coarse,
            cells=cells,
            edges=edges,
            parent_children=parent_children,
        )

    def save_parquet(self, h3_df: pd.DataFrame, path: str) -> None:
        """Persist an H3 table as Parquet."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        h3_df.to_parquet(output_path, index=False)

    def load_parquet(self, path: str) -> pd.DataFrame:
        """Load and validate an H3 table from a Parquet cache."""
        input_path = Path(path)
        if not input_path.exists():
            raise FileNotFoundError(f"H3 Parquet file does not exist: {path}")
        try:
            frame = pd.read_parquet(input_path)
        except (ImportError, OSError, ValueError) as exc:
            raise GridBuildError(f"failed to read H3 Parquet file: {path}") from exc
        return _require_h3_frame(frame)

    def load_graph(self, path: str) -> H3Graph:
        """Load a persisted H3 table and rebuild an in-memory graph."""
        return self.build_graph(self.load_parquet(path))

    def _sample_dem_records(
        self,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
    ) -> list[dict[str, float | str]]:
        records: list[dict[str, float | str]] = []
        for row in range(0, dem.shape[0], self.sample_stride):
            for col in range(0, dem.shape[1], self.sample_stride):
                if self.max_cells is not None and len(records) >= self.max_cells:
                    return records
                record = self._record_from_pixel(dem, slope, tri, affine, row, col)
                if record is not None:
                    records.append(record)
        return records

    def _record_from_pixel(
        self,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
        row: int,
        col: int,
    ) -> dict[str, float | str] | None:
        elevation = float(dem[row, col])
        slope_value = float(slope[row, col])
        tri_value = float(tri[row, col])
        if not np.isfinite([elevation, slope_value, tri_value]).all():
            return None
        lng, lat = affine * (col + 0.5, row + 0.5)
        cell_id = h3.latlng_to_cell(float(lat), float(lng), self.res_fine)
        return {
            "h3index": str(cell_id),
            "lat": float(lat),
            "lng": float(lng),
            "elevation": elevation,
            "slope": slope_value,
            "tri": tri_value,
            "parent_h3": str(h3.cell_to_parent(cell_id, self.res_coarse)),
        }

    def _record_from_cell_center(
        self,
        cell_id: str,
        dem: npt.NDArray[np.float64],
        slope: npt.NDArray[np.float64],
        tri: npt.NDArray[np.float64],
        affine: Affine,
    ) -> dict[str, float | str] | None:
        lat, lng = h3.cell_to_latlng(cell_id)
        col_float, row_float = ~affine * (float(lng), float(lat))
        row = int(np.floor(row_float))
        col = int(np.floor(col_float))
        if row < 0 or col < 0 or row >= dem.shape[0] or col >= dem.shape[1]:
            return None
        elevation = float(dem[row, col])
        slope_value = float(slope[row, col])
        tri_value = float(tri[row, col])
        if not np.isfinite([elevation, slope_value, tri_value]).all():
            return None
        return {
            "elevation": elevation,
            "h3index": str(cell_id),
            "lat": float(lat),
            "lng": float(lng),
            "parent_h3": str(h3.cell_to_parent(cell_id, self.res_coarse)),
            "slope": slope_value,
            "tri": tri_value,
        }

    def _edges_from_cells(self, cells: dict[str, H3Cell]) -> dict[tuple[str, str], H3Edge]:
        edges: dict[tuple[str, str], H3Edge] = {}
        for cell_id, cell in cells.items():
            if not cell.is_passable:
                continue
            for neighbor_id in _safe_neighbors(cell_id):
                if neighbor_id in cells and cell_id < neighbor_id:
                    neighbor = cells[neighbor_id]
                    if not neighbor.is_passable:
                        continue
                    distance_m = _haversine_m(cell.lat, cell.lng, neighbor.lat, neighbor.lng)
                    edges[(cell_id, neighbor_id)] = _edge_from_cells(cell, neighbor, distance_m)
        return edges


def _require_h3_frame(h3_df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "elevation",
        "h3index",
        "lat",
        "lc_factor",
        "lng",
        "parent_h3",
        "slope",
        "tri",
    }
    missing = required.difference(h3_df.columns)
    if missing:
        raise GridBuildError(f"H3 DataFrame is missing required columns: {sorted(missing)}")
    if h3_df.empty:
        raise GridBuildError("H3 DataFrame must be non-empty.")
    frame = h3_df.copy()
    if "has_road" not in frame.columns:
        frame["has_road"] = False
    if "is_passable" not in frame.columns:
        frame["is_passable"] = True
    if "landcover_code" not in frame.columns:
        frame["landcover_code"] = None
    if "landcover_type" not in frame.columns:
        frame["landcover_type"] = None
    if "depth" not in frame.columns:
        frame["depth"] = None
    if "rowspacing" not in frame.columns:
        frame["rowspacing"] = None
    if "score" not in frame.columns:
        frame["score"] = 0.0
    if "cost_score" not in frame.columns:
        frame["cost_score"] = 1.0 - frame["score"].astype(float)
    defaults: dict[str, object] = {
        "soil_source": None,
        "source_support_m": None,
        "twi": None,
        "drainage_sensitivity": None,
        "drainage_valid": False,
        "drainage_boundary_affected": False,
        "surface_response": None,
        "surface_evidence": None,
    }
    for column, value in defaults.items():
        if column not in frame.columns:
            frame[column] = pd.Series([value] * len(frame), index=frame.index)
    return frame


def _landcover_factors(overrides: dict[int, float] | None) -> dict[int, float]:
    factors = dict(LAND_COVER_FACTORS)
    if overrides is None:
        return factors
    for code, factor in overrides.items():
        if isinstance(code, bool) or not isinstance(code, int) or code < 0:
            raise ValueError("land_cover_factors keys must be non-negative integer codes.")
        if not _valid_landcover_factor(factor):
            raise ValueError("land_cover_factors values must be positive or infinity.")
        factors[code] = float(factor)
    return factors


def _valid_landcover_factor(value: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    return numeric == inf or (isfinite(numeric) and numeric > 0.0)


def _attach_vector_landcover(
    frame: pd.DataFrame,
    landcover: gpd.GeoDataFrame,
    factors: dict[int, float],
    default_factor: float,
) -> pd.DataFrame:
    if landcover.empty:
        return frame
    vector = landcover
    if vector.crs is not None and vector.crs.to_string() != CRS_WGS84:
        vector = vector.to_crs(CRS_WGS84)
    spatial_index = cast(_SpatialIndex, vector.sindex)
    codes: list[int | None] = []
    types: list[str | None] = []
    lc_factors: list[float] = []
    passable: list[bool] = []
    depths: list[float | None] = []
    rowspacings: list[float | None] = []
    for row in frame.itertuples(index=False):
        current_code = _optional_int(getattr(row, "landcover_code", None))
        current_type = _optional_str(getattr(row, "landcover_type", None))
        current_factor = _row_float(row, "lc_factor")
        current_depth = _optional_float(getattr(row, "depth", None))
        current_rowspacing = _optional_float(getattr(row, "rowspacing", None))
        code, depth, rowspacing = _dominant_vector_landcover_details(
            str(row.h3index), vector, spatial_index
        )
        if code is None:
            final_code = current_code
            final_type = current_type
            factor = current_factor
            final_depth = current_depth
            final_rowspacing = current_rowspacing
        else:
            final_code = code
            final_type = _landcover_type(code)
            factor = _landcover_factor_for_code(code, factors, default_factor)
            final_depth = depth if depth is not None else current_depth
            final_rowspacing = rowspacing if rowspacing is not None else current_rowspacing
        codes.append(final_code)
        types.append(final_type)
        lc_factors.append(factor)
        passable.append(bool(row.is_passable) and factor != inf)
        depths.append(final_depth)
        rowspacings.append(final_rowspacing)
    frame["landcover_code"] = codes
    frame["landcover_type"] = types
    frame["lc_factor"] = lc_factors
    frame["is_passable"] = passable
    frame["depth"] = depths
    frame["rowspacing"] = rowspacings
    return frame


def _dominant_vector_landcover_code(
    h3index: str,
    landcover: gpd.GeoDataFrame,
    spatial_index: _SpatialIndex,
) -> int | None:
    code, _, _ = _dominant_vector_landcover_details(h3index, landcover, spatial_index)
    return code


def _dominant_vector_landcover_details(
    h3index: str,
    landcover: gpd.GeoDataFrame,
    spatial_index: _SpatialIndex,
) -> tuple[int | None, float | None, float | None]:
    cell_polygon = _h3_polygon(h3index)
    candidate_indexes = list(spatial_index.query(cell_polygon, predicate="intersects"))
    best_area = 0.0
    best_code: int | None = None
    best_depth: float | None = None
    best_rowspacing: float | None = None
    cell_area = cell_polygon.area
    for index in candidate_indexes:
        feature = landcover.iloc[int(index)]
        geometry = _feature_geometry(feature)
        code = _feature_landcover_code(feature)
        if geometry is None or geometry.is_empty or code is None:
            continue
        if geometry.contains(cell_polygon):
            area = cell_area
        else:
            area = float(cell_polygon.intersection(geometry).area)
        if area <= 0.0:
            continue
        is_obstacle = code in {5, 6}
        current_is_obstacle = best_code in {5, 6} if best_code is not None else False
        is_road = code == 8
        current_is_road = best_code == 8 if best_code is not None else False

        if (is_obstacle and not current_is_obstacle and area > 0.05 * cell_area) or (
            is_road and not current_is_obstacle and not current_is_road and area > 0.10 * cell_area
        ):
            should_update = True
        elif (current_is_obstacle and not is_obstacle) or (
            current_is_road and not is_obstacle and not is_road
        ):
            should_update = False
        else:
            should_update = area > best_area

        if should_update:
            best_area = area
            best_code = code
            best_depth = _optional_float(feature.get("depth")) if "depth" in feature.index else None
            best_rowspacing = (
                _optional_float(feature.get("rowspacing"))
                if "rowspacing" in feature.index
                else None
            )
    return best_code, best_depth, best_rowspacing


def _feature_geometry(feature: pd.Series) -> BaseGeometry | None:
    value: object = feature.get("geometry")
    return value if isinstance(value, BaseGeometry) else None


def _feature_landcover_code(feature: pd.Series) -> int | None:
    for column in LANDCOVER_CODE_COLUMNS:
        if column not in feature.index:
            continue
        value: object = feature.get(column)
        if _is_missing(value):
            continue
        if isinstance(value, str):
            val_clean = value.strip()
            if val_clean.lower() in FCLASS_CODE_MAPPING:
                return FCLASS_CODE_MAPPING[val_clean.lower()]
            digits = val_clean.lstrip("0") or "0"
            try:
                numeric = float(digits)
                if isfinite(numeric) and numeric >= 0.0:
                    return int(round(numeric))
            except ValueError:
                continue
        elif isinstance(value, (int, float, np.integer, np.floating)):
            numeric = float(value)
            if isfinite(numeric) and numeric >= 0.0:
                return int(round(numeric))
    return None


def _h3_frame_from_records(records: list[dict[str, float | str]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    grouped = frame.groupby("h3index", as_index=False).agg(
        lat=("lat", "mean"),
        lng=("lng", "mean"),
        elevation=("elevation", "mean"),
        slope=("slope", "mean"),
        tri=("tri", "mean"),
        parent_h3=("parent_h3", "first"),
    )
    grouped["lc_factor"] = 1.0
    grouped["landcover_code"] = None
    grouped["landcover_type"] = None
    grouped["soil_code"] = None
    grouped["soil_type"] = None
    grouped["soil_texture"] = None
    grouped["uscs"] = None
    grouped["soil_moisture"] = None
    grouped["soil_source"] = None
    grouped["source_support_m"] = None
    grouped["twi"] = None
    grouped["drainage_sensitivity"] = None
    grouped["drainage_valid"] = False
    grouped["drainage_boundary_affected"] = False
    grouped["surface_response"] = None
    grouped["surface_evidence"] = None
    grouped["has_road"] = False
    grouped["is_passable"] = True
    grouped["score"] = 0.0
    grouped["cost_score"] = 1.0
    return grouped


def _roi_polyfill_cells(
    roi_geometry: BaseGeometry,
    resolution: int,
    max_cells: int | None,
) -> list[str]:
    if roi_geometry.is_empty or roi_geometry.area <= 0.0:
        raise GridBuildError("ROI geometry must be non-empty with positive area.")
    estimate = _estimate_roi_cell_count(roi_geometry, resolution)
    if max_cells is not None and estimate > max_cells:
        raise GridBuildError(_oversize_roi_message(estimate, max_cells))
    cells = sorted(_polygon_cells(roi_geometry, resolution))
    if not cells:
        raise GridBuildError("ROI H3 polyfill produced no cells.")
    if max_cells is not None and len(cells) > max_cells:
        raise GridBuildError(_oversize_roi_message(len(cells), max_cells))
    return cells


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


def _estimate_roi_cell_count(geometry: BaseGeometry, resolution: int) -> int:
    area_m2 = _approx_wgs84_area_m2(geometry)
    average_area = float(h3.average_hexagon_area(resolution, unit="m^2"))
    return max(1, int(area_m2 / max(average_area, 1.0)))


def _approx_wgs84_area_m2(geometry: BaseGeometry) -> float:
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    mean_lat = radians((min_lat + max_lat) / 2.0)
    meters_per_degree_lng = 111_320.0 * max(cos(mean_lat), 0.01)
    return float(geometry.area) * meters_per_degree_lng * 111_320.0


def _oversize_roi_message(cell_count: int, max_cells: int) -> str:
    return (
        f"ROI H3 cell count {cell_count} exceeds max_cells={max_cells}; "
        "shrink ROI, reduce resolution for smoke runs, or use tiled construction."
    )


def _sample_raster_values(layer: RasterLayer, frame: pd.DataFrame) -> list[float]:
    with rasterio.open(layer.path) as src:
        lng = [_row_float(row, "lng") for row in frame.itertuples(index=False)]
        lat = [_row_float(row, "lat") for row in frame.itertuples(index=False)]
        if src.crs != CRS.from_string(CRS_WGS84):
            lng, lat = transform_coordinates(CRS.from_string(CRS_WGS84), src.crs, lng, lat)
        coordinates = list(zip(lng, lat, strict=True))
        return [float(value[0]) for value in src.sample(coordinates)]


def _dominant_soil_codes_or_fallback(layer: RasterLayer, frame: pd.DataFrame) -> list[int | None]:
    try:
        if CRS.from_string(layer.crs) != CRS.from_string(CRS_WGS84):
            raise GridBuildError("area-dominance soil sampling requires WGS84 raster geometry")
        if layer.width * layer.height > AREA_DOMINANCE_MAX_PIXELS:
            raise GridBuildError("soil raster is too large for area-dominance sampling")
        return _dominant_soil_codes(layer, frame)
    except (GridBuildError, rasterio.errors.RasterioError, ValueError) as exc:
        LOGGER.warning("Falling back to soil center sampling: %s", exc)
        values = _sample_raster_values(layer, frame)
        return [None if _is_nodata(value, layer.nodata) else _to_int(value) for value in values]


def _dominant_soil_codes(layer: RasterLayer, frame: pd.DataFrame) -> list[int | None]:
    codes: list[int | None] = []
    with rasterio.open(layer.path) as src:
        for row in frame.itertuples(index=False):
            cell_polygon = _h3_polygon(str(row.h3index))
            window = _bounded_window(src, cell_polygon.bounds)
            if window.width <= 0 or window.height <= 0:
                codes.append(None)
                continue
            array = src.read(1, window=window, masked=True)
            codes.append(
                _dominant_code_in_window(array, src.window_transform(window), cell_polygon)
            )
    return codes


def _bounded_window(
    src: rasterio.io.DatasetReader,
    bounds: tuple[float, float, float, float],
) -> Window:
    raw = src.window(*bounds).round_offsets().round_lengths()
    col_off = max(int(raw.col_off), 0)
    row_off = max(int(raw.row_off), 0)
    width = min(int(raw.width), src.width - col_off)
    height = min(int(raw.height), src.height - row_off)
    return Window(col_off=col_off, row_off=row_off, width=max(width, 0), height=max(height, 0))


def _dominant_code_in_window(
    array: np.ma.MaskedArray,
    transform: Affine,
    cell_polygon: Polygon,
) -> int | None:
    area_by_code: dict[int, float] = {}
    for row in range(array.shape[0]):
        for col in range(array.shape[1]):
            if bool(np.ma.is_masked(array[row, col])):
                continue
            code = _to_int(float(array[row, col]))
            if code == 0:
                continue
            area = _pixel_intersection_area(transform, row, col, cell_polygon)
            if area > 0.0:
                area_by_code[code] = area_by_code.get(code, 0.0) + area
    if not area_by_code:
        return None
    return max(area_by_code.items(), key=lambda item: item[1])[0]


def _pixel_intersection_area(
    transform: Affine,
    row: int,
    col: int,
    cell_polygon: Polygon,
) -> float:
    x0, y0 = transform * (col, row)
    x1, y1 = transform * (col + 1, row + 1)
    pixel_polygon = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return float(pixel_polygon.intersection(cell_polygon).area)


def _h3_polygon(h3index: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3index)])


def _attach_empty_soil_columns(frame: pd.DataFrame) -> pd.DataFrame:
    for column in ("soil_code", "soil_type", "soil_texture", "uscs", "soil_moisture"):
        frame[column] = None
    frame["soil_source"] = None
    frame["source_support_m"] = None
    return frame


def _apply_soil_catalog(
    frame: pd.DataFrame,
    codes: list[int | None],
    soil_catalog: dict[int, SoilProfile],
) -> pd.DataFrame:
    frame["soil_code"] = codes
    frame["soil_type"] = [_soil_name(code, soil_catalog) for code in codes]
    frame["soil_texture"] = [_soil_attr(code, soil_catalog, "soil_texture") for code in codes]
    frame["uscs"] = [_soil_attr(code, soil_catalog, "uscs") for code in codes]
    frame["soil_moisture"] = [_soil_moisture(code, soil_catalog) for code in codes]
    frame["is_passable"] = [
        bool(frame.iloc[index].is_passable) and _soil_passable(code, soil_catalog)
        for index, code in enumerate(codes)
    ]
    return frame


def _soil_name(code: int | None, catalog: dict[int, SoilProfile]) -> str | None:
    if code is None:
        return None
    profile = catalog.get(code)
    return profile.name_zh if profile is not None else str(code)


def _soil_attr(
    code: int | None,
    catalog: dict[int, SoilProfile],
    attr_name: str,
) -> str | None:
    if code is None or code not in catalog:
        return None
    return cast(str | None, getattr(catalog[code], attr_name))


def _soil_moisture(code: int | None, catalog: dict[int, SoilProfile]) -> float | None:
    if code is None or code not in catalog:
        return None
    return catalog[code].soil_moisture


def _soil_passable(code: int | None, catalog: dict[int, SoilProfile]) -> bool:
    if code is None or code not in catalog:
        return True
    return catalog[code].is_passable


def _to_int(value: float) -> int:
    if not np.isfinite(value):
        return 0
    return int(round(value))


def _is_nodata(value: float, nodata: float | None) -> bool:
    return not np.isfinite(value) or (nodata is not None and value == nodata) or value == 0.0


def _landcover_code(value: float, nodata: float | None) -> int | None:
    return None if _is_nodata(value, nodata) else _to_int(value)


def _landcover_factor_for_code(
    code: int | None,
    factors: dict[int, float],
    default_factor: float,
) -> float:
    return factors.get(0, default_factor) if code is None else factors.get(code, default_factor)


def _landcover_type(code: int | None) -> str | None:
    if code is None:
        return None
    return LAND_COVER_TYPES.get(code, f"landcover_{code}")


def _point_near_road(
    point: Point,
    roads: gpd.GeoDataFrame,
    spatial_index: _SpatialIndex,
    buffer_deg: float,
) -> bool:
    candidate_indexes = list(spatial_index.query(point.buffer(buffer_deg), predicate="intersects"))
    return any(
        roads.geometry.iloc[int(index)].distance(point) <= buffer_deg for index in candidate_indexes
    )


def _cells_from_frame(frame: pd.DataFrame) -> dict[str, H3Cell]:
    cells: dict[str, H3Cell] = {}
    for row in frame.itertuples(index=False):
        soil_type = _optional_str(getattr(row, "soil_type", None))
        cells[str(row.h3index)] = H3Cell(
            h3index=str(row.h3index),
            lat=_row_float(row, "lat"),
            lng=_row_float(row, "lng"),
            elevation=_row_float(row, "elevation"),
            slope=_row_float(row, "slope"),
            tri=_row_float(row, "tri"),
            lc_factor=_row_float(row, "lc_factor"),
            landcover_code=_optional_int(getattr(row, "landcover_code", None)),
            landcover_type=_optional_str(getattr(row, "landcover_type", None)),
            soil_code=_optional_int(getattr(row, "soil_code", None)),
            soil_type=soil_type,
            soil_texture=_optional_str(getattr(row, "soil_texture", None)),
            uscs=_optional_str(getattr(row, "uscs", None)),
            soil_moisture=_optional_float(getattr(row, "soil_moisture", None)),
            depth=_optional_float(getattr(row, "depth", None)),
            rowspacing=_optional_float(getattr(row, "rowspacing", None)),
            cone_index_kpa=_optional_float(getattr(row, "cone_index_kpa", None)),
            sinkage_m=_optional_float(getattr(row, "sinkage_m", None)),
            sinkage_resistance=_optional_float(getattr(row, "sinkage_resistance", None)),
            soil_mobility=_optional_float(getattr(row, "soil_mobility", None)),
            soil_source=_optional_str(getattr(row, "soil_source", None)),
            source_support_m=_optional_float(getattr(row, "source_support_m", None)),
            twi=_optional_float(getattr(row, "twi", None)),
            drainage_sensitivity=_optional_float(getattr(row, "drainage_sensitivity", None)),
            drainage_valid=bool(getattr(row, "drainage_valid", False)),
            drainage_boundary_affected=bool(getattr(row, "drainage_boundary_affected", False)),
            surface_response=_optional_float(getattr(row, "surface_response", None)),
            surface_evidence=_optional_str(getattr(row, "surface_evidence", None)),
            has_road=bool(row.has_road),
            parent_h3=str(row.parent_h3),
            is_passable=bool(row.is_passable),
            score=_optional_float(getattr(row, "score", 0.0)) or 0.0,
            cost_score=_optional_float(getattr(row, "cost_score", None)),
        )
    return cells


def _optional_str(value: object) -> str | None:
    return None if _is_missing(value) else str(value)


def _optional_int(value: object) -> int | None:
    if _is_missing(value):
        return None
    if isinstance(value, (int, float, str, np.integer, np.floating)):
        return int(float(value))
    raise GridBuildError(f"cannot convert optional integer value: {value!r}")


def _optional_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, (int, float, str, np.integer, np.floating)):
        return float(value)
    raise GridBuildError(f"cannot convert optional float value: {value!r}")


def _row_float(row: object, name: str) -> float:
    return _required_float(name, getattr(row, name))


def _required_float(name: str, value: object) -> float:
    if isinstance(value, bool) or _is_missing(value):
        raise GridBuildError(f"{name} must be a finite numeric value.")
    if isinstance(value, (int, float, str, np.integer, np.floating)):
        return float(value)
    raise GridBuildError(f"cannot convert required float value {name}: {value!r}")


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    return isinstance(value, (float, np.floating)) and bool(np.isnan(value))


def _parent_children(cells: dict[str, H3Cell]) -> dict[str, set[str]]:
    parent_children: dict[str, set[str]] = {}
    for cell in cells.values():
        parent_children.setdefault(cell.parent_h3, set()).add(cell.h3index)
    return parent_children


def _safe_neighbors(h3index: str) -> list[str]:
    neighbors = sorted({str(cell) for cell in h3.grid_disk(h3index, 1) if str(cell) != h3index})
    if h3.is_pentagon(h3index) and len(neighbors) > 5:
        raise GridBuildError(
            f"pentagon H3 cell {h3index!r} produced {len(neighbors)} ring-1 neighbors."
        )
    return neighbors


def _edge_from_cells(cell: H3Cell, neighbor: H3Cell, distance_m: float) -> H3Edge:
    slope_a_to_b = degrees(atan2(neighbor.elevation - cell.elevation, max(distance_m, 1.0)))
    slope_b_to_a = degrees(atan2(cell.elevation - neighbor.elevation, max(distance_m, 1.0)))
    return H3Edge(
        cell_a=cell.h3index,
        cell_b=neighbor.h3index,
        geo_distance=max(distance_m, 1.0),
        has_road=cell.has_road or neighbor.has_road,
        slope_a_to_b=slope_a_to_b,
        slope_b_to_a=slope_b_to_a,
    )


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    first_lat = radians(lat_a)
    second_lat = radians(lat_b)
    root = sin(d_lat / 2.0) ** 2 + cos(first_lat) * cos(second_lat) * sin(d_lng / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * atan2(sqrt(root), sqrt(max(0.0, 1.0 - root)))


def _attach_surface_response(frame: pd.DataFrame) -> pd.DataFrame:
    responses: list[float | None] = []
    evidence: list[str | None] = []
    for value in frame["landcover_code"]:
        code = _optional_int(value)
        if code == 8:
            responses.append(0.0)
            evidence.append("mapped_impervious_surface")
        elif code in {1, 2, 3, 4, 7, 9}:
            responses.append(1.0)
            evidence.append("mapped_unpaved_surface")
        else:
            responses.append(None)
            evidence.append(None)
    frame["surface_response"] = responses
    frame["surface_evidence"] = evidence
    return frame


def _raster_support_m(layer: RasterLayer, frame: pd.DataFrame) -> float:
    with rasterio.open(layer.path) as src:
        x_resolution = abs(float(src.transform.a))
        y_resolution = abs(float(src.transform.e))
        if src.crs is not None and src.crs.is_geographic:
            center_lat = float(pd.to_numeric(frame["lat"]).mean())
            x_resolution *= 111_320.0 * max(cos(radians(center_lat)), 0.01)
            y_resolution *= 111_320.0
        return max(x_resolution, y_resolution)
