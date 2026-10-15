# 模块参考：portsmap

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/portsmap.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`e3e8ac3b79ec8676af02a4da03332599909ea9c8c8f81c7185808e5b123f875e`；类 7 个，函数/方法 36 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`。
- 直接导入本模块者：`candidate_aggregation`, `offline_pairs`, `planners.deterministic_pareto`, `replanning`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# PortsMapLimitError — src/h3_offroad_planner/portsmap.py:43
class PortsMapLimitError(PlanningFailedError):
    'Raised when exact PortsMap construction exceeds configured demo limits.'
    code: str = 'PORTS_MAP_LIMIT_EXCEEDED'
    ...

# ScalarProfile — src/h3_offroad_planner/portsmap.py:50
@dataclass(frozen=True)
class ScalarProfile:
    'Non-negative additive objective weights and robust normalization scales.'
    weights: Mapping[str, float]
    scales: Mapping[str, float] = field(default_factory=lambda: {'distance': 1.0, 'eta': 1.0, 'terrain_risk': 1.0, 'travel_cost': 1.0})
    name: str = 'custom'
    environment_pressure: float | None = None
    environment_weight: float = 0.0
    environment_scale: float = 1.0
    _w_dist: float = field(init=False, repr=False, default=0.0)
    _w_eta: float = field(init=False, repr=False, default=0.0)
    _w_risk: float = field(init=False, repr=False, default=0.0)
    _w_cost: float = field(init=False, repr=False, default=0.0)
    ...

# Port — src/h3_offroad_planner/portsmap.py:144
@dataclass(frozen=True)
class Port:
    'Fine-grid endpoint participating in a parent-level macro graph.'
    h3index: str
    parent_h3: str
    is_temporary: bool = False
    ...

# PortPairPath — src/h3_offroad_planner/portsmap.py:157
@dataclass(frozen=True)
class PortPairPath:
    'Exact directed shortest path between two Ports inside one parent.'
    parent_h3: str
    from_port: str
    to_port: str
    h3_path: tuple[str, ...]
    scalar_cost: float
    ...

# PortsMapTopology — src/h3_offroad_planner/portsmap.py:178
@dataclass(frozen=True)
class PortsMapTopology:
    'Explicit Ports and cross-parent directed edge segments for one request.'
    ports: Mapping[str, Port]
    ports_by_parent: Mapping[str, tuple[str, ...]]
    cross_parent_edges: Mapping[tuple[str, str], tuple[str, ...]]
    port_hashes: Mapping[str, str] = field(default_factory=dict)
    ...

# PortsMapSearchResult — src/h3_offroad_planner/portsmap.py:188
@dataclass(frozen=True)
class PortsMapSearchResult:
    'Expanded continuous fine-grid route with exact scalar and path metrics.'
    h3_path: tuple[str, ...]
    scalar_cost: float
    metrics: PathMetrics
    ports_count: int
    port_pairs_count: int
    cache_hits: int
    ...

# PortsMapSearchContext — src/h3_offroad_planner/portsmap.py:199
class PortsMapSearchContext:
    'Request-scoped exact PortsMap kernel with safe Port-pair reuse.'
    _fine_dijkstra = _fine_tile_search
    # self.graph: 未注解; L220; initial=graph
    # self.evaluation: 未注解; L221; initial=evaluation
    # self.max_ports: 未注解; L222; initial=max_ports
    # self.max_port_pairs: 未注解; L223; initial=max_port_pairs
    # self.base_cache_identity: 未注解; L224; initial=base_cache_identity
    # self._offline_pairs: 未注解; L225; initial=offline_pairs
    # self._offline_cache_hits: 未注解; L226; initial=0
    # self._neighbors: 未注解; L252; initial=_directed_neighbors(evaluation.directed_edges)
    _pair_cache: dict[tuple[str, str, object, object, str], dict[tuple[str, str], PortPairPath]]  # instance; L253; initial={}
    _source_edge_cache: dict[tuple[str, str, object, object, str], dict[str, list[tuple[str, tuple[str, ...], float]]]]  # instance; L257; initial={}
    _computed_sources: dict[tuple[str, str, object, object, str], set[str]]  # instance; L261; initial={}
    # self._cache_hits: 未注解; L265; initial=0
    # self._base_cache_hits: 未注解; L266; initial=0
    # self._base_cache_misses: 未注解; L267; initial=0
    # self._fine_search_calls: 未注解; L268; initial=0
    _visited_parents: set[str]  # instance; L269; initial=set()
    # self._coord_scale: 未注解; L283; initial=coord_scale
    _base_topology_cache: dict[frozenset[str], tuple[dict[str, Port], dict[tuple[str, str], tuple[str, ...]], dict[str, tuple[str, ...]]]]  # instance; L284; initial={}
    _parent_keys: dict[str, set[tuple[str, str, object, object, str]]]  # instance; L292; initial={}
    _goal_dist_caches: dict[str, dict[str, float]]  # instance; L293; initial={}
    _offline_parents_by_profile: set[tuple[str, str]]  # instance; L229; initial=set(offline_pairs.offline_parents_by_profile)
    # self._offline_parents: 未注解; L244; initial=set(offline_parents) if offline_parents is not None else set()
    # self._parent_children: 未注解; L246; initial=graph.parent_children
    ...
```

