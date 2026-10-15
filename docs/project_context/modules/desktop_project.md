# 模块参考：desktop_project

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/desktop_project.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`94eb0beff8a46dd80bcd9fcf7c5da10366f52aaca74dc84d06c8869603209c99`；类 1 个，函数/方法 22 个（含嵌套定义）。
- 项目内导入依赖：`cli`, `models`。
- 直接导入本模块者：`desktop_client`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# DesktopProjectState — src/h3_offroad_planner/desktop_project.py:26
@dataclass
class DesktopProjectState:
    'The only editable configuration source for the desktop client.\n\n    The two request mappings deliberately retain every imported value.  This lets\n    the settings dialog edit the fields it understands without discarding valid\n    fields that have no current control.  A map-drawn study area is held as\n    geometry until a run or export materializes it as GeoJSON.\n    '
    tile_build: dict[str, object]
    route: dict[str, object]
    extra_sections: dict[str, object] = field(default_factory=dict)
    study_area_geojson: dict[str, object] | None = None
    ...
```

```text
# L227 write_study_area_file
'type' => 'Feature'
'properties' => {  }
'geometry' => json.loads(json.dumps(geometry.__geo_interface__))

# L233 write_study_area_file
'type' => 'FeatureCollection'
'features' => [feature]
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import copy
import json
import uuid
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import cast
import yaml
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from h3_offroad_planner.cli import ROUTE_FIELDS, TILE_BUILD_FIELDS
from h3_offroad_planner.models import ConfigError

# DesktopProjectState — L26
@dataclass
class DesktopProjectState:
    """The only editable configuration source for the desktop client.

    The two request mappings deliberately retain every imported value.  This lets
    the settings dialog edit the fields it understands without discarding valid
    fields that have no current control.  A map-drawn study area is held as
    geometry until a run or export materializes it as GeoJSON.
    """

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> DesktopProjectState:
        """Create an editable project from a decoded delivery YAML mapping."""
        ...

    def to_mapping(self) -> dict[str, object]:
        """Return a detached delivery mapping without materializing map geometry."""
        ...

    def unsupported_fields(self) -> list[str]:
        """List imported field paths that the existing request adapters cannot run."""
        ...

    def ensure_runnable(self) -> None:
        """Reject preserved, but backend-unsupported, fields before any operation starts."""
        ...

    def set_study_area(self, geojson: dict[str, object]) -> None:
        """Use a map-drawn Polygon or MultiPolygon as the active research area."""
        ...

    def clear_study_area(self) -> None:
        """Return to the ROI layer path stored in the project configuration."""
        ...

    def endpoint(self, role: str) -> tuple[float, float] | None:
        """Return one stored coordinate endpoint when it is complete and valid."""
        ...

    def set_endpoint(self, role: str, lat: float, lng: float) -> None:
        """Apply a map endpoint and explicitly select coordinate-input mode."""
        ...

    def clear_endpoints(self) -> None:
        """Remove map-coordinate endpoints without discarding an endpoint-layer path."""
        ...

    def blocked_cells(self) -> list[str]:
        """Return validated dynamic H3 blockages from the canonical route mapping."""
        ...

    def toggle_blocked_cell(self, cell_id: str) -> bool:
        """Toggle a blockage and return whether the cell is now blocked."""
        ...

    def clear_blocked_cells(self) -> None:
        """Clear every map-selected dynamic blockage."""
        ...

    def candidate_index(self) -> int:
        """Return the active candidate index, retaining backend validation semantics."""
        ...

    def set_candidate_index(self, index: int) -> None:
        """Store the result-panel candidate choice in the canonical route mapping."""
        ...

    def build_run_payload(self, session_root: Path) -> dict[str, object]:
        """Create one execution payload and materialize any map research geometry."""
        ...

    def export_yaml(self, path: Path) -> Path | None:
        """Write YAML and, for drawn geometry, a paired relative-path GeoJSON artifact."""
        ...

# load_project_yaml — L188
def load_project_yaml(path: Path) -> DesktopProjectState:
    """Parse a selected YAML file without changing the current desktop project on error."""
    ...

# validate_study_area — L199
def validate_study_area(geojson: dict[str, object]) -> BaseGeometry:
    """Validate the Polygon/MultiPolygon geometry used by map selection and export."""
    ...

# write_session_study_area — L216
def write_session_study_area(geojson: dict[str, object], session_root: Path) -> str:
    """Write the active map research area to a run-specific session directory."""
    ...

# write_study_area_file — L223
def write_study_area_file(geojson: dict[str, object], output: Path) -> None:
    """Write validated map geometry as a single-feature GeoJSON collection."""
    ...

# _mapping — L238
def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    ...

# _is_wgs84_point — L245
def _is_wgs84_point(lat: object, lng: object) -> bool:
    ...
```
