# 模块参考：routing

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/routing.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`68473eb59ae8a94384ece68a8d2c5cf536990b7f7b0e9d0925eb7784b147a4b6`；类 0 个，函数/方法 50 个（含嵌套定义）。
- 项目内导入依赖：`config`, `exporting`, `grid`, `models`, `planners`, `routing_index`。
- 直接导入本模块者：`h3_offroad_planner`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L64
JsonObject = dict[str, object]
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from heapq import heappop, heappush
from math import atan2, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from time import perf_counter
from typing import cast
import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from h3_offroad_planner.config import load_config, load_vehicle
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GISInputError, GridBuildError, H3Cell, H3Edge, H3Graph, PlannerInput, PlanningInputError, RouteEndpoint, RouteRequest, VehicleProfile
from h3_offroad_planner.models import Path as PlannerPath
from h3_offroad_planner.planners import PlannerFactory
from h3_offroad_planner.routing_index import ROUTING_INDEX_KIND, RoutingIndex, open_routing_index

# run_route — L67
def run_route(request: RouteRequest) -> dict[str, object]:
    """Run a user-parameterized single-vehicle route request.

    Args:
        request: Valid route request with coordinate or layer endpoints.

    Returns:
        JSON-serializable manifest describing inputs, snapped cells, outputs, and route.

    Raises:
        GridBuildError: If the ROI estimate is too large or filtering removes all cells.
        PlanningInputError: If endpoint input is invalid or cannot be snapped.
        PlanningFailedError: Propagated from the configured planner when no path exists.
    """
    ...

# load_route_endpoints — L107
def load_route_endpoints(path: str) -> list[RouteEndpoint]:
    """Load route endpoints from a point vector layer with a `role` field."""
    ...

# snap_endpoint — L120
def snap_endpoint(graph: H3Graph, endpoint: RouteEndpoint, max_distance_m: float) -> str:
    """Snap one endpoint to the nearest passable H3 cell in a graph."""
    ...

# estimate_h3_cells_for_roi — L143
def estimate_h3_cells_for_roi(roi: BaseGeometry, resolution: int) -> int:
    """Estimate H3 cell count for a WGS84 ROI polygon."""
    ...

# _request_endpoints — L154
def _request_endpoints(request: RouteRequest) -> list[RouteEndpoint]:
    ...

# _resolve_roi — L172
def _resolve_roi(request: RouteRequest, endpoints: list[RouteEndpoint]) -> tuple[BaseGeometry, str]:
    ...

# _load_route_graph — L186
def _load_route_graph(request: RouteRequest, roi_geometry: BaseGeometry, source_metadata: dict[str, object], progress: Callable[[str, int, str], None] | None=None, progress_range: tuple[int, int]=(75, 84), corridor_ring: int=1, max_widest_detour_ratio: float | None=None, extra_parents: set[str] | None=None) -> tuple[H3Graph, dict[str, object]]:
    ...

# _source_metadata — L214
def _source_metadata(parquet_path: str) -> dict[str, object]:
    ...

# _read_source_manifest — L239
def _read_source_manifest(path: Path) -> dict[str, object]:
    ...

# _parquet_manifest_path — L253
def _parquet_manifest_path(parquet_path: str) -> Path:
    ...

# _is_tile_cache_metadata — L257
def _is_tile_cache_metadata(source_metadata: JsonObject) -> bool:
    ...

# _is_routing_index_metadata — L261
def _is_routing_index_metadata(source_metadata: JsonObject) -> bool:
    ...

# _routing_index_metadata — L265
def _routing_index_metadata(path: Path) -> JsonObject:
    ...

# _load_index_route_graph — L274
def _load_index_route_graph(request: RouteRequest, source_metadata: JsonObject, corridor_ring: int, *, max_widest_detour_ratio: float | None=None, extra_parents: set[str] | None=None) -> tuple[H3Graph, JsonObject]:
    ...

# _coarse_skeletons — L336
def _coarse_skeletons(index: RoutingIndex, start: RouteEndpoint, goal: RouteEndpoint, *, max_widest_detour_ratio: float | None=None) -> tuple[dict[str, list[str]], JsonObject]:
    ...

# _coarse_path_distance — L409
def _coarse_path_distance(adjacency: Mapping[str, list[tuple[str, dict[str, float]]]], path: list[str]) -> float:
    ...

# _snap_parent — L425
def _snap_parent(nodes: set[str], endpoint: RouteEndpoint, resolution: int) -> str:
    ...

# _coarse_shortest_path — L440
def _coarse_shortest_path(adjacency: Mapping[str, list[tuple[str, dict[str, float]]]], start: str, goal: str, profile: str, blocked: frozenset[str]) -> list[str]:
    ...

# _coarse_weight — L470
def _coarse_weight(metrics: Mapping[str, float], profile: str) -> float:
    ...

# _coarse_widest_path — L490
def _coarse_widest_path(adjacency: Mapping[str, list[tuple[str, dict[str, float]]]], start: str, goal: str) -> list[str]:
    ...

# _is_valid_h3_parent — L526
def _is_valid_h3_parent(cell: str | None) -> bool:
    ...

