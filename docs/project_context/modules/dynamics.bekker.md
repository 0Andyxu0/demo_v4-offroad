# 模块参考：dynamics.bekker

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/dynamics/bekker.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`21509cccb1a6111eba94dfbeab43b7672506099edbc4b64638081d2a503c0549`；类 1 个，函数/方法 14 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`assessment.trafficability`, `factor_model`, `vectorized_factor`, `vectorized_soil`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# BekkerChecker — src/h3_offroad_planner/dynamics/bekker.py:37
class BekkerChecker:
    'Check soil mobility using CI and Bekker sinkage formulas.'
    # self.speed_score_floor: 未注解; L52; initial=speed_score_floor
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from math import exp, isfinite, log
from h3_offroad_planner.models import AssessmentError, H3Cell, VehicleProfile

# BekkerChecker — L37
class BekkerChecker:
    """Check soil mobility using CI and Bekker sinkage formulas."""

    def __init__(self, speed_score_floor: float=0.2) -> None:
        """Initialize configurable Bekker helper controls.

        Args:
            speed_score_floor: Minimum score multiplier used by `compute_max_speed`.
                Unit: ratio. Valid range: [0, 1].

        Raises:
            ValueError: If `speed_score_floor` is outside [0, 1].
        """
        ...

    def check(self, cell: H3Cell, vehicle: VehicleProfile) -> bool:
        """Return whether a vehicle passes the cell sinkage constraint."""
        ...

    def compute_cone_index_kpa(self, uscs: str, soil_moisture: float) -> float:
        """Compute cone index from USCS class and volumetric soil moisture."""
        ...

    def compute_sinkage(self, cell: H3Cell, vehicle: VehicleProfile) -> dict[str, float]:
        """Compute Bekker parameters and sinkage for one soil-equipped cell."""
        ...

    def enrich_cell(self, cell: H3Cell, vehicle: VehicleProfile) -> None:
        """Populate CI, sinkage, resistance, and raw mobility fields on a cell."""
        ...

    def compute_max_speed(self, cell: H3Cell, vehicle: VehicleProfile) -> float:
        """Return a conservative terrain speed cap in meters per second."""
        ...

    def _legacy_sinkage_m(self, vehicle: VehicleProfile, params: dict[str, float]) -> float:
        ...

# _require_ratio — L143
def _require_ratio(name: str, value: float) -> None:
    ...

# _ground_pressure_n_per_mm2 — L148
def _ground_pressure_n_per_mm2(vehicle: VehicleProfile) -> float:
    ...

# _water_percent — L156
def _water_percent(bekker_soil: str, soil_moisture: float) -> float:
    ...

# _bekker_exponent — L161
def _bekker_exponent(bekker_soil: str, w_percent: float) -> float:
    ...

# _bekker_stiffness — L171
def _bekker_stiffness(bekker_soil: str, w_percent: float) -> tuple[float, float]:
    ...

# _sinkage_passes — L179
def _sinkage_passes(cell: H3Cell, vehicle: VehicleProfile) -> bool:
    ...

# _cell_bekker_soil — L183
def _cell_bekker_soil(cell: H3Cell) -> str | None:
    ...
```