校验 `ScalarProfile.__post_init__`：

- `L69 if unknown` → `raise ValueError(f'unknown scalar objectives: {sorted(unknown)}')`
- `L71 if sum(self.weights.values()) + self.environment_weight <= 0.0` → `raise ValueError('scalar profile must contain a positive weight sum.')`
- `L76 if set(self.scales) != set(OBJECTIVE_NAMES)` → `raise ValueError('scalar scales must define all four additive objectives.')`
- `L78 if any((not isfinite(value) or value <= 0.0 for value in self.scales.values()))` → `raise ValueError('scalar scales must be finite and positive.')`
- `L80 if not isfinite(self.environment_weight) or self.environment_weight < 0.0` → `raise ValueError('environment_weight must be finite and non-negative.')`
- `L82 if not isfinite(self.environment_scale) or self.environment_scale <= 0.0` → `raise ValueError('environment_scale must be finite and positive.')`
- `L84 if self.environment_pressure is not None and (not isfinite(self.environment_pressure) or self.environment_pressure < 0.0)` → `raise ValueError('environment_pressure must be finite and non-negative.')`
- `L88 if self.environment_weight > 0.0 and self.environment_pressure is None` → `raise ValueError('environment_pressure is required for environment_weight.')`
- `L74 if not isfinite(value) or value < 0.0` → `raise ValueError('scalar weights must be finite and non-negative.')`

校验 `Port.__post_init__`：

- `L152 if not self.h3index or not self.parent_h3` → `raise ValueError('Port identifiers must be non-empty.')`

校验 `PortPairPath.__post_init__`：

- `L167 if not self.parent_h3 or not self.from_port or (not self.to_port)` → `raise ValueError('Port-pair identifiers must be non-empty.')`
- `L169 if len(self.h3_path) < 2` → `raise ValueError('Port-pair path must contain at least two cells.')`
- `L171 if self.h3_path[0] != self.from_port or self.h3_path[-1] != self.to_port` → `raise ValueError('Port-pair path endpoints must match its Port ids.')`
- `L173 if not isfinite(self.scalar_cost) or self.scalar_cost < 0.0` → `raise ValueError('Port-pair scalar cost must be finite and non-negative.')`

