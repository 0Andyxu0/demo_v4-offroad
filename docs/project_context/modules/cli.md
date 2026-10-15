# 模块参考：cli

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/cli.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`ad72589c883d61066359913ce6616984e64848d665ebca04eadfe9bfe418dbde`；类 0 个，函数/方法 32 个（含嵌套定义）。
- 项目内导入依赖：`config`, `factor_model`, `models`, `preprocessing.hydrology`, `replanning`, `route_models`, `route_persistence`, `route_planning`, `tiling`。
- 直接导入本模块者：`__main__`, `desktop_client`, `desktop_project`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L238
ProgressCallback = Callable[[str, int, str], None]
```

```python
# L46
EXIT_REQUEST_ERROR: int = 2
# L47
HYDROLOGY_FIELDS: frozenset[str] = frozenset({'analysis_resolution_m', 'backend', 'dem_path', 'flow_method', 'grass_executable', 'mapping_t0', 'mapping_t1', 'output_dir', 'upstream_complete', 'version'})
# L61
TILE_BUILD_FIELDS: frozenset[str] = frozenset({'continue_on_error', 'dem_path', 'landcover_path', 'max_cells_per_tile', 'max_tiles', 'output_dir', 'overwrite', 'res_fine', 'road_path', 'roi_layer_path', 'sampling_mode', 'soil_catalog_path', 'soil_path', 'twi_path', 'drainage_path', 'drainage_validity_path', 'drainage_boundary_path', 'tile_res', 'vehicle_path', 'factor_model_path', 'static_planning_path'})
# L86
ROUTE_FIELDS: frozenset[str] = frozenset({'corridor_buffer_deg', 'candidate_index', 'blocked_cells', 'endpoint_layer_path', 'goal_lat', 'goal_lng', 'input_mode', 'max_estimated_cells', 'max_snap_distance_m', 'output_dir', 'parquet_path', 'planner_config_path', 'res_coarse', 'res_fine', 'roi_layer_path', 'roi_strategy', 'start_lat', 'start_lng', 'theme_attributes', 'objectives', 'vehicle_path', 'factor_model_path', 'mission_profile', 'max_candidate_paths', 'candidate_limit', 'penalty_factor', 'static_planning_path', 'environment_snapshot_path'})
# L118
SELECT_FIELDS: frozenset[str] = frozenset({'candidate_id', 'expected_selection_version', 'plan_path', 'role'})
# L121
REPLAN_FIELDS: frozenset[str] = frozenset({'blockage_observations', 'current_h3', 'current_lat', 'current_lng', 'now_epoch_s', 'policy', 'selection_path', 'snap_distance_m'})
# L637
_REQUEST_ERRORS = (ConfigError, FileNotFoundError, GISInputError, GridBuildError, OSError, PlanningFailedError, PlanningInputError, ValueError)
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import argparse
import inspect
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast
import yaml
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import evaluate_factor_model, load_factor_model
from h3_offroad_planner.models import ConfigError, GISInputError, GridBuildError, PlanningFailedError, PlanningInputError, RouteRequest, TileBuildRequest
from h3_offroad_planner.preprocessing.hydrology import HydrologyConfig, preprocess_hydrology
from h3_offroad_planner.replanning import ReplanPolicy, replan_route
from h3_offroad_planner.route_models import BlockageRecord, ReplanRequest, ReplanResult
from h3_offroad_planner.route_persistence import load_route_graph_snapshot, select_route
from h3_offroad_planner.route_planning import run_route_plan
from h3_offroad_planner.tiling import TILE_MANIFEST_NAME, build_h3_tile_cache

# main — L135
def main(argv: Sequence[str] | None=None) -> int:
    """Run one GIS build, route, or combined delivery request.

    Args:
        argv: Optional command arguments excluding the executable name. Unit: none.
            When omitted, process command arguments are used.

    Returns:
        Process status code: zero for a completed request and two for a validated
        input, GIS, construction, or planning error.
    """
    ...

# _build_parser — L156
def _build_parser() -> argparse.ArgumentParser:
    """Create the delivery CLI parser."""
    ...

# _console_progress — L173
def _console_progress(module: str, percent: int, message: str) -> None:
    """Stream real-time CLI progress to stderr without polluting JSON stdout."""
    ...

# _call_with_progress — L178
def _call_with_progress(func: Callable[..., object], request: object, progress: ProgressCallback | None=None, **kwargs: object) -> object:
    ...

# _normalize_route_payload — L195
def _normalize_route_payload(payload: dict[str, object]) -> dict[str, object]:
    """Extract nested route configuration from delivery request if present."""
    ...

