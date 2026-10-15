# 模块参考：desktop_client

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/desktop_client.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`df97691872c297fcbc718646a1b90e16f1eb4a5c075ade062f94e9101bcd50db`；类 3 个，函数/方法 71 个（含嵌套定义）。
- 项目内导入依赖：`cli`, `desktop_map`, `desktop_project`, `models`, `route_persistence`, `tiling`, `web_console`。
- 直接导入本模块者：未检出。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L117
ProgressCallback = Callable[[str, int, str], None]

# L118
DesktopOperationEvent = tuple[str, object]

# DesktopOperationWorker — src/h3_offroad_planner/desktop_client.py:121
class DesktopOperationWorker(QObject):
    'Legacy Qt compatibility shim for executing one delivery operation.'
    progress = pyqtSignal(str, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    # self._operation: 未注解; L132; initial=operation
    # self._payload: 未注解; L133; initial=payload
    ...

# ProjectSettingsDialog — src/h3_offroad_planner/desktop_client.py:149
class ProjectSettingsDialog(QDialog):
    'Edit the typed desktop project without exposing raw YAML text.'
    # self._project: 未注解; L154; initial=project
    _path_inputs: dict[tuple[str, str], tuple[QLineEdit, bool]]  # instance; L155; initial={}
    _int_inputs: dict[tuple[str, str], QSpinBox]  # instance; L156; initial={}
    _float_inputs: dict[tuple[str, str], QDoubleSpinBox]  # instance; L157; initial={}
    _bool_inputs: dict[tuple[str, str], QCheckBox]  # instance; L158; initial={}
    # self._sections: 未注解; L162; initial=QToolBox()
    # self._mission_profile: 未注解; L196; initial=QComboBox()
    # self._endpoint_mode: 未注解; L211; initial=QComboBox()
    # self._start_summary: 未注解; L223; initial=QLabel(_endpoint_text('起点', self._project.endpoint('start')))
    # self._goal_summary: 未注解; L224; initial=QLabel(_endpoint_text('终点', self._project.endpoint('goal')))
    # self._sampling_mode: 未注解; L264; initial=sampling
    # self._roi_strategy: 未注解; L304; initial=roi_strategy
    ...

# DesktopMainWindow — src/h3_offroad_planner/desktop_client.py:442
class DesktopMainWindow(QMainWindow):
    'Map-first desktop shell backed by one structured project state.'
    # self._project: 未注解; L447; initial=load_project_yaml(DEFAULT_DELIVERY_PATH)
    _last_result: dict[str, object] | None  # instance; L448; initial=None
    _active_grid_level: str  # instance; L449; initial='parent'
    _selected_parent_h3: str | None  # instance; L450; initial=None
    _selected_fine_grid: dict[str, object] | None  # instance; L451; initial=None
    _candidate_routes: list[dict[str, object]]  # instance; L452; initial=[]
    _active_thread: Thread | None  # instance; L453; initial=None
    _operation_events: SimpleQueue[DesktopOperationEvent]  # instance; L454; initial=SimpleQueue()
    # self._operation_poll_timer: 未注解; L455; initial=QTimer(self)
    # self._status_bar: 未注解; L461; initial=status_bar
    # self.map_view: 未注解; L468; initial=DesktopMapView()
    # self.project_summary: 未注解; L519; initial=QLabel()
    # self.settings_button: 未注解; L521; initial=QPushButton('打开项目设置…')
    # self.progress_bar: 未注解; L537; initial=QProgressBar()
    # self.progress_label: 未注解; L539; initial=QLabel('Waiting for operation')
    # self.result_text: 未注解; L540; initial=QTextBrowser()
    # self.theme_box: 未注解; L542; initial=QComboBox()
    # self.candidate_box: 未注解; L545; initial=QComboBox()
    # self.activate_candidate_button: 未注解; L547; initial=QPushButton('确认并激活当前候选')
    # self.fine_grid_button: 未注解; L551; initial=QPushButton('显示细层格网')
    # self.parent_grid_button: 未注解; L554; initial=QPushButton('显示父层格网')
    # self.log_text: 未注解; L558; initial=QPlainTextEdit()
    operation_buttons: list[QPushButton]  # instance; L579; initial=[]
    _last_logged_step: str | None  # instance; L867; initial=None
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import html
import json
import re
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from typing import cast
import yaml
from PyQt5.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QAction, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTextBrowser, QToolBox, QVBoxLayout, QWidget
from h3_offroad_planner.cli import run_delivery_payload, run_replan_payload, run_route_payload, run_select_payload, run_tile_payload
from h3_offroad_planner.desktop_map import DesktopMapView
from h3_offroad_planner.desktop_project import DesktopProjectState, load_project_yaml
from h3_offroad_planner.models import ConfigError, GISInputError, GridBuildError, PlanningFailedError, PlanningInputError
from h3_offroad_planner.route_persistence import load_active_route_feature
from h3_offroad_planner.tiling import TILE_CACHE_KIND, TILE_MANIFEST_NAME
from h3_offroad_planner.web_console import serialize_tile_grid, serialize_webgis_result

# DesktopOperationWorker — L121
class DesktopOperationWorker(QObject):
    """Legacy Qt compatibility shim for executing one delivery operation."""

    def __init__(self, operation: str, payload: dict[str, object]) -> None:
        ...

    @pyqtSlot()
    def run(self) -> None:
        ...

    def _emit_progress(self, module: str, percent: int, message: str) -> None:
        ...

# ProjectSettingsDialog — L149
class ProjectSettingsDialog(QDialog):
    """Edit the typed desktop project without exposing raw YAML text."""

    def __init__(self, project: DesktopProjectState, parent: QWidget | None=None) -> None:
        ...

    def _build_data_page(self) -> QWidget:
        ...

    def _build_planning_page(self) -> QWidget:
        ...

    def _build_advanced_page(self) -> QWidget:
        ...

    def _add_path_row(self, form: QFormLayout, section: str, field: str, label: str, *, optional: bool, directory: bool=False) -> None:
        ...

    def _choose_path(self, editor: QLineEdit, field: str, directory: bool) -> None:
        ...

    def _add_int_row(self, form: QFormLayout, section: str, field: str, label: str, default: int, minimum: int, maximum: int) -> None:
        ...

    def _add_float_row(self, form: QFormLayout, section: str, field: str, label: str, *, default: float, minimum: float, maximum: float, decimals: int) -> None:
        ...

    def _add_bool_row(self, form: QFormLayout, section: str, field: str, label: str, default: bool) -> None:
        ...

    def _mapping(self, section: str) -> dict[str, object]:
        ...

    def accept(self) -> None:
        ...

    def _apply_to_project(self) -> None:
        ...

# DesktopMainWindow — L442
class DesktopMainWindow(QMainWindow):
    """Map-first desktop shell backed by one structured project state."""

    def __init__(self) -> None:
        ...

    def _build_window(self) -> None:
        ...

    def _build_menu(self) -> None:
        ...

    def _build_workspace_dock(self) -> None:
        ...

    def _build_result_dock(self) -> None:
        ...

    def _operation_group(self) -> QGroupBox:
        ...

    def _load_default_project(self) -> None:
        ...

    def _choose_delivery_yaml(self) -> None:
        ...

    def _export_delivery_yaml(self) -> None:
        ...

    def _open_project_settings(self) -> None:
        ...

    def _replace_project(self, project: DesktopProjectState, message: str) -> None:
        ...

    def _sync_map_from_project(self) -> None:
        ...

    def _refresh_project_summary(self) -> None:
        ...

    def _safe_blocked_cells(self) -> list[str]:
        ...

    def _set_study_area(self, geojson: object) -> None:
        ...

    def _set_endpoint(self, role: str, lat: float, lng: float) -> None:
        ...

    def _toggle_blocked_cell(self, cell_id: str) -> None:
        ...

    def _select_parent_grid(self, parent_h3: str) -> None:
        ...

    def _handle_map_action(self, action: str) -> None:
        ...

    def _start_operation(self, operation: str, **kwargs: object) -> None:
        ...

    def _drain_operation_events(self) -> None:
        ...

    def _on_progress(self, module: str, percent: int, message: str) -> None:
        ...

    def _on_completed(self, result: object) -> None:
        ...

    def _on_failed(self, message: str) -> None:
        ...

    def _finish_background_operation(self) -> None:
        ...

    def closeEvent(self, event: QCloseEvent | None) -> None:
        """Keep the Qt application alive while native GIS work is still running."""
        ...

    def _redraw_active_grid(self, *_args: object) -> None:
        ...

    def _redraw_fine_grid(self, *_args: object) -> None:
        ...

    def _draw_parent_grid(self, *_args: object) -> None:
        ...

    def _has_fine_grid(self) -> bool:
        ...

    def _reset_grid_drilldown(self) -> None:
        ...

    def _load_candidates(self) -> None:
        ...

    def _activate_candidate(self) -> None:
        ...

    def _set_candidate_index(self, position: int) -> None:
        ...

    def _render_candidate(self, candidate_index: int) -> bool:
        ...

    def _show_evaluation(self, evaluation: dict[str, object] | None) -> None:
        ...

    def _append_log(self, level: str, module: str, percent: int, message: str) -> None:
        ...

    def _show_map_error(self, message: str) -> None:
        ...

    def _show_error(self, message: str) -> None:
        ...

    def _set_running(self, running: bool) -> None:
        ...

# _execute_desktop_operation — L1193
def _execute_desktop_operation(operation: str, payload: dict[str, object], progress: ProgressCallback) -> dict[str, object]:
    """Dispatch one desktop operation solely through existing CLI payload adapters."""
    ...

# _run_desktop_operation_in_background — L1310
def _run_desktop_operation_in_background(operation: str, payload: dict[str, object], events: SimpleQueue[DesktopOperationEvent]) -> None:
    """Run one operation without giving Qt ownership of the compute thread."""
    ...

# _run_desktop_operation_in_background.report — L1317
def report(module: str, percent: int, message: str) -> None:
    ...

# _mapping — L1334
def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    ...

# _set_route_tile_manifest — L1341
def _set_route_tile_manifest(route: dict[str, object], tile: dict[str, object]) -> None:
    ...

# _short_path — L1361
def _short_path(value: object) -> str:
    ...

# _endpoint_text — L1365
def _endpoint_text(name: str, value: tuple[float, float] | None) -> str:
    ...

# _format_number — L1369
def _format_number(value: object) -> str:
    ...

# _format_minutes — L1373
def _format_minutes(value: object) -> str:
    ...

# _grid_has_features — L1377
def _grid_has_features(value: object) -> bool:
    ...

# _candidate_routes_from_result — L1384
def _candidate_routes_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    """Return serializer-provided candidate entries while rejecting malformed values."""
    ...

# _show_route_status — L1392
def _show_route_status(window: DesktopMainWindow, result: dict[str, object]) -> None:
    ...

# _route_status_message — L1399
def _route_status_message(result: dict[str, object]) -> str:
    ...

# _candidate_label — L1424
def _candidate_label(candidate: dict[str, object], candidate_index: int) -> str:
    """Format one new role candidate from exact PathMetrics."""
    ...

# _route_tooltip — L1451
def _route_tooltip(evaluation: dict[str, object]) -> str:
    ...

# run_desktop_client — L1470
def run_desktop_client() -> int:
    """Start the PyQt5 desktop main interface and return the event-loop exit code."""
    ...
```
