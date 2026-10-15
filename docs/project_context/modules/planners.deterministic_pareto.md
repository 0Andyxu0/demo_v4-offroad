# 模块参考：planners.deterministic_pareto

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/planners/deterministic_pareto.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`becf662bc9d29b79c7f597c30a1bcb2058f888926c0ab69ef625b407d9869daa`；类 2 个，函数/方法 12 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`, `portsmap`。
- 直接导入本模块者：`candidate_aggregation`, `planners`, `replanning`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L16
ProgressCallback = Callable[[str, int, str], None]

# GeneratedPath — src/h3_offroad_planner/planners/deterministic_pareto.py:33
@dataclass(frozen=True)
class GeneratedPath:
    'One unique raw path with exact original-unit metrics and its search profile.'
    h3_path: tuple[str, ...]
    metrics: PathMetrics
    generation_profile: str
    scalar_cost: float
    ...

# DeterministicParetoPlanner — src/h3_offroad_planner/planners/deterministic_pareto.py:63
class DeterministicParetoPlanner:
    'Generate bounded alternatives without genetic populations or generations.'
    # self.context: 未注解; L85; initial=context
    # self.max_paths: 未注解; L86; initial=max_paths
    # self.candidate_limit: 未注解; L87; initial=candidate_limit
    # self.penalty_factor: 未注解; L88; initial=penalty_factor
    # self.include_composite: 未注解; L89; initial=include_composite
    # self.attempts_per_profile: 未注解; L90; initial=max(1, min(max_paths, 3)) if attempts_per_profile is None else attempts_per_profile
    # self.profile_search_count: 未注解; L95; initial=0
    # self.environment_pressures: 未注解; L100; initial=environment_pressures
    ...
```

校验 `GeneratedPath.__post_init__`：

- `L42 if not self.h3_path or not self.generation_profile` → `raise ValueError('generated path and profile must be non-empty.')`
- `L44 if not isfinite(self.scalar_cost) or self.scalar_cost < 0.0` → `raise ValueError('generated scalar cost must be finite and non-negative.')`

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from math import inf, isfinite
from statistics import median
from h3_offroad_planner.factor_model import FactorEvaluation, PathMetrics
from h3_offroad_planner.models import PlanningFailedError
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile

# GeneratedPath — L33
@dataclass(frozen=True)
class GeneratedPath:
    """One unique raw path with exact original-unit metrics and its search profile."""

    def __post_init__(self) -> None:
        ...

    @property
    def objectives(self) -> dict[str, float]:
        """Return the five raw-unit values used for route-level Pareto comparison."""
        ...

# DeterministicParetoPlanner — L63
class DeterministicParetoPlanner:
    """Generate bounded alternatives without genetic populations or generations."""

    def __init__(self, context: PortsMapSearchContext, max_paths: int=DEFAULT_MAX_PATHS, candidate_limit: int=DEFAULT_CANDIDATE_LIMIT, penalty_factor: float=DEFAULT_PENALTY_FACTOR, include_composite: bool=False, environment_pressures: tuple[float, ...]=(), attempts_per_profile: int | None=None) -> None:
        """Initialize deterministic profile and reuse-penalty candidate generation."""
        ...

    def plan(self, start: str, goal: str, blocked: frozenset[str]=frozenset(), progress: ProgressCallback | None=None) -> list[GeneratedPath]:
        """Return at most 24 exact unique raw candidates including a widest anchor."""
        ...

# _robust_scales — L167
def _robust_scales(evaluation: FactorEvaluation) -> dict[str, float]:
    ...

# _fixed_profiles — L188
def _fixed_profiles(scales: dict[str, float], include_composite: bool=False, environment_pressures: tuple[float, ...]=()) -> list[ScalarProfile]:
    ...

# _add_reuse_penalties — L233
def _add_reuse_penalties(penalties: dict[str, int], path: tuple[str, ...]) -> None:
    ...

# _bounded_candidates — L238
def _bounded_candidates(candidates: list[GeneratedPath], limit: int) -> list[GeneratedPath]:
    ...

# _non_dominated_fronts — L256
def _non_dominated_fronts(candidates: list[GeneratedPath]) -> list[list[GeneratedPath]]:
    ...

# _dominates — L271
def _dominates(first: GeneratedPath, second: GeneratedPath) -> bool:
    ...

# _crowding_order — L279
def _crowding_order(paths: list[GeneratedPath]) -> list[GeneratedPath]:
    ...

# _candidate_tie_key — L297
def _candidate_tie_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    ...
```
