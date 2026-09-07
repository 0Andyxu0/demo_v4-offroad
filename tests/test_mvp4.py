"""Spec-derived tests for MVP-4 continuous ROI H3 construction."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Point, Polygon, box

from demo.run_mvp4_continuous_roi import _continuous_manifest, run_continuous_roi_build
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GridBuildError


def test_t058_roi_to_h3_builds_continuous_polyfill_cells() -> None:
    """T-058: ROI H3 construction returns the full polyfill set without sampled gaps."""
    dem, slope, tri, affine = _terrain_arrays()
    roi = box(117.999, 31.999, 118.001, 32.001)
    builder = H3GridBuilder(res_fine=9, res_coarse=7, max_cells=100)

    h3_df = builder.roi_to_h3(dem, slope, tri, affine, roi)

    expected_cells = _polyfill_cells(roi, 9)
    assert set(h3_df["h3index"]) == expected_cells
    assert h3_df["h3index"].is_unique
    assert len(h3_df) > 0
    assert {"lc_factor", "score", "cost_score", "is_passable"}.issubset(h3_df.columns)
    assert all(roi.covers(_cell_point(cell_id)) for cell_id in h3_df["h3index"])


def test_t059_roi_to_h3_rejects_oversized_roi() -> None:
    """T-059: max_cells guards oversized continuous ROI builds."""
    dem, slope, tri, affine = _terrain_arrays()
    roi = box(117.99, 31.99, 118.03, 32.03)
    builder = H3GridBuilder(res_fine=9, res_coarse=7, max_cells=1)

    with pytest.raises(GridBuildError, match="shrink ROI|tiled|resolution"):
        builder.roi_to_h3(dem, slope, tri, affine, roi)


def test_t060_continuous_manifest_records_true_coverage() -> None:
    """T-060: continuous sidecar records non-sampled artifact semantics."""
    dem, slope, tri, affine = _terrain_arrays()
    roi = box(117.999, 31.999, 118.001, 32.001)
    builder = H3GridBuilder(res_fine=9, res_coarse=7, max_cells=100)
    graph = builder.build_graph(builder.roi_to_h3(dem, slope, tri, affine, roi))

    payload = _continuous_manifest(
        builder,
        graph,
        "unit_test_roi",
        Path("continuous.parquet"),
        Path("continuous.gpkg"),
    )

    assert payload["artifact_kind"] == "continuous_h3_graph"
    assert payload["coverage_mode"] == "h3_polyfill_roi"
    assert payload["is_continuous_coverage"] is True
    assert payload["res_fine"] == 9
    assert payload["res_coarse"] == 7
    assert payload["cells_count"] == len(graph.cells)
    assert "warning" not in payload


def test_t061_real_nanjing_continuous_roi_smoke(tmp_path: Path) -> None:
    """T-061: bounded real-data MVP-4 build produces continuous GIS artifacts."""
    if not Path("data/dem_nanjing.tif").exists():
        pytest.skip("Nanjing real GIS data is not available in this workspace.")

    manifest = run_continuous_roi_build(
        output_dir=str(tmp_path),
        res_fine=8,
        res_coarse=6,
        max_cells=500,
    )

    assert manifest["artifact_kind"] == "continuous_h3_graph"
    assert manifest["is_continuous_coverage"] is True
    assert Path(str(manifest["output_parquet"])).exists()
    assert Path(str(manifest["output_gpkg"])).exists()
    cells = gpd.read_file(str(manifest["output_gpkg"]), layer="h3_cells")
    assert len(cells) == manifest["cells_count"]
    assert set(cells["is_continuous"]) == {1}


def _terrain_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray, Affine]:
    shape = (220, 220)
    dem = np.arange(shape[0] * shape[1], dtype=np.float64).reshape(shape) / 100.0
    slope = np.ones(shape, dtype=np.float64)
    tri = np.full(shape, 0.5, dtype=np.float64)
    affine = Affine.translation(117.99, 32.01) * Affine.scale(0.0001, -0.0001)
    return dem, slope, tri, affine


def _polyfill_cells(roi: Polygon, resolution: int) -> set[str]:
    outer = [(lat, lng) for lng, lat in roi.exterior.coords]
    return {str(cell) for cell in h3.polygon_to_cells(h3.LatLngPoly(outer), resolution)}


def _cell_point(cell_id: str) -> Point:
    lat, lng = h3.cell_to_latlng(cell_id)
    return Point(lng, lat)
