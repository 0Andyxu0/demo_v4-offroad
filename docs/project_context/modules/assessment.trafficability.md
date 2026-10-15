# 模块参考：assessment.trafficability

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/assessment/trafficability.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`c8fe2951722db79d1951a5b8d99f9cec73b823edda6e16ad41ebbb21b49f6699`；类 1 个，函数/方法 5 个（含嵌套定义）。
- 项目内导入依赖：`dynamics.bekker`, `models`。
- 直接导入本模块者：`assessment`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# TrafficabilityAssessor — src/h3_offroad_planner/assessment/trafficability.py:16
class TrafficabilityAssessor:
    'Legacy standalone evaluator retained outside the RoutePlan production chain.'
    # self.vehicle: 未注解; L28; initial=vehicle
    # self.weights: 未注解; L29; initial=weights
    # self.bekker: 未注解; L30; initial=BekkerChecker()
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Iterable
from math import inf, isfinite
from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.models import AssessmentError, H3Cell, H3Graph, VehicleProfile

# TrafficabilityAssessor — L16
class TrafficabilityAssessor:
    """Legacy standalone evaluator retained outside the RoutePlan production chain."""

    def __init__(self, vehicle: VehicleProfile, weights: dict[str, float]) -> None:
        """Initialize the assessor with vehicle and non-negative feature weights."""
        ...

    def assess(self, graph: H3Graph) -> H3Graph:
        """Update cell `score` and `is_passable` fields in a graph."""
        ...

    def _score_cell(self, slope: float, lc_factor: float, tri: float, soil_mobility: float | None, has_road: bool) -> float:
        ...

# _assign_soil_mobility — L81
def _assign_soil_mobility(cells: Iterable[H3Cell]) -> None:
    ...

# _mobility_from_normalized_resistance — L99
def _mobility_from_normalized_resistance(value: float) -> float:
    ...
```
