# 模块参考：dynamics.cost_function

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/dynamics/cost_function.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`45f649f123c74ebd95f4bdefdaface481138f415ac9ac6fdf470430923487be0`；类 1 个，函数/方法 5 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`dynamics`, `planners.factory`, `planners.h3_astar`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# CostFunction — src/h3_offroad_planner/dynamics/cost_function.py:12
class CostFunction:
    'Compute single-step movement cost with directional slope constraints.'
    # self.vehicle: 未注解; L44; initial=vehicle
    # self.k_r: 未注解; L45; initial=k_r
    # self.gravity_coeff: 未注解; L46; initial=gravity_coeff
    # self.score_coefficient: 未注解; L47; initial=score_coefficient
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from math import inf, isfinite, sqrt
from h3_offroad_planner.models import H3Edge, H3Graph, VehicleProfile

# CostFunction — L12
class CostFunction:
    """Compute single-step movement cost with directional slope constraints."""

    def __init__(self, vehicle: VehicleProfile, k_r: float=0.1, gravity_coeff: float=5.0, score_coefficient: float=0.0) -> None:
        """Initialize the cost function.

        Args:
            vehicle: Vehicle physical profile.
            k_r: TRI roughness coefficient. Unit: dimensionless. Valid range: >= 0.
            gravity_coeff: Uphill elevation penalty. Unit: cost per meter. Range: >= 0.
            score_coefficient: Cost multiplier for low trafficability score.
                Unit: dimensionless. Valid range: >= 0.

        Raises:
            ValueError: If coefficients are negative or non-finite.
        """
        ...

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Compute directional movement cost from one cell to an adjacent cell.

        Args:
            graph: In-memory planning graph.
            from_cell: Source cell id. Must exist in `graph`.
            to_cell: Destination cell id. Must exist in `graph`.

        Returns:
            Movement cost. Unit: abstract non-negative cost. Returns infinity when
            the transition is physically impossible.
        """
        ...

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Return a conservative coordinate-distance lower bound for legacy cost."""
        ...

# _get_directed_edge — L89
def _get_directed_edge(graph: H3Graph, from_cell: str, to_cell: str) -> H3Edge | None:
    ...

# _directional_slope — L96
def _directional_slope(edge: H3Edge, from_cell: str, to_cell: str) -> float:
    ...
```
