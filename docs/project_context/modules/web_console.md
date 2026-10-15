# 模块参考：web_console

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/web_console.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`0a0c2c6b2d86f737297f9227bbb05deddf5657c64cdac45f309aa8e9915e7c5a`；类 1 个，函数/方法 65 个（含嵌套定义）。
- 项目内导入依赖：`cli`, `config`, `map_config`, `models`, `route_persistence`, `tiling`。
- 直接导入本模块者：`desktop_client`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L96
ProgressCallback = Callable[[str, int, str], None]

# _ConsoleHandler — src/h3_offroad_planner/web_console.py:115
class _ConsoleHandler(BaseHTTPRequestHandler):
    'Serve static WebGIS content, bootstrap metadata, and delivery operations.'
    ...
```

```text
# L67 <module>
'distance' => 'shortest distance'
'trafficability' => 'lowest trafficability penalty'
'travel_cost' => 'minimum travel cost'
'slope' => 'lowest slope exposure'
'roughness' => 'lowest terrain roughness'

# L378 serialize_webgis_result
'delivery' => result
'fine_grid_geojson' => fine_grid
'parent_grid_geojson' => parent_grid
'route_geojson' => route_geojson
'route_evaluation' => evaluation
'candidate_routes' => candidate_routes

# L473 _serialize_route_plan
'delivery' => result
'fine_grid_geojson' => fine_grid
'parent_grid_geojson' => parent_grid
'route_geojson' => recommended_geojson
'route_evaluation' => recommended_evaluation
'candidate_routes' => candidate_routes
'route_status' => { 'warnings' => plan.get('warnings', []); 'environment_snapshot' => cast(dict[str, object], plan.get('aggregation_stats', {})).get('environment_snapshot', {}); 'environment_pressure_basis' => cast(dict[str, object], plan.get('aggregation_stats', {})).get('environment_pressure_basis') }

# L533 _parent_record_feature
'h3index' => parent_h3
'parent_h3' => parent_h3
'resolution' => 'parent'
'status' => status
'selectable' => status in {'completed', 'skipped'} and isinstance(record.get('path'), str) and bool(cast(str, record.get('path')))
'cell_count' => _record_non_negative_int(record, 'cells_count')
'error' => record.get('error') if isinstance(record.get('error'), str) else None

# L547 _parent_record_feature
'type' => 'Feature'
'geometry' => _h3_geometry(parent_h3)
'properties' => properties

# L580 _cell_feature
'type' => 'Feature'
'geometry' => _h3_geometry(cell_id)
'properties' => properties

# L589 _parent_feature
'h3index' => parent_id
'cell_count' => len(values)
'score' => sum(scores) / len(scores) if scores else None
'resolution' => 'parent'

# L595 _parent_feature
'type' => 'Feature'
'geometry' => _h3_geometry(parent_id)
'properties' => properties

# L628 _candidate_evaluation
'quality_score' => score
'distance_m' => distance
'estimated_time_s' => distance / speed_mps if speed_mps > 0.0 else None
'landcover_distance_share' => shares
'min_turn_radius_m' => vehicle.min_turn_radius_m
'candidate_index' => candidate_index
'selection_reason' => _selection_reason(manifest, candidate_index)
'replanned' => manifest.get('replanned', False)

# L845 _decode_web_request
'operation' => operation
'payload' => payload

# L922 _bootstrap_payload
'map_provider' => MAP_PROVIDER_CONFIG.provider
'map_layer_type' => MAP_PROVIDER_CONFIG.layer_type
'map_token_source' => MAP_PROVIDER_CONFIG.token_source
'tianditu_key' => TIANDITU_KEY
'default_request_yaml' => DEFAULT_DELIVERY_PATH.read_text(encoding='utf-8')
'data_catalog' => []
'theme_attributes' => list(THEME_ATTRIBUTES)
'max_web_grid_features' => MAX_WEB_GRID_FEATURES

# L1049 _h3_geometry
'type' => 'Polygon'
'coordinates' => [coordinates]

