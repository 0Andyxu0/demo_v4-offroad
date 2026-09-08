"""Offscreen tests for the desktop configuration and map bridge UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Empty, SimpleQueue
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget

from h3_offroad_planner import desktop_client, desktop_map
from h3_offroad_planner.desktop_client import (
    DesktopMainWindow,
    DesktopOperationWorker,
    ProjectSettingsDialog,
)
from h3_offroad_planner.desktop_map import DesktopMapView
from h3_offroad_planner.desktop_project import DesktopProjectState
from h3_offroad_planner.models import ConfigError


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one non-visible QApplication for widget construction."""
    return QApplication.instance() or QApplication([])


@dataclass
class _Signal:
    callbacks: list[Callable[..., None]] = field(default_factory=list)
    emitted: list[tuple[object, ...]] = field(default_factory=list)

    def connect(self, callback: Callable[..., None]) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: object) -> None:
        self.emitted.append(args)
        for callback in self.callbacks:
            callback(*args)


class _FakeMap(QWidget):
    """A QWidget-shaped map contract for desktop-window tests without QWebEngine."""

    def __init__(self) -> None:
        super().__init__()
        self.study_area_selected = _Signal()
        self.coordinate_selected = _Signal()
        self.parent_grid_selected = _Signal()
        self.grid_cell_selected = _Signal()
        self.toolbar_action = _Signal()
        self.map_error = _Signal()
        self.calls: list[tuple[str, object]] = []

    def reset_project_overlays(self) -> None:
        self.calls.append(("reset", None))

    def set_endpoints(self, start: object, goal: object) -> None:
        self.calls.append(("endpoints", (start, goal)))

    def set_blocked_cells(self, cells: list[str]) -> None:
        self.calls.append(("blocked", list(cells)))

    def set_blockage_selection_enabled(self, enabled: bool) -> None:
        self.calls.append(("blockage_enabled", enabled))

    def draw_grid(self, geojson: dict[str, object], theme: str) -> None:
        self.calls.append(("grid", (geojson, theme)))

    def draw_route(self, geojson: dict[str, object] | None, tooltip: str) -> None:
        self.calls.append(("route", (geojson, tooltip)))


def _project() -> DesktopProjectState:
    return DesktopProjectState.from_mapping(
        {
            "tile_build": {
                "dem_path": "data/dem.tif",
                "landcover_path": "data/land.tif",
                "roi_layer_path": "data/roi.geojson",
                "output_dir": "outputs/tiles",
                "res_fine": 9,
                "tile_res": 7,
                "max_tiles": 80,
                "max_cells_per_tile": 500,
                "sampling_mode": "center",
                "continue_on_error": True,
                "overwrite": False,
            },
            "route": {
                "input_mode": "layer",
                "endpoint_layer_path": "data/endpoints.geojson",
                "planner_config_path": "configs/planner.yaml",
                "vehicle_path": "configs/vehicle.yaml",
                "output_dir": "outputs/route",
                "res_fine": 9,
                "res_coarse": 7,
                "max_snap_distance_m": 500.0,
                "corridor_buffer_deg": 0.15,
                "max_estimated_cells": 500_000,
                "roi_strategy": "auto_corridor",
                "objectives": ["distance", "trafficability"],
                "theme_attributes": ["score", "slope"],
                "blocked_cells": [],
                "candidate_index": 0,
            },
        }
    )


def test_settings_dialog_updates_project_without_yaml_editor(qt_app: QApplication) -> None:
    """The settings dialog maps all exposed controls back to the canonical state."""
    project = _project()
    dialog = ProjectSettingsDialog(project)

    assert dialog._sections.count() == 3
    dialog._path_inputs[("tile_build", "dem_path")][0].setText("data/new-dem.tif")
    dialog._path_inputs[("tile_build", "road_path")][0].setText("data/roads.geojson")
    dialog._endpoint_mode.setCurrentIndex(dialog._endpoint_mode.findData("coordinates"))
    dialog._int_inputs[("tile_build", "max_tiles")].setValue(120)
    dialog._float_inputs[("route", "max_snap_distance_m")].setValue(750.0)
    dialog._float_inputs[("route", "penalty_factor")].setValue(0.5)
    dialog._apply_to_project()

    assert project.tile_build["dem_path"] == "data/new-dem.tif"
    assert project.tile_build["road_path"] == "data/roads.geojson"
    assert project.tile_build["max_tiles"] == 120
    assert project.route["input_mode"] == "coordinates"
    assert project.route["objectives"] == ["distance", "trafficability"]
    assert project.route["theme_attributes"] == ["score", "slope"]
    assert project.route["max_snap_distance_m"] == 750.0
    assert project.route["penalty_factor"] == 0.5
    dialog.close()


