# 模块参考：replanning

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/replanning.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`b7b2609890532ef1a34b374fb03771d1ca8a725c9ff5c4ff69ea5474b31b392e`；类 2 个，函数/方法 30 个（含嵌套定义）。
- 项目内导入依赖：`candidate_aggregation`, `config`, `dynamics.trajectory_geometry`, `factor_model`, `models`, `planners.deterministic_pareto`, `planners.dstar_lite`, `portsmap`, `route_models`, `route_persistence`。
- 直接导入本模块者：`cli`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# ReplanPolicy — src/h3_offroad_planner/replanning.py:49
@dataclass(frozen=True)
class ReplanPolicy:
    'Explicit bounded confirmation, timing, and fallback-loop controls.'
    confirmation_threshold: int = 2
    debounce_window_s: float = 1.0
    cooldown_s: float = 2.0
    recent_failed_corridor_ttl_s: float = 120.0
    global_fallback_window_s: float = 300.0
    max_global_fallbacks: int = 3
    ...

# _FrozenRoleCost — src/h3_offroad_planner/replanning.py:72
class _FrozenRoleCost:
    'Read-only role-specific edge-cost adapter consumed by D* Lite.'
    # self.evaluation: 未注解; L81; initial=evaluation
    # self.role: 未注解; L82; initial=role
    # self.passability_threshold: 未注解; L83; initial=passability_threshold
    ...
```

校验 `ReplanPolicy.__post_init__`：

- `L60 if self.confirmation_threshold <= 0 or self.max_global_fallbacks <= 0` → `raise ValueError('replan count thresholds must be positive.')`
- `L68 if any((not isfinite(value) or value < 0.0 for value in values))` → `raise ValueError('replan time windows must be finite and non-negative.')`

```text
# L460 _persist_replan
'schema_version' => 1
'event_epoch_s' => now_epoch_s
'plan_id' => result.plan_id
'candidate_id' => result.candidate_id
'algorithm' => result.algorithm
'status' => result.status
'replan_version' => result.replan_version
'old_path_hash' => result.old_path_hash
'new_path_hash' => result.new_path_hash
'metrics_before' => result.metrics_before.to_dict()
'metrics_after' => None if result.metrics_after is None else result.metrics_after.to_dict()
'warnings' => list(result.warnings)
'blockages' => [asdict(record) for record in ordered]
'failed_corridor_cells' => sorted(failed_corridor)
'failed_corridor_expires_at_epoch_s' => now_epoch_s + policy.recent_failed_corridor_ttl_s if failed_corridor else None
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import atan2, cos, inf, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import cast
from h3_offroad_planner.candidate_aggregation import CandidateAggregator, select_robust_candidates
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.dynamics.trajectory_geometry import build_and_validate_trajectory
from h3_offroad_planner.factor_model import FactorEvaluation, StaticPlanningConfig, canonical_hash, evaluate_path_metrics, load_static_planning_config
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError
from h3_offroad_planner.models import Path as PlannerPath
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.planners.dstar_lite import DStarLiteReplanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.route_models import BlockageRecord, ReplanRequest, ReplanResult, RouteSelection
from h3_offroad_planner.route_persistence import atomic_write_json, load_route_plan, load_route_selection, write_active_route_state

# ReplanPolicy — L49
@dataclass(frozen=True)
class ReplanPolicy:
    """Explicit bounded confirmation, timing, and fallback-loop controls."""

    def __post_init__(self) -> None:
        ...

# _FrozenRoleCost — L72
class _FrozenRoleCost:
    """Read-only role-specific edge-cost adapter consumed by D* Lite."""

    def __init__(self, evaluation: FactorEvaluation, role: str, passability_threshold: float) -> None:
        ...

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Return selected-role movement cost without recalculating any factor."""
        ...

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Use a universally admissible zero estimate across heterogeneous role units."""
        ...

