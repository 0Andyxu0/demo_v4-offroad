# 模块参考：route_models

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/route_models.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`1b51b15a0fe5d25f6520adbe0aaf8cd2bc0b105999ba31aabf97928228c23dae`；类 6 个，函数/方法 12 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`。
- 直接导入本模块者：`candidate_aggregation`, `cli`, `h3_offroad_planner`, `replanning`, `route_persistence`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# RouteCandidate — src/h3_offroad_planner/route_models.py:44
@dataclass(frozen=True)
class RouteCandidate:
    'One unique fine-grid route with zero or more deterministic product roles.'
    candidate_id: str
    h3_path: tuple[str, ...]
    roles: tuple[str, ...]
    is_recommended: bool
    objectives: Mapping[str, float]
    metrics: PathMetrics
    corridor_signature: tuple[str, ...]
    independence_evidence: Mapping[str, object] = field(default_factory=dict)
    geojson: Mapping[str, object] = field(default_factory=dict)
    generation_profile: str = 'unknown'
    replan_profile: str = 'eta'
    trajectory: Mapping[str, object] = field(default_factory=dict)
    ...

# RoutePlan — src/h3_offroad_planner/route_models.py:104
@dataclass(frozen=True)
class RoutePlan:
    'Stable planning result written before any user route is activated.'
    plan_id: str
    mission_profile: str
    recommended_candidate_id: str
    independence_reference_candidate_id: str | None
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str
    candidates: tuple[RouteCandidate, ...]
    planning_policy_hash: str = ''
    scenario_hash: str = ''
    aggregation_stats: Mapping[str, object] = field(default_factory=dict)
    output_files: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    planner_name: str = 'DeterministicParetoPlanner'
    schema_version: int = 1
    ...

# RouteSelection — src/h3_offroad_planner/route_models.py:198
@dataclass(frozen=True)
class RouteSelection:
    'Persisted explicit user activation and current active-route state.'
    plan_id: str
    candidate_id: str
    selected_role: str
    active_h3_path: tuple[str, ...]
    active_metrics: PathMetrics
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str
    state: str = 'active'
    replan_version: int = 0
    selection_version: int = 1
    active_trajectory: Mapping[str, object] = field(default_factory=dict)
    ...

# BlockageRecord — src/h3_offroad_planner/route_models.py:250
@dataclass(frozen=True)
class BlockageRecord:
    'Persistable blockage observation lifecycle record.'
    blockage_id: str
    h3index: str
    state: str
    confirmation_count: int
    trusted_source: bool
    observed_at_epoch_s: float
    expires_at_epoch_s: float | None = None
    mission_lifetime: bool = False
    source: str = 'user'
    ...

# ReplanRequest — src/h3_offroad_planner/route_models.py:280
@dataclass(frozen=True)
class ReplanRequest:
    'Explicit local-replan input; current position is never inferred.'
    selection_path: str
    blockage_observations: tuple[BlockageRecord, ...]
    current_h3: str | None = None
    current_lat: float | None = None
    current_lng: float | None = None
    snap_distance_m: float = 20000.0
    now_epoch_s: float = 0.0
    ...

# ReplanResult — src/h3_offroad_planner/route_models.py:311
@dataclass(frozen=True)
class ReplanResult:
    'Product-level result of one local repair or global fallback attempt.'
    plan_id: str
    candidate_id: str
    algorithm: str
    status: str
    replan_version: int
    old_path_hash: str
    new_path_hash: str | None
    metrics_before: PathMetrics
    metrics_after: PathMetrics | None
    warnings: tuple[str, ...] = ()
    ...
```

校验 `RouteCandidate.__post_init__`：

- `L61 if not self.candidate_id or not self.h3_path` → `raise ValueError('candidate_id and h3_path must be non-empty.')`
- `L63 if self.candidate_id != candidate_id_for_path(self.h3_path)` → `raise ValueError('candidate_id must equal the stable H3 path hash.')`
- `L65 if len(set(self.roles)) != len(self.roles) or set(self.roles).difference(PATH_ROLES)` → `raise ValueError('candidate roles must be unique known role names.')`
- `L67 if any((not isfinite(value) or value < 0.0 for value in self.objectives.values()))` → `raise ValueError('candidate objectives must be finite and non-negative.')`
- `L69 if not self.generation_profile or not self.replan_profile` → `raise ValueError('candidate profiles must be non-empty.')`
- `L81 if status not in {'valid', 'invalid', 'not_evaluated', 'incomplete'}` → `raise ValueError('candidate trajectory status is invalid.')`

校验 `RoutePlan.__post_init__`：