def test_settings_dialog_hides_legacy_objective_and_theme_controls(
    qt_app: QApplication,
) -> None:
    """Hidden legacy controls cannot overwrite fields still retained by the request."""
    project = _project()
    dialog = ProjectSettingsDialog(project)
    dialog._apply_to_project()

    assert not hasattr(dialog, "_objective_boxes")
    assert not hasattr(dialog, "_themes")
    assert project.route["objectives"] == ["distance", "trafficability"]
    assert project.route["theme_attributes"] == ["score", "slope"]
    dialog.close()


def test_main_window_synchronizes_map_and_project_state(
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """Map signals mutate the project mapping and update the visible desktop state."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window = DesktopMainWindow()
    fake_map = window.map_view
    assert isinstance(fake_map, _FakeMap)
    assert "DEM" in window.project_summary.text()

    fake_map.coordinate_selected.emit("start", 31.901, 118.801)
    fake_map.coordinate_selected.emit("goal", 31.909, 118.809)
    fake_map.grid_cell_selected.emit("8928308280fffff")
    assert window._project.route["input_mode"] == "coordinates"
    assert window._project.endpoint("goal") == (31.909, 118.809)
    assert window._project.blocked_cells() == ["8928308280fffff"]

    study_area = {
        "type": "Polygon",
        "coordinates": [[[118.8, 31.9], [118.81, 31.9], [118.81, 31.91], [118.8, 31.9]]],
    }
    fake_map.study_area_selected.emit(study_area)
    assert window._project.study_area_geojson == study_area
    fake_map.study_area_selected.emit(None)
    assert window._project.study_area_geojson is None

    fake_map.toolbar_action.emit("clear_blocked")
    fake_map.toolbar_action.emit("clear_endpoints")
    assert window._project.blocked_cells() == []
    assert window._project.endpoint("start") is None
    assert any(name == "endpoints" for name, _ in fake_map.calls)
    window.close()


def test_main_window_drills_from_parent_to_one_cached_fine_tile(
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """Parent overview loads one child collection and keeps blockage selection layer-scoped."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    parent_h3 = "8a30910e6b27fff"
    parent_grid = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": {"h3index": parent_h3}}],
    }
    fine_grid = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": {"h3index": "cell"}}],
    }
    loaded: list[tuple[dict[str, object], str]] = []

    def fake_tile(result: dict[str, object], selected: str) -> dict[str, object]:
        loaded.append((result, selected))
        return fine_grid

    monkeypatch.setattr(desktop_client, "serialize_tile_grid", fake_tile)
    window = DesktopMainWindow()
    fake_map = window.map_view
    assert isinstance(fake_map, _FakeMap)
    result = {
        "delivery": {"tile_manifest": {"tiles": []}},
        "fine_grid_geojson": {"type": "FeatureCollection", "features": []},
        "parent_grid_geojson": parent_grid,
        "route_geojson": None,
        "route_evaluation": None,
        "candidate_routes": [],
    }

    window._on_completed(result)
    assert window._active_grid_level == "parent"
    assert window.fine_grid_button.isEnabled() is False
    assert fake_map.calls[-1] == ("blockage_enabled", False)

    fake_map.parent_grid_selected.emit(parent_h3)
    assert loaded == [({"tile_manifest": {"tiles": []}}, parent_h3)]
    assert window._active_grid_level == "fine"
    assert window._selected_fine_grid == fine_grid
    assert window.fine_grid_button.isEnabled() is True
    assert fake_map.calls[-2:] == [("blockage_enabled", True), ("blocked", [])]

    window._draw_parent_grid()
    assert window._active_grid_level == "parent"
    assert fake_map.calls[-1] == ("blockage_enabled", False)
    window.close()