# _dispatch — L208
def _dispatch(command: str, request_path: Path) -> dict[str, object]:
    """Dispatch one validated CLI command from a YAML request file."""
    ...

# run_hydrology_payload — L241
def run_hydrology_payload(payload: dict[str, object]) -> dict[str, object]:
    """Run the configured offline GRASS hydrology preprocessing request."""
    ...

# run_tile_payload — L262
def run_tile_payload(payload: dict[str, object], progress: ProgressCallback | None=None) -> dict[str, object]:
    """Build one tile-cache request decoded from a YAML mapping."""
    ...

# run_route_payload — L273
def run_route_payload(payload: dict[str, object], progress: ProgressCallback | None=None) -> dict[str, object]:
    """Plan one route request decoded from a YAML mapping."""
    ...

# run_select_payload — L283
def run_select_payload(payload: dict[str, object]) -> dict[str, object]:
    """Explicitly activate one persisted RoutePlan candidate."""
    ...

# run_replan_payload — L300
def run_replan_payload(payload: dict[str, object]) -> dict[str, object]:
    """Restore persisted graph/config state and execute one D* Lite product replan."""
    ...

# run_delivery_payload — L323
def run_delivery_payload(payload: dict[str, object], progress: ProgressCallback | None=None, *, export_gpkg: bool=False) -> dict[str, object]:
    """Build a tile cache and route through its manifest in one delivery request."""
    ...

# _report_progress — L362
def _report_progress(progress: ProgressCallback | None, module: str, percent: int, message: str) -> None:
    """Publish one bounded progress event when a caller requested it."""
    ...

# _load_yaml_mapping — L373
def _load_yaml_mapping(path: Path) -> dict[str, object]:
    """Load a non-empty YAML mapping from a readable filesystem path."""
    ...

# _required_mapping — L387
def _required_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    """Return a required nested request mapping or raise a configuration error."""
    ...

# _tile_request — L395
def _tile_request(payload: dict[str, object]) -> TileBuildRequest:
    """Construct a validated tile-build request from decoded YAML fields."""
    ...

# _route_request — L426
def _route_request(payload: dict[str, object]) -> RouteRequest:
    """Construct a validated route request from decoded YAML fields."""
    ...

# _reject_unknown_fields — L466
def _reject_unknown_fields(payload: dict[str, object], allowed: frozenset[str]) -> None:
    """Reject YAML fields not owned by the target request contract."""
    ...

# _required_string — L473
def _required_string(payload: dict[str, object], key: str) -> str:
    """Return a required string field from a decoded request mapping."""
    ...

# _optional_string — L481
def _optional_string(payload: dict[str, object], key: str) -> str | None:
    """Return an optional string field, preserving an explicit null."""
    ...

# _integer_or_default — L491
def _integer_or_default(payload: dict[str, object], key: str, default: int) -> int:
    """Return an integer field or its contract default."""
    ...

# _optional_float — L501
def _optional_float(payload: dict[str, object], key: str) -> float | None:
    """Return an optional numeric field normalized to float."""
    ...

# _float_or_default — L508
def _float_or_default(payload: dict[str, object], key: str, default: float) -> float:
    """Return a numeric field normalized to float or its contract default."""
    ...

# _number_as_float — L515
def _number_as_float(value: object, key: str) -> float:
    """Validate one YAML number without accepting boolean values."""
    ...

# _required_float — L522
def _required_float(payload: dict[str, object], key: str) -> float:
    ...

# _bool_or_default — L528
def _bool_or_default(payload: dict[str, object], key: str, default: bool) -> bool:
    """Return a boolean field or its contract default."""
    ...

# _optional_bool — L538
def _optional_bool(payload: dict[str, object], key: str) -> bool | None:
    ...

# _string_or_default — L547
def _string_or_default(payload: dict[str, object], key: str, default: str) -> str:
    """Return a string field or its contract default."""
    ...

# _string_list_or_default — L557
def _string_list_or_default(payload: dict[str, object], key: str, default: list[str]) -> list[str]:
    """Return a list of strings or a new copy of its contract default."""
    ...

# _blockage_records — L567
def _blockage_records(payload: dict[str, object], now_epoch_s: float) -> tuple[BlockageRecord, ...]:
    ...

# _replan_policy — L599
def _replan_policy(payload: dict[str, object]) -> ReplanPolicy:
    ...

# _replan_result_payload — L622
def _replan_result_payload(typed: ReplanResult) -> dict[str, object]:
    ...
```
