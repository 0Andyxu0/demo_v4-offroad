# 模块参考：coordination.interfaces

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/coordination/interfaces.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`d8702a5506f497a92fa013b9241273575388ea0981d8e8d42d8b6b0423a81b49`；类 1 个，函数/方法 1 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`coordination`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# FleetCoordinator — src/h3_offroad_planner/coordination/interfaces.py:12
class FleetCoordinator(Protocol):
    'Abstract boundary reserved for a future multi-vehicle coordinator.'
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from typing import Protocol
from h3_offroad_planner.models import FleetPlan, FleetPlanningInput

# FleetCoordinator — L12
class FleetCoordinator(Protocol):
    """Abstract boundary reserved for a future multi-vehicle coordinator."""

    def coordinate(self, planning_input: FleetPlanningInput) -> FleetPlan:
        """Coordinate fleet tasks; no concrete implementation ships in this release."""
        ...
```