def test_main_window_renders_result_and_handles_errors(
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """Result, candidate, progress, and validation error paths remain GUI-thread safe."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, _title, message: errors.append(message)
    )
    window = DesktopMainWindow()
    result = {
        "fine_grid_geojson": {"type": "FeatureCollection", "features": []},
        "route_geojson": {"type": "FeatureCollection", "features": []},
        "route_evaluation": {
            "quality_score": 0.8,
            "distance_m": 1200.0,
            "estimated_time_s": 300.0,
            "selection_reason": ["minimum cost"],
            "landcover_distance_share": {"grass": 1.0},
            "min_turn_radius_m": 4.2,
        },
        "delivery": {"route_manifest": {"candidate_paths": [{"total_cost": 12.0}]}},
    }
    window._on_progress("build", 50, "halfway")
    window._on_completed(result)
    window.candidate_box.setCurrentIndex(0)
    window._on_failed("expected failure")
    window._project.route["unsupported_field"] = True
    window._start_operation("combined")

    assert window.progress_bar.value() == 100
    assert "路线评价" in window.result_text.toPlainText()
    assert window._project.candidate_index() == 0
    assert errors[-1].startswith("desktop project contains backend-unsupported")
    window.close()


def test_completed_render_failure_is_contained_by_qt_event_boundary(
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """A map rendering error becomes a recoverable GUI failure instead of escaping Qt."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, _title, message: errors.append(message)
    )
    window = DesktopMainWindow()

    def fail_render(_geojson: dict[str, object] | None, _tooltip: str) -> None:
        raise ValueError("invalid route geometry")

    window.map_view.draw_route = fail_render  # type: ignore[method-assign]
    window._operation_events.put(
        (
            "completed",
            {
                "fine_grid_geojson": {"type": "FeatureCollection", "features": []},
                "parent_grid_geojson": {"type": "FeatureCollection", "features": []},
                "candidate_routes": [
                    {
                        "candidate_index": 0,
                        "roles": ["fastest_eta"],
                        "geojson": {"type": "FeatureCollection", "features": []},
                        "evaluation": {},
                    }
                ],
            },
        )
    )

    window._drain_operation_events()

    assert errors == ["desktop result rendering failed: invalid route geometry"]
    assert window.progress_label.text() == "Failed"
    assert window._active_thread is None
    assert all(button.isEnabled() for button in window.operation_buttons)
    window.close()


def test_operation_worker_emits_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker terminal signals cover both execution outcomes without a real thread."""
    completed: list[object] = []
    failed: list[str] = []
    worker = DesktopOperationWorker("build", {"tile_build": {}, "route": {}})
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)
    monkeypatch.setattr(desktop_client, "_execute_desktop_operation", lambda *args: {"ok": True})
    worker.run()
    monkeypatch.setattr(
        desktop_client,
        "_execute_desktop_operation",
        lambda *args: (_ for _ in ()).throw(ConfigError("broken")),
    )
    worker.run()

    assert len(completed) == 1
    assert isinstance(completed[0], dict)
    assert completed[0]["delivery"] == {"ok": True}
    assert failed == ["broken"]


def test_cl038_plain_background_thread_contract_uses_queue_not_qthread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop computation reports progress and completion without Qt thread ownership."""
    events: SimpleQueue[desktop_client.DesktopOperationEvent] = SimpleQueue()

    def fake_execute(
        _operation: str,
        _payload: dict[str, object],
        progress: Callable[[str, int, str], None],
    ) -> dict[str, object]:
        progress("evaluation", 95, "ready")
        return {"ok": True}

    monkeypatch.setattr(desktop_client, "_execute_desktop_operation", fake_execute)
    desktop_client._run_desktop_operation_in_background("build", {}, events)

    assert events.get_nowait() == ("progress", ("evaluation", 95, "ready"))
    kind, payload = events.get_nowait()
    assert kind == "completed"
    assert isinstance(payload, dict)
    assert payload["delivery"] == {"ok": True}
    with pytest.raises(Empty):
        events.get_nowait()