# L1053 _collection
'type' => 'FeatureCollection'
'features' => [] if features is None else features

# L190 _ConsoleHandler._write_event
'type' => event_type
'module' => module
'percent' => percent
'level' => level
'message' => message

# L275 _run_replan_operation
'replan_result' => result
'active_route_geojson' => cast(dict[str, object], active)

# L342 serialize_webgis_result
'delivery' => result
'fine_grid_geojson' => _collection()
'parent_grid_geojson' => _collection()
'route_geojson' => render_route
'route_evaluation' => evaluation
'candidate_routes' => []

# L685 _replanned_candidate_route
'candidate_index' => selected_index
'geojson' => active_geojson
'objectives' => {  }
'total_cost' => None
'evaluation' => evaluation
'is_selected' => True
'replanned' => True

# L738 _candidate_geojson
'type' => 'Point'
'coordinates' => coordinates[0]

# L740 _candidate_geojson
'type' => 'LineString'
'coordinates' => coordinates

# L461 _serialize_route_plan
'candidate_index' => index
'candidate_id' => candidate.get('candidate_id')
'roles' => roles
'is_recommended' => candidate.get('is_recommended', False)
'geojson' => render_geojson
'evaluation' => evaluation

# L659 _candidate_routes
'candidate_index' => index
'geojson' => geojson
'objectives' => objectives
'total_cost' => candidate.get('total_cost')
'evaluation' => evaluation
'is_selected' => index == selected_index
'replanned' => False

# L744 _candidate_geojson
'type' => 'Feature'
'properties' => { 'candidate_index' => candidate_index; 'objectives' => objectives; 'total_cost' => total_cost }
'geometry' => geometry

# L893 _write_study_area
'type' => 'FeatureCollection'
'features' => [{'type': 'Feature', 'properties': {}, 'geometry': value.get('geometry', value)}]

# L958 _catalog
'path' => str(candidate)
'kind' => kind
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
import sys
import uuid
from collections.abc import Callable
from contextlib import suppress
from email.message import Message
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse
import h3
import pandas as pd
import yaml
from shapely.geometry import shape
from h3_offroad_planner.cli import run_delivery_payload, run_replan_payload, run_route_payload, run_select_payload, run_tile_payload
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.map_config import MAP_PROVIDER_CONFIG, TIANDITU_KEY, TIANDITU_LAYER_TYPE
from h3_offroad_planner.models import ConfigError, GISInputError, GridBuildError, PlanningFailedError, PlanningInputError
from h3_offroad_planner.route_persistence import load_active_route_feature
from h3_offroad_planner.tiling import TILE_CACHE_KIND

# run_web_console — L99
def run_web_console(host: str=DEFAULT_HOST, port: int=DEFAULT_PORT) -> None:
    """Serve the loopback WebGIS console until process interruption."""
    ...

# create_web_console — L106
def create_web_console(host: str=DEFAULT_HOST, port: int=DEFAULT_PORT) -> ThreadingHTTPServer:
    """Create a loopback-only HTTP server for the WebGIS console."""
    ...

