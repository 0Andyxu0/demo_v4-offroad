"""Validation branches for the structured desktop project state."""

from __future__ import annotations

from pathlib import Path

import pytest

from h3_offroad_planner.desktop_project import DesktopProjectState, load_project_yaml
from h3_offroad_planner.models import ConfigError


def _project() -> DesktopProjectState:
    return DesktopProjectState.from_mapping(
        {
            "tile_build": {"roi_layer_path": "data/roi.geojson", "output_dir": "outputs/tiles"},
            "route": {"input_mode": "coordinates", "candidate_index": 0, "blocked_cells": []},
        }
    )


def test_project_state_rejects_invalid_import_structure_and_map_input() -> None:
    """Import and map mutation errors do not produce partial desktop state."""
    with pytest.raises(ConfigError, match="tile_build and route"):
        DesktopProjectState.from_mapping({"tile_build": {}})

    project = _project()
    with pytest.raises(ValueError, match="endpoint role"):
        project.endpoint("other")
    with pytest.raises(ConfigError, match="endpoint"):
        project.set_endpoint("start", 100.0, 118.8)
    with pytest.raises(ConfigError, match="study area"):
        project.set_study_area({"type": "Point", "coordinates": [118.8, 31.9]})
    with pytest.raises(ConfigError, match="H3 blockage"):
        project.toggle_blocked_cell("")


def test_project_state_validates_blockages_candidates_and_endpoint_clearing() -> None:
    """Canonical route values reject malformed imported collections and index values."""
    project = _project()
    project.route["blocked_cells"] = ["same", "same"]
    with pytest.raises(ConfigError, match="unique"):
        project.blocked_cells()
    project.route["blocked_cells"] = [1]
    with pytest.raises(ConfigError, match="non-empty"):
        project.blocked_cells()
    for value in (True, -1):
        with pytest.raises(ConfigError, match="candidate_index"):
            project.set_candidate_index(value)  # type: ignore[arg-type]

    project.set_endpoint("start", 31.9, 118.8)
    project.set_endpoint("goal", 31.91, 118.81)
    project.clear_endpoints()
    assert project.endpoint("start") is None
    assert project.endpoint("goal") is None


def test_project_yaml_loader_and_export_without_drawn_roi(tmp_path: Path) -> None:
    """Malformed YAML fails safely while normal export retains configured ROI paths."""
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("route: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_project_yaml(invalid)

    target = tmp_path / "project.yaml"
    project = _project()
    assert project.export_yaml(target) is None
    loaded = load_project_yaml(target)
    assert loaded.tile_build["roi_layer_path"] == "data/roi.geojson"
    assert loaded.route["candidate_index"] == 0


def test_project_run_payload_rejects_preserved_unsupported_fields(tmp_path: Path) -> None:
    """Unknown imported fields can be exported but never reach backend execution."""
    project = _project()
    project.route["future"] = "value"
    with pytest.raises(ConfigError, match="backend-unsupported"):
        project.build_run_payload(tmp_path)
