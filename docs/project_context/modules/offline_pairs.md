# 模块参考：offline_pairs

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/offline_pairs.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`b664ab10c6affc78dd4a7b9d0225b9188f1b38846936c8a6d84a576574c3660e`；类 1 个，函数/方法 19 个（含嵌套定义）。
- 项目内导入依赖：`config`, `factor_model`, `grid`, `models`, `portsmap`, `routing_index`。
- 直接导入本模块者：`route_planning`, `routing_index`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L43
OfflinePairs = Mapping[tuple[str, str, str], Mapping[str, tuple[tuple[str, ...], float]]]

# OfflinePairsTable — src/h3_offroad_planner/offline_pairs.py:129
class OfflinePairsTable(Mapping[tuple[str, str, str], Mapping[str, tuple[tuple[str, ...], float]]]):
    'Lightweight, ultra-fast view of offline port pairs backed by PyArrow and NumPy slices.\n\n    Loads scalar costs into memory for macro graph search in sub-second time,\n    indexing contiguous slices per parent and unpacking pure Python dicts on-demand,\n    while deferring fine cell path resolution until the winning trajectory is found.\n    '
    # self.parquet_path: 未注解; L144; initial=Path(path)
    active_parents: frozenset[str]  # instance; L145; initial=frozenset(active_parents) if active_parents is not None else frozenset()
    _path_cache: dict[tuple[str, str, str, str], tuple[str, ...]]  # instance; L148; initial={}
    _parent_tables: dict[tuple[str, str], dict[str, dict[str, tuple[tuple[str, ...], float]]]]  # instance; L149; initial={}
    _macro_adj_cache: dict[tuple[str, float, frozenset[str]], dict[str, list[tuple[str, tuple[str, ...], float]]]]  # instance; L152; initial={}
    # self._profs: 未注解; L191; initial=table['profile'].to_numpy(zero_copy_only=False)
    # self._parents: 未注解; L192; initial=table['parent_h3'].to_numpy(zero_copy_only=False)
    # self._sources: 未注解; L193; initial=table['source'].to_numpy(zero_copy_only=False)
    # self._targets: 未注解; L194; initial=table['target'].to_numpy(zero_copy_only=False)
    # self._costs: 未注解; L195; initial=table['cost'].to_numpy(zero_copy_only=False)
    _slices: dict[tuple[str, str], list[tuple[int, int]]]  # instance; L166; initial={}
    offline_parents_by_profile: frozenset[tuple[str, str]]  # instance; L167; initial=frozenset()
    offline_parents: frozenset[str]  # instance; L168; initial=frozenset()
    ...
```

```python
# L47
BASE_PROFILE_NAMES: tuple[str, ...] = ('distance', 'eta', 'terrain_risk', 'travel_cost')
# L54
PORT_PAIRS_SCHEMA = pa.schema([pa.field('profile', pa.string(), nullable=False), pa.field('parent_h3', pa.string(), nullable=False), pa.field('source', pa.string(), nullable=False), pa.field('target', pa.string(), nullable=False), pa.field('path', pa.list_(pa.string()), nullable=False), pa.field('cost', pa.float64(), nullable=False)])
```

```python
# L54
pa.schema([pa.field('profile', pa.string(), nullable=False), pa.field('parent_h3', pa.string(), nullable=False), pa.field('source', pa.string(), nullable=False), pa.field('target', pa.string(), nullable=False), pa.field('path', pa.list_(pa.string()), nullable=False), pa.field('cost', pa.float64(), nullable=False)])
```

```text
# L642 _precompute_single_parent
'profile' => profile.name
'parent_h3' => parent
'source' => source
'target' => target
'path' => list(path)
'cost' => float(cost)

# L103 save_offline_pairs
'profile' => profile
'parent_h3' => parent
'source' => source
'target' => target
'path' => list(h3_path)
'cost' => float(cost)
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, cast
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import FactorModelConfig, evaluate_factor_model
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import VehicleProfile
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile

# extract_offline_pairs — L66
def extract_offline_pairs(context: PortsMapSearchContext, profile_name: str) -> dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]]:
    """Extract unpenalized and unblocked port-pair paths from a warmed context."""
    ...

# save_offline_pairs — L82
def save_offline_pairs(pairs: OfflinePairs | pd.DataFrame | list[dict[str, object]], path: Path, vehicle_hash: str | None=None, row_group_size: int=5000) -> None:
    """Write offline port pairs to a compressed Parquet file."""
    ...

