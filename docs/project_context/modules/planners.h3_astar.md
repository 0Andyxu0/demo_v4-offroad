# 模块参考：planners.h3_astar

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/planners/h3_astar.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`0f6478584fc8064eede355fc03c5aef762e83ac029aadb184c923721e87fd53e`；类 1 个，函数/方法 17 个（含嵌套定义）。
- 项目内导入依赖：`dynamics.cost_function`, `models`, `planners.interfaces`。
- 直接导入本模块者：`planners`, `planners.factory`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# H3AStarPlanner — src/h3_offroad_planner/planners/h3_astar.py:21
class H3AStarPlanner(GlobalPlanner):
    'Plan through a parent-cell corridor before running fine-cell A*.'
    # self.cost_function: 未注解; L26; initial=cost_function
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from heapq import heappop, heappush
from math import inf, isfinite, sqrt
from h3_offroad_planner.dynamics.cost_function import CostFunction
from h3_offroad_planner.models import H3Graph, Path, PlannerInput, PlannerOutput, PlanningFailedError
from h3_offroad_planner.planners.interfaces import GlobalPlanner

# H3AStarPlanner — L21
class H3AStarPlanner(GlobalPlanner):
    """Plan through a parent-cell corridor before running fine-cell A*."""

    def __init__(self, cost_function: CostFunction) -> None:
        """Initialize the planner with a physical edge-cost function."""
        ...

    def plan(self, inp: PlannerInput) -> PlannerOutput:
        """Plan a single finite-cost path from `inp.start` to `inp.goal`."""
        ...

    def _build_ports_map(self, graph: H3Graph) -> dict[str, dict[str, float]]:
        """Build directional parent adjacency weighted by physical boundary traversal."""
        ...

    def _macro_astar(self, ports_map: dict[str, dict[str, float]], graph: H3Graph, start: str, goal: str) -> list[str]:
        """Find a finite parent-cell route and attach endpoint cells by parent."""
        ...

    def _extract_corridor(self, graph: H3Graph, macro_route: list[str], dilation: int=1) -> set[str]:
        """Return passable cells in the parent route plus a parent-neighbor shell."""
        ...

    def _corridor_astar(self, graph: H3Graph, corridor: set[str], start: str, goal: str) -> Path:
        ...

    def _search(self, graph: H3Graph, corridor: set[str], start: str, goal: str) -> tuple[dict[str, str], dict[str, float]]:
        ...

    def _expand_node(self, graph: H3Graph, corridor: set[str], goal: str, current: str, came_from: dict[str, str], g_score: dict[str, float], open_heap: list[tuple[float, str]]) -> None:
        ...

    def _neighbors(self, graph: H3Graph, cell_id: str) -> list[str]:
        """Return deterministic fine-cell neighbors present in graph edges."""
        ...

    def _parent_id(self, graph: H3Graph, cell_id: str) -> str:
        """Return a cell parent, preserving compatibility with synthetic graphs."""
        ...

    def _edge_is_passable(self, graph: H3Graph, cell_a: str, cell_b: str) -> bool:
        """Check that both endpoints of a candidate Port edge are passable."""
        ...

    def _search_parent_graph(self, ports_map: dict[str, dict[str, float]], start_parent: str, goal_parent: str) -> list[str]:
        """Run deterministic Dijkstra search over accumulated parent-edge weights."""
        ...

    def _normalize_parent_route(self, graph: H3Graph, macro_route: list[str]) -> set[str]:
        """Normalize old fine-cell route inputs and new parent-route inputs."""
        ...

    def _dilate_parent_route(self, graph: H3Graph, parent_route: set[str], dilation: int) -> set[str]:
        """Expand a parent route by graph-derived parent adjacency rings."""
        ...

    def _record_boundary_cost(self, ports_map: dict[str, dict[str, float]], graph: H3Graph, source_parent: str, target_parent: str, source_cell: str, target_cell: str) -> None:
        """Keep the lowest finite directional cost among parent-boundary crossings."""
        ...

    def _heuristic(self, graph: H3Graph, cell_a: str, cell_b: str) -> float:
        ...

# _reconstruct_path — L255
def _reconstruct_path(came_from: dict[str, str], start: str, goal: str) -> list[str]:
    ...
```
