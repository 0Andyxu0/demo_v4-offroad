# 模块参考：exporting.gis_exporter

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/exporting/gis_exporter.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`39bb53ccce8a3b84006c08e3a39e240c3e47a348d06cb580d2f85cd090e1c471`；类 1 个，函数/方法 22 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`exporting`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# GISExporter — src/h3_offroad_planner/exporting/gis_exporter.py:42
class GISExporter:
    'Export H3 graph and path artifacts to GIS-friendly files.'
    ...
```

```text
# L138 _cell_record
'h3index' => cell.h3index
'parent_h3' => cell.parent_h3
'lat' => _finite_or_none(cell.lat)
'lng' => _finite_or_none(cell.lng)
'elevation' => _finite_or_none(cell.elevation)
'slope' => _finite_or_none(cell.slope)
'tri' => _finite_or_none(cell.tri)
'lc_factor' => _finite_or_none(cell.lc_factor)
'landcover_code' => cell.landcover_code
'landcover_type' => cell.landcover_type
'soil_code' => cell.soil_code
'soil_type' => cell.soil_type
'soil_texture' => cell.soil_texture
'uscs' => cell.uscs
'soil_moisture' => _finite_or_none(cell.soil_moisture)
'soil_mobility' => _finite_or_none(cell.soil_mobility)
'has_road' => cell.has_road
'is_passable' => cell.is_passable
'score' => _finite_or_none(cell.score)
'cost_score' => _finite_or_none(cell.cost_score)

# L244 _export_theme_layers
'attributes' => {  }
'color_ramp' => list(THEME_COLORS)

# L265 _theme_spec
'attribute' => attribute
'field' => 'style_value'
'kind' => 'categorical'
'categories' => categories
'colors' => {category: THEME_COLORS[index % len(THEME_COLORS)] for index, category in enumerate(categories)}

# L286 _numeric_theme_spec
'attribute' => attribute
'field' => 'style_value'
'kind' => 'numeric'
'min' => min(values)
'max' => max(values)
'colors' => list(THEME_COLORS)

# L323 _style_fields
'style_value' => str(value)
'style_bin' => str(value)
'style_color' => color

# L334 _numeric_style_fields
'style_value' => value
'style_bin' => bin_index
'style_color' => THEME_COLORS[bin_index]

# L174 _edges_gdf
'cell_a' => edge.cell_a
'cell_b' => edge.cell_b
'distance_m' => _finite_or_none(edge.geo_distance)
'has_road' => edge.has_road
'slope_a_b' => _finite_or_none(edge.slope_a_to_b)
'slope_b_a' => _finite_or_none(edge.slope_b_to_a)

# L279 _numeric_theme_spec
'attribute' => attribute
'field' => 'style_value'
'kind' => 'numeric'
'max' => None
'min' => None

# L315 _style_fields
'style_value' => None
'style_bin' => 'no_data'
'style_color' => NO_DATA_COLOR

# L330 _numeric_style_fields
'style_value' => value
'style_bin' => 0
'style_color' => NO_DATA_COLOR

# L193 _path_gdf
'cell_count' => len(path_result.cells)
'total_cost' => _finite_or_none(path_result.total_cost)
'start' => path_result.cells[0]
'goal' => path_result.cells[-1]
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
from collections.abc import Mapping
from math import isfinite
from pathlib import Path
import geopandas as gpd
import h3
from shapely.geometry import LineString, Point, Polygon
from h3_offroad_planner.models import H3Cell, H3Graph, PlanningInputError
from h3_offroad_planner.models import Path as PlannerPath

# GISExporter — L42
class GISExporter:
    """Export H3 graph and path artifacts to GIS-friendly files."""

    @staticmethod
    def export_graph_gpkg(graph: H3Graph, path: str, theme_attributes: list[str] | None=None, style_manifest_path: str | None=None, layer_metadata: Mapping[str, object] | None=None) -> None:
        """Write H3 cell polygons and edge lines to a GeoPackage.

        Args:
            graph: Non-empty in-memory H3 graph.
            path: Output GeoPackage path. Unit: filesystem path.
            theme_attributes: Optional H3 cell attributes exported as themed layers.
            style_manifest_path: Optional JSON style manifest path.
            layer_metadata: Optional scalar metadata copied into graph and theme layers.

        Raises:
            PlanningInputError: If the graph is empty.
            OSError: If the target cannot be written.
        """
        ...

    @staticmethod
    def export_path_gpkg(graph: H3Graph, path_result: PlannerPath, path: str, layer: str='planned_path') -> None:
        """Write a planned path as a named GeoPackage layer."""
        ...

    @staticmethod
    def export_path_geojson(graph: H3Graph, path_result: PlannerPath, path: str) -> None:
        """Write a planned path as a GeoJSON FeatureCollection."""
        ...

    @staticmethod
    def write_manifest(path: str, payload: Mapping[str, object]) -> None:
        """Write a UTF-8 JSON manifest for reproducing a demo run."""
        ...

# _prepare_parent — L119
def _prepare_parent(path: str) -> Path:
    ...

# _cells_gdf — L125
def _cells_gdf(graph: H3Graph, layer_metadata: Mapping[str, object] | None=None) -> gpd.GeoDataFrame:
    ...

# _cell_record — L134
def _cell_record(cell: H3Cell, layer_metadata: Mapping[str, object] | None=None) -> dict[str, object]:
    ...

# _edges_gdf — L164
def _edges_gdf(graph: H3Graph, layer_metadata: Mapping[str, object] | None=None) -> gpd.GeoDataFrame:
    ...

# _path_gdf — L188
def _path_gdf(graph: H3Graph, path_result: PlannerPath) -> gpd.GeoDataFrame:
    ...

# _cell_lnglat — L205
def _cell_lnglat(graph: H3Graph, cell_id: str) -> tuple[float, float]:
    ...

# _cell_polygon — L212
def _cell_polygon(h3index: str) -> Polygon:
    ...

# _finite_or_none — L219
def _finite_or_none(value: float | None) -> float | None:
    ...

# _validated_theme_attributes — L225
def _validated_theme_attributes(attributes: list[str]) -> list[str]:
    ...

# _export_theme_layers — L238
def _export_theme_layers(graph: H3Graph, gpkg_path: Path, attributes: list[str], layer_metadata: Mapping[str, object] | None=None) -> dict[str, object]:
    ...

# _theme_spec — L259
def _theme_spec(graph: H3Graph, attribute: str) -> dict[str, object]:
    ...

# _numeric_theme_spec — L277
def _numeric_theme_spec(attribute: str, values: list[float]) -> dict[str, object]:
    ...

# _theme_gdf — L296
def _theme_gdf(graph: H3Graph, attribute: str, spec: dict[str, object], layer_metadata: Mapping[str, object] | None=None) -> gpd.GeoDataFrame:
    ...

# _style_fields — L313
def _style_fields(value: object, spec: dict[str, object]) -> dict[str, object]:
    ...

# _numeric_style_fields — L326
def _numeric_style_fields(value: float, spec: dict[str, object]) -> dict[str, object]:
    ...

# _theme_value — L337
def _theme_value(cell: H3Cell, attribute: str) -> object:
    ...

# _metadata_fields — L344
def _metadata_fields(payload: Mapping[str, object] | None) -> dict[str, object]:
    ...

# _metadata_scalar — L373
def _metadata_scalar(value: object) -> object:
    ...
```