# replan_route — L111
def replan_route(request: ReplanRequest, graph: H3Graph, evaluation: FactorEvaluation, policy: ReplanPolicy | None=None) -> ReplanResult:
    """Apply blockage lifecycle, repair locally, and perform bounded global fallback."""
    ...

# _global_fallback — L229
def _global_fallback(selection: RouteSelection, graph: H3Graph, evaluation: FactorEvaluation, confirmed: set[str], history: list[dict[str, object]], now_epoch_s: float, policy: ReplanPolicy, output_dir: str, current: str, failed_corridor: set[str]) -> tuple[RouteSelection, ReplanResult]:
    ...

# _load_replan_static_config — L327
def _load_replan_static_config(output_dir: str) -> StaticPlanningConfig:
    ...

# _replanned_trajectory — L334
def _replanned_trajectory(path: tuple[str, ...], selection: RouteSelection, graph: H3Graph, evaluation: FactorEvaluation, output_dir: str) -> dict[str, object]:
    ...

# _merge_blockages — L360
def _merge_blockages(previous: dict[str, BlockageRecord], observations: tuple[BlockageRecord, ...], now_epoch_s: float, policy: ReplanPolicy) -> dict[str, BlockageRecord]:
    ...

# _unchanged_warning — L393
def _unchanged_warning(history: list[dict[str, object]], previous_confirmed: set[str], confirmed: set[str], now_epoch_s: float, policy: ReplanPolicy) -> str | None:
    ...

# _unchanged_result — L410
def _unchanged_result(selection: RouteSelection, warning: str) -> ReplanResult:
    ...

# _result — L426
def _result(before: RouteSelection, after: RouteSelection, algorithm: str, warnings: tuple[str, ...]=(), has_new_path: bool=True) -> ReplanResult:
    ...

# _persist_replan — L447
def _persist_replan(output_dir: str, graph: H3Graph, selection: RouteSelection, result: ReplanResult, blockages: Mapping[str, BlockageRecord], now_epoch_s: float, failed_corridor: set[str], policy: ReplanPolicy) -> None:
    ...

# _overlay_graph — L482
def _overlay_graph(graph: H3Graph) -> H3Graph:
    ...

# _resolve_current — L495
def _resolve_current(request: ReplanRequest, graph: H3Graph, evaluation: FactorEvaluation) -> str:
    ...

# _validate_hashes — L521
def _validate_hashes(selection: RouteSelection, evaluation: FactorEvaluation) -> None:
    ...

# _load_history — L532
def _load_history(path: Path) -> list[dict[str, object]]:
    ...

# _latest_blockages — L549
def _latest_blockages(history: list[dict[str, object]]) -> dict[str, BlockageRecord]:
    ...

# _blockage_from_mapping — L564
def _blockage_from_mapping(payload: Mapping[str, object]) -> BlockageRecord:
    ...

# _recent_global_fallbacks — L581
def _recent_global_fallbacks(history: list[dict[str, object]], now_epoch_s: float, window_s: float) -> int:
    ...

# _recent_failed_cells — L593
def _recent_failed_cells(history: list[dict[str, object]], now_epoch_s: float, ttl_s: float) -> set[str]:
    ...

# _latest_history_epoch — L613
def _latest_history_epoch(history: list[dict[str, object]]) -> float | None:
    ...

# _event_epoch — L617
def _event_epoch(event: Mapping[str, object]) -> float:
    ...

# _append_history_atomic — L621
def _append_history_atomic(path: Path, event: dict[str, object]) -> None:
    ...

# _haversine_m — L631
def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    ...

# _string — L642
def _string(payload: Mapping[str, object], key: str) -> str:
    ...

# _integer — L649
def _integer(payload: Mapping[str, object], key: str) -> int:
    ...

# _boolean — L656
def _boolean(payload: Mapping[str, object], key: str) -> bool:
    ...

# _number — L663
def _number(payload: Mapping[str, object], key: str) -> float:
    ...

# _number_value — L669
def _number_value(value: object, key: str) -> float:
    ...
```