def test_background_replan_feature_is_normalized_before_desktop_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persisted active-route Feature reaches the desktop map as a FeatureCollection."""
    events: SimpleQueue[desktop_client.DesktopOperationEvent] = SimpleQueue()
    active_route = {
        "type": "Feature",
        "properties": {"candidate_id": "route-a", "replan_version": 1},
        "geometry": {
            "type": "LineString",
            "coordinates": [[118.8, 31.9], [118.81, 31.91]],
        },
    }
    backend = {
        "candidate_id": "route-a",
        "algorithm": "DStarLite",
        "status": "active",
        "replan_version": 1,
        "metrics_after": {"eta_s": 120.0},
        "warnings": [],
    }
    monkeypatch.setattr(
        desktop_client,
        "_execute_desktop_operation",
        lambda *_args: {"replan_result": backend, "active_route_geojson": active_route},
    )

    desktop_client._run_desktop_operation_in_background("replan", {}, events)

    kind, payload = events.get_nowait()
    assert kind == "completed"
    assert isinstance(payload, dict)
    assert payload["route_geojson"] == {
        "type": "FeatureCollection",
        "features": [active_route],
    }
    harness = _MapHarness()
    DesktopMapView.draw_route(harness, payload["route_geojson"], "D* Lite")  # type: ignore[arg-type]
    assert len(harness.scripts) == 1


def test_pyqt_share_context_attribute_supports_offscreen_startup() -> None:
    script = (
        "import os;"
        "os.environ['QT_QPA_PLATFORM']='offscreen';"
        "from PyQt5.QtCore import QCoreApplication,Qt;"
        "QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts);"
        "from PyQt5.QtWidgets import QApplication;"
        "app=QApplication([]);"
        "assert app is not None"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr


def test_main_window_repeated_background_completion_has_no_qthread_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """Repeated terminal events return the GUI to idle without Qt-owned workers."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    monkeypatch.setattr(
        DesktopProjectState,
        "build_run_payload",
        lambda *_args: {"tile_build": {}, "route": {}},
    )

    def fake_execute(
        _operation: str,
        _payload: dict[str, object],
        progress: Callable[[str, int, str], None],
    ) -> dict[str, object]:
        progress("build_map", 85, "ready")
        return {"tile_manifest": {"tiles": []}}

    monkeypatch.setattr(desktop_client, "_execute_desktop_operation", fake_execute)
    window = DesktopMainWindow()
    for _ in range(20):
        window._start_operation("build")
        deadline = time.monotonic() + 2.0
        while window._active_thread is not None and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.001)
        assert window._active_thread is None
        assert window.progress_bar.value() == 100
    window.close()


class _MapHarness:
    """Plain-Python receiver for unbound DesktopMapView methods."""

    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.study_area_selected = _Signal()
        self.coordinate_selected = _Signal()
        self.parent_grid_selected = _Signal()
        self.grid_cell_selected = _Signal()
        self.toolbar_action = _Signal()
        self.map_error = _Signal()

    def _run_js(self, script: str) -> None:
        self.scripts.append(script)


