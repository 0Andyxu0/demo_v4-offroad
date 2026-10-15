# 模块参考：planners.factory

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/planners/factory.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`758f1432e35775c80098698635dcca727a6c2b87e965b9385523462e0cce3685`；类 1 个，函数/方法 6 个（含嵌套定义）。
- 项目内导入依赖：`dynamics.cost_function`, `models`, `planners.dstar_lite`, `planners.facade`, `planners.h3_astar`。
- 直接导入本模块者：`planners`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# PlannerFactory — src/h3_offroad_planner/planners/factory.py:22
class PlannerFactory:
    'Build a `PathPlannerFacade` from validated configuration.'
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from typing import cast
from h3_offroad_planner.dynamics.cost_function import CostFunction
from h3_offroad_planner.models import ConfigError, VehicleProfile
from h3_offroad_planner.planners.dstar_lite import DStarLiteReplanner
from h3_offroad_planner.planners.facade import PathPlannerFacade
from h3_offroad_planner.planners.h3_astar import H3AStarPlanner

# PlannerFactory — L22
class PlannerFactory:
    """Build a `PathPlannerFacade` from validated configuration."""

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> PathPlannerFacade:
        """Create the configured global/local planner pair.

        Args:
            cfg: Configuration mapping with planner names, cost mapping, and `_vehicle`.

        Returns:
            Configured facade.

        Raises:
            ConfigError: If a planner name is unknown or `_vehicle` is missing.
        """
        ...

# _vehicle_from_config — L51
def _vehicle_from_config(cfg: dict[str, object]) -> VehicleProfile:
    ...

# _cost_mapping — L58
def _cost_mapping(cfg: dict[str, object]) -> dict[str, object]:
    ...

# _float_from_mapping — L65
def _float_from_mapping(mapping: dict[str, object], key: str, default: float, label: str='cost') -> float:
    ...

# _build_global — L80
def _build_global(name: str, cost_function: CostFunction) -> H3AStarPlanner:
    ...

# _build_local — L94
def _build_local(name: str, cost_function: CostFunction) -> DStarLiteReplanner:
    ...
```
