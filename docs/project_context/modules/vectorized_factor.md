# 模块参考：vectorized_factor

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/vectorized_factor.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`035bc42e7aa8121c4b5815b5ac9d86d4652112703ecf0befbe538549c05e8b2a`；类 1 个，函数/方法 6 个（含嵌套定义）。
- 项目内导入依赖：`dynamics.bekker`, `factor_model`, `models`, `vectorized_soil`。
- 直接导入本模块者：`factor_model`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# VectorizedEdgeArrays — src/h3_offroad_planner/vectorized_factor.py:90
@dataclass(frozen=True)
class VectorizedEdgeArrays:
    'Container holding continuous arrays of batch directed edge computations.'
    u_keys: list[str]
    v_keys: list[str]
    u_indices: npt.NDArray[np.int32]
    v_indices: npt.NDArray[np.int32]
    distances_m: npt.NDArray[np.float64]
    slopes_deg: npt.NDArray[np.float64]
    grade_force_n: npt.NDArray[np.float64]
    speed_lower_mps: npt.NDArray[np.float64]
    speed_nominal_mps: npt.NDArray[np.float64]
    speed_upper_mps: npt.NDArray[np.float64]
    safety_margin: npt.NDArray[np.float64]
    travel_cost: npt.NDArray[np.float64]
    is_passable: npt.NDArray[np.bool_]
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
import numpy as np
import numpy.typing as npt
from h3_offroad_planner.dynamics.bekker import GRAVITY_MPS2
from h3_offroad_planner.factor_model import _EMPTY_ENV, DirectedEdgeMetrics, EnvironmentConfig, FactorModelConfig, NodeFactorMetrics, _pressure_key, environment_multiplier
from h3_offroad_planner.models import H3Graph, PlanningInputError, VehicleProfile
from h3_offroad_planner.vectorized_soil import vectorized_bekker_sinkage, vectorized_cone_index_kpa

# scalar_speed_multiplier — L39
def scalar_speed_multiplier(landcover_code: int | None, uscs: str | None, tri: float, config: FactorModelConfig) -> float:
    """Return one terrain speed multiplier for a single cell."""
    ...

# vectorized_speed_multiplier — L61
def vectorized_speed_multiplier(landcover_codes: npt.NDArray[np.float64], uscs_values: npt.NDArray[np.str_], tri_values: npt.NDArray[np.float64], config: FactorModelConfig) -> npt.NDArray[np.float64]:
    """Return terrain speed multipliers for arrays of cells."""
    ...

# vectorized_speed_multiplier._lc_lookup — L68
def _lc_lookup(code: float) -> float:
    ...

# vectorized_speed_multiplier._soil_lookup — L75
def _soil_lookup(uscs: str) -> float:
    ...

# VectorizedEdgeArrays — L90
@dataclass(frozen=True)
class VectorizedEdgeArrays:
    """Container holding continuous arrays of batch directed edge computations."""

# compute_vectorized_edge_arrays — L108
def compute_vectorized_edge_arrays(graph: H3Graph, node_metrics: Mapping[str, NodeFactorMetrics], vehicle: VehicleProfile, config: FactorModelConfig) -> VectorizedEdgeArrays:
    """Compute dense continuous NumPy arrays for all potential directed edges in graph."""
    ...

# evaluate_directed_edges_vectorized — L273
def evaluate_directed_edges_vectorized(graph: H3Graph, node_metrics: Mapping[str, NodeFactorMetrics], vehicle: VehicleProfile, config: FactorModelConfig, environment: EnvironmentConfig | None=None) -> dict[tuple[str, str], DirectedEdgeMetrics]:
    """Build the authoritative directed metrics using NumPy batch vectorization."""
    ...
```