def test_map_view_commands_and_event_decoding() -> None:
    """The Python map bridge queues commands and decodes all sequenced event classes."""
    harness = _MapHarness()
    DesktopMapView.begin_study_area(harness)  # type: ignore[arg-type]
    DesktopMapView.clear_study_area(harness)  # type: ignore[arg-type]
    DesktopMapView.set_selection_mode(harness, "start")  # type: ignore[arg-type]
    DesktopMapView.set_endpoints(harness, (31.9, 118.8), None)  # type: ignore[arg-type]
    DesktopMapView.set_blocked_cells(harness, ["8928308280fffff"])  # type: ignore[arg-type]
    DesktopMapView.set_blockage_selection_enabled(harness, True)  # type: ignore[arg-type]
    DesktopMapView.reset_project_overlays(harness)  # type: ignore[arg-type]
    assert any("beginStudyArea" in script for script in harness.scripts)
    assert any("setEndpoints" in script for script in harness.scripts)

    DesktopMapView._emit_study_area(harness, "null")  # type: ignore[arg-type]
    DesktopMapView._emit_study_area(  # type: ignore[arg-type]
        harness, json.dumps({"type": "Polygon", "coordinates": []})
    )
    DesktopMapView._emit_coordinate(harness, "start:31.9,118.8")  # type: ignore[arg-type]
    DesktopMapView._emit_grid_cell(harness, "8928308280fffff")  # type: ignore[arg-type]
    DesktopMapView._emit_parent_grid(harness, "872830828ffffff")  # type: ignore[arg-type]
    DesktopMapView._emit_coordinate(harness, "bad-value")  # type: ignore[arg-type]
    DesktopMapView._emit_grid_cell(harness, "")  # type: ignore[arg-type]

    assert harness.study_area_selected.emitted[0] == (None,)
    assert harness.coordinate_selected.emitted == [("start", 31.9, 118.8)]
    assert harness.grid_cell_selected.emitted == [("8928308280fffff",)]
    assert harness.parent_grid_selected.emitted == [("872830828ffffff",)]
    assert len(harness.map_error.emitted) == 2


def test_map_bridge_title_dispatch_and_load_queue() -> None:
    """Repeated, sequenced title events and pre-load scripts are handled deterministically."""
    harness = _MapHarness()
    received: list[tuple[str, str]] = []
    harness._emit_study_area = lambda raw: received.append(("study", raw))  # type: ignore[attr-defined]
    harness._emit_coordinate = lambda raw: received.append(("coordinate", raw))  # type: ignore[attr-defined]
    harness._emit_grid_cell = lambda raw: received.append(("grid", raw))  # type: ignore[attr-defined]
    harness._emit_parent_grid = lambda raw: received.append(("parent", raw))  # type: ignore[attr-defined]
    DesktopMapView._on_title_changed(harness, "desktop:1:study_area:null")  # type: ignore[arg-type]
    DesktopMapView._on_title_changed(harness, "desktop:2:map_click:start:31.9,118.8")  # type: ignore[arg-type]
    DesktopMapView._on_title_changed(harness, "desktop:3:grid_click:8928308280fffff")  # type: ignore[arg-type]
    DesktopMapView._on_title_changed(harness, "desktop:4:parent_grid_click:872830828ffffff")  # type: ignore[arg-type]
    DesktopMapView._on_title_changed(harness, "desktop:5:action:clear_blocked")  # type: ignore[arg-type]
    DesktopMapView._on_title_changed(harness, "ordinary browser title")  # type: ignore[arg-type]

    assert received == [
        ("study", "null"),
        ("coordinate", "start:31.9,118.8"),
        ("grid", "8928308280fffff"),
        ("parent", "872830828ffffff"),
    ]
    assert harness.toolbar_action.emitted == [("clear_blocked",)]

    page_scripts: list[str] = []
    queued = SimpleNamespace(
        _page_ready=False,
        _pending_scripts=[],
        map_error=_Signal(),
        page=lambda: SimpleNamespace(runJavaScript=page_scripts.append),
    )
    DesktopMapView._run_js(queued, "queued();")  # type: ignore[arg-type]
    DesktopMapView._on_load_finished(queued, True)  # type: ignore[arg-type]
    assert page_scripts == ["queued();"]


