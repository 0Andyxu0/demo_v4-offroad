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

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import geopandas as gpd
import pandas as pd
import pyproj
import rasterio
from rasterio.warp import transform_bounds
import yaml

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
    "load_static_scene",
    "prepare_static_scene",
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
    """Road network vector data and width attribute reference."""

    path: str
    crs: str
    width_field: str
    feature_count: int
    sample_widths: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrthophotoReference:
    """Local orthophoto raster reference for display and boundary verification."""

    source_path: str
    crs: str
    native_resolution_m: float
    bounds_wgs84: list[list[float]]  # [[south, west], [north, east]]
    preview_path: str | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MoistureReference:
    """Static moisture observation products (e.g. CLDAS daily NetCDF)."""

    paths: list[str]
    unit: str = "m3/m3"
    depth_layers: list[str] = field(default_factory=list)
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
        )

        ortho_data = data.get("orthophoto", {})
        orthophoto = OrthophotoReference(
            source_path=ortho_data.get("source_path", ""),
            crs=ortho_data.get("crs", ""),
            native_resolution_m=float(ortho_data.get("native_resolution_m", 0.5)),
            bounds_wgs84=list(ortho_data.get("bounds_wgs84", [[0.0, 0.0], [0.0, 0.0]])),
            preview_path=ortho_data.get("preview_path"),
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
        )

        moisture_data = data.get("moisture", {})
        moisture = MoistureReference(
            paths=list(moisture_data.get("paths", [])),
            unit=moisture_data.get("unit", "m3/m3"),
            depth_layers=list(moisture_data.get("depth_layers", [])),
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
    inputs_dict = _resolve_inputs_dict(inputs, config.get("assets_config_path"))

    scene_id = str(config.get("scene_id", "qdx-dem-coverage-001"))
    metric_crs = str(config.get("metric_crs", "EPSG:4528"))
    model_version = str(config.get("model_version", "m0_static_scene_v1"))
    baseline_source_commit = str(config.get("baseline_source_commit", "986bd58"))
    mapping_time = str(config.get("mapping_time", datetime.now(timezone.utc).isoformat()))

    field_mapping: dict[str, dict[str, str]] = config.get(
        "field_mapping",
        {
            "forest.shp": {"rowspacing": "rowspacing"},
            "water.shp": {"depth": "depth"},
            "road_fina.shp": {"width": "Width"},
        },
    )

    # 1. Study Area / ROI
    roi_path = Path(inputs_dict["roi_path"])
    if not roi_path.is_file():
        raise FileNotFoundError(f"Study boundary layer does not exist: {roi_path}")
    roi_gdf = gpd.read_file(roi_path)
    if roi_gdf.empty or roi_gdf.crs is None:
        raise ValueError(f"Study boundary layer is empty or has no CRS: {roi_path}")

    # Compute WGS84 bounds [west, south, east, north]
    wgs84_gdf = roi_gdf.to_crs("EPSG:4326")
    w, s, e, n = [float(v) for v in wgs84_gdf.total_bounds]
    bounds_wgs84 = [w, s, e, n]

    # Compute metric bounds [left, bottom, right, top]
    metric_gdf = roi_gdf.to_crs(metric_crs)
    bounds_metric = [float(v) for v in metric_gdf.total_bounds]

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
    study_geom = roi_gdf.geometry.union_all()

    attribute_checks: list[LandcoverAttributeAudit] = []
    semantic_statuses = {
        "rowspacing": "raw source field retained; physical units and vehicle rule remain M1 work",
        "depth": "raw source field retained; physical units and crossing rule remain M1 work",
        "Width": "raw source field retained; road-area construction remains M1 work",
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
        if str(layer_gdf.crs) != str(roi_gdf.crs):
            layer_gdf = layer_gdf.to_crs(roi_gdf.crs)

        for src_field in fields_dict.values():
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
    sample_widths: list[float] = []
    if "Width" in road_gdf.columns:
        w_series = pd.to_numeric(road_gdf["Width"], errors="coerce").dropna()
        sample_widths = [float(v) for v in w_series.head(5).tolist()]
    road = RoadReference(
        path=road_path.as_posix(),
        crs=str(road_gdf.crs),
        width_field="Width",
        feature_count=len(road_gdf),
        sample_widths=sample_widths,
    )

    # 5. Orthophoto Reference
    ortho_path = Path(inputs_dict["orthophoto_path"])
    preview_path = inputs_dict.get("orthophoto_preview_path")
    if not ortho_path.is_file():
        raise FileNotFoundError(f"Orthophoto raster does not exist: {ortho_path}")
    with rasterio.open(ortho_path) as ortho_ds:
        if ortho_ds.crs is None:
            raise ValueError(f"Orthophoto raster has no CRS: {ortho_path}")
        ortho_bounds_wgs84 = transform_bounds(
            ortho_ds.crs, "EPSG:4326", *ortho_ds.bounds, densify_pts=21
        )
        ortho_res_m = float(ortho_ds.res[0])
        orthophoto = OrthophotoReference(
            source_path=ortho_path.as_posix(),
            crs=str(ortho_ds.crs),
            native_resolution_m=ortho_res_m,
            bounds_wgs84=[
                [float(ortho_bounds_wgs84[1]), float(ortho_bounds_wgs84[0])],
                [float(ortho_bounds_wgs84[3]), float(ortho_bounds_wgs84[2])],
            ],
            preview_path=Path(preview_path).as_posix() if preview_path else None,
        )

    # 6. Soil Reference
    soil_path = Path(inputs_dict["soil_path"])
    catalog_path = Path(inputs_dict["soil_catalog_path"])
    if not soil_path.is_file():
        raise FileNotFoundError(f"Soil raster does not exist: {soil_path}")
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Soil catalog does not exist: {catalog_path}")
    with rasterio.open(soil_path) as soil_ds:
        soil_crs = str(soil_ds.crs)
        soil_res = [float(soil_ds.res[0]), float(soil_ds.res[1])]
    catalog_gdf = gpd.read_file(catalog_path)
    soil = SoilReference(
        raster_path=soil_path.as_posix(),
        catalog_path=catalog_path.as_posix(),
        crs=soil_crs,
        native_resolution=soil_res,
        class_count=len(catalog_gdf),
    )

    # 7. Moisture Reference
    moisture_paths = [Path(p).as_posix() for p in inputs_dict.get("static_moisture_paths", [])]
    moisture = MoistureReference(
        paths=moisture_paths,
        unit="m3/m3",
        depth_layers=["0-5cm", "5-10cm", "10-40cm"],
    )

    # 8. Hydrology Reference
    hydro_dict = {str(k): Path(v).as_posix() for k, v in inputs_dict.get("hydrology_layers", {}).items()}
    hydro_crs: str | None = None
    if hydro_dict:
        first_layer = Path(next(iter(hydro_dict.values())))
        if first_layer.is_file():
            with rasterio.open(first_layer) as hds:
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
) -> dict[str, Any]:
    """Normalize input parameters from various request mappings or files."""
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

    dem = (
        (tile_build.get("dem_path") if isinstance(tile_build, dict) else None)
        or payload.get("dem")
        or payload.get("dem_path")
    )
    ortho = (
        (map_display.get("orthophoto_source_path") if isinstance(map_display, dict) else None)
        or payload.get("orthophoto")
        or payload.get("orthophoto_path")
        or payload.get("orthophoto_source_path")
    )
    preview = (
        (map_display.get("orthophoto_preview_path") if isinstance(map_display, dict) else None)
        or payload.get("orthophoto_preview_path")
    )
    landcover = (
        (tile_build.get("landcover_path") if isinstance(tile_build, dict) else None)
        or payload.get("landcover_directory")
        or payload.get("landcover_path")
    )
    road = (
        (tile_build.get("road_path") if isinstance(tile_build, dict) else None)
        or payload.get("road")
        or payload.get("road_path")
    )
    roi = (
        (tile_build.get("roi_layer_path") if isinstance(tile_build, dict) else None)
        or payload.get("roi")
        or payload.get("roi_layer_path")
        or payload.get("roi_path")
    )
    soil = (
        (tile_build.get("soil_path") if isinstance(tile_build, dict) else None)
        or payload.get("soil")
        or payload.get("soil_path")
    )
    soil_cat = (
        (tile_build.get("soil_catalog_path") if isinstance(tile_build, dict) else None)
        or payload.get("soil_catalog")
        or payload.get("soil_catalog_path")
    )

    static_moisture = payload.get("static_moisture") or payload.get("static_moisture_paths")
    hydrology = payload.get("hydrology") or payload.get("hydrology_layers")

    # If moisture or hydrology are missing, attempt fallback to assets config
    if (not static_moisture or not hydrology) and assets_fallback_path:
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

    return WeatherSnapshotReference(
        snapshot_path=snapshot_path_str,
        provider=str(raw.get("provider", "open-meteo")),
        valid_at=str(raw.get("valid_at", "")),
        precipitation_24h_mm=float(raw.get("precipitation_24h_mm", 0.0)),
        soil_moisture_surface_m3_m3=float(raw.get("soil_moisture_surface_m3_m3", 0.0)),
        degraded=bool(raw.get("degraded", False)),
        model=str(raw.get("model", "best_match")),
        replay_rule=str(
            raw.get(
                "replay_rule",
                "All M0 reruns read this frozen snapshot; do not query new weather for this baseline.",
            )
        ),
    )
