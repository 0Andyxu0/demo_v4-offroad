"""Formal StaticScene specification and preparation contract for M0.

This module implements the formal data contract specified in
IMPLEMENTATION_PLAN.md §5.1 and §6.1:
    prepare_static_scene(inputs, weather_snapshot, build_config) -> StaticScene

The scene representation captures the verified static environment, CRS projections,
study area bounds, and references to DEM, landcover, roads, orthophoto, soil,
moisture, hydrology, and frozen weather without implementing M1-M5 physical model
alterations or graph transformations.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, cast

import hashlib
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from pyproj import Transformer
import rasterio
import rasterio.transform
from rasterio.warp import transform_bounds
import yaml

from h3_offroad_planner.models import H3Graph
from h3_offroad_planner.preprocessing.gis_preprocessor import GISPreprocessor

__all__ = [
    "DemReference",
    "HydrologyReference",
    "LandcoverAttributeAudit",
    "LandcoverReference",
    "MoistureReference",
    "OrthophotoReference",
    "RoadReference",
    "SoilReference",
    "StaticScene",
    "StudyArea",
    "WeatherSnapshotReference",
    "enrich_graph_from_static_scene",
    "load_static_scene",
    "prepare_static_scene",
    "resolve_road_effective_width_m",
]


@dataclass(frozen=True)
class StudyArea:
    """Study area spatial extent and projection definition."""

    source_layer: str
    source_crs: str
    bounds_wgs84: list[float]  # [west, south, east, north]
    bounds_metric: list[float]  # [left, bottom, right, top]
    metric_crs: str
    selection_basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DemReference:
    """DEM raster metadata and spatial properties."""

    path: str
    crs: str
    native_resolution: list[float]  # [dx, dy]
    horizontal_unit: str
    elevation_unit: str
    bounds: list[float]  # [left, bottom, right, top] in DEM CRS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LandcoverAttributeAudit:
    """Audit record for a key physical attribute on a landcover layer."""

    layer: str
    field: str
    features_in_study_area: int
    non_null: int
    sample_raw_values: list[str]
    numeric_min: float | None
    numeric_max: float | None
    semantic_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LandcoverReference:
    """Landcover vector data directory and verified key attribute audits."""

    source_directory: str
    crs: str
    layers: list[str]
    attribute_checks: list[LandcoverAttributeAudit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_directory": self.source_directory,
            "crs": self.crs,
            "layers": list(self.layers),
            "attribute_checks": [c.to_dict() for c in self.attribute_checks],
        }


@dataclass(frozen=True)
class RoadReference:
    """Road network vector data, type and width attribute reference."""

    path: str
    crs: str
    width_field: str
    feature_count: int
    sample_widths: list[float] = field(default_factory=list)
    road_type_field: str | None = None
    sample_road_types: list[str] = field(default_factory=list)
    width_unit_or_scale: str = "0.1m"
    effective_width_m_range: list[float] = field(default_factory=lambda: [3.0, 5.5])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_road_effective_width_m(
    raw_width: Any,
    func_class: Any = None,
    scale: float = 0.1,
    default_m: float = 3.5,
) -> float:
    """Convert raw road Width (decimeters in GIS source e.g. '30', '55') to effective road width in meters.

    In the QDX road dataset (`road_fina.shp`), `FuncClass = '5'` (rural track/path) records `Width`
    in decimeters (0.1 m scale), where '30' represents 3.0 m (or single-lane rural road ~3.5 m)
    and '55' represents 5.5 m (two-lane rural road).
    This function ensures that raw width values in decimeters (e.g. >= 15.0) are properly scaled by 0.1 m,
    preventing 30~55 m corridor explosions.
    """
    if raw_width is None:
        if func_class is not None and str(func_class).strip() == "5":
            return default_m
        return default_m
    try:
        val = float(raw_width)
    except (ValueError, TypeError):
        if func_class is not None and str(func_class).strip() == "5":
            return default_m
        return default_m

    if not np.isfinite(val) or val <= 0:
        return default_m

    if val >= 15.0:
        val = val * scale

    return float(np.clip(val, 2.0, 15.0))


@dataclass(frozen=True)
class OrthophotoReference:
    """Local orthophoto raster reference for display and boundary verification."""

    source_path: str
    crs: str
    native_resolution_m: float
    bounds_wgs84: list[list[float]]  # [[south, west], [north, east]]
    preview_path: str | None = None
    acquisition_time: str | None = None
    purpose: str = (
        "Desktop display and manual boundary verification only; "
        "it is not an M0 classification or factor-model input."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SoilReference:
    """Soil raster and attribute catalog reference."""

    raster_path: str
    catalog_path: str
    crs: str
    native_resolution: list[float]
    class_count: int
    applicability: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MoistureReference:
    """Static moisture observation products (e.g. CLDAS daily NetCDF)."""

    paths: list[str]
    unit: str = "m3/m3"
    depth_layers: list[str] = field(default_factory=list)
    observation_time: str | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HydrologyReference:
    """Upstream hydrology D-field and flow rasters reference."""

    upstream_layers: dict[str, str]
    crs: str | None = None
    purpose: str = (
        "Fixed upstream hydrology D-field reference; not recalibrated on small ROI."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherSnapshotReference:
    """Frozen weather snapshot used to fix ground conditions at mapping time."""

    snapshot_path: str
    provider: str
    valid_at: str
    precipitation_24h_mm: float
    soil_moisture_surface_m3_m3: float
    degraded: bool = False
    model: str = "best_match"
    replay_rule: str = (
        "All M0 reruns read this frozen snapshot; do not query new weather for this baseline."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StaticScene:
    """Canonical M0 static scene representation as defined in IMPLEMENTATION_PLAN.md §5.1.

    Contains verified references to all source rasters, vectors, moisture, hydrology,
    frozen weather, metric CRS, study boundary, and field mapping.
    """

    scene_id: str
    metric_crs: str
    study_area: StudyArea
    dem: DemReference
    landcover: LandcoverReference
    road: RoadReference
    orthophoto: OrthophotoReference
    soil: SoilReference
    moisture: MoistureReference
    hydrology: HydrologyReference
    weather: WeatherSnapshotReference
    mapping_time: str
    field_mapping: dict[str, dict[str, str]]
    model_version: str = "m0_static_scene_v1"
    baseline_source_commit: str = "986bd58"
    primary_od: dict[str, Any] | None = None
    vehicle: dict[str, Any] | None = None
    quality_and_budget_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert StaticScene to a JSON-serializable dictionary."""
        return {
            "schema_version": self.model_version,
            "scene_id": self.scene_id,
            "metric_crs": self.metric_crs,
            "model_version": self.model_version,
            "baseline_source_commit": self.baseline_source_commit,
            "mapping_time": self.mapping_time,
            "study_area": self.study_area.to_dict(),
            "dem": self.dem.to_dict(),
            "landcover": self.landcover.to_dict(),
            "road": self.road.to_dict(),
            "orthophoto": self.orthophoto.to_dict(),
            "soil": self.soil.to_dict(),
            "moisture": self.moisture.to_dict(),
            "hydrology": self.hydrology.to_dict(),
            "weather": self.weather.to_dict(),
            "field_mapping": self.field_mapping,
            "key_landcover_attributes": [
                {
                    "layer": c.layer,
                    "field": c.field,
                    "verification_scope": "features intersecting the fixed study boundary",
                    "semantic_status": c.semantic_status,
                }
                for c in self.landcover.attribute_checks
            ],
            "primary_od": self.primary_od,
            "vehicle": self.vehicle,
            "quality_and_budget_status": self.quality_and_budget_status,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize StaticScene to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save_json(self, path: Path | str, indent: int = 2) -> Path:
        """Save StaticScene to a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")
        return target

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StaticScene:
        """Instantiate StaticScene from a dictionary."""
        sa = data["study_area"]
        study_area = StudyArea(
            source_layer=sa["source_layer"],
            source_crs=sa["source_crs"],
            bounds_wgs84=list(sa["bounds_wgs84"]),
            bounds_metric=list(sa.get("bounds_metric", [])),
            metric_crs=sa.get("metric_crs", data.get("metric_crs", "EPSG:4528")),
            selection_basis=sa.get("selection_basis", ""),
        )

        dem_data = data.get("dem", {})
        dem = DemReference(
            path=dem_data.get("path", ""),
            crs=dem_data.get("crs", ""),
            native_resolution=list(dem_data.get("native_resolution", [0.0, 0.0])),
            horizontal_unit=dem_data.get("horizontal_unit", "degree"),
            elevation_unit=dem_data.get("elevation_unit", "meter"),
            bounds=list(dem_data.get("bounds", [0.0, 0.0, 0.0, 0.0])),
        )

        lc_data = data.get("landcover", {})
        attribute_checks: list[LandcoverAttributeAudit] = []
        for ac in lc_data.get("attribute_checks", []):
            attribute_checks.append(
                LandcoverAttributeAudit(
                    layer=ac["layer"],
                    field=ac["field"],
                    features_in_study_area=int(ac.get("features_in_study_area", 0)),
                    non_null=int(ac.get("non_null", 0)),
                    sample_raw_values=[str(v) for v in ac.get("sample_raw_values", [])],
                    numeric_min=ac.get("numeric_min"),
                    numeric_max=ac.get("numeric_max"),
                    semantic_status=ac.get("semantic_status", ""),
                )
            )
        landcover = LandcoverReference(
            source_directory=lc_data.get("source_directory", ""),
            crs=lc_data.get("crs", ""),
            layers=list(lc_data.get("layers", [])),
            attribute_checks=attribute_checks,
        )

        road_data = data.get("road", {})
        road = RoadReference(
            path=road_data.get("path", ""),
            crs=road_data.get("crs", ""),
            width_field=road_data.get("width_field", "Width"),
            feature_count=int(road_data.get("feature_count", 0)),
            sample_widths=[float(v) for v in road_data.get("sample_widths", [])],
            road_type_field=road_data.get("road_type_field"),
            sample_road_types=[str(v) for v in road_data.get("sample_road_types", [])],
            width_unit_or_scale=str(road_data.get("width_unit_or_scale", "0.1m")),
            effective_width_m_range=[
                float(v) for v in road_data.get("effective_width_m_range", [3.0, 5.5])
            ],
        )

        ortho_data = data.get("orthophoto", {})
        orthophoto = OrthophotoReference(
            source_path=ortho_data.get("source_path", ""),
            crs=ortho_data.get("crs", ""),
            native_resolution_m=float(ortho_data.get("native_resolution_m", 0.5)),
            bounds_wgs84=list(ortho_data.get("bounds_wgs84", [[0.0, 0.0], [0.0, 0.0]])),
            preview_path=ortho_data.get("preview_path"),
            acquisition_time=ortho_data.get("acquisition_time"),
            purpose=ortho_data.get(
                "purpose",
                "Desktop display and manual boundary verification only; "
                "it is not an M0 classification or factor-model input.",
            ),
        )

        soil_data = data.get("soil", {})
        soil = SoilReference(
            raster_path=soil_data.get("raster_path", ""),
            catalog_path=soil_data.get("catalog_path", ""),
            crs=soil_data.get("crs", ""),
            native_resolution=list(soil_data.get("native_resolution", [0.0, 0.0])),
            class_count=int(soil_data.get("class_count", 0)),
            applicability=soil_data.get("applicability"),
        )

        moisture_data = data.get("moisture", {})
        moisture = MoistureReference(
            paths=list(moisture_data.get("paths", [])),
            unit=moisture_data.get("unit", "m3/m3"),
            depth_layers=list(moisture_data.get("depth_layers", [])),
            observation_time=moisture_data.get("observation_time"),
            tags=dict(moisture_data.get("tags", {})),
        )

        hydro_data = data.get("hydrology", {})
        hydrology = HydrologyReference(
            upstream_layers=dict(hydro_data.get("upstream_layers", {})),
            crs=hydro_data.get("crs"),
            purpose=hydro_data.get(
                "purpose",
                "Fixed upstream hydrology D-field reference; not recalibrated on small ROI.",
            ),
        )

        weather_data = data.get("weather", {})
        weather = WeatherSnapshotReference(
            snapshot_path=weather_data.get("snapshot_path", ""),
            provider=weather_data.get("provider", "open-meteo"),
            valid_at=weather_data.get("valid_at", ""),
            precipitation_24h_mm=float(weather_data.get("precipitation_24h_mm", 0.0)),
            soil_moisture_surface_m3_m3=float(weather_data.get("soil_moisture_surface_m3_m3", 0.0)),
            degraded=bool(weather_data.get("degraded", False)),
            model=weather_data.get("model", "best_match"),
            replay_rule=weather_data.get(
                "replay_rule",
                "All M0 reruns read this frozen snapshot; do not query new weather for this baseline.",
            ),
        )

        return cls(
            scene_id=data["scene_id"],
            metric_crs=data.get("metric_crs", "EPSG:4528"),
            study_area=study_area,
            dem=dem,
            landcover=landcover,
            road=road,
            orthophoto=orthophoto,
            soil=soil,
            moisture=moisture,
            hydrology=hydrology,
            weather=weather,
            mapping_time=data.get("mapping_time", ""),
            field_mapping=dict(data.get("field_mapping", {})),
            model_version=data.get("model_version", data.get("schema_version", "m0_static_scene_v1")),
            baseline_source_commit=data.get("baseline_source_commit", "986bd58"),
            primary_od=data.get("primary_od"),
            vehicle=data.get("vehicle"),
            quality_and_budget_status=data.get("quality_and_budget_status"),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, path: Path | str) -> StaticScene:
        """Load StaticScene from a JSON file."""
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Scene JSON must contain a root object: {target}")
        return cls.from_dict(cast(dict[str, Any], payload))


def load_static_scene(path: Path | str) -> StaticScene:
    """Public helper to load a StaticScene from a JSON file."""
    return StaticScene.from_json(path)


def _check_raster_overlaps_bounds(
    ds: rasterio.DatasetReader, target_wgs84: list[float], raster_name: str
) -> None:
    """Verify that a raster overlaps the study area WGS84 bounding box."""
    rw, rs, re, rn = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
    w, s, e, n = target_wgs84
    if rw >= e or re <= w or rs >= n or rn <= s:
        raise ValueError(
            f"{raster_name} raster at '{ds.name}' does not overlap study area: "
            f"raster WGS84 bounds [{rw:.4f}, {rs:.4f}, {re:.4f}, {rn:.4f}], "
            f"study area [{w:.4f}, {s:.4f}, {e:.4f}, {n:.4f}]."
        )


def prepare_static_scene(
    inputs: dict[str, Any] | str | Path,
    weather_snapshot: dict[str, Any] | str | Path,
    build_config: dict[str, Any] | None = None,
) -> StaticScene:
    """Implement the formal M0 prepare_static_scene contract (IMPLEMENTATION_PLAN.md §6.1).

    Args:
        inputs: Mapping or path to YAML/JSON providing GIS input references.
        weather_snapshot: Mapping or path to JSON providing frozen weather snapshot.
        build_config: Optional build configuration mapping (scene_id, metric_crs, etc.).

    Returns:
        A validated, fully populated StaticScene instance.
    """
    config = dict(build_config or {})
    weather_ref = _resolve_weather_reference(weather_snapshot)
    inputs_dict = _resolve_inputs_dict(
        inputs,
        assets_fallback_path=config.get("assets_config_path"),
        preview_fallback_path=config.get("orthophoto_preview_path"),
    )

    scene_id = str(config.get("scene_id", "qdx-dem-coverage-001"))
    metric_crs = str(config.get("metric_crs", "EPSG:4528"))

    # Validate that metric_crs is a valid projected metric CRS (not geographic degree CRS)
    try:
        metric_proj = pyproj.CRS.from_user_input(metric_crs)
    except Exception as exc:
        raise ValueError(f"Invalid metric CRS: {metric_crs}") from exc
    if not metric_proj.is_projected:
        raise ValueError(
            f"metric_crs must be a projected metric coordinate reference system, got geographic CRS: {metric_crs}"
        )

    model_version = str(config.get("model_version", "m0_static_scene_v1"))
    baseline_source_commit = str(config.get("baseline_source_commit", "986bd58"))
    mapping_time = str(config.get("mapping_time", datetime.now(timezone.utc).isoformat()))

    field_mapping: dict[str, dict[str, str]] = config.get(
        "field_mapping",
        {
            "forest.shp": {"rowspacing": "rowspacing"},
            "water.shp": {"depth": "depth"},
            "road_fina.shp": {"width": "Width", "functional_class": "FuncClass"},
        },
    )

    # 1. Study Area / ROI
    roi_path = Path(inputs_dict["roi_path"])
    if not roi_path.is_file():
        raise FileNotFoundError(f"Study boundary layer does not exist: {roi_path}")
    roi_gdf = gpd.read_file(roi_path)
    if roi_gdf.empty or roi_gdf.crs is None:
        raise ValueError(f"Study boundary layer is empty or has no CRS: {roi_path}")
    if roi_gdf.geometry.isnull().all() or roi_gdf.geometry.is_empty.all():
        raise ValueError(f"Study boundary layer contains no valid geometries: {roi_path}")

    # Compute WGS84 bounds [west, south, east, north]
    wgs84_gdf = roi_gdf.to_crs("EPSG:4326")
    wgs_bounds = wgs84_gdf.total_bounds
    if len(wgs_bounds) != 4 or any(not np.isfinite(v) for v in wgs_bounds):
        raise ValueError(f"Study boundary produces non-finite or empty WGS84 bounds: {wgs_bounds}")
    w, s, e, n = [float(v) for v in wgs_bounds]
    if not w < e or not s < n:
        raise ValueError(f"Study boundary WGS84 bounds are degenerate: west={w}, south={s}, east={e}, north={n}")
    bounds_wgs84 = [w, s, e, n]

    # Compute metric bounds [left, bottom, right, top]
    metric_gdf = roi_gdf.to_crs(metric_crs)
    metric_bounds = metric_gdf.total_bounds
    if len(metric_bounds) != 4 or any(not np.isfinite(v) for v in metric_bounds):
        raise ValueError(f"Study boundary produces non-finite or empty metric bounds: {metric_bounds}")
    left, bottom, right, top = [float(v) for v in metric_bounds]
    if not left < right or not bottom < top:
        raise ValueError(f"Study boundary metric bounds are degenerate: left={left}, bottom={bottom}, right={right}, top={top}")
    bounds_metric = [left, bottom, right, top]

    study_area = StudyArea(
        source_layer=roi_path.as_posix(),
        source_crs=str(roi_gdf.crs),
        bounds_wgs84=bounds_wgs84,
        bounds_metric=bounds_metric,
        metric_crs=metric_crs,
        selection_basis=str(
            config.get(
                "selection_basis",
                "The supplied study boundary, DEM, land-cover layers, road layer, "
                "soil raster, and local orthophoto overlap this area.",
            )
        ),
    )

    # 2. DEM Reference
    dem_path = Path(inputs_dict["dem_path"])
    if not dem_path.is_file():
        raise FileNotFoundError(f"DEM raster does not exist: {dem_path}")
    with rasterio.open(dem_path) as dem_ds:
        if dem_ds.crs is None:
            raise ValueError(f"DEM raster has no CRS: {dem_path}")
        _check_raster_overlaps_bounds(dem_ds, bounds_wgs84, "DEM")
        is_geo = dem_ds.crs.is_geographic
        h_unit = "degree" if is_geo else "meter"
        dem = DemReference(
            path=dem_path.as_posix(),
            crs=str(dem_ds.crs),
            native_resolution=[float(dem_ds.res[0]), float(dem_ds.res[1])],
            horizontal_unit=h_unit,
            elevation_unit="meter",
            bounds=[
                float(dem_ds.bounds.left),
                float(dem_ds.bounds.bottom),
                float(dem_ds.bounds.right),
                float(dem_ds.bounds.top),
            ],
        )

    # 3. Landcover & Key Attribute Audits
    landcover_dir = Path(inputs_dict["landcover_directory"])
    if not landcover_dir.is_dir():
        raise FileNotFoundError(f"Landcover directory does not exist: {landcover_dir}")
    shp_files = sorted(p.name for p in landcover_dir.glob("*.shp"))
    study_geom = roi_gdf.geometry.make_valid().union_all()

    attribute_checks: list[LandcoverAttributeAudit] = []
    semantic_statuses = {
        "rowspacing": "raw source field retained; physical units and vehicle rule remain M1 work",
        "depth": "raw source field retained; physical units and crossing rule remain M1 work",
        "Width": "raw source field in decimeters (0.1m scale); converted to effective width 3.0~5.5m",
        "FuncClass": "raw source functional classification field audited; road category modeling",
    }

    for layer_name, fields_dict in field_mapping.items():
        layer_file = (
            Path(inputs_dict["road_path"])
            if layer_name == "road_fina.shp"
            else landcover_dir / layer_name
        )
        if not layer_file.is_file():
            continue
        layer_gdf = gpd.read_file(layer_file)
        if layer_gdf.crs is None:
            continue
        if layer_gdf.crs != roi_gdf.crs:
            layer_gdf = layer_gdf.to_crs(roi_gdf.crs)

        for attr_key, src_field in fields_dict.items():
            if attr_key in {"width_unit_or_scale", "effective_width_m_range"} or not isinstance(src_field, str):
                continue
            if src_field not in layer_gdf.columns:
                continue
            intersecting = layer_gdf.loc[layer_gdf.geometry.intersects(study_geom), src_field].dropna()
            sample_values = [str(v) for v in intersecting.head(5).tolist()]
            numeric_series = pd.to_numeric(intersecting, errors="coerce").dropna()
            attribute_checks.append(
                LandcoverAttributeAudit(
                    layer=layer_name,
                    field=src_field,
                    features_in_study_area=int(intersecting.size),
                    non_null=int(intersecting.size),
                    sample_raw_values=sample_values,
                    numeric_min=None if numeric_series.empty else float(numeric_series.min()),
                    numeric_max=None if numeric_series.empty else float(numeric_series.max()),
                    semantic_status=semantic_statuses.get(
                        src_field, "raw source field audited; M1 modeling pending"
                    ),
                )
            )

    landcover = LandcoverReference(
        source_directory=landcover_dir.as_posix(),
        crs=str(roi_gdf.crs),
        layers=shp_files,
        attribute_checks=attribute_checks,
    )

    # 4. Road Reference
    road_path = Path(inputs_dict["road_path"])
    if not road_path.is_file():
        raise FileNotFoundError(f"Road shapefile does not exist: {road_path}")
    road_gdf = gpd.read_file(road_path)
    road_mapping = field_mapping.get("road_fina.shp", {})
    width_col = (
        road_mapping.get("width")
        if isinstance(road_mapping.get("width"), str) and road_mapping.get("width") in road_gdf.columns
        else ("Width" if "Width" in road_gdf.columns else None)
    )
    scale_raw = road_mapping.get("width_unit_or_scale", "0.1m")
    scale = 0.1
    if isinstance(scale_raw, str):
        cleaned = scale_raw.rstrip("m").strip()
        try:
            scale = float(cleaned)
        except ValueError:
            scale = 0.1
    elif isinstance(scale_raw, (int, float)):
        scale = float(scale_raw)

    sample_widths: list[float] = []
    effective_widths: list[float] = []
    if width_col and width_col in road_gdf.columns:
        w_series = pd.to_numeric(road_gdf[width_col], errors="coerce").dropna()
        sample_widths = [float(v) for v in w_series.head(5).tolist()]
        eff_series = w_series.apply(lambda w: resolve_road_effective_width_m(w, scale=scale))
        if not eff_series.empty:
            effective_widths = [float(eff_series.min()), float(eff_series.max())]

    sample_types: list[str] = []
    road_type_col = (
        road_mapping.get("functional_class")
        if isinstance(road_mapping.get("functional_class"), str) and road_mapping.get("functional_class") in road_gdf.columns
        else (
            "FuncClass"
            if "FuncClass" in road_gdf.columns
            else ("Kind" if "Kind" in road_gdf.columns else None)
        )
    )
    if road_type_col and road_type_col in road_gdf.columns:
        sample_types = [str(v) for v in road_gdf[road_type_col].dropna().head(5).tolist()]

    range_cfg = road_mapping.get("effective_width_m_range")
    if isinstance(range_cfg, list) and len(range_cfg) == 2 and all(isinstance(v, (int, float)) for v in range_cfg):
        fallback_range = [float(range_cfg[0]), float(range_cfg[1])]
    else:
        fallback_range = [3.0, 5.5]

    road = RoadReference(
        path=road_path.as_posix(),
        crs=str(road_gdf.crs),
        width_field=width_col or "Width",
        feature_count=len(road_gdf),
        sample_widths=sample_widths,
        road_type_field=road_type_col,
        sample_road_types=sample_types,
        width_unit_or_scale=str(scale_raw),
        effective_width_m_range=effective_widths if effective_widths else fallback_range,
    )

    # 5. Orthophoto Reference
    ortho_path = Path(inputs_dict["orthophoto_path"])
    preview_path = inputs_dict.get("orthophoto_preview_path")
    if not ortho_path.is_file():
        raise FileNotFoundError(f"Orthophoto raster does not exist: {ortho_path}")
    with rasterio.open(ortho_path) as ortho_ds:
        if ortho_ds.crs is None:
            raise ValueError(f"Orthophoto raster has no CRS: {ortho_path}")
        _check_raster_overlaps_bounds(ortho_ds, bounds_wgs84, "Orthophoto")
        ortho_bounds_wgs84 = transform_bounds(
            ortho_ds.crs, "EPSG:4326", *ortho_ds.bounds, densify_pts=21
        )
        ortho_res_m = float(ortho_ds.res[0])

        acquisition_time = config.get("orthophoto_acquisition_time")
        if not acquisition_time:
            with suppress(Exception):
                dt_tag = ortho_ds.tags().get("TIFFTAG_DATETIME")
                if dt_tag:
                    acquisition_time = str(dt_tag)
        if not acquisition_time:
            with suppress(Exception):
                mtime_val = ortho_path.stat().st_mtime
                acquisition_time = datetime.fromtimestamp(mtime_val, tz=timezone.utc).isoformat()

        orthophoto = OrthophotoReference(
            source_path=ortho_path.as_posix(),
            crs=str(ortho_ds.crs),
            native_resolution_m=ortho_res_m,
            bounds_wgs84=[
                [float(ortho_bounds_wgs84[1]), float(ortho_bounds_wgs84[0])],
                [float(ortho_bounds_wgs84[3]), float(ortho_bounds_wgs84[2])],
            ],
            preview_path=Path(preview_path).as_posix() if preview_path else None,
            acquisition_time=acquisition_time,
        )

    # 6. Soil Reference
    soil_path = Path(inputs_dict["soil_path"])
    catalog_path = Path(inputs_dict["soil_catalog_path"])
    if not soil_path.is_file():
        raise FileNotFoundError(f"Soil raster does not exist: {soil_path}")
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Soil catalog does not exist: {catalog_path}")
    with rasterio.open(soil_path) as soil_ds:
        if soil_ds.crs is None:
            raise ValueError(f"Soil raster has no CRS: {soil_path}")
        _check_raster_overlaps_bounds(soil_ds, bounds_wgs84, "Soil")
        soil_crs = str(soil_ds.crs)
        soil_res = [float(soil_ds.res[0]), float(soil_ds.res[1])]
    catalog_gdf = gpd.read_file(catalog_path)
    soil = SoilReference(
        raster_path=soil_path.as_posix(),
        catalog_path=catalog_path.as_posix(),
        crs=soil_crs,
        native_resolution=soil_res,
        class_count=len(catalog_gdf),
        applicability=str(
            config.get(
                "soil_applicability",
                "M0 registers source classes; M1 implements Bekker/CI vehicle rating rules.",
            )
        ),
    )

    # 7. Moisture Reference
    moisture_paths = [Path(p).as_posix() for p in inputs_dict.get("static_moisture_paths", [])]
    for mp in moisture_paths:
        if not Path(mp).is_file():
            raise FileNotFoundError(f"Static moisture file does not exist: {mp}")
    observation_time = config.get("moisture_observation_time")
    if not observation_time and moisture_paths:
        first_name = Path(moisture_paths[0]).name
        match = re.search(r"(\d{4})(\d{2})(\d{2})\d{2}\.nc", first_name)
        if match:
            observation_time = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    moisture = MoistureReference(
        paths=moisture_paths,
        unit="m3/m3",
        depth_layers=["0-5cm", "5-10cm", "10-40cm"],
        observation_time=observation_time,
    )

    # 8. Hydrology Reference
    hydro_dict = {str(k): Path(v).as_posix() for k, v in inputs_dict.get("hydrology_layers", {}).items()}
    hydro_crs: str | None = None
    for hname, hpath in hydro_dict.items():
        hp = Path(hpath)
        if not hp.is_file():
            raise FileNotFoundError(f"Hydrology layer '{hname}' does not exist: {hpath}")
        if hydro_crs is None:
            with rasterio.open(hp) as hds:
                hydro_crs = str(hds.crs)
    hydrology = HydrologyReference(
        upstream_layers=hydro_dict,
        crs=hydro_crs,
    )

    primary_od = config.get("primary_od")
    vehicle = config.get("vehicle")
    quality_and_budget_status = config.get(
        "quality_and_budget_status",
        "M0 freezes no quality-cost parameters or length budget because those interfaces "
        "begin at M2/M3; this baseline is baseline_original, not B0 under a common A2 layer.",
    )
    metadata = dict(config.get("metadata", {}))

    return StaticScene(
        scene_id=scene_id,
        metric_crs=metric_crs,
        study_area=study_area,
        dem=dem,
        landcover=landcover,
        road=road,
        orthophoto=orthophoto,
        soil=soil,
        moisture=moisture,
        hydrology=hydrology,
        weather=weather_ref,
        mapping_time=mapping_time,
        field_mapping=field_mapping,
        model_version=model_version,
        baseline_source_commit=baseline_source_commit,
        primary_od=primary_od,
        vehicle=vehicle,
        quality_and_budget_status=quality_and_budget_status,
        metadata=metadata,
    )


def _resolve_inputs_dict(
    inputs: dict[str, Any] | str | Path,
    assets_fallback_path: str | Path | None = None,
    preview_fallback_path: str | Path | None = None,
) -> dict[str, Any]:
    """Normalize input parameters from various request mappings, serialized scenes, or files."""
    payload: dict[str, Any]
    if isinstance(inputs, (str, Path)):
        p = Path(inputs)
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            payload = cast(dict[str, Any], yaml.safe_load(text))
        else:
            payload = cast(dict[str, Any], json.loads(text))
    else:
        payload = dict(inputs)

    # Detect nested project format (tile_build, route, map_display)
    tile_build = payload.get("tile_build")
    map_display = payload.get("map_display")

    # Detect nested StaticScene format (dem, orthophoto, landcover, road, soil, study_area)
    dem_val = payload.get("dem")
    ortho_val = payload.get("orthophoto")
    lc_val = payload.get("landcover")
    road_val = payload.get("road")
    soil_val = payload.get("soil")
    sa_val = payload.get("study_area")
    moisture_val = payload.get("moisture")
    hydro_val = payload.get("hydrology")

    dem = (
        (tile_build.get("dem_path") if isinstance(tile_build, dict) else None)
        or (dem_val.get("path") if isinstance(dem_val, dict) else dem_val)
        or payload.get("dem_path")
    )
    ortho = (
        (map_display.get("orthophoto_source_path") if isinstance(map_display, dict) else None)
        or (ortho_val.get("source_path") if isinstance(ortho_val, dict) else ortho_val)
        or payload.get("orthophoto_path")
        or payload.get("orthophoto_source_path")
    )
    preview = (
        preview_fallback_path
        or (map_display.get("orthophoto_preview_path") if isinstance(map_display, dict) else None)
        or (ortho_val.get("preview_path") if isinstance(ortho_val, dict) else None)
        or payload.get("orthophoto_preview_path")
    )
    if not preview and isinstance(map_display, dict):
        preview_meta_path = map_display.get("orthophoto_preview_metadata_path")
        if preview_meta_path and Path(preview_meta_path).is_file():
            with suppress(Exception):
                pm = json.loads(Path(preview_meta_path).read_text(encoding="utf-8"))
                if isinstance(pm, dict) and "preview_path" in pm:
                    preview = pm["preview_path"]

    landcover = (
        (tile_build.get("landcover_path") if isinstance(tile_build, dict) else None)
        or (lc_val.get("source_directory") if isinstance(lc_val, dict) else lc_val)
        or payload.get("landcover_directory")
        or payload.get("landcover_path")
    )
    road = (
        (tile_build.get("road_path") if isinstance(tile_build, dict) else None)
        or (road_val.get("path") if isinstance(road_val, dict) else road_val)
        or payload.get("road_path")
    )
    roi = (
        (tile_build.get("roi_layer_path") if isinstance(tile_build, dict) else None)
        or (sa_val.get("source_layer") if isinstance(sa_val, dict) else sa_val)
        or payload.get("roi")
        or payload.get("roi_layer_path")
        or payload.get("roi_path")
    )
    soil = (
        (tile_build.get("soil_path") if isinstance(tile_build, dict) else None)
        or (soil_val.get("raster_path") if isinstance(soil_val, dict) else soil_val)
        or payload.get("soil_path")
    )
    soil_cat = (
        (tile_build.get("soil_catalog_path") if isinstance(tile_build, dict) else None)
        or (soil_val.get("catalog_path") if isinstance(soil_val, dict) else None)
        or payload.get("soil_catalog")
        or payload.get("soil_catalog_path")
    )

    static_moisture = (
        (moisture_val.get("paths") if isinstance(moisture_val, dict) else None)
        or payload.get("static_moisture")
        or payload.get("static_moisture_paths")
    )
    hydrology = (
        (hydro_val.get("upstream_layers") if isinstance(hydro_val, dict) else None)
        or payload.get("hydrology")
        or payload.get("hydrology_layers")
    )

    # Automatic fallback to standard private assets file if not in payload and not passed
    if not static_moisture or not hydrology:
        if not assets_fallback_path:
            std_assets = (
                Path(__file__).resolve().parents[2] / "configs" / "manned_assets.private.yaml"
            )
            if std_assets.is_file():
                assets_fallback_path = std_assets
        if assets_fallback_path:
            ap = Path(assets_fallback_path)
            if ap.is_file():
                assets = cast(dict[str, Any], yaml.safe_load(ap.read_text(encoding="utf-8")))
                if not static_moisture:
                    static_moisture = assets.get("static_moisture", [])
                if not hydrology:
                    hydrology = assets.get("hydrology", {})

    if not dem or not ortho or not landcover or not road or not roi or not soil or not soil_cat:
        missing = [
            k
            for k, v in [
                ("dem", dem),
                ("orthophoto", ortho),
                ("landcover", landcover),
                ("road", road),
                ("roi", roi),
                ("soil", soil),
                ("soil_catalog", soil_cat),
            ]
            if not v
        ]
        raise ValueError(f"Missing required GIS input paths in scene inputs: {missing}")

    return {
        "dem_path": dem,
        "orthophoto_path": ortho,
        "orthophoto_preview_path": preview,
        "landcover_directory": landcover,
        "road_path": road,
        "roi_path": roi,
        "soil_path": soil,
        "soil_catalog_path": soil_cat,
        "static_moisture_paths": list(static_moisture or []),
        "hydrology_layers": dict(hydrology or {}),
    }


def _resolve_weather_reference(
    weather_snapshot: dict[str, Any] | str | Path,
) -> WeatherSnapshotReference:
    """Normalize and validate the frozen weather snapshot input."""
    raw: dict[str, Any]
    snapshot_path_str: str
    if isinstance(weather_snapshot, (str, Path)):
        p = Path(weather_snapshot)
        if not p.is_file():
            raise FileNotFoundError(f"Weather snapshot file does not exist: {p}")
        raw = cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
        snapshot_path_str = p.as_posix()
    else:
        raw = dict(weather_snapshot)
        val = raw.get("snapshot_path", "")
        snapshot_path_str = Path(str(val)).as_posix() if val else ""

    if raw.get("degraded", False):
        reason = raw.get("degradation_reason", "unknown")
        raise ValueError(f"Weather snapshot is marked degraded: {reason}")

    valid_at = str(raw.get("valid_at", ""))
    if not valid_at:
        raise ValueError("Weather snapshot missing required 'valid_at' timestamp.")

    precip = float(raw.get("precipitation_24h_mm", 0.0))
    if precip < 0.0:
        raise ValueError(f"Weather snapshot precipitation cannot be negative: {precip}")

    moisture_surface = float(raw.get("soil_moisture_surface_m3_m3", 0.0))
    if moisture_surface < 0.0:
        raise ValueError(
            f"Weather snapshot surface soil moisture cannot be negative: {moisture_surface}"
        )

    return WeatherSnapshotReference(
        snapshot_path=snapshot_path_str,
        provider=str(raw.get("provider", "open-meteo")),
        valid_at=valid_at,
        precipitation_24h_mm=precip,
        soil_moisture_surface_m3_m3=moisture_surface,
        degraded=bool(raw.get("degraded", False)),
        model=str(raw.get("model", "best_match")),
        replay_rule=str(
            raw.get(
                "replay_rule",
                "All M0 reruns read this frozen snapshot; do not query new weather for this baseline.",
            )
        ),
    )


def _file_sha256(path: Path | str) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _pixel_index(
    inverse_transform: Any, x: float, y: float
) -> tuple[int, int]:
    """Return the (row, col) of the raster pixel that contains (x, y).

    `~dataset.transform * (x, y)` yields *corner-based* pixel coordinates:
    integer values lie on pixel edges and `k + 0.5` is a pixel centre. The
    pixel containing the point is therefore `floor(...)`. Using `round(...)`
    instead shifts every sample in the second half of a pixel into the
    neighbouring pixel, which for the 0.0625 deg CLDAS grid is a ~3.45 km error
    and can collapse an entire corridor onto a single value.

    Args:
        inverse_transform: Affine inverse of the dataset transform.
        x: World x coordinate (or longitude for a geographic raster).
        y: World y coordinate (or latitude for a geographic raster).

    Returns:
        `(row, col)` pixel indices; callers must still bounds-check the shape.
    """
    col_float, row_float = inverse_transform * (x, y)
    return int(math.floor(row_float)), int(math.floor(col_float))


def enrich_graph_from_static_scene(
    graph: H3Graph,
    scene_source: StaticScene | dict[str, Any] | str | Path,
    cldas_layer_index: int = 0,
) -> dict[str, Any]:
    """Enrich an in-memory H3Graph with real raster inputs registered in StaticScene.

    Samples:
      - Soil raster (soil_nanjing.tif) + VAT DBF catalog -> soil_code, soil_type, soil_texture, uscs.
        (Nodata/unmapped cells retain None; no hardcoded 'CL' default).
      - CLDAS soil moisture NetCDF layer -> soil_moisture (0-5cm layer by default).
      - Drainage sensitivity raster (EPSG:32650) -> drainage_sensitivity, drainage_valid.
      - Road vs offroad surface response -> surface_response (0.0 for road, 0.9 for offroad).

    Returns:
      Comprehensive metadata dictionary including file paths, SHA-256 hashes,
      enrichment histograms, and statistics.
    """
    if isinstance(scene_source, (str, Path)):
        scene_path = Path(scene_source)
        if not scene_path.is_file():
            raise FileNotFoundError(f"Scene file does not exist: {scene_path}")
        scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
    elif isinstance(scene_source, StaticScene):
        scene_data = scene_source.to_dict()
    elif isinstance(scene_source, dict):
        scene_data = scene_source
    else:
        raise TypeError(f"Unsupported scene_source type: {type(scene_source)}")

    soil_cfg = scene_data.get("soil", {})
    soil_raster_path = Path(str(soil_cfg.get("raster_path", "")))
    soil_catalog_path = Path(str(soil_cfg.get("catalog_path", "")))

    moisture_cfg = scene_data.get("moisture", {})
    moisture_paths = [Path(p) for p in moisture_cfg.get("paths", [])]

    hydro_cfg = scene_data.get("hydrology", {})
    hydro_layers = hydro_cfg.get("upstream_layers", {})
    drainage_path_str = hydro_layers.get("drainage_sensitivity")
    drainage_path = Path(drainage_path_str) if drainage_path_str else None

    # Compute input hashes
    file_hashes: dict[str, str] = {
        "soil_raster": _file_sha256(soil_raster_path) if soil_raster_path.is_file() else "",
        "soil_catalog": _file_sha256(soil_catalog_path) if soil_catalog_path.is_file() else "",
        "drainage_sensitivity": _file_sha256(drainage_path) if (drainage_path and drainage_path.is_file()) else "",
    }
    cldas_file = moisture_paths[cldas_layer_index] if (0 <= cldas_layer_index < len(moisture_paths)) else None
    if cldas_file and cldas_file.is_file():
        file_hashes["cldas_moisture"] = _file_sha256(cldas_file)

    # 1. Load Soil Catalog
    catalog = {}
    if soil_catalog_path.is_file():
        catalog = GISPreprocessor().load_soil_catalog(str(soil_catalog_path))

    cells = list(graph.cells.values())
    if not cells:
        return {"total_cells_enriched": 0, "file_hashes": file_hashes}

    lats = [c.lat for c in cells]
    lngs = [c.lng for c in cells]

    # 2. Sample Soil Raster
    soil_hist: dict[int, int] = {}
    uscs_hist: dict[str, int] = {}
    missing_soil_count = 0
    soil_pixels: set[tuple[int, int]] = set()

    if soil_raster_path.is_file():
        with rasterio.open(soil_raster_path) as s_ds:
            s_band = s_ds.read(1)
            s_nodata = s_ds.nodata
            s_ny, s_nx = s_band.shape
            inv_s_gt = ~s_ds.transform
            
            if s_ds.crs and not s_ds.crs.is_geographic:
                s_trans = Transformer.from_crs("EPSG:4326", s_ds.crs, always_xy=True)
                s_xs, s_ys = s_trans.transform(lngs, lats)
            else:
                s_xs, s_ys = lngs, lats

            for i, c in enumerate(cells):
                row, col = _pixel_index(inv_s_gt, s_xs[i], s_ys[i])
                matched_profile = None
                if 0 <= row < s_ny and 0 <= col < s_nx:
                    soil_pixels.add((row, col))
                    raw_val = int(s_band[row, col])
                    if raw_val > 0 and (s_nodata is None or raw_val != s_nodata) and raw_val in catalog:
                        matched_profile = catalog[raw_val]
                        soil_hist[raw_val] = soil_hist.get(raw_val, 0) + 1

                if matched_profile is not None:
                    c.soil_code = matched_profile.code
                    c.soil_type = matched_profile.name_zh
                    c.soil_texture = matched_profile.soil_texture
                    c.uscs = matched_profile.uscs
                    u_key = matched_profile.uscs or "UNKNOWN"
                    uscs_hist[u_key] = uscs_hist.get(u_key, 0) + 1
                else:
                    c.soil_code = None
                    c.soil_type = None
                    c.soil_texture = None
                    c.uscs = None
                    missing_soil_count += 1
                    uscs_hist["MISSING_SOIL"] = uscs_hist.get("MISSING_SOIL", 0) + 1
    else:
        missing_soil_count = len(cells)
        uscs_hist["MISSING_SOIL"] = len(cells)
        for c in cells:
            c.soil_code = None
            c.soil_type = None
            c.soil_texture = None
            c.uscs = None

    # 3. Sample CLDAS Moisture raster
    moisture_vals: list[float] = []
    missing_moisture_count = 0
    moisture_pixels: set[tuple[int, int]] = set()
    if cldas_file and cldas_file.is_file():
        with rasterio.open(cldas_file) as c_ds:
            c_band = c_ds.read(1)
            c_nodata = c_ds.nodata
            c_ny, c_nx = c_band.shape
            inv_c_gt = ~c_ds.transform
            if c_ds.crs is not None and not c_ds.crs.is_geographic:
                c_trans = Transformer.from_crs("EPSG:4326", c_ds.crs, always_xy=True)
                c_xs, c_ys = c_trans.transform(lngs, lats)
            else:
                c_xs, c_ys = lngs, lats
            for i, c in enumerate(cells):
                row, col = _pixel_index(inv_c_gt, c_xs[i], c_ys[i])
                assigned = False
                if 0 <= row < c_ny and 0 <= col < c_nx:
                    moisture_pixels.add((row, col))
                    val = float(c_band[row, col])
                    if np.isfinite(val) and val > 0.0 and (c_nodata is None or abs(val - c_nodata) > 1e-3) and val <= 1.0:
                        c.soil_moisture = val
                        moisture_vals.append(val)
                        assigned = True
                if not assigned:
                    c.soil_moisture = None
                    missing_moisture_count += 1
    else:
        missing_moisture_count = len(cells)
        for c in cells:
            c.soil_moisture = None

    # 4. Sample Drainage Sensitivity Raster
    drainage_vals: list[float] = []
    valid_drainage_count = 0
    missing_drainage_count = 0
    drainage_pixels: set[tuple[int, int]] = set()
    if drainage_path and drainage_path.is_file():
        with rasterio.open(drainage_path) as d_ds:
            d_band = d_ds.read(1)
            d_nodata = d_ds.nodata
            d_ny, d_nx = d_band.shape
            inv_d_gt = ~d_ds.transform
            if d_ds.crs and not d_ds.crs.is_geographic:
                d_trans = Transformer.from_crs("EPSG:4326", d_ds.crs, always_xy=True)
                d_xs, d_ys = d_trans.transform(lngs, lats)
            else:
                d_xs, d_ys = lngs, lats

            for i, c in enumerate(cells):
                row, col = _pixel_index(inv_d_gt, d_xs[i], d_ys[i])
                assigned = False
                if 0 <= row < d_ny and 0 <= col < d_nx:
                    drainage_pixels.add((row, col))
                    val = float(d_band[row, col])
                    is_nodata = (d_nodata is not None and (np.isnan(val) if np.isnan(d_nodata) else val == d_nodata))
                    if np.isfinite(val) and not is_nodata:
                        clamped = float(np.clip(val, 0.0, 1.0))
                        c.drainage_sensitivity = clamped
                        c.drainage_valid = True
                        drainage_vals.append(clamped)
                        valid_drainage_count += 1
                        assigned = True
                if not assigned:
                    c.drainage_sensitivity = None
                    c.drainage_valid = False
                    missing_drainage_count += 1
    else:
        missing_drainage_count = len(cells)
        for c in cells:
            c.drainage_sensitivity = None
            c.drainage_valid = False

    # 5. Set Surface Response
    road_count = 0
    offroad_count = 0
    for c in cells:
        if c.has_road:
            c.surface_response = 0.0
            road_count += 1
        else:
            c.surface_response = 0.9
            offroad_count += 1

    return {
        "total_cells_enriched": len(cells),
        "soil": {
            "source_path": str(soil_raster_path),
            "catalog_path": str(soil_catalog_path),
            "histogram": soil_hist,
            "uscs_histogram": uscs_hist,
            "missing_soil_count": missing_soil_count,
            "distinct_pixels": len(soil_pixels),
        },
        "moisture": {
            "source_path": str(cldas_file) if cldas_file else None,
            "layer_index": cldas_layer_index,
            "count": len(moisture_vals),
            "missing_count": missing_moisture_count,
            "min": float(min(moisture_vals)) if moisture_vals else None,
            "max": float(max(moisture_vals)) if moisture_vals else None,
            "mean": float(sum(moisture_vals) / len(moisture_vals)) if moisture_vals else None,
            "distinct_pixels": len(moisture_pixels),
            "distinct_values": len({round(v, 6) for v in moisture_vals}),
        },
        "drainage": {
            "source_path": str(drainage_path) if drainage_path else None,
            "valid_count": valid_drainage_count,
            "missing_count": missing_drainage_count,
            "min": float(min(drainage_vals)) if drainage_vals else None,
            "max": float(max(drainage_vals)) if drainage_vals else None,
            "mean": float(sum(drainage_vals) / len(drainage_vals)) if drainage_vals else None,
            "distinct_pixels": len(drainage_pixels),
        },
        "surface_response": {
            "road_cells": road_count,
            "offroad_cells": offroad_count,
        },
        "file_hashes": file_hashes,
    }