def test_map_view_rejects_invalid_commands_and_reports_bridge_failures() -> None:
    """Invalid map input and unavailable page paths produce bounded bridge errors."""
    harness = _MapHarness()
    with pytest.raises(ValueError, match="selection mode"):
        DesktopMapView.set_selection_mode(harness, "invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="marker coordinates"):
        DesktopMapView.draw_marker(harness, 100.0, 118.8, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="endpoint coordinates"):
        DesktopMapView.set_endpoints(harness, (100.0, 118.8), None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="blocked cells"):
        DesktopMapView.set_blocked_cells(harness, [""])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="FeatureCollection"):
        DesktopMapView.draw_grid(harness, {"type": "Feature"}, "score")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="FeatureCollection"):
        DesktopMapView.draw_route(harness, {"type": "Feature"}, "tip")  # type: ignore[arg-type]

    DesktopMapView._emit_study_area(harness, "not-json")  # type: ignore[arg-type]
    DesktopMapView._emit_study_area(harness, "[]")  # type: ignore[arg-type]
    DesktopMapView._emit_coordinate(harness, "bad:100,200")  # type: ignore[arg-type]
    assert len(harness.map_error.emitted) == 3

    unavailable = SimpleNamespace(
        _page_ready=True,
        _pending_scripts=[],
        map_error=_Signal(),
        page=lambda: None,
    )
    DesktopMapView._run_js(unavailable, "ignored();")  # type: ignore[arg-type]
    DesktopMapView._on_load_finished(unavailable, False)  # type: ignore[arg-type]
    DesktopMapView._on_load_finished(unavailable, True)  # type: ignore[arg-type]
    assert len(unavailable.map_error.emitted) == 3


def test_map_view_blocks_oversized_grid_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last native boundary refuses oversized JavaScript before QWebEngine sees it."""
    harness = _MapHarness()
    monkeypatch.setattr(desktop_map, "MAX_DESKTOP_MAP_SCRIPT_CHARS", 100)
    grid = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": {"value": "x" * 200}}],
    }

    DesktopMapView.draw_grid(harness, grid, "score")  # type: ignore[arg-type]

    assert harness.scripts == []
    assert len(harness.map_error.emitted) == 1
    assert "超过桌面安全上限" in str(harness.map_error.emitted[0][0])


def test_desktop_load_map_and_load_route_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qt_app: QApplication,
) -> None:
    """The desktop client can directly load existing tile manifests and route plans."""
    monkeypatch.setattr(desktop_client, "DesktopMapView", _FakeMap)
    window = DesktopMainWindow()

    tile_manifest_file = tmp_path / "tile_manifest.json"
    tile_manifest_file.write_text(
        json.dumps({
            "artifact_kind": "tile_h3_cache",
            "output_dir": str(tmp_path),
            "tiles": [],
        }),
        encoding="utf-8",
    )

    route_plan_file = tmp_path / "route_plan.json"
    route_plan_file.write_text(
        json.dumps({
            "plan_id": "test-plan",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "roles": ["fastest_route"],
                    "is_recommended": True,
                    "geojson": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [[118.81, 31.90], [118.78, 31.93]],
                                },
                                "properties": {},
                            }
                        ],
                    },
                    "metrics": {
                        "distance_m": 5000.0,
                        "eta_s": 300.0,
                        "score_lower_min": 0.85,
                        "travel_cost": 10.0,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    # 1. Test execute load_map
    progress_log: list[str] = []
    map_res = desktop_client._execute_desktop_operation(
        "load_map",
        {"tile_manifest_path": str(tile_manifest_file)},
        lambda mod, pct, msg: progress_log.append(f"{mod}:{pct}:{msg}"),
    )
    assert "tile_manifest" in map_res
    assert any("loaded tile manifest" in p for p in progress_log)

    # 2. Test execute load_route
    route_res = desktop_client._execute_desktop_operation(
        "load_route",
        {"route_file_path": str(route_plan_file)},
        lambda mod, pct, msg: progress_log.append(f"{mod}:{pct}:{msg}"),
    )
    assert "route_manifest" in route_res

    # 3. Test window integration: load_map
    window._start_operation("load_map", tile_manifest_path=str(tile_manifest_file))
    deadline = time.monotonic() + 3.0
    while window._active_thread is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.001)
    assert window._project.tile_build["output_dir"] == str(tmp_path)
    assert window._project.route["parquet_path"] == str(tile_manifest_file)
    assert window.progress_bar.value() == 100

    # 4. Test window integration: load_route
    window._start_operation("load_route", route_file_path=str(route_plan_file))
    deadline = time.monotonic() + 3.0
    while window._active_thread is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.001)
    assert window._project.route["output_dir"] == str(tmp_path)
    assert window.candidate_box.count() == 1
    assert "fastest_route" in window.candidate_box.itemText(0)
    assert window.progress_bar.value() == 100

    window.close()

