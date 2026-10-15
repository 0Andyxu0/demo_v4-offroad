# 模块参考：desktop_map

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/desktop_map.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`ec3b774bdb0553fd4d5bac9669c48365616b9541ecb3403fac5d29d84881eb6c`；类 1 个，函数/方法 19 个（含嵌套定义）。
- 项目内导入依赖：`map_config`。
- 直接导入本模块者：`desktop_client`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# DesktopMapView — src/h3_offroad_planner/desktop_map.py:74
class DesktopMapView(QWebEngineView):
    'Bridge one Leaflet/TianDiTu map to typed Qt signals and GeoJSON display.'
    study_area_selected = pyqtSignal(object)
    coordinate_selected = pyqtSignal(str, float, float)
    parent_grid_selected = pyqtSignal(str)
    grid_cell_selected = pyqtSignal(str)
    toolbar_action = pyqtSignal(str)
    map_error = pyqtSignal(str)
    # self._page_ready: 未注解; L86; initial=False
    _pending_scripts: list[str]  # instance; L87; initial=[]
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
from math import isfinite
from typing import cast
from PyQt5.QtCore import QUrl, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView
from h3_offroad_planner.map_config import TIANDITU_KEY, TIANDITU_LAYER_TYPE

# DesktopMapView — L74
class DesktopMapView(QWebEngineView):
    """Bridge one Leaflet/TianDiTu map to typed Qt signals and GeoJSON display."""

    def __init__(self) -> None:
        ...

    def begin_study_area(self) -> None:
        """Enable a one-polygon Leaflet.draw interaction."""
        ...

    def clear_study_area(self) -> None:
        """Clear the selected ROI from the Leaflet study layer and notify Qt."""
        ...

    def set_selection_mode(self, mode: str) -> None:
        """Set start, goal, blocked, or none selection mode for map clicks."""
        ...

    def draw_marker(self, lat: float, lng: float, is_start: bool) -> None:
        """Draw a WGS84 endpoint marker after desktop validation."""
        ...

    def set_endpoints(self, start: tuple[float, float] | None, goal: tuple[float, float] | None) -> None:
        """Synchronize map endpoint markers from the canonical project state."""
        ...

    def set_blocked_cells(self, cells: list[str]) -> None:
        """Render the canonical dynamic blockage set on the current fine grid."""
        ...

    def set_blockage_selection_enabled(self, enabled: bool) -> None:
        """Enable blockage selection only while a fine grid is available."""
        ...

    def reset_project_overlays(self) -> None:
        """Clear visual map choices before loading another desktop project."""
        ...

    def draw_grid(self, geojson: dict[str, object], theme: str) -> None:
        """Render bounded H3 grid GeoJSON with one supported thematic attribute."""
        ...

    def draw_route(self, geojson: dict[str, object] | None, tooltip_html: str) -> None:
        """Render route GeoJSON with pre-rendered escaped evaluation text."""
        ...

    def _run_js(self, script: str) -> None:
        ...

    def _on_load_finished(self, success: bool) -> None:
        """Run state synchronization requested while the Leaflet page was loading."""
        ...

    def _on_title_changed(self, title: str) -> None:
        """Decode sequenced map events carried through the document-title bridge."""
        ...

    def _emit_study_area(self, raw: str) -> None:
        ...

    def _emit_coordinate(self, raw: str) -> None:
        ...

    def _emit_grid_cell(self, cell_id: str) -> None:
        ...

    def _emit_parent_grid(self, parent_h3: str) -> None:
        ...

# _is_wgs84_point — L251
def _is_wgs84_point(lat: float, lng: float) -> bool:
    """Return whether one latitude/longitude pair is finite and WGS84 bounded."""
    ...
```
