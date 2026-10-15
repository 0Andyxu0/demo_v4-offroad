# 模块参考：planners.dstar_lite

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/planners/dstar_lite.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`18928ad900f112526f608a2d2ff4c81b309d313b67669f80bd4c9c1a81e25f65`；类 2 个，函数/方法 18 个（含嵌套定义）。
- 项目内导入依赖：`models`, `planners.interfaces`。
- 直接导入本模块者：`planners`, `planners.factory`, `replanning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L14
Key = tuple[float, float]

# MovementCost — src/h3_offroad_planner/planners/dstar_lite.py:17
class MovementCost(Protocol):
    'Minimal directed movement-cost interface required by D* Lite.'
    ...

# DStarLiteReplanner — src/h3_offroad_planner/planners/dstar_lite.py:27
class DStarLiteReplanner(LocalReplanner):
    'Incrementally repair a reverse shortest-path tree after cell blockages.'
    # self.cost_function: 未注解; L32; initial=cost_function
    _g: dict[str, float]  # instance; L33; initial={}
    _rhs: dict[str, float]  # instance; L34; initial={}
    _queue: list[tuple[float, float, str]]  # instance; L35; initial=[]
    _queued_keys: dict[str, Key]  # instance; L36; initial={}
    _start: str | None  # instance; L37; initial=None
    _goal: str | None  # instance; L38; initial=None
    _km: float  # instance; L39; initial=0.0
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from heapq import heappop, heappush
from math import inf, isfinite
from typing import Protocol
from h3_offroad_planner.models import H3Graph, Path, PlanningFailedError
from h3_offroad_planner.planners.interfaces import LocalReplanner

# MovementCost — L17
class MovementCost(Protocol):
    """Minimal directed movement-cost interface required by D* Lite."""

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Return finite non-negative cost or infinity for an unavailable edge."""
        ...

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Return a finite admissible estimate in the same unit as movement cost."""
        ...

# DStarLiteReplanner — L27
class DStarLiteReplanner(LocalReplanner):
    """Incrementally repair a reverse shortest-path tree after cell blockages."""

    def __init__(self, cost_function: MovementCost) -> None:
        """Initialize an empty D* Lite state for one compatible graph and goal."""
        ...

    @property
    def rhs(self) -> dict[str, float]:
        """Expose a copy of reverse one-step values for validation."""
        ...

    @property
    def g(self) -> dict[str, float]:
        """Expose a copy of reverse path values for validation."""
        ...

    def initialize(self, graph: H3Graph, start: str, goal: str) -> None:
        """Initialize reverse D* Lite state with `rhs[goal] == 0`.

        Raises:
            PlanningFailedError: If either endpoint is absent from the graph.
        """
        ...

    def replan(self, graph: H3Graph, blocked_cells: set[str], current_path: Path) -> Path:
        """Incrementally repair the path after newly blocked cells.

        The lifecycle controller resolves timestamps and confirmation state before this
        call; the graph-level planner receives only confirmed impassable cell ids.
        """
        ...

    def _move_start(self, graph: H3Graph, start: str) -> None:
        """Apply D* Lite's key shift when the vehicle advances along a path."""
        ...

    def _repair_affected_vertices(self, graph: H3Graph, affected: set[str]) -> None:
        """Update changed cells and predecessors after obstacle-state changes."""
        ...

    def _compute_shortest_path(self, graph: H3Graph) -> None:
        """Repair inconsistent reverse values until the current start is consistent."""
        ...

    def _update_vertex(self, graph: H3Graph, cell_id: str) -> None:
        """Refresh one reverse one-step value and its lazy priority-queue entry."""
        ...

    def _extract_path(self, graph: H3Graph) -> Path:
        """Follow minimum `cost + g` successors from the current start to the goal."""
        ...

    def _calculate_key(self, graph: H3Graph, cell_id: str) -> Key:
        """Compute the lexicographic D* Lite key for one graph cell."""
        ...

    def _push(self, cell_id: str, graph: H3Graph) -> None:
        """Add or replace a lazy priority-queue entry for one inconsistent cell."""
        ...

    def _pop(self) -> tuple[Key, str] | None:
        """Pop the next non-stale D* Lite queue entry."""
        ...

    def _top_key(self) -> Key:
        """Return the next non-stale key without removing its valid entry."""
        ...

# _mark_unpassable — L204
def _mark_unpassable(graph: H3Graph, blocked: set[str]) -> set[str]:
    """Mark known obstacle cells impassable and return their changed identifiers."""
    ...

# _neighbors — L214
def _neighbors(graph: H3Graph, cell_id: str) -> list[str]:
    """Return deterministic graph neighbors for reverse D* Lite updates."""
    ...
```