# read_offline_pairs_vehicle_hash — L116
def read_offline_pairs_vehicle_hash(path: Path) -> str | None:
    """Read vehicle_hash stored in Parquet schema metadata if present."""
    ...

# OfflinePairsTable — L129
class OfflinePairsTable(Mapping[tuple[str, str, str], Mapping[str, tuple[tuple[str, ...], float]]]):
    """Lightweight, ultra-fast view of offline port pairs backed by PyArrow and NumPy slices.

    Loads scalar costs into memory for macro graph search in sub-second time,
    indexing contiguous slices per parent and unpacking pure Python dicts on-demand,
    while deferring fine cell path resolution until the winning trajectory is found.
    """

    def __init__(self, path: Path, active_parents: Collection[str] | None=None) -> None:
        ...

    def _ensure_parent_table(self, parent_key: tuple[str, str]) -> dict[str, dict[str, tuple[tuple[str, ...], float]]] | None:
        ...

    def get(self, key: tuple[str, str, str], default: Mapping[str, tuple[tuple[str, ...], float]] | None=None) -> Mapping[str, tuple[tuple[str, ...], float]] | None:
        ...

    def __getitem__(self, key: tuple[str, str, str]) -> Mapping[str, tuple[tuple[str, ...], float]]:
        ...

    def __len__(self) -> int:
        ...

    def __iter__(self) -> Iterator[tuple[str, str, str]]:
        ...

    def __contains__(self, key: object) -> bool:
        ...

    def build_macro_adjacency(self, base_objective: str, scale: float=1.0, weight: float=1.0, excluded_parents: Collection[str] | None=None) -> dict[str, list[tuple[str, tuple[str, ...], float]]]:
        """Build macro port-pair adjacency dictionary for an entire corridor in vectorized time."""
        ...

    def resolve_paths(self, queries: Iterable[tuple[str, str, str, str]]) -> dict[tuple[str, str, str, str], tuple[str, ...]]:
        """Resolve full fine cell paths for requested (profile, parent, source, target) edges."""
        ...

# load_offline_pairs — L356
def load_offline_pairs(path: Path, active_parents: Collection[str] | None=None, *, load_paths: bool=True) -> OfflinePairs:
    """Load offline pairs from Parquet, optionally slicing via PyArrow predicate pushdown."""
    ...

# default_vehicle — L402
def default_vehicle() -> VehicleProfile:
    """Return a baseline vehicle profile for offline precomputations."""
    ...

# _extract_parent_ports — L420
def _extract_parent_ports(parent: str, cells_df: pd.DataFrame, res_coarse: int, known_parents: set[str], seed_ports: Collection[str]=()) -> list[str]:
    ...

# _precompute_chunk — L442
def _precompute_chunk(chunk_parents: list[str], index: RoutingIndex, known_parents: set[str], ports_by_parent: dict[str, set[str]], builder: H3GridBuilder, vehicle: VehicleProfile, factor_config: FactorModelConfig, profiles: list[ScalarProfile], res_coarse: int) -> list[dict[str, object]]:
    ...

# _worker_precompute_chunk — L479
def _worker_precompute_chunk(index_path_str: str, chunk_parents: list[str], known_parents: set[str], ports_by_parent: dict[str, set[str]], vehicle: VehicleProfile, factor_dict: dict[str, object], profiles: list[ScalarProfile], res_fine: int, res_coarse: int) -> list[dict[str, object]]:
    ...

# precompute_port_pairs — L508
def precompute_port_pairs(index: RoutingIndex, *, vehicle: VehicleProfile | None=None, factor_config: FactorModelConfig | None=None, parents: Collection[str] | None=None, profiles: Sequence[ScalarProfile] | None=None, max_parents: int | None=None, batch_size: int=50, workers: int=1) -> pd.DataFrame:
    """Precompute optimal port-pair paths and scalar costs across parent tiles."""
    ...

# _precompute_single_parent — L608
def _precompute_single_parent(parent: str, ports: list[str], cells_df: pd.DataFrame, builder: H3GridBuilder, vehicle: VehicleProfile, factor_config: FactorModelConfig, profiles: Sequence[ScalarProfile]) -> list[dict[str, object]]:
    ...
```
