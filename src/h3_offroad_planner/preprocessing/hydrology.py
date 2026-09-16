"""Offline GRASS hydrology preprocessing for static drainage evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds

from h3_offroad_planner.models import ConfigError, GISInputError

__all__ = [
    "HydrologyArtifacts",
    "HydrologyConfig",
    "map_twi_to_drainage",
    "preprocess_hydrology",
]


@dataclass(frozen=True)
class HydrologyConfig:
    """Frozen, region-independent GRASS/TWI processing policy."""

    backend: str = "grass_r_watershed"
    flow_method: str = "mfd"
    analysis_resolution_m: float | None = None
    mapping_t0: float | None = None
    mapping_t1: float | None = None
    upstream_complete: bool | None = None
    version: str = "twi_drainage_v1"

    def __post_init__(self) -> None:
        if self.backend != "grass_r_watershed":
            raise ConfigError("hydrology backend must be 'grass_r_watershed'.")
        if self.flow_method not in {"mfd", "d8"}:
            raise ConfigError("hydrology flow_method must be 'mfd' or 'd8'.")
        if self.analysis_resolution_m is not None and (
            not isfinite(self.analysis_resolution_m) or self.analysis_resolution_m <= 0.0
        ):
            raise ConfigError("analysis_resolution_m must be finite and positive.")
        if (self.mapping_t0 is None) != (self.mapping_t1 is None):
            raise ConfigError("mapping_t0 and mapping_t1 must be provided together.")
        if self.mapping_t0 is not None and self.mapping_t1 is not None:
            if not all(isfinite(value) for value in (self.mapping_t0, self.mapping_t1)):
                raise ConfigError("TWI mapping thresholds must be finite.")
            if self.mapping_t1 <= self.mapping_t0:
                raise ConfigError("mapping_t1 must be greater than mapping_t0.")
        if not self.version:
            raise ConfigError("hydrology version must be non-empty.")


@dataclass(frozen=True)
class HydrologyArtifacts:
    """Paths produced by one immutable static hydrology run."""

    accumulation_path: str
    drainage_direction_path: str
    twi_path: str
    drainage_sensitivity_path: str | None
    validity_path: str
    boundary_influence_path: str
    manifest_path: str


def map_twi_to_drainage(
    twi: npt.NDArray[np.floating],
    valid: npt.NDArray[np.bool_],
    t0: float,
    t1: float,
) -> npt.NDArray[np.float32]:
    """Map valid TWI values to D in [0, 1], preserving invalid cells as NaN."""
    if twi.shape != valid.shape or twi.ndim != 2:
        raise ValueError("twi and valid must be same-shape 2D arrays.")
    if not isfinite(t0) or not isfinite(t1) or t1 <= t0:
        raise ValueError("TWI thresholds must be finite and satisfy t1 > t0.")
    usable = valid & np.isfinite(twi)
    result = np.full(twi.shape, np.nan, dtype=np.float32)
    result[usable] = np.clip((twi[usable] - t0) / (t1 - t0), 0.0, 1.0)
    return result


def preprocess_hydrology(
    dem_path: str,
    output_dir: str,
    config: HydrologyConfig,
    *,
    grass_executable: str = "grass",
) -> HydrologyArtifacts:
    """Run one offline GRASS r.watershed backend and persist TWI/D provenance."""
    dem = Path(dem_path)
    if not dem.is_file():
        raise FileNotFoundError(dem_path)
    executable = shutil.which(grass_executable)
    if executable is None:
        raise GISInputError(
            f"GRASS executable {grass_executable!r} is unavailable; hydrology must be "
            "prepared offline before route requests."
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    analysis_dem = _prepare_metric_dem(dem, output, config.analysis_resolution_m)
    paths = {
        "accumulation": output / "accumulation.tif",
        "drainage_direction": output / "drainage_direction.tif",
        "twi": output / "twi.tif",
        "drainage_sensitivity": output / "drainage_sensitivity.tif",
        "validity": output / "drainage_validity.tif",
        "boundary": output / "boundary_influence.tif",
        "manifest": output / "hydrology_manifest.json",
    }
    with TemporaryDirectory(prefix="h3-hydrology-", dir=output) as temporary:
        location = Path(temporary) / "location"
        _run_grass([executable, "-c", str(analysis_dem), str(location), "-e"])
        mapset = str(location / "PERMANENT")
        _run_grass(
            [
                executable,
                mapset,
                "--exec",
                "r.in.gdal",
                f"input={analysis_dem}",
                "output=dem",
                "--overwrite",
            ]
        )
        region = [executable, mapset, "--exec", "g.region", "raster=dem"]
        if config.analysis_resolution_m is not None:
            region.append(f"res={config.analysis_resolution_m}")
        _run_grass(region)
        watershed = [
            executable,
            mapset,
            "--exec",
            "r.watershed",
            "elevation=dem",
            "accumulation=accumulation",
            "drainage=drainage_direction",
            "tci=twi",
            "--overwrite",
        ]
        if config.flow_method == "d8":
            watershed.append("-s")
        _run_grass(watershed)
        for name in ("accumulation", "drainage_direction", "twi"):
            _run_grass(
                [
                    executable,
                    mapset,
                    "--exec",
                    "r.out.gdal",
                    f"input={name}",
                    f"output={paths[name]}",
                    "format=GTiff",
                    "createopt=COMPRESS=DEFLATE",
                    "--overwrite",
                ]
            )
    _write_masks_and_drainage(paths, config)
    manifest = _manifest_payload(dem, analysis_dem, paths, config, executable)
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return HydrologyArtifacts(
        accumulation_path=str(paths["accumulation"]),
        drainage_direction_path=str(paths["drainage_direction"]),
        twi_path=str(paths["twi"]),
        drainage_sensitivity_path=(
            str(paths["drainage_sensitivity"]) if paths["drainage_sensitivity"].exists() else None
        ),
        validity_path=str(paths["validity"]),
        boundary_influence_path=str(paths["boundary"]),
        manifest_path=str(paths["manifest"]),
    )


def _run_grass(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GISInputError(f"GRASS hydrology command failed: {detail}")


def _require_metric_dem(path: Path) -> None:
    with rasterio.open(path) as src:
        if src.crs is None:
            raise GISInputError(f"DEM raster has no CRS: {path}")
        if src.crs.is_geographic:
            raise GISInputError("hydrology DEM must use a projected metric CRS.")
        units = (src.crs.linear_units or "").lower()
        if units not in {"metre", "meter", "metres", "meters", "m"}:
            raise GISInputError(f"hydrology DEM linear unit must be meters, got {units!r}.")


def _prepare_metric_dem(
    source_path: Path,
    output_dir: Path,
    resolution_m: float | None,
) -> Path:
    """Return a meter-projected DEM, persisting an auditable reprojection when needed."""
    with rasterio.open(source_path) as src:
        if src.crs is None:
            raise GISInputError(f"DEM raster has no CRS: {source_path}")
        if not src.crs.is_geographic:
            _require_metric_dem(source_path)
            return source_path
        west, south, east, north = transform_bounds(
            src.crs,
            "EPSG:4326",
            *src.bounds,
            densify_pts=21,
        )
        center_lng = (west + east) / 2.0
        center_lat = (south + north) / 2.0
        zone = min(60, max(1, int((center_lng + 180.0) // 6.0) + 1))
        target_crs = f"EPSG:{32600 + zone if center_lat >= 0.0 else 32700 + zone}"
        transform, width, height = calculate_default_transform(
            src.crs,
            target_crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=resolution_m,
        )
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            crs=target_crs,
            transform=transform,
            width=width,
            height=height,
            count=1,
            compress="deflate",
        )
        target = output_dir / "analysis_dem_metric.tif"
        with rasterio.open(target, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs=target_crs,
                dst_nodata=src.nodata,
                resampling=Resampling.bilinear,
            )
    _require_metric_dem(target)
    return target


def _write_masks_and_drainage(
    paths: dict[str, Path],
    config: HydrologyConfig,
) -> None:
    with rasterio.open(paths["twi"]) as twi_src:
        twi = twi_src.read(1, masked=True).astype(np.float64).filled(np.nan)
        profile = twi_src.profile.copy()
    with rasterio.open(paths["accumulation"]) as accumulation_src:
        accumulation = accumulation_src.read(1, masked=True).astype(np.float64).filled(np.nan)
    valid = np.isfinite(twi)
    boundary = np.isfinite(accumulation) & (accumulation < 0.0)
    if config.upstream_complete is not True:
        boundary[[0, -1], :] = True
        boundary[:, [0, -1]] = True
    _write_mask(paths["validity"], valid, profile)
    _write_mask(paths["boundary"], boundary, profile)
    if config.mapping_t0 is not None and config.mapping_t1 is not None:
        drainage = map_twi_to_drainage(twi, valid, config.mapping_t0, config.mapping_t1)
        drainage_profile = profile | {"dtype": "float32", "nodata": np.nan, "count": 1}
        with rasterio.open(paths["drainage_sensitivity"], "w", **drainage_profile) as dst:
            dst.write(drainage, 1)


def _write_mask(path: Path, values: npt.NDArray[np.bool_], profile: dict[str, object]) -> None:
    mask_profile = profile | {"dtype": "uint8", "nodata": 255, "count": 1}
    with rasterio.open(path, "w", **mask_profile) as dst:
        dst.write(values.astype(np.uint8), 1)


def _manifest_payload(
    dem: Path,
    analysis_dem: Path,
    paths: dict[str, Path],
    config: HydrologyConfig,
    executable: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "static_hydrology_cache",
        "backend": config.backend,
        "backend_executable": executable,
        "config": asdict(config),
        "dem_path": str(dem),
        "dem_sha256": _file_hash(dem),
        "analysis_dem_path": str(analysis_dem),
        "analysis_dem_sha256": _file_hash(analysis_dem),
        "analysis_dem_crs": _raster_crs(analysis_dem),
        "outputs": {
            key: str(path) for key, path in paths.items() if key != "manifest" and path.exists()
        },
        "boundary_influence": (
            "complete_upstream_declared"
            if config.upstream_complete is True
            else "potential_boundary_influence"
        ),
        "drainage_mapping_status": (
            "frozen" if config.mapping_t0 is not None else "diagnostic_only"
        ),
    }


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raster_crs(path: Path) -> str:
    with rasterio.open(path) as src:
        if src.crs is None:
            raise GISInputError(f"raster has no CRS: {path}")
        return str(src.crs)