```python
# L31
EPSILON: float = 1e-12
# L32
OBJECTIVE_NAMES: tuple[str, ...] = ('distance', 'eta', 'terrain_risk', 'travel_cost')
# L33
BASE_PAIR_CACHE_LIMIT: int = 65536
# L34
_BASE_PAIR_CACHE: dict[tuple[str, str, str, str, str], tuple[tuple[str, tuple[str, ...], float], ...]] = {}
# L38
_BASE_PAIR_CACHE_RANKS: list[tuple[int, tuple[str, str, str, str, str]]] = []
# L39
_BASE_PAIR_CACHE_LOCK = Lock()
# L40
_GET_FIRST = itemgetter(0)
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from heapq import heappop, heappush, heapreplace
from math import asin, cos, inf, isfinite, radians, sin, sqrt
from operator import itemgetter
from threading import Lock
from h3_offroad_planner.factor_model import DirectedEdgeMetrics, FactorEvaluation, PathMetrics, canonical_hash, evaluate_path_metrics
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError

# PortsMapLimitError — L43
class PortsMapLimitError(PlanningFailedError):
    """Raised when exact PortsMap construction exceeds configured demo limits."""

# ScalarProfile — L50
@dataclass(frozen=True)
class ScalarProfile:
    """Non-negative additive objective weights and robust normalization scales."""

    def __post_init__(self) -> None:
        ...

    @property
    def signature(self) -> str:
        """Return a stable cache signature for this complete scalar profile."""
        ...

    def edge_cost(self, edge: DirectedEdgeMetrics) -> float:
        """Compute normalized additive scalar edge cost."""
        ...

# Port — L144
@dataclass(frozen=True)
class Port:
    """Fine-grid endpoint participating in a parent-level macro graph."""

    def __post_init__(self) -> None:
        ...

# PortPairPath — L157
@dataclass(frozen=True)
class PortPairPath:
    """Exact directed shortest path between two Ports inside one parent."""

    def __post_init__(self) -> None:
        ...

# PortsMapTopology — L178
@dataclass(frozen=True)
class PortsMapTopology:
    """Explicit Ports and cross-parent directed edge segments for one request."""

# PortsMapSearchResult — L188
@dataclass(frozen=True)
class PortsMapSearchResult:
    """Expanded continuous fine-grid route with exact scalar and path metrics."""

# PortsMapSearchContext — L199
class PortsMapSearchContext:
    """Request-scoped exact PortsMap kernel with safe Port-pair reuse."""

    def __init__(self, graph: H3Graph, evaluation: FactorEvaluation, max_ports: int=20000, max_port_pairs: int=200000, base_cache_identity: str | None=None, offline_pairs: Mapping[tuple[str, str, str], Mapping[str, tuple[tuple[str, ...], float]]] | None=None, offline_parents: Collection[str] | None=None) -> None:
        """Initialize an immutable base graph/evaluation search context."""
        ...

    def clear_pair_cache(self) -> None:
        """Release request-local Port-pair paths once callers no longer need them."""
        ...

    @property
    def cache_hits(self) -> int:
        """Return all request-local and cross-request Port-pair cache hits."""
        ...

    @property
    def base_cache_hits(self) -> int:
        """Return cross-request immutable base Port-pair cache hits."""
        ...

    @property
    def offline_cache_hits(self) -> int:
        """Return port-pair cache hits served from offline precomputed pairs."""
        ...

    @property
    def base_cache_size(self) -> int:
        """Return the current bounded cross-request cache entry count."""
        ...

    @property
    def base_cache_misses(self) -> int:
        """Return eligible base searches not served by the cross-request cache."""
        ...

    @property
    def fine_search_calls(self) -> int:
        """Return all request-local fine-grid searches, including overlays."""
        ...

    @property
    def visited_parent_count(self) -> int:
        """Return unique parents expanded by exact macro searches."""
        ...

    def build_topology(self, start: str, goal: str, blocked: frozenset[str]=frozenset()) -> PortsMapTopology:
        """Build explicit boundary and temporary Ports for a request overlay."""
        ...

    def search(self, start: str, goal: str, profile: ScalarProfile, blocked: frozenset[str]=frozenset(), exploration_penalties: Mapping[str, int] | None=None, penalty_factor: float=0.0) -> PortsMapSearchResult:
        """Run exact weighted PortsMap search and expand the complete fine path."""
        ...

    def search_widest(self, start: str, goal: str, blocked: frozenset[str]=frozenset()) -> PortsMapSearchResult:
        """Find the maximum-minimum passability route with fixed metric tie-breaks."""
        ...

    def _all_port_pairs(self, topology: PortsMapTopology, profile: ScalarProfile, blocked: frozenset[str], penalties: Mapping[str, int], penalty_factor: float) -> dict[tuple[str, str], PortPairPath]:
        ...

    def _evict_stale_parent_contexts(self, parent: str, active_key: tuple[str, str, object, object, str]) -> None:
        """Bound cache growth while retaining immediate identical-search reuse."""
        ...

    def _get_or_compute_source_pairs(self, source: str, parent: str, port_ids: tuple[str, ...], profile: ScalarProfile, blocked: frozenset[str], penalties: Mapping[str, int], penalty_factor: float, local_penalty_key: tuple[tuple[str, int], ...], local_blocked_key: tuple[str, ...], port_hash: str, temporary_ports: frozenset[str]=frozenset(), temporary_destinations: frozenset[str]=frozenset(), goal: str | None=None, goal_connections: Mapping[str, tuple[float, tuple[str, ...]]] | None=None) -> list[tuple[str, tuple[str, ...], float]]:
        ...

    def _base_pair_key(self, parent: str, profile: ScalarProfile, port_hash: str, source: str, blocked: frozenset[str], local_penalty_key: tuple[tuple[str, int], ...], penalty_factor: float) -> tuple[str, str, str, str, str] | None:
        ...

    def _parent_port_pairs(self, parent: str, port_ids: tuple[str, ...], profile: ScalarProfile, blocked: frozenset[str], penalties: Mapping[str, int], penalty_factor: float) -> dict[tuple[str, str], PortPairPath]:
        ...

    def _fine_tile_search(self, source: str, allowed: set[str], profile: ScalarProfile, penalties: Mapping[str, int], penalty_factor: float, targets: set[str] | None=None) -> dict[str, tuple[float, tuple[str, ...]]]:
        ...

    def _backward_fine_search(self, goal: str, allowed: set[str], profile: ScalarProfile, penalties: Mapping[str, int], penalty_factor: float, targets: set[str]) -> dict[str, tuple[float, tuple[str, ...]]]:
        ...

    def _macro_search(self, topology: PortsMapTopology, start: str, goal: str, profile: ScalarProfile, blocked: frozenset[str], penalties: Mapping[str, int], penalty_factor: float, pairs: Mapping[tuple[str, str], PortPairPath] | None=None) -> tuple[tuple[str, ...], float, int]:
        ...

    def _validate_endpoints(self, start: str, goal: str, blocked: frozenset[str]) -> None:
        ...

    def _enforce_limits(self, ports: Mapping[str, Port], by_parent: Mapping[str, tuple[str, ...]]) -> None:
        ...

    def _parent(self, cell_id: str) -> str:
        ...

# PortsMapSearchContext._macro_search._h — L991
def _h(node: str) -> float:
    ...

# _base_pair_cache_get — L1200
def _base_pair_cache_get(key: tuple[str, str, str, str, str]) -> tuple[tuple[str, tuple[str, ...], float], ...] | None:
    ...

# _base_pair_cache_put — L1207
def _base_pair_cache_put(key: tuple[str, str, str, str, str], value: tuple[tuple[str, tuple[str, ...], float], ...]) -> None:
    ...

# _directed_neighbors — L1228
def _directed_neighbors(edges: Mapping[tuple[str, str], DirectedEdgeMetrics]) -> dict[str, tuple[str, ...]]:
    ...

# _penalized_cost — L1237
def _penalized_cost(edge: DirectedEdgeMetrics, profile: ScalarProfile, target: str, penalties: Mapping[str, int], penalty_factor: float) -> float:
    ...

# _is_better — L1248
def _is_better(candidate: tuple[float, tuple[str, ...]], current: tuple[float, tuple[str, ...]] | None) -> bool:
    ...

# _validate_continuous_path — L1259
def _validate_continuous_path(path: tuple[str, ...], edges: Mapping[tuple[str, str], DirectedEdgeMetrics]) -> None:
    ...

# _haversine_m — L1272
def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    ...
```