- `L125 if self.mission_profile not in MISSION_PROFILES` → `raise ValueError(f'mission_profile must be one of {MISSION_PROFILES!r}.')`
- `L127 if not 1 <= len(self.candidates) <= 5` → `raise ValueError('RoutePlan must contain one to five candidates.')`
- `L130 if len(set(identifiers)) != len(identifiers)` → `raise ValueError('RoutePlan candidates must be unique.')`
- `L132 if self.recommended_candidate_id not in identifiers` → `raise ValueError('recommended_candidate_id must identify a candidate.')`
- `L134 if sum((candidate.is_recommended for candidate in self.candidates)) != 1` → `raise ValueError('RoutePlan must mark exactly one recommended candidate.')`
- `L136 if self.planner_name != 'DeterministicParetoPlanner'` → `raise ValueError('new RoutePlan outputs must use DeterministicParetoPlanner.')`
- `L138 if self.plan_id != plan_id_for_payload(self.identity_payload())` → `raise ValueError('plan_id does not match the canonical plan identity payload.')`

校验 `RouteSelection.__post_init__`：

- `L216 if not self.plan_id or not self.candidate_id or (not self.active_h3_path)` → `raise ValueError('selection identifiers and active path must be non-empty.')`
- `L218 if self.selected_role not in PATH_ROLES` → `raise ValueError('selected_role must be a known path role.')`
- `L220 if self.state not in ROUTE_STATES` → `raise ValueError(f'selection state must be one of {sorted(ROUTE_STATES)}.')`
- `L222 if self.replan_version < 0 or self.selection_version <= 0` → `raise ValueError('selection versions are outside their valid ranges.')`

校验 `BlockageRecord.__post_init__`：

- `L264 if not self.blockage_id or not self.h3index or (not self.source)` → `raise ValueError('blockage identifiers and source must be non-empty.')`
- `L266 if self.state not in BLOCKAGE_STATES` → `raise ValueError(f'blockage state must be one of {sorted(BLOCKAGE_STATES)}.')`
- `L268 if self.confirmation_count <= 0` → `raise ValueError('confirmation_count must be positive.')`
- `L270 if not isfinite(self.observed_at_epoch_s) or self.observed_at_epoch_s < 0.0` → `raise ValueError('observed_at_epoch_s must be finite and non-negative.')`
- `L273 if not isfinite(self.expires_at_epoch_s)` → `raise ValueError('expires_at_epoch_s must be finite when provided.')`
- `L275 if self.expires_at_epoch_s <= self.observed_at_epoch_s` → `raise ValueError('expires_at_epoch_s must follow observed_at_epoch_s.')`

校验 `ReplanRequest.__post_init__`：

- `L292 if not self.selection_path` → `raise ValueError('selection_path must be non-empty.')`
- `L296 if has_h3 == has_coordinates` → `raise ValueError('provide exactly one of current_h3 or current_lat/current_lng.')`
- `L298 if (self.current_lat is None) != (self.current_lng is None)` → `raise ValueError('current_lat and current_lng must be provided together.')`
- `L300 if self.current_lat is not None and (not -90.0 <= self.current_lat <= 90.0)` → `raise ValueError('current_lat must be in [-90, 90] degrees.')`
- `L302 if self.current_lng is not None and (not -180.0 <= self.current_lng <= 180.0)` → `raise ValueError('current_lng must be in [-180, 180] degrees.')`
- `L304 if not isfinite(self.snap_distance_m) or self.snap_distance_m <= 0.0` → `raise ValueError('snap_distance_m must be finite and positive.')`
- `L306 if not isfinite(self.now_epoch_s) or self.now_epoch_s < 0.0` → `raise ValueError('now_epoch_s must be finite and non-negative.')`

校验 `ReplanResult.__post_init__`：

- `L326 if self.status not in ROUTE_STATES` → `raise ValueError('replan status is invalid.')`
- `L328 if self.algorithm not in {'DStarLite', 'global_fallback', 'safe_hold'}` → `raise ValueError('replan algorithm is invalid.')`
- `L330 if self.replan_version < 0` → `raise ValueError('replan_version must be non-negative.')`

```python
# L25
PATH_ROLES: tuple[str, ...] = ('fastest_eta', 'shortest_distance', 'max_passability_margin', 'minimum_travel_cost', 'independent_backup')
# L32
MISSION_PROFILES: tuple[str, ...] = ('fastest', 'shortest', 'passability', 'economy', 'resilient')
# L39
ROUTE_STATES: frozenset[str] = frozenset({'active', 'safe_hold', 'superseded', 'invalidated'})
# L40
BLOCKAGE_STATES: frozenset[str] = frozenset({'tentative', 'confirmed', 'cleared', 'expired'})
```