# _ConsoleHandler — L115
class _ConsoleHandler(BaseHTTPRequestHandler):
    """Serve static WebGIS content, bootstrap metadata, and delivery operations."""

    def do_GET(self) -> None:
        """Handle page and bootstrap requests."""
        ...

    def do_POST(self) -> None:
        """Handle compatible JSON and incremental NDJSON delivery requests."""
        ...

    def _run_state_operation(self, body: bytes, operation: Callable[[dict[str, object]], dict[str, object]]) -> None:
        ...

    def _run_compatible(self, body: bytes) -> None:
        ...

    def _run_stream(self, body: bytes) -> None:
        ...

    def _progress(self, module: str, percent: int, message: str) -> None:
        ...

    def _write_event(self, event_type: str, module: str, percent: int, level: str, message: str, payload: dict[str, object] | None=None) -> None:
        ...

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default request logging; structured events are shown in the UI."""
        ...

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        ...

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        ...

# _run_operation — L220
def _run_operation(request: dict[str, object], progress: ProgressCallback | None) -> dict[str, object]:
    ...

# _run_replan_operation — L264
def _run_replan_operation(payload: dict[str, object]) -> dict[str, object]:
    """Execute a persisted replan and return its active geometry for Web rendering."""
    ...

# _set_route_tile_manifest — L279
def _set_route_tile_manifest(payload: dict[str, object]) -> None:
    """Use the configured tile-cache manifest for a route-only WebGIS action."""
    ...

# _apply_map_selection — L304
def _apply_map_selection(payload: dict[str, object], request: dict[str, object]) -> None:
    ...

# serialize_webgis_result — L325
def serialize_webgis_result(result: dict[str, object], *, parent_only: bool=False) -> dict[str, object]:
    """Serialize existing tile and route artifacts for Web or QWebEngine display."""
    ...

# serialize_tile_grid — L388
def serialize_tile_grid(result: dict[str, object], parent_h3: str) -> dict[str, object]:
    """Load one manifest-authorized parent tile for desktop drill-down display."""
    ...

# _serialize_route_plan — L439
def _serialize_route_plan(result: dict[str, object], plan: dict[str, object], fine_grid: dict[str, object], parent_grid: dict[str, object]) -> dict[str, object]:
    ...

# _grid_layers — L492
def _grid_layers(manifest: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, dict[str, object]]]:
    ...

# _desktop_parent_grid — L515
def _desktop_parent_grid(manifest: dict[str, object]) -> dict[str, object]:
    """Build a lightweight parent overview without reading any tile Parquet."""
    ...

# _parent_record_feature — L526
def _parent_record_feature(record: dict[str, object]) -> dict[str, object]:
    ...

# _parent_statistic — L550
def _parent_statistic(statistics: object, theme: str) -> float | None:
    ...

# _cell_feature — L563
def _cell_feature(cell_id: str, row: dict[str, object]) -> dict[str, object]:
    ...

# _parent_feature — L583
def _parent_feature(parent_id: str, values: list[dict[str, object]]) -> dict[str, object]:
    ...

# _route_evaluation — L598
def _route_evaluation(manifest: dict[str, object], rows: dict[str, dict[str, object]]) -> dict[str, object] | None:
    """Return evaluation only for a complete route manifest."""
    ...

# _candidate_evaluation — L609
def _candidate_evaluation(manifest: dict[str, object], rows: dict[str, dict[str, object]], cells: list[str], candidate_index: int) -> dict[str, object] | None:
    """Evaluate one rendered route using the same tile rows as the Web map."""
    ...

# _candidate_routes — L640
def _candidate_routes(manifest: dict[str, object], rows: dict[str, dict[str, object]], active_geojson: dict[str, object] | None, active_evaluation: dict[str, object] | None) -> list[dict[str, object]]:
    """Build independently selectable route entries without changing legacy outputs."""
    ...

# _replanned_candidate_route — L672
def _replanned_candidate_route(selected_index: int, active_geojson: dict[str, object] | None, active_evaluation: dict[str, object] | None) -> list[dict[str, object]]:
    """Expose only the active D* Lite route so stale Pareto values are never displayed."""
    ...

# _manifest_candidates — L697
def _manifest_candidates(manifest: dict[str, object]) -> list[dict[str, object]]:
    ...

# _candidate_cells — L704
def _candidate_cells(candidate: dict[str, object]) -> list[str]:
    ...

# _candidate_objectives — L711
def _candidate_objectives(candidate: dict[str, object]) -> dict[str, float]:
    ...

# _candidate_geojson — L726
def _candidate_geojson(cells: list[str], rows: dict[str, dict[str, object]], candidate_index: int, objectives: dict[str, float], total_cost: object) -> dict[str, object] | None:
    """Build WGS84 GeoJSON for one candidate when every cell has loaded map coordinates."""
    ...

# _selected_candidate_index — L757
def _selected_candidate_index(manifest: dict[str, object]) -> int:
    ...

# _selection_reason — L762
def _selection_reason(manifest: dict[str, object], candidate_index: int) -> list[str]:
    """Explain one candidate relative to the minimum requested old objectives."""
    ...

# _requested_objectives — L784
def _requested_objectives(manifest: dict[str, object], objectives: dict[str, float]) -> list[str]:
    ...

# _route_distance_and_landcover — L797
def _route_distance_and_landcover(cells: list[str], rows: dict[str, dict[str, object]]) -> tuple[float, dict[str, float]]:
    ...

# _haversine — L812
def _haversine(first: dict[str, object], second: dict[str, object]) -> float:
    ...

# _numeric — L824
def _numeric(row: dict[str, object], key: str) -> float:
    """Read one finite numeric map attribute for route evaluation."""
    ...

# _attach_evaluation — L832
def _attach_evaluation(geojson: dict[str, object], evaluation: dict[str, object]) -> None:
    ...

# _decode_web_request — L839
def _decode_web_request(body: bytes) -> dict[str, object]:
    ...

# _decode_envelope — L852
def _decode_envelope(body: bytes) -> dict[str, object]:
    ...

# _decode_json_mapping — L862
def _decode_json_mapping(body: bytes) -> dict[str, object]:
    ...

# _load_request_yaml — L872
def _load_request_yaml(envelope: dict[str, object]) -> dict[str, object]:
    ...

# _write_study_area — L879
def _write_study_area(value: object) -> str:
    ...

# _point_lat_lng — L905
def _point_lat_lng(value: object, role: str) -> tuple[float, float]:
    ...

# _bootstrap_payload — L921
def _bootstrap_payload() -> dict[str, object]:
    ...

# _catalog_query — L934
def _catalog_query(query: str) -> list[dict[str, str]]:
    """Validate a lazy data-catalog query and return its cached controlled files."""
    ...

# _catalog — L946
@lru_cache(maxsize=len(CATALOG_KINDS))
def _catalog(kind: str) -> tuple[dict[str, str], ...]:
    """Discover one bounded, controlled data category once per server lifetime."""
    ...

# _catalog_kind — L964
def _catalog_kind(path: Path) -> str:
    ...

# _tile_manifest — L981
def _tile_manifest(result: dict[str, object]) -> dict[str, object] | None:
    ...

# _tile_records — L995
def _tile_records(manifest: dict[str, object]) -> list[dict[str, object]]:
    ...

# _all_tile_records — L1004
def _all_tile_records(manifest: dict[str, object]) -> list[dict[str, object]]:
    ...

# _record_non_negative_int — L1013
def _record_non_negative_int(record: dict[str, object], key: str) -> int:
    ...

# _manifest_tile_path — L1021
def _manifest_tile_path(manifest: dict[str, object], record: dict[str, object], parent_h3: str) -> Path:
    ...

# _route_geojson — L1036
def _route_geojson(route_manifest: dict[str, object]) -> dict[str, object]:
    ...

# _h3_geometry — L1046
def _h3_geometry(cell_id: str) -> dict[str, object]:
    ...

# _collection — L1052
def _collection(features: list[dict[str, object]] | None=None) -> dict[str, object]:
    ...

# _route_feature_collection — L1056
def _route_feature_collection(geojson: dict[str, object]) -> dict[str, object]:
    """Normalize one persisted route at the WebGIS display boundary."""
    ...

# _json_scalar — L1066
def _json_scalar(value: object) -> object:
    ...

# _mapping — L1072
def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    ...

# _report — L1079
def _report(progress: ProgressCallback | None, module: str, percent: int, message: str) -> None:
    ...

# _content_length — L1084
def _content_length(headers: Message) -> int:
    ...

# _read_index — L1095
def _read_index() -> bytes:
    ...

# _error_status — L1111
def _error_status(exc: Exception) -> HTTPStatus:
    ...
```
