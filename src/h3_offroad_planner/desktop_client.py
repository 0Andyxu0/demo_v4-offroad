# ruff: noqa: E501
"""PyQt5 desktop main interface for local H3 off-road planning workflows."""

from __future__ import annotations

import html
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from typing import cast

import yaml  # type: ignore[import-untyped]
from PyQt5.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from h3_offroad_planner.cli import (
    run_delivery_payload,
    run_replan_payload,
    run_route_payload,
    run_select_payload,
    run_tile_payload,
)
from h3_offroad_planner.desktop_map import DesktopMapView
from h3_offroad_planner.desktop_project import (
    DesktopProjectState,
    load_project_yaml,
)
from h3_offroad_planner.models import (
    ConfigError,
    GISInputError,
    GridBuildError,
    PlanningFailedError,
    PlanningInputError,
)
from h3_offroad_planner.tiling import TILE_MANIFEST_NAME
from h3_offroad_planner.web_console import serialize_tile_grid, serialize_webgis_result

__all__ = [
    "DesktopOperationWorker",
    "DesktopProjectState",
    "run_desktop_client",
]

_TILE_PROGRESS_REGEX: re.Pattern[str] = re.compile(r"^(.*?):\s*\[(\d+/\d+)\]$")

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_DELIVERY_PATH: Path = PROJECT_ROOT / "configs" / "mvp81_delivery.example.yaml"
DESKTOP_SESSION_ROOT: Path = PROJECT_ROOT / "outputs" / "desktop_sessions"
OPERATIONS: frozenset[str] = frozenset({"build", "plan", "replan", "combined"})
CANDIDATE_OBJECTIVE_LABELS: tuple[tuple[str, str, str], ...] = (
    ("distance", "距离", "m"),
    ("trafficability", "通行惩罚", "m"),
    ("travel_cost", "行驶代价", ""),
    ("slope", "坡度暴露", "deg·m"),
    ("roughness", "粗糙度暴露", "TRI·m"),
)
CANDIDATE_TOOLTIP_ROLE: int = 3
FILE_FILTERS: dict[str, str] = {
    "dem_path": "DEM 栅格 (*.tif *.tiff)",
    "landcover_path": "土地利用数据 (*.tif *.tiff *.shp *.geojson)",
    "soil_path": "土壤数据 (*.tif *.tiff *.shp *.geojson)",
    "soil_catalog_path": "土壤分类 YAML (*.yaml *.yml)",
    "road_path": "道路矢量 (*.shp *.geojson)",
    "roi_layer_path": "研究区矢量 (*.shp *.geojson)",
    "endpoint_layer_path": "端点矢量 (*.shp *.geojson)",
    "vehicle_path": "车辆 YAML (*.yaml *.yml)",
    "planner_config_path": "规划器 YAML (*.yaml *.yml)",
    "factor_model_path": "地形物理模型 YAML (*.yaml *.yml)",
}
_DESKTOP_ERRORS = (
    ConfigError,
    FileNotFoundError,
    GISInputError,
    GridBuildError,
    OSError,
    PlanningFailedError,
    PlanningInputError,
    ValueError,
    yaml.YAMLError,
)
ProgressCallback = Callable[[str, int, str], None]
DesktopOperationEvent = tuple[str, object]


class DesktopOperationWorker(QObject):
    """Legacy Qt compatibility shim for executing one delivery operation."""

    progress = pyqtSignal(str, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation: str, payload: dict[str, object]) -> None:
        super().__init__()
        if operation not in OPERATIONS:
            raise ValueError(f"operation must be one of {sorted(OPERATIONS)}.")
        self._operation = operation
        self._payload = payload

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = _execute_desktop_operation(self._operation, self._payload, self._emit_progress)
            self.completed.emit(serialize_webgis_result(result, parent_only=True))
        except _DESKTOP_ERRORS as exc:
            self.failed.emit(str(exc))

    def _emit_progress(self, module: str, percent: int, message: str) -> None:
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            raise ConfigError("backend emitted an invalid progress percent.")
        self.progress.emit(module, percent, message)