```text
# L87 RouteCandidate.to_dict
'candidate_id' => self.candidate_id
'h3_path' => list(self.h3_path)
'roles' => list(self.roles)
'is_recommended' => self.is_recommended
'objectives' => dict(sorted(self.objectives.items()))
'metrics' => self.metrics.to_dict()
'corridor_signature' => list(self.corridor_signature)
'independence_evidence' => dict(self.independence_evidence)
'geojson' => dict(self.geojson)
'generation_profile' => self.generation_profile
'replan_profile' => self.replan_profile
'trajectory' => dict(self.trajectory)

# L149 RoutePlan.identity_payload
'schema_version' => self.schema_version
'mission_profile' => self.mission_profile
'recommended_candidate_id' => self.recommended_candidate_id
'independence_reference_candidate_id' => self.independence_reference_candidate_id
'vehicle_hash' => self.vehicle_hash
'factor_model_hash' => self.factor_model_hash
'static_input_hash' => self.static_input_hash
'graph_topology_hash' => self.graph_topology_hash
'candidate_ids' => [candidate.candidate_id for candidate in self.candidates]
'candidate_roles' => [list(candidate.roles) for candidate in self.candidates]

# L177 RoutePlan.to_dict
'schema_version' => self.schema_version
'plan_id' => self.plan_id
'planner_name' => self.planner_name
'mission_profile' => self.mission_profile
'recommended_candidate_id' => self.recommended_candidate_id
'independence_reference_candidate_id' => self.independence_reference_candidate_id
'vehicle_hash' => self.vehicle_hash
'factor_model_hash' => self.factor_model_hash
'static_input_hash' => self.static_input_hash
'graph_topology_hash' => self.graph_topology_hash
'planning_policy_hash' => self.planning_policy_hash
'scenario_hash' => self.scenario_hash
'candidates' => [candidate.to_dict() for candidate in self.candidates]
'aggregation_stats' => dict(self.aggregation_stats)
'output_files' => dict(self.output_files)
'warnings' => list(self.warnings)

# L232 RouteSelection.to_dict
'plan_id' => self.plan_id
'candidate_id' => self.candidate_id
'selected_role' => self.selected_role
'active_h3_path' => list(self.active_h3_path)
'active_metrics' => self.active_metrics.to_dict()
'vehicle_hash' => self.vehicle_hash
'factor_model_hash' => self.factor_model_hash
'static_input_hash' => self.static_input_hash
'graph_topology_hash' => self.graph_topology_hash
'state' => self.state
'replan_version' => self.replan_version
'selection_version' => self.selection_version
'active_trajectory' => dict(self.active_trajectory)

# L165 RoutePlan.identity_payload
'planning_policy_hash' => self.planning_policy_hash
'scenario_hash' => self.scenario_hash
'trajectory_ids' => [candidate.trajectory.get('trajectory_id') for candidate in self.candidates]
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from h3_offroad_planner.factor_model import PathMetrics, canonical_hash

# RouteCandidate — L44
@dataclass(frozen=True)
class RouteCandidate:
    """One unique fine-grid route with zero or more deterministic product roles."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping in canonical field order."""
        ...

# RoutePlan — L104
@dataclass(frozen=True)
class RoutePlan:
    """Stable planning result written before any user route is activated."""

    def __post_init__(self) -> None:
        ...

    def identity_payload(self) -> dict[str, object]:
        """Return deterministic fields participating in stable plan identity."""
        ...

    def to_dict(self) -> dict[str, object]:
        """Return the complete JSON-compatible public plan contract."""
        ...

# RouteSelection — L198
@dataclass(frozen=True)
class RouteSelection:
    """Persisted explicit user activation and current active-route state."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible persisted selection mapping."""
        ...

# BlockageRecord — L250
@dataclass(frozen=True)
class BlockageRecord:
    """Persistable blockage observation lifecycle record."""

    def __post_init__(self) -> None:
        ...

# ReplanRequest — L280
@dataclass(frozen=True)
class ReplanRequest:
    """Explicit local-replan input; current position is never inferred."""

    def __post_init__(self) -> None:
        ...

# ReplanResult — L311
@dataclass(frozen=True)
class ReplanResult:
    """Product-level result of one local repair or global fallback attempt."""

    def __post_init__(self) -> None:
        ...

# candidate_id_for_path — L334
def candidate_id_for_path(h3_path: tuple[str, ...] | list[str]) -> str:
    """Return stable candidate id from the complete ordered H3 sequence."""
    ...

# plan_id_for_payload — L341
def plan_id_for_payload(payload: Mapping[str, object]) -> str:
    """Return stable plan id from a canonical identity payload."""
    ...
```
