"""Display-only local orthophoto preview tests for the M0 desktop workflow."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from h3_offroad_planner.desktop_map import DesktopMapView
from h3_offroad_planner.desktop_project import DesktopProjectState
from h3_offroad_planner.orthophoto_preview import create_orthophoto_preview


def test_create_orthophoto_preview_crops_and_downsamples_rgb(tmp_path: Path) -> None:
    source = tmp_path / "orthophoto.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=12,
        height=8,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(118.0, 32.0, 0.01, 0.01),
    ) as dataset:
        for band, value in enumerate((30, 120, 220), start=1):
            dataset.write(np.full((8, 12), value, dtype=np.uint8), band)

    preview = create_orthophoto_preview(
        source,
        tmp_path / "preview.png",
        (118.02, 31.94, 118.10, 31.99),
        max_dimension=4,
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(preview.preview_path) as rendered:
            assert rendered.count == 3
            assert max(rendered.width, rendered.height) == 4
    assert preview.bounds_wgs84[0][0] < preview.bounds_wgs84[1][0]
    assert preview.bounds_wgs84[0][1] < preview.bounds_wgs84[1][1]


def test_create_orthophoto_preview_rejects_out_of_range_coordinates(tmp_path: Path) -> None:
    import pytest
    source = tmp_path / "orthophoto.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=12,
        height=8,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(118.0, 32.0, 0.01, 0.01),
    ) as dataset:
        dataset.write(np.full((3, 8, 12), 100, dtype=np.uint8))

    with pytest.raises(ValueError, match="study bounds WGS84 coordinates are outside"):
        create_orthophoto_preview(
            source,
            tmp_path / "preview.png",
            (-200.0, 31.0, 118.0, 32.0),
        )


def test_desktop_project_accepts_display_only_orthophoto_metadata(tmp_path: Path) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"png")
    metadata = tmp_path / "preview.json"
    metadata.write_text(
        json.dumps(
            {
                "preview_path": str(preview),
                "bounds_wgs84": [[31.90, 118.80], [31.95, 118.90]],
            }
        ),
        encoding="utf-8",
    )
    project = DesktopProjectState.from_mapping(
        {
            "map_display": {
                "orthophoto_preview_metadata_path": str(metadata),
                "orthophoto_opacity": 0.7,
            },
            "tile_build": {},
            "route": {},
        }
    )

    assert project.unsupported_fields() == []
    assert project.orthophoto_overlay() == (
        preview,
        [[31.90, 118.80], [31.95, 118.90]],
        0.7,
    )
    assert "map_display" not in project.build_run_payload(tmp_path)


def test_desktop_map_encodes_the_generated_preview_as_a_local_overlay(tmp_path: Path) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"PNG")
    scripts: list[str] = []
    map_errors: list[tuple[object, ...]] = []
    view = SimpleNamespace(
        _run_js=scripts.append,
        map_error=SimpleNamespace(emit=lambda *args: map_errors.append(args)),
    )

    DesktopMapView.set_orthophoto_overlay(
        view, preview, [[31.90, 118.80], [31.95, 118.90]], 0.7
    )

    assert map_errors == []
    assert len(scripts) == 1
    assert "setOrthophotoOverlay" in scripts[0]
    assert "data:image/png;base64,UE5H" in scripts[0]