class ProjectSettingsDialog(QDialog):
    """Edit the typed desktop project without exposing raw YAML text."""

    def __init__(self, project: DesktopProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._path_inputs: dict[tuple[str, str], tuple[QLineEdit, bool]] = {}
        self._int_inputs: dict[tuple[str, str], QSpinBox] = {}
        self._float_inputs: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._bool_inputs: dict[tuple[str, str], QCheckBox] = {}
        self.setWindowTitle("项目设置")
        self.resize(720, 620)
        root = QVBoxLayout(self)
        self._sections = QToolBox()
        self._sections.addItem(self._build_data_page(), "数据与研究区")
        self._sections.addItem(self._build_planning_page(), "路径规划")
        self._sections.addItem(self._build_advanced_page(), "高级参数")
        root.addWidget(self._sections)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_data_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._add_path_row(form, "tile_build", "dem_path", "DEM 栅格", optional=False)
        self._add_path_row(form, "tile_build", "landcover_path", "土地利用", optional=False)
        self._add_path_row(form, "tile_build", "soil_path", "土壤数据", optional=True)
        self._add_path_row(form, "tile_build", "soil_catalog_path", "土壤分类", optional=True)
        self._add_path_row(form, "tile_build", "road_path", "道路矢量", optional=True)
        self._add_path_row(form, "tile_build", "roi_layer_path", "配置研究区图层", optional=True)
        self._add_path_row(
            form, "tile_build", "output_dir", "瓦片输出目录", optional=False, directory=True
        )
        return page

    def _build_planning_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._add_path_row(form, "route", "planner_config_path", "规划器配置", optional=False)
        self._add_path_row(form, "route", "vehicle_path", "车辆配置", optional=False)
        self._add_path_row(form, "route", "factor_model_path", "因子模型配置", optional=False)
        self._add_path_row(form, "route", "output_dir", "路径输出目录", optional=False, directory=True)

        self._mission_profile = QComboBox()
        for label, value in (
            ("最快 ETA", "fastest"),
            ("最短距离", "shortest"),
            ("最大通行裕度", "passability"),
            ("最小综合行驶代价", "economy"),
            ("独立备选", "resilient"),
        ):
            self._mission_profile.addItem(label, value)
        mission_index = self._mission_profile.findData(
            self._project.route.get("mission_profile", "fastest")
        )
        self._mission_profile.setCurrentIndex(mission_index if mission_index >= 0 else 0)
        form.addRow("任务偏好", self._mission_profile)

        self._endpoint_mode = QComboBox()
        self._endpoint_mode.addItem("地图坐标", "coordinates")
        self._endpoint_mode.addItem("端点矢量文件", "layer")
        active_mode = self._project.route.get("input_mode", "coordinates")
        selected = self._endpoint_mode.findData(active_mode)
        self._endpoint_mode.setCurrentIndex(selected if selected >= 0 else 0)
        form.addRow("端点来源", self._endpoint_mode)
        self._add_path_row(form, "route", "endpoint_layer_path", "端点矢量", optional=True)

        endpoints = QWidget()
        endpoint_layout = QVBoxLayout(endpoints)
        endpoint_layout.setContentsMargins(0, 0, 0, 0)
        self._start_summary = QLabel(_endpoint_text("起点", self._project.endpoint("start")))
        self._goal_summary = QLabel(_endpoint_text("终点", self._project.endpoint("goal")))
        endpoint_layout.addWidget(self._start_summary)
        endpoint_layout.addWidget(self._goal_summary)
        form.addRow("地图端点", endpoints)

        self._add_float_row(
            form,
            "route",
            "max_snap_distance_m",
            "最大吸附距离 (m)",
            default=20_000.0,
            minimum=0.01,
            maximum=10_000_000.0,
            decimals=2,
        )
        return page

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        tile_group = QGroupBox("瓦片构建")
        tile_form = QFormLayout(tile_group)
        self._add_int_row(tile_form, "tile_build", "res_fine", "细层 H3 分辨率", 9, 0, 15)
        self._add_int_row(tile_form, "tile_build", "tile_res", "父层 H3 分辨率", 7, 0, 15)
        self._add_int_row(tile_form, "tile_build", "max_tiles", "最大瓦片数", 1_000, 1, 2_000_000_000)
        self._add_int_row(
            tile_form, "tile_build", "max_cells_per_tile", "单瓦片最大格网数", 100_000, 1, 2_000_000_000
        )
        sampling = QComboBox()
        sampling.addItem("中心采样", "center")
        selection = sampling.findData(self._project.tile_build.get("sampling_mode", "center"))
        sampling.setCurrentIndex(selection if selection >= 0 else 0)
        self._sampling_mode = sampling
        tile_form.addRow("属性采样", sampling)
        self._add_bool_row(tile_form, "tile_build", "continue_on_error", "遇到数据错误继续", True)
        self._add_bool_row(tile_form, "tile_build", "overwrite", "覆盖既有瓦片", True)
        root.addWidget(tile_group)

        route_group = QGroupBox("路径规划")
        route_form = QFormLayout(route_group)
        self._add_int_row(route_form, "route", "res_fine", "细层 H3 分辨率", 9, 0, 15)
        self._add_int_row(route_form, "route", "res_coarse", "父层 H3 分辨率", 7, 0, 15)
        self._add_float_row(
            route_form,
            "route",
            "corridor_buffer_deg",
            "自动走廊缓冲 (度)",
            default=0.15,
            minimum=0.000001,
            maximum=180.0,
            decimals=6,
        )
        self._add_int_row(
            route_form, "route", "max_estimated_cells", "最大预估格网数", 500_000, 1, 2_000_000_000
        )
        self._add_int_row(route_form, "route", "max_candidate_paths", "返回候选数", 5, 1, 5)
        self._add_int_row(
            route_form, "route", "candidate_limit", "原始候选池上限", 24, 1, 24
        )
        self._add_float_row(
            route_form,
            "route",
            "penalty_factor",
            "路径复用惩罚",
            default=0.25,
            minimum=0.0,
            maximum=1_000_000.0,
            decimals=4,
        )
        roi_strategy = QComboBox()
        roi_strategy.addItem("自动走廊", "auto_corridor")
        roi_strategy.addItem("图层研究区", "layer")
        selected = roi_strategy.findData(self._project.route.get("roi_strategy", "auto_corridor"))
        roi_strategy.setCurrentIndex(selected if selected >= 0 else 0)
        self._roi_strategy = roi_strategy
        route_form.addRow("研究区策略", roi_strategy)
        root.addWidget(route_group)
        root.addStretch()
        return page

    def _add_path_row(
        self,
        form: QFormLayout,
        section: str,
        field: str,
        label: str,
        *,
        optional: bool,
        directory: bool = False,
    ) -> None:
        mapping = self._mapping(section)
        initial = mapping.get(field, "")
        editor = QLineEdit(str(initial) if isinstance(initial, str) else "")
        button = QPushButton("浏览…")
        button.clicked.connect(
            lambda _checked=False, item=editor, key=field, folder=directory: self._choose_path(
                item, key, folder
            )
        )
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(editor)
        layout.addWidget(button)
        form.addRow(label, row)
        self._path_inputs[(section, field)] = (editor, optional)

    def _choose_path(self, editor: QLineEdit, field: str, directory: bool) -> None:
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择输出目录", editor.text() or str(PROJECT_ROOT))
        else:
            value, _ = QFileDialog.getOpenFileName(
                self, "选择文件", editor.text() or str(PROJECT_ROOT), FILE_FILTERS[field]
            )
        if value:
            editor.setText(value)

    def _add_int_row(
        self,
        form: QFormLayout,
        section: str,
        field: str,
        label: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> None:
        editor = QSpinBox()
        editor.setRange(minimum, maximum)
        value = self._mapping(section).get(field, default)
        editor.setValue(value if isinstance(value, int) and not isinstance(value, bool) else default)
        form.addRow(label, editor)
        self._int_inputs[(section, field)] = editor

    def _add_float_row(
        self,
        form: QFormLayout,
        section: str,
        field: str,
        label: str,
        *,
        default: float,
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> None:
        editor = QDoubleSpinBox()
        editor.setRange(minimum, maximum)
        editor.setDecimals(decimals)
        editor.setSingleStep(1.0 if decimals <= 2 else 0.01)
        value = self._mapping(section).get(field, default)
        editor.setValue(float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default)
        form.addRow(label, editor)
        self._float_inputs[(section, field)] = editor

    def _add_bool_row(
        self,
        form: QFormLayout,
        section: str,
        field: str,
        label: str,
        default: bool,
    ) -> None:
        editor = QCheckBox()
        value = self._mapping(section).get(field, default)
        editor.setChecked(value if isinstance(value, bool) else default)
        form.addRow(label, editor)
        self._bool_inputs[(section, field)] = editor

    def _mapping(self, section: str) -> dict[str, object]:
        return self._project.tile_build if section == "tile_build" else self._project.route

    def accept(self) -> None:
        try:
            self._apply_to_project()
        except ConfigError as exc:
            QMessageBox.warning(self, "项目设置", str(exc))
            return
        super().accept()

    def _apply_to_project(self) -> None:
        for (section, key), (editor, optional) in self._path_inputs.items():
            mapping = self._mapping(section)
            value = editor.text().strip()
            if value or not optional:
                mapping[key] = value
            else:
                mapping.pop(key, None)
        for (section, key), editor in self._int_inputs.items():
            self._mapping(section)[key] = editor.value()
        for (section, key), editor in self._float_inputs.items():
            self._mapping(section)[key] = editor.value()
        for (section, key), editor in self._bool_inputs.items():
            self._mapping(section)[key] = editor.isChecked()
        self._project.tile_build["sampling_mode"] = str(self._sampling_mode.currentData())
        self._project.route["input_mode"] = str(self._endpoint_mode.currentData())
        self._project.route["roi_strategy"] = str(self._roi_strategy.currentData())
        self._project.route["mission_profile"] = str(self._mission_profile.currentData())
        if self._project.route["input_mode"] == "layer" and not self._project.route.get(
            "endpoint_layer_path"
        ):
            raise ConfigError("endpoint layer mode requires an endpoint vector file.")


class DesktopMainWindow(QMainWindow):
    """Map-first desktop shell backed by one structured project state."""

    def __init__(self) -> None:
        super().__init__()
        self._project = load_project_yaml(DEFAULT_DELIVERY_PATH)
        self._last_result: dict[str, object] | None = None
        self._active_grid_level: str = "parent"
        self._selected_parent_h3: str | None = None
        self._selected_fine_grid: dict[str, object] | None = None
        self._candidate_routes: list[dict[str, object]] = []
        self._active_thread: Thread | None = None
        self._operation_events: SimpleQueue[DesktopOperationEvent] = SimpleQueue()
        self._operation_poll_timer = QTimer(self)
        self._operation_poll_timer.setInterval(25)
        self._operation_poll_timer.timeout.connect(self._drain_operation_events)
        status_bar = self.statusBar()
        if status_bar is None:
            raise RuntimeError("desktop main window status bar is unavailable.")
        self._status_bar = status_bar
        self._build_window()
        self._replace_project(self._project, "已加载默认规划配置。")

    def _build_window(self) -> None:
        self.setWindowTitle("H3 越野通行地图与路径规划客户端")
        self.resize(1560, 940)
        self.map_view = DesktopMapView()
        self.map_view.study_area_selected.connect(self._set_study_area)
        self.map_view.coordinate_selected.connect(self._set_endpoint)
        self.map_view.parent_grid_selected.connect(self._select_parent_grid)
        self.map_view.grid_cell_selected.connect(self._toggle_blocked_cell)
        self.map_view.toolbar_action.connect(self._handle_map_action)
        self.map_view.map_error.connect(self._show_map_error)
        self.setCentralWidget(self.map_view)
        self._build_menu()
        self._build_workspace_dock()
        self._build_result_dock()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        if menu_bar is None:
            raise RuntimeError("desktop menu bar is unavailable.")
        file_menu = menu_bar.addMenu("文件")
        if file_menu is None:
            raise RuntimeError("desktop file menu is unavailable.")
        import_action = QAction("导入 YAML…", self)
        import_action.triggered.connect(self._choose_delivery_yaml)
        export_action = QAction("导出当前配置为 YAML…", self)
        export_action.triggered.connect(self._export_delivery_yaml)
        default_action = QAction("恢复默认配置", self)
        default_action.triggered.connect(self._load_default_project)
        file_menu.addAction(import_action)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(default_action)
        project_menu = menu_bar.addMenu("项目")
        if project_menu is None:
            raise RuntimeError("desktop project menu is unavailable.")
        settings_action = QAction("项目设置…", self)
        settings_action.triggered.connect(self._open_project_settings)
        project_menu.addAction(settings_action)

    def _build_workspace_dock(self) -> None:
        dock = QDockWidget("规划工作台", self)
        dock.setObjectName("workflowDock")
        dock.setMinimumWidth(260)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        summary = QGroupBox("当前项目")
        summary_layout = QVBoxLayout(summary)
        self.project_summary = QLabel()
        self.project_summary.setWordWrap(True)
        self.settings_button = QPushButton("打开项目设置…")
        self.settings_button.clicked.connect(self._open_project_settings)
        summary_layout.addWidget(self.project_summary)
        summary_layout.addWidget(self.settings_button)
        layout.addWidget(summary)
        layout.addWidget(self._operation_group())
        layout.addStretch()
        dock.setWidget(panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)  # type: ignore[attr-defined]

    def _build_result_dock(self) -> None:
        dock = QDockWidget("运行信息", self)
        dock.setObjectName("resultDock")
        dock.setMinimumWidth(310)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_label = QLabel("Waiting for operation")
        self.result_text = QTextBrowser()
        self.result_text.setMinimumHeight(150)
        self.theme_box = QComboBox()
        self.theme_box.addItems(["slope", "tri", "elevation"])
        self.theme_box.currentTextChanged.connect(self._redraw_active_grid)
        self.candidate_box = QComboBox()
        self.candidate_box.currentIndexChanged.connect(self._set_candidate_index)
        self.activate_candidate_button = QPushButton("确认并激活当前候选")
        self.activate_candidate_button.clicked.connect(self._activate_candidate)
        self.activate_candidate_button.setDisabled(True)
        grid_buttons = QHBoxLayout()
        self.fine_grid_button = QPushButton("显示细层格网")
        self.fine_grid_button.clicked.connect(self._redraw_fine_grid)
        self.fine_grid_button.setDisabled(True)
        self.parent_grid_button = QPushButton("显示父层格网")
        self.parent_grid_button.clicked.connect(self._draw_parent_grid)
        grid_buttons.addWidget(self.fine_grid_button)
        grid_buttons.addWidget(self.parent_grid_button)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(260)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(QLabel("路线与通行评价"))
        layout.addWidget(self.result_text)
        layout.addWidget(QLabel("专题属性"))
        layout.addWidget(self.theme_box)
        layout.addLayout(grid_buttons)
        layout.addWidget(QLabel("DeterministicParetoPlanner 多角色候选路线"))
        layout.addWidget(self.candidate_box)
        layout.addWidget(self.activate_candidate_button)
        layout.addWidget(QLabel("后端运行日志"))
        layout.addWidget(self.log_text)
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)  # type: ignore[attr-defined]

    def _operation_group(self) -> QGroupBox:
        group = QGroupBox("执行规划")
        layout = QVBoxLayout(group)
        self.operation_buttons: list[QPushButton] = []
        for label, operation in (
            ("构建通行地图", "build"),
            ("生成多角色 RoutePlan", "plan"),
            ("一键端到端交付", "combined"),
            ("运行 D* Lite 重规划", "replan"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=operation: self._start_operation(value)
            )
            self.operation_buttons.append(button)
            layout.addWidget(button)
        return group

    def _load_default_project(self) -> None:
        try:
            self._replace_project(load_project_yaml(DEFAULT_DELIVERY_PATH), "已恢复默认规划配置。")
        except (ConfigError, OSError) as exc:
            self._show_error(str(exc))

    def _choose_delivery_yaml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入交付 YAML", str(PROJECT_ROOT), "YAML (*.yaml *.yml)"
        )
        if not path:
            return
        try:
            self._replace_project(load_project_yaml(Path(path)), f"已导入：{path}")
        except (ConfigError, OSError) as exc:
            self._show_error(str(exc))

    def _export_delivery_yaml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前规划配置",
            str(PROJECT_ROOT / "configs" / "desktop_project.yaml"),
            "YAML (*.yaml *.yml)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in {".yaml", ".yml"}:
            target = target.with_suffix(".yaml")
        try:
            roi_path = self._project.export_yaml(target)
        except (ConfigError, OSError, yaml.YAMLError) as exc:
            self._show_error(str(exc))
            return
        suffix = f"，并写出研究区：{roi_path.name}" if roi_path is not None else ""
        unsupported = self._project.unsupported_fields()
        warning = (
            f" 未支持字段已原样保留：{', '.join(unsupported)}。"
            if unsupported
            else ""
        )
        self._status_bar.showMessage(f"已导出：{target}{suffix}。{warning}")

    def _open_project_settings(self) -> None:
        dialog = ProjectSettingsDialog(self._project, self)
        if dialog.exec_() == QDialog.Accepted:
            self._sync_map_from_project()
            self._refresh_project_summary()
            self._status_bar.showMessage("项目设置已更新。")

    def _replace_project(self, project: DesktopProjectState, message: str) -> None:
        self._project = project
        self._last_result = None
        self._candidate_routes = []
        self._reset_grid_drilldown()
        self.map_view.reset_project_overlays()
        self._sync_map_from_project()
        self._refresh_project_summary()
        unsupported = self._project.unsupported_fields()
        if unsupported:
            message += " 发现后端不支持字段，运行前会阻止执行。"
        self._status_bar.showMessage(message)

    def _sync_map_from_project(self) -> None:
        mode = self._project.route.get("input_mode", "coordinates")
        start = self._project.endpoint("start") if mode == "coordinates" else None
        goal = self._project.endpoint("goal") if mode == "coordinates" else None
        self.map_view.set_endpoints(start, goal)
        try:
            blocked = self._project.blocked_cells()
        except ConfigError:
            blocked = []
        self.map_view.set_blocked_cells(blocked)
        self.map_view.set_blockage_selection_enabled(self._has_fine_grid())

    def _refresh_project_summary(self) -> None:
        tile = self._project.tile_build
        route = self._project.route
        data_summary = "\n".join(
            (
                f"DEM：{_short_path(tile.get('dem_path'))}",
                f"土地利用：{_short_path(tile.get('landcover_path'))}",
                f"研究区：{'地图绘制' if self._project.study_area_geojson else _short_path(tile.get('roi_layer_path'))}",
                f"端点：{'地图坐标' if route.get('input_mode') == 'coordinates' else '端点矢量文件'}",
                _endpoint_text("起点", self._project.endpoint("start")),
                _endpoint_text("终点", self._project.endpoint("goal")),
                f"动态障碍：{len(self._safe_blocked_cells())} 个",
            )
        )
        unsupported = self._project.unsupported_fields()
        if unsupported:
            data_summary += "\n[WARN] 运行前需处理未支持字段：" + ", ".join(unsupported)
        self.project_summary.setText(data_summary)

    def _safe_blocked_cells(self) -> list[str]:
        try:
            return self._project.blocked_cells()
        except ConfigError:
            return []

    def _set_study_area(self, geojson: object) -> None:
        if geojson is None:
            self._project.clear_study_area()
            self._status_bar.showMessage("已清除地图研究区，恢复配置研究区。")
        elif isinstance(geojson, dict):
            try:
                self._project.set_study_area(cast(dict[str, object], geojson))
                self._status_bar.showMessage("地图研究区已更新，将优先于配置图层。")
            except ConfigError as exc:
                self._show_error(str(exc))
                return
        else:
            self._show_error("地图返回了无效的研究区。")
            return
        self._refresh_project_summary()

    def _set_endpoint(self, role: str, lat: float, lng: float) -> None:
        try:
            self._project.set_endpoint(role, lat, lng)
        except ConfigError as exc:
            self._show_error(str(exc))
            return
        self._sync_map_from_project()
        self._refresh_project_summary()
        self._status_bar.showMessage(f"{role} 已选取：{lat:.6f}, {lng:.6f}；已切换为地图坐标模式。")

    def _toggle_blocked_cell(self, cell_id: str) -> None:
        try:
            active = self._project.toggle_blocked_cell(cell_id)
        except ConfigError as exc:
            self._show_error(str(exc))
            return
        self.map_view.set_blocked_cells(self._project.blocked_cells())
        self._refresh_project_summary()
        action = "Marked" if active else "Unmarked"
        self._append_log("WARN", "replan", 0, f"{action} dynamic blockage: {cell_id}")

    def _select_parent_grid(self, parent_h3: str) -> None:
        if self._last_result is None:
            return
        delivery = self._last_result.get("delivery")
        if not isinstance(delivery, dict):
            self._show_error("当前结果缺少瓦片清单，无法加载子格网。")
            return
        try:
            grid = serialize_tile_grid(cast(dict[str, object], delivery), parent_h3)
        except _DESKTOP_ERRORS as exc:
            self._show_error(str(exc))
            return
        if not _grid_has_features(grid):
            self._show_error(f"父格网 {parent_h3} 没有可显示的子格网。")
            return
        self._selected_parent_h3 = parent_h3
        self._selected_fine_grid = grid
        self.fine_grid_button.setDisabled(False)
        self._redraw_fine_grid()
        self._status_bar.showMessage(f"已加载父格网 {parent_h3} 的子格网。")

    def _handle_map_action(self, action: str) -> None:
        if action == "clear_endpoints":
            self._project.clear_endpoints()
            self._sync_map_from_project()
            self._refresh_project_summary()
            self._status_bar.showMessage("已清除地图端点。")
        elif action == "clear_blocked":
            self._project.clear_blocked_cells()
            self._sync_map_from_project()
            self._refresh_project_summary()
            self._status_bar.showMessage("已清空动态障碍。")

    def _start_operation(self, operation: str) -> None:
        if self._active_thread is not None and self._active_thread.is_alive():
            self._show_error("已有任务正在运行。")
            return
        try:
            payload = self._project.build_run_payload(DESKTOP_SESSION_ROOT)
        except (ConfigError, OSError, yaml.YAMLError) as exc:
            self._show_error(str(exc))
            return
        if operation == "replan":
            current_h3, accepted = QInputDialog.getText(
                self,
                "D* Lite 重规划",
                "请输入当前车辆所在 H3 ID（不会从旧路线猜测）：",
            )
            if not accepted or not current_h3.strip():
                return
            route_output = self._project.route.get("output_dir")
            if not isinstance(route_output, str) or not route_output:
                self._show_error("路线输出目录未配置，无法读取 RouteSelection。")
                return
            now_epoch_s = time.time()
            payload = {
                "replan_request": {
                    "selection_path": str(Path(route_output) / "route_selection.json"),
                    "current_h3": current_h3.strip(),
                    "now_epoch_s": now_epoch_s,
                    "blockage_observations": [
                        {
                            "blockage_id": f"client-{cell_id}",
                            "h3index": cell_id,
                            "state": "tentative",
                            "confirmation_count": 1,
                            "trusted_source": True,
                            "observed_at_epoch_s": now_epoch_s,
                            "mission_lifetime": True,
                            "source": "desktop_client",
                        }
                        for cell_id in self._safe_blocked_cells()
                    ],
                }
            }
        self._set_running(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self._last_logged_step: str | None = None
        self._operation_events = SimpleQueue()
        self._active_thread = Thread(
            target=_run_desktop_operation_in_background,
            args=(operation, payload, self._operation_events),
            name=f"desktop-{operation}",
            daemon=True,
        )
        self._operation_poll_timer.start()
        self._active_thread.start()

    def _drain_operation_events(self) -> None:
        terminal = False
        while True:
            try:
                kind, payload = self._operation_events.get_nowait()
            except Empty:
                break
            if kind == "progress" and isinstance(payload, tuple) and len(payload) == 3:
                module, percent, message = payload
                if isinstance(module, str) and isinstance(percent, int) and isinstance(message, str):
                    try:
                        self._on_progress(module, percent, message)
                    except Exception as exc:
                        print(f"Error handling progress: {exc}", file=sys.stderr, flush=True)
            elif kind == "completed":
                try:
                    self._on_completed(payload)
                except _DESKTOP_ERRORS as exc:
                    self._on_failed(f"desktop result rendering failed: {exc}")
                terminal = True
            elif kind == "failed" and isinstance(payload, str):
                self._on_failed(payload)
                terminal = True
        if terminal:
            self._finish_background_operation()

    def _on_progress(self, module: str, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        match = _TILE_PROGRESS_REGEX.match(message)
        if match:
            step = match.group(1).strip()
            detail = match.group(2).strip()
            self.progress_label.setText(f"{module}: {percent}% {step} [{detail}]")
            if getattr(self, "_last_logged_step", None) != step:
                self._last_logged_step = step
                self._append_log("INFO", module, percent, step)
        else:
            self._last_logged_step = message
            self.progress_label.setText(f"{module}: {percent}% {message}")
            self._append_log("INFO", module, percent, message)

    def _on_completed(self, result: object) -> None:
        if not isinstance(result, dict):
            self._on_failed("desktop worker returned an invalid result.")
            return
        self._last_result = cast(dict[str, object], result)
        self._reset_grid_drilldown()
        self._draw_parent_grid()
        self._candidate_routes = _candidate_routes_from_result(self._last_result)
        self._load_candidates()
        if self._render_candidate(self._project.candidate_index()):
            self._sync_map_from_project()
            self.progress_bar.setValue(100)
            self.progress_label.setText("Complete")
            self._append_log("INFO", "complete", 100, "Grid, routes, and evaluation generated.")
            return
        route_geojson = result.get("route_geojson")
        evaluation = result.get("route_evaluation")
        self.map_view.draw_route(
            cast(dict[str, object] | None, route_geojson)
            if isinstance(route_geojson, dict)
            else None,
            _route_tooltip(cast(dict[str, object], evaluation))
            if isinstance(evaluation, dict)
            else "规划路线",
        )
        self._show_evaluation(
            cast(dict[str, object], evaluation) if isinstance(evaluation, dict) else None
        )
        self._sync_map_from_project()
        self.progress_bar.setValue(100)
        self.progress_label.setText("Complete")
        self._append_log("INFO", "complete", 100, "Grid, routes, and evaluation generated.")

    def _on_failed(self, message: str) -> None:
        self._append_log("ERROR", "failed", 100, message)
        self.progress_label.setText("Failed")
        self._show_error(message)

    def _finish_background_operation(self) -> None:
        self._operation_poll_timer.stop()
        if self._active_thread is not None and self._active_thread.is_alive():
            self._active_thread.join(timeout=2.0)
        self._active_thread = None
        self._set_running(False)

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        """Keep the Qt application alive while native GIS work is still running."""
        if self._active_thread is not None and self._active_thread.is_alive():
            self._active_thread.join(timeout=2.0)
            if self._active_thread.is_alive():
                if event is not None:
                    event.ignore()
                self._status_bar.showMessage("后台任务仍在运行，完成后才能关闭程序。")
                return
        self._active_thread = None
        super().closeEvent(event)

    def _redraw_active_grid(self, *_args: object) -> None:
        if self._active_grid_level == "fine" and self._selected_fine_grid is not None:
            self._redraw_fine_grid()
        else:
            self._draw_parent_grid()

    def _redraw_fine_grid(self, *_args: object) -> None:
        if self._selected_fine_grid is None:
            self._status_bar.showMessage("请先点击一个可用父格网以加载其子格网。")
            return
        self.map_view.draw_grid(self._selected_fine_grid, self.theme_box.currentText())
        self._active_grid_level = "fine"
        self.map_view.set_blockage_selection_enabled(True)
        self.map_view.set_blocked_cells(self._safe_blocked_cells())

    def _draw_parent_grid(self, *_args: object) -> None:
        if self._last_result is None:
            return
        grid = self._last_result.get("parent_grid_geojson")
        if isinstance(grid, dict):
            self.map_view.draw_grid(cast(dict[str, object], grid), self.theme_box.currentText())
            self._active_grid_level = "parent"
            self.map_view.set_blockage_selection_enabled(False)

    def _has_fine_grid(self) -> bool:
        return self._active_grid_level == "fine" and _grid_has_features(
            self._selected_fine_grid
        )

    def _reset_grid_drilldown(self) -> None:
        self._active_grid_level = "parent"
        self._selected_parent_h3 = None
        self._selected_fine_grid = None
        if hasattr(self, "fine_grid_button"):
            self.fine_grid_button.setDisabled(True)

    def _load_candidates(self) -> None:
        self.candidate_box.blockSignals(True)
        self.candidate_box.clear()
        for candidate in self._candidate_routes:
            candidate_index = candidate.get("candidate_index")
            if not isinstance(candidate_index, int) or isinstance(candidate_index, bool):
                continue
            position = self.candidate_box.count()
            label = _candidate_label(candidate, candidate_index)
            self.candidate_box.addItem(label, candidate_index)
            self.candidate_box.setItemData(position, label, CANDIDATE_TOOLTIP_ROLE)
        active_index = self._project.candidate_index()
        for position in range(self.candidate_box.count()):
            if self.candidate_box.itemData(position) == active_index:
                self.candidate_box.setCurrentIndex(position)
                break
        self.candidate_box.blockSignals(False)
        self.activate_candidate_button.setDisabled(self.candidate_box.count() == 0)

    def _activate_candidate(self) -> None:
        candidate_index = self.candidate_box.currentData()
        candidate = next(
            (
                item
                for item in self._candidate_routes
                if item.get("candidate_index") == candidate_index
            ),
            None,
        )
        if candidate is None or not isinstance(candidate.get("candidate_id"), str):
            self._show_error("当前候选缺少稳定 candidate_id。")
            return
        route_output = self._project.route.get("output_dir")
        if not isinstance(route_output, str) or not route_output:
            self._show_error("路线输出目录未配置。")
            return
        try:
            selection = run_select_payload(
                {
                    "plan_path": str(Path(route_output) / "route_plan.json"),
                    "candidate_id": candidate["candidate_id"],
                }
            )
        except _DESKTOP_ERRORS as exc:
            self._show_error(str(exc))
            return
        self._append_log(
            "INFO",
            "select",
            100,
            f"Activated {selection.get('candidate_id')}, role {selection.get('selected_role')}.",
        )
        self._status_bar.showMessage("候选路线已显式激活并持久化。")

    def _set_candidate_index(self, position: int) -> None:
        candidate_index = self.candidate_box.itemData(position)
        if isinstance(candidate_index, int) and not isinstance(candidate_index, bool):
            self._project.set_candidate_index(candidate_index)
            self._render_candidate(candidate_index)

    def _render_candidate(self, candidate_index: int) -> bool:
        candidate = next(
            (
                item
                for item in self._candidate_routes
                if item.get("candidate_index") == candidate_index
            ),
            None,
        )
        if candidate is None:
            return False
        geojson = candidate.get("geojson")
        evaluation = candidate.get("evaluation")
        if not isinstance(geojson, dict) or not isinstance(evaluation, dict):
            return False
        self.map_view.draw_route(geojson, _route_tooltip(evaluation))
        self._show_evaluation(evaluation)
        return True

    def _show_evaluation(self, evaluation: dict[str, object] | None) -> None:
        if evaluation is None:
            self.result_text.setText("通行地图构建完成。")
            return
        if "eta_s" in evaluation:
            reasons = ", ".join(
                str(item)
                for item in cast(list[object], evaluation.get("selection_reason", []))
            )
            upper = evaluation.get("eta_upper_s")
            eta_interval = (
                f"{_format_minutes(evaluation.get('eta_lower_s'))}–"
                f"{_format_minutes(upper)} min"
                if upper is not None
                else f"≥ {_format_minutes(evaluation.get('eta_lower_s'))} min（上界无界）"
            )
            self.result_text.setHtml(
                "<b>多角色路线评价</b><br>"
                f"角色：{html.escape(reasons or '—')}<br>"
                f"ETA：{_format_minutes(evaluation.get('eta_s'))} min<br>"
                f"ETA 区间：{eta_interval}<br>"
                f"距离：{_format_number(evaluation.get('distance_m'))} m<br>"
                f"通行裕度：{_format_number(evaluation.get('score_lower_min'))}<br>"
                f"综合行驶代价：{_format_number(evaluation.get('travel_cost'))}<br>"
                f"地形风险：{_format_number(evaluation.get('terrain_risk'))}<br>"
                f"路线状态：{html.escape(str(evaluation.get('route_state', 'planned')))}；"
                f"重规划版本：{html.escape(str(evaluation.get('replan_version', 0)))}"
            )
            return
        shares = evaluation.get("landcover_distance_share")
        share_text = ""
        if isinstance(shares, dict):
            share_text = "；".join(
                f"{html.escape(str(name))}: {float(value) * 100:.1f}%"
                for name, value in shares.items()
                if isinstance(value, (int, float))
            )
        reasons = "；".join(
            str(item) for item in cast(list[object], evaluation.get("selection_reason", []))
        )
        self.result_text.setHtml(
            "<b>路线评价</b><br>"
            f"通行质量：{_format_number(evaluation.get('quality_score'))}<br>"
            f"总距离：{_format_number(evaluation.get('distance_m'))} m<br>"
            f"预计时间：{_format_minutes(evaluation.get('estimated_time_s'))} min<br>"
            f"选取理由：{html.escape(reasons or '—')}<br>"
            f"全程地物占比：{share_text or '—'}<br>"
            f"最小转弯半径：{_format_number(evaluation.get('min_turn_radius_m'))} m"
        )

    def _append_log(self, level: str, module: str, percent: int, message: str) -> None:
        self.log_text.appendPlainText(f"[{level}] {module} {percent}% {message}")

    def _show_map_error(self, message: str) -> None:
        self._append_log("ERROR", "map", 0, message)
        self._status_bar.showMessage(message)

    def _show_error(self, message: str) -> None:
        self._status_bar.showMessage(message)
        QMessageBox.critical(self, "H3 越野规划", message)

    def _set_running(self, running: bool) -> None:
        for button in self.operation_buttons:
            button.setDisabled(running)
        self.settings_button.setDisabled(running)
        self.activate_candidate_button.setDisabled(running or self.candidate_box.count() == 0)


def _execute_desktop_operation(
    operation: str,
    payload: dict[str, object],
    progress: ProgressCallback,
) -> dict[str, object]:
    """Dispatch one desktop operation solely through existing CLI payload adapters."""
    if operation not in OPERATIONS:
        raise ConfigError(f"operation must be one of {sorted(OPERATIONS)}.")
    if operation == "build":
        progress("build_map", 10, "started trafficability-map build")
        try:
            tile_manifest = run_tile_payload(_mapping(payload, "tile_build"), progress=progress)
        except TypeError:
            tile_manifest = run_tile_payload(_mapping(payload, "tile_build"))
        result: dict[str, object] = {"tile_manifest": tile_manifest}
        progress("build_map", 85, "completed trafficability-map build")
        return result
    if operation == "replan":
        progress("replan", 65, "started D* Lite route repair")
        request = _mapping(payload, "replan_request")
        typed_result = run_replan_payload(request)
        selection_path = request.get("selection_path")
        if not isinstance(selection_path, str) or not selection_path:
            raise ConfigError("replan_request.selection_path must be a non-empty string.")
        active_path = Path(selection_path).parent / "active_route.geojson"
        if not active_path.is_file():
            raise ConfigError("replan did not produce active_route.geojson.")
        active = json.loads(active_path.read_text(encoding="utf-8"))
        if not isinstance(active, dict):
            raise ConfigError("active_route.geojson must contain a GeoJSON object.")
        progress("evaluation", 95, "loaded persisted active-route metrics")
        return {"replan_result": typed_result, "active_route_geojson": active}
    if operation == "plan":
        route = dict(_mapping(payload, "route"))
        _set_route_tile_manifest(route, _mapping(payload, "tile_build"))
        manifest_path = Path(str(route.get("parquet_path", "")))
        if not manifest_path.is_file():
            progress("build_map", 10, "trafficability map missing; building tile cache...")
            return run_delivery_payload(payload, progress)
        progress("global_plan", 65, "started route planning")
        try:
            route_manifest = run_route_payload(route, progress=progress)
        except TypeError:
            route_manifest = run_route_payload(route)
        result = {"route_manifest": route_manifest}
        progress("evaluation", 95, "exported route artifacts")
        return result
    return run_delivery_payload(payload, progress)


def _run_desktop_operation_in_background(
    operation: str,
    payload: dict[str, object],
    events: SimpleQueue[DesktopOperationEvent],
) -> None:
    """Run one operation without giving Qt ownership of the compute thread."""

    def report(module: str, percent: int, message: str) -> None:
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            raise ConfigError("backend emitted an invalid progress percent.")
        print(f"[{module}] {percent:>3}%: {message}", file=sys.stderr, flush=True)
        events.put(("progress", (module, percent, message)))

    try:
        result = _execute_desktop_operation(operation, payload, report)
        serialized = serialize_webgis_result(result, parent_only=True)
    except _DESKTOP_ERRORS as exc:
        events.put(("failed", str(exc)))
    except Exception as exc:  # pragma: no cover - native-library safety boundary
        events.put(("failed", f"unexpected {type(exc).__name__}: {exc}"))
    else:
        events.put(("completed", serialized))


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"request field {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _set_route_tile_manifest(route: dict[str, object], tile: dict[str, object]) -> None:
    source = route.get("parquet_path")
    if isinstance(source, str) and source:
        return
    output_dir = tile.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        raise ConfigError("route operation requires route.parquet_path or tile_build.output_dir.")
    route["parquet_path"] = str(Path(output_dir) / TILE_MANIFEST_NAME)


def _short_path(value: object) -> str:
    return Path(value).name if isinstance(value, str) and value else "未设置"


def _endpoint_text(name: str, value: tuple[float, float] | None) -> str:
    return f"{name}：{value[0]:.6f}, {value[1]:.6f}" if value is not None else f"{name}：未选择"


def _format_number(value: object) -> str:
    return f"{float(value):.3f}" if isinstance(value, (int, float)) else "—"


def _format_minutes(value: object) -> str:
    return f"{float(value) / 60.0:.3f}" if isinstance(value, (int, float)) else "—"


def _grid_has_features(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    features = value.get("features")
    return isinstance(features, list) and bool(features)


def _candidate_routes_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    """Return serializer-provided candidate entries while rejecting malformed values."""
    routes = result.get("candidate_routes")
    if not isinstance(routes, list):
        return []
    return [cast(dict[str, object], route) for route in routes if isinstance(route, dict)]


def _candidate_label(candidate: dict[str, object], candidate_index: int) -> str:
    """Format one new role candidate from exact PathMetrics."""
    evaluation = candidate.get("evaluation")
    roles = candidate.get("roles")
    if isinstance(evaluation, dict) and isinstance(roles, list):
        role_text = ", ".join(str(role) for role in roles)
        return (
            f"候选 {candidate_index + 1} | {role_text} | "
            f"ETA {_format_minutes(evaluation.get('eta_s'))} min | "
            f"距离 {_format_number(evaluation.get('distance_m'))} m | "
            f"通行裕度 {_format_number(evaluation.get('score_lower_min'))} | "
            f"行驶代价 {_format_number(evaluation.get('travel_cost'))}"
        )
    if candidate.get("replanned") is True:
        return "D* Lite 重规划活动路线（旧候选目标不再适用）"
    objectives = candidate.get("objectives")
    values = objectives if isinstance(objectives, dict) else {}
    metrics = " | ".join(
        f"{label} {_format_number(values.get(key))}{unit}".rstrip()
        for key, label, unit in CANDIDATE_OBJECTIVE_LABELS
    )
    return (
        f"候选 {candidate_index + 1} | {metrics} | "
        f"统一行驶代价 {_format_number(candidate.get('total_cost'))}"
    )


def _route_tooltip(evaluation: dict[str, object]) -> str:
    reasons = "；".join(
        str(item) for item in cast(list[object], evaluation.get("selection_reason", []))
    )
    if "eta_s" in evaluation:
        return (
            f"角色：{html.escape(reasons or '—')}<br>"
            f"ETA：{_format_minutes(evaluation.get('eta_s'))} min<br>"
            f"距离：{_format_number(evaluation.get('distance_m'))} m<br>"
            f"通行裕度：{_format_number(evaluation.get('score_lower_min'))}<br>"
            f"综合行驶代价：{_format_number(evaluation.get('travel_cost'))}"
        )
    return (
        f"路线质量：{_format_number(evaluation.get('quality_score'))}<br>"
        f"选取理由：{html.escape(reasons or '—')}<br>"
        f"最小转弯半径：{_format_number(evaluation.get('min_turn_radius_m'))} m"
    )


def run_desktop_client() -> int:
    """Start the PyQt5 desktop main interface and return the event-loop exit code."""
    import os
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QTWEBENGINE_DISABLE_GPU_SHADER_DISK_CACHE", "1")
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)  # type: ignore[attr-defined]
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    application = QApplication.instance() or QApplication(sys.argv)
    window = DesktopMainWindow()
    window.show()
    return int(application.exec_())


if __name__ == "__main__":
    raise SystemExit(run_desktop_client())
