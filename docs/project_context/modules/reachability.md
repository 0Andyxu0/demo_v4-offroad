# 模块参考：reachability

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/reachability.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`15a6a5091f737c619fab84b462bab5e5ad2110f0e44f0996736c26830cf68783`；类 2 个，函数/方法 6 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`。
- 直接导入本模块者：`route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L19
ProgressCallback = Callable[[str, int, str], None]

# ReachabilityDiagnosis — src/h3_offroad_planner/reachability.py:54
@dataclass(frozen=True)
class ReachabilityDiagnosis:
    'Detailed structural diagnosis of reachability and barrier boundaries.'
    reachable: bool
    visited_cells: frozenset[str] = frozenset()
    boundary_blockage_cells: frozenset[str] = frozenset()
    bottleneck_parents: tuple[str, ...] = ()
    barrier_reasons: tuple[str, ...] = ()
    component_size: int = 0
    disconnect_reason: str = ''
    ...

# ReachabilityDisconnectionError — src/h3_offroad_planner/reachability.py:66
class ReachabilityDisconnectionError(PlanningFailedError):
    'Raised when reachability pre-check fails, carrying diagnostic barrier details.'
    # self.diagnosis: 未注解; L75; initial=diagnosis
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
import h3
from h3_offroad_planner.factor_model import FactorEvaluation
from h3_offroad_planner.models import H3Graph, PlanningFailedError

# _haversine_m — L22
def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    ...

# _is_valid_h3 — L32
def _is_valid_h3(cell: str | None) -> bool:
    ...

# _parent_of_cell — L41
def _parent_of_cell(cell: str, cell_obj: object | None, res_coarse: int) -> str:
    ...

# ReachabilityDiagnosis — L54
@dataclass(frozen=True)
class ReachabilityDiagnosis:
    """Detailed structural diagnosis of reachability and barrier boundaries."""

# ReachabilityDisconnectionError — L66
class ReachabilityDisconnectionError(PlanningFailedError):
    """Raised when reachability pre-check fails, carrying diagnostic barrier details."""

    def __init__(self, message: str='Endpoints disconnected', diagnosis: ReachabilityDiagnosis | None=None) -> None:
        ...

# diagnose_route_reachability — L78
def diagnose_route_reachability(graph: H3Graph, evaluation: FactorEvaluation, start: str, goal: str, res_coarse: int | None=None) -> ReachabilityDiagnosis:
    """Analyze reachability between start and goal and diagnose bottleneck barriers."""
    ...

# check_route_reachability — L402
def check_route_reachability(graph: H3Graph, evaluation: FactorEvaluation, start: str, goal: str, progress: ProgressCallback | None=None, res_coarse: int | None=None) -> ReachabilityDiagnosis:
    """Pre-flight reachability gate.

    Verifies that the start and goal endpoints are physically passable and mutually
    reachable via directed passable edges before entering heavy Pareto search.

    If disconnected, raises ReachabilityDisconnectionError carrying detailed
    barrier and bottleneck parent diagnosis for targeted repair.
    """
    ...
```
