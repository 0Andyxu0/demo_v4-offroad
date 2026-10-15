# 模块参考：planners.interfaces

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/planners/interfaces.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`af215b76547866474193c16e08e4777107d1f15d44fa643bbf6b8c7b996adfda`；类 2 个，函数/方法 2 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`planners`, `planners.dstar_lite`, `planners.facade`, `planners.h3_astar`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# GlobalPlanner — src/h3_offroad_planner/planners/interfaces.py:12
class GlobalPlanner(ABC):
    'Abstract global planner interface.'
    ...

# LocalReplanner — src/h3_offroad_planner/planners/interfaces.py:20
class LocalReplanner(ABC):
    'Abstract local replanner interface.'
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from h3_offroad_planner.models import H3Graph, Path, PlannerInput, PlannerOutput

# GlobalPlanner — L12
class GlobalPlanner(ABC):
    """Abstract global planner interface."""

    @abstractmethod
    def plan(self, inp: PlannerInput) -> PlannerOutput:
        """Plan one or more paths for a validated planner input."""
        ...

# LocalReplanner — L20
class LocalReplanner(ABC):
    """Abstract local replanner interface."""

    @abstractmethod
    def replan(self, graph: H3Graph, blocked_cells: set[str], current_path: Path) -> Path:
        """Replan around the currently confirmed impassable cells."""
        ...
```