# _expanded_corridor_parents — L535
def _expanded_corridor_parents(index: RoutingIndex, skeletons: Mapping[str, list[str]], ring: int, extra_parents: set[str] | None=None) -> set[str]:
    ...

# expand_targeted_bottleneck_parents — L565
def expand_targeted_bottleneck_parents(index: RoutingIndex, current_parents: set[str], bottleneck_parents: Sequence[str], max_additional: int=15) -> set[str]:
    """Perform targeted dilation around specific bottleneck parent cells.

    Only dilates the bottleneck parents by 1-ring (grid_disk(p, 1)) and returns
    up to max_additional newly activated parent tiles available in the coarse graph.
    Neighbors of higher-priority bottleneck parents are prioritized.
    """
    ...

# _load_tile_route_graph — L616
def _load_tile_route_graph(request: RouteRequest, roi_geometry: BaseGeometry, source_metadata: JsonObject, progress: Callable[[str, int, str], None] | None=None, progress_range: tuple[int, int]=(75, 84)) -> tuple[H3Graph, JsonObject]:
    ...

# _selected_tile_records — L658
def _selected_tile_records(source_metadata: JsonObject, roi_geometry: BaseGeometry) -> list[JsonObject]:
    ...

# _tile_records — L685
def _tile_records(source_metadata: JsonObject) -> list[JsonObject]:
    ...

# _tile_record_geometry — L697
def _tile_record_geometry(record: JsonObject) -> BaseGeometry:
    ...

# _tile_bounds_values — L705
def _tile_bounds_values(bounds: list[object]) -> tuple[float, float, float, float]:
    ...

# _load_tile_frames — L714
def _load_tile_frames(selected_records: list[JsonObject], manifest_path: Path, res_fine: int, tile_res: int, progress: Callable[[str, int, str], None] | None=None, progress_range: tuple[int, int]=(75, 84)) -> list[pd.DataFrame]:
    ...

# _tile_record_path — L741
def _tile_record_path(record: JsonObject, manifest_path: Path) -> Path:
    ...

# _tile_route_metadata — L754
def _tile_route_metadata(source_metadata: JsonObject, selected_records: list[JsonObject], res_fine: int, tile_res: int) -> JsonObject:
    ...

# _metadata_int — L770
def _metadata_int(source: JsonObject, key: str) -> int:
    ...

# _metadata_str — L777
def _metadata_str(source: JsonObject, key: str) -> str:
    ...

# _plan_route — L784
def _plan_route(request: RouteRequest, graph: H3Graph, vehicle: VehicleProfile, endpoints: list[RouteEndpoint]) -> tuple[PlannerPath, list[PlannerPath], bool]:
    ...

# _export_route_outputs — L825
def _export_route_outputs(graph: H3Graph, route_path: PlannerPath, request: RouteRequest, source_metadata: dict[str, object]) -> dict[str, object]:
    ...

# _route_manifest — L851
def _route_manifest(request: RouteRequest, graph: H3Graph, endpoints: list[RouteEndpoint], route_path: PlannerPath, outputs: dict[str, object], roi_source: str, estimated_cells: int, source_metadata: dict[str, object], candidates: list[PlannerPath], replanned: bool) -> dict[str, object]:
    ...

# _candidate_payload — L892
def _candidate_payload(candidate: PlannerPath) -> dict[str, object]:
    """Return one JSON-safe candidate summary for WebGIS selection."""
    ...

# _route_source_metadata_payload — L901
def _route_source_metadata_payload(source_metadata: dict[str, object]) -> dict[str, object]:
    ...

# _read_wgs84_layer — L923
def _read_wgs84_layer(path: Path) -> gpd.GeoDataFrame:
    ...

# _endpoint_from_mapping — L935
def _endpoint_from_mapping(row: dict[str, object]) -> RouteEndpoint:
    ...

# _validate_endpoint_roles — L949
def _validate_endpoint_roles(endpoints: list[RouteEndpoint]) -> None:
    ...

# _single_endpoint — L957
def _single_endpoint(endpoints: list[RouteEndpoint], role: str) -> RouteEndpoint:
    ...

# _load_roi_geometry — L964
def _load_roi_geometry(path: str) -> BaseGeometry:
    ...

# _filter_graph_by_roi — L972
def _filter_graph_by_roi(graph: H3Graph, roi_geometry: BaseGeometry) -> H3Graph:
    ...

# _filtered_edges — L991
def _filtered_edges(graph: H3Graph, cell_ids: set[str]) -> dict[tuple[str, str], H3Edge]:
    ...

# _filtered_parent_children — L999
def _filtered_parent_children(cells: dict[str, H3Cell]) -> dict[str, set[str]]:
    ...

# _approx_wgs84_area_m2 — L1006
def _approx_wgs84_area_m2(geometry: BaseGeometry) -> float:
    ...

# _haversine_m — L1014
def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    ...

# _endpoint_payload — L1023
def _endpoint_payload(endpoint: RouteEndpoint) -> dict[str, object]:
    ...

# _oversize_message — L1032
def _oversize_message(estimated_cells: int, max_cells: int) -> str:
    ...
```
