"""Spec-derived tests for MVP-4.1 tile-based H3 cache construction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import geopandas as gpd
import h3
import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest
import rasterio
from affine import Affine
from shapely.geometry import Polygon, box

from h3_offroad_planner import TileBuildRequest, build_h3_tile_cache
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GridBuildError


def test_t062_tile_build_request_rejects_invalid_values() -> None:
    """T-062: Tile build request validation rejects invalid inputs early."""
    valid = {
        "dem_path": "dem.tif",
        "landcover_path": "landcover.tif",
        "roi_layer_path": "roi.geojson",
        "output_dir": "out",
    }

    with pytest.raises(ValueError, match="dem_path"):
        TileBuildRequest(**(valid | {"dem_path": ""}))
    with pytest.raises(ValueError, match="res_fine"):
        TileBuildRequest(**valid, res_fine=8, tile_res=8)
    with pytest.raises(ValueError, match="max_tiles"):
        TileBuildRequest(**valid, max_tiles=0)
    with pytest.raises(ValueError, match="soil_catalog_path"):
        TileBuildRequest(**valid, soil_path="soil.tif")
    with pytest.raises(ValueError, match="road_path"):
        TileBuildRequest(**valid, road_path="")


def test_t063_tile_cache_writes_per_tile_parquet_and_manifest(tmp_path: Path) -> None:
    """T-063: tile cache build writes per-parent Parquet outputs."""
    sources = _synthetic_sources(tmp_path)

    manifest = build_h3_tile_cache(_tile_request(sources, tmp_path / "cache"))
    manifest_path = tmp_path / "cache" / "tile_manifest.json"

    completed = _completed_records(manifest)
    assert completed
    assert manifest_path.exists()
    assert all(Path(str(record["path"])).exists() for record in completed)
    assert all("parent_res=8" in str(record["path"]) for record in completed)
    assert cast(dict[str, int], manifest["status_counts"])["completed"] == len(completed)


def test_t064_tile_cache_rejects_too_many_parent_tiles(tmp_path: Path) -> None:
    """T-064: max_tiles guards overly broad tile requests."""
    sources = _synthetic_sources(tmp_path, roi=box(117.985, 31.985, 118.015, 32.015))
    request = _tile_request(
        sources,
        tmp_path / "cache",
        res_fine=11,
        tile_res=10,
        max_tiles=1,
    )

    with pytest.raises(GridBuildError, match="max_tiles|shrink|split"):
        build_h3_tile_cache(request)


def test_t065_tile_cache_skips_existing_tiles_when_overwrite_false(tmp_path: Path) -> None:
    """T-065: overwrite=False reuses existing tile Parquet files."""
    sources = _synthetic_sources(tmp_path)
    output_dir = tmp_path / "cache"
    first_manifest = build_h3_tile_cache(_tile_request(sources, output_dir))
    paths = [Path(str(record["path"])) for record in _completed_records(first_manifest)]
    mtimes = {path: path.stat().st_mtime_ns for path in paths}

    second_manifest = build_h3_tile_cache(
        _tile_request(sources, output_dir, overwrite=False)
    )

    assert cast(dict[str, int], second_manifest["status_counts"])["skipped"] == len(paths)
    assert {path: path.stat().st_mtime_ns for path in paths} == mtimes


def test_t066_tile_manifest_records_cache_semantics(tmp_path: Path) -> None:
    """T-066: tile manifest records cache metadata and status counts."""
    sources = _synthetic_sources(tmp_path)
    manifest = build_h3_tile_cache(_tile_request(sources, tmp_path / "cache"))
    manifest_path = tmp_path / "cache" / "tile_manifest.json"
    disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert disk_manifest == manifest
    assert manifest["artifact_kind"] == "tile_h3_cache"
    assert manifest["coverage_mode"] == "h3_polyfill_tile_cache"
    assert manifest["is_continuous_coverage"] is True
    assert manifest["res_fine"] == 9
    assert manifest["tile_res"] == 8
    assert cast(dict[str, int], manifest["status_counts"])["completed"] >= 1
    assert all("parent_h3" in record for record in cast(list[dict[str, object]], manifest["tiles"]))


def test_t067_impassable_cells_are_kept_but_edges_are_pruned() -> None:
    """T-067: hard-blocked cells remain mappable while route edges skip them."""
    cell_id = str(h3.latlng_to_cell(32.0, 118.0, 9))
    neighbor_id = next(str(cell) for cell in h3.grid_disk(cell_id, 1) if str(cell) != cell_id)
    frame = pd.DataFrame(
        [
            _h3_row(cell_id, is_passable=True, landcover_code=1),
            _h3_row(neighbor_id, is_passable=False, landcover_code=5),
        ]
    )
    builder = H3GridBuilder(res_fine=9, res_coarse=8)

    graph = builder.build_graph(frame)

    assert set(graph.cells) == {cell_id, neighbor_id}
    assert graph.cells[neighbor_id].is_passable is False
    assert graph.edges == {}


def test_t107_tile_manifest_records_quality_and_vehicle_independent_authority(
    tmp_path: Path,
) -> None:
    """T-107: Tile output records static quality without vehicle scoring authority."""
    sources = _synthetic_sources(tmp_path)
    request = _tile_request(sources, tmp_path / "cache")

    manifest = build_h3_tile_cache(request)

    quality = cast(dict[str, object], manifest["dem_quality"])
    assert quality["width"] == 420
    assert quality["nodata_ratio"] == 0.0
    assert manifest["tile_fact_authority"] == "vehicle_independent"
    assert isinstance(manifest["static_input_hash"], str)
    assert "assessment_vehicle_path" not in manifest
    assert "assessment_weights" not in manifest


def _synthetic_sources(
    tmp_path: Path,
    roi: Polygon | None = None,
) -> dict[str, Path]:
    width = 420
    height = 420
    transform = Affine.translation(117.98, 32.02) * Affine.scale(0.0001, -0.0001)
    dem = np.linspace(10.0, 30.0, width * height, dtype=np.float64).reshape((height, width))
    landcover = np.ones((height, width), dtype=np.int16)
    dem_path = tmp_path / "dem.tif"
    landcover_path = tmp_path / "landcover.tif"
    roi_path = tmp_path / "roi.geojson"
    _write_raster(dem_path, dem, transform, nodata=-9999.0)
    _write_raster(landcover_path, landcover, transform, nodata=0.0)
    _write_roi(roi_path, roi or box(117.995, 31.995, 118.005, 32.005))
    return {"dem": dem_path, "landcover": landcover_path, "roi": roi_path}


def _tile_request(
    sources: dict[str, Path],
    output_dir: Path,
    res_fine: int = 9,
    tile_res: int = 8,
    max_tiles: int = 80,
    overwrite: bool = True,
) -> TileBuildRequest:
    return TileBuildRequest(
        dem_path=str(sources["dem"]),
        landcover_path=str(sources["landcover"]),
        roi_layer_path=str(sources["roi"]),
        output_dir=str(output_dir),
        res_fine=res_fine,
        tile_res=tile_res,
        max_tiles=max_tiles,
        max_cells_per_tile=100,
        overwrite=overwrite,
    )


def _write_raster(
    path: Path,
    array: npt.NDArray[np.float64] | npt.NDArray[np.int16],
    transform: Affine,
    nodata: float,
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=str(array.dtype),
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def _write_roi(path: Path, roi: Polygon) -> None:
    gdf = gpd.GeoDataFrame({"name": ["roi"]}, geometry=[roi], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def _completed_records(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = cast(list[dict[str, object]], manifest["tiles"])
    return [record for record in records if record["status"] == "completed"]


def _h3_row(h3index: str, is_passable: bool, landcover_code: int) -> dict[str, object]:
    lat, lng = h3.cell_to_latlng(h3index)
    return {
        "cost_score": 1.0,
        "elevation": 10.0,
        "h3index": h3index,
        "is_passable": is_passable,
        "landcover_code": landcover_code,
        "landcover_type": "water" if landcover_code == 5 else "cropland",
        "lat": float(lat),
        "lc_factor": float("inf") if landcover_code == 5 else 1.0,
        "lng": float(lng),
        "parent_h3": str(h3.cell_to_parent(h3index, 8)),
        "score": 0.0,
        "slope": 1.0,
        "tri": 0.5,
    }
