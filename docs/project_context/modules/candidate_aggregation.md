# 模块参考：candidate_aggregation

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/candidate_aggregation.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`80889967bcc787ae2b82ae7b4e55a39452b2a15d22ab3e94a894a5039bb79981`；类 2 个，函数/方法 32 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`, `planners.deterministic_pareto`, `portsmap`, `route_models`。
- 直接导入本模块者：`replanning`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# AggregationResult — src/h3_offroad_planner/candidate_aggregation.py:44
@dataclass(frozen=True)
class AggregationResult:
    'Unique role candidates or a bounded pre-display candidate pool.'
    candidates: tuple[RouteCandidate, ...]
    recommended_candidate_id: str
    independence_reference_candidate_id: str | None
    warnings: tuple[str, ...]
    statistics: dict[str, object]
    ...

# CandidateAggregator — src/h3_offroad_planner/candidate_aggregation.py:54
class CandidateAggregator:
    'Aggregate raw deterministic paths into five fixed product roles.'
    # self.graph: 未注解; L66; initial=graph
    # self.context: 未注解; L67; initial=context
    # self.disruption_radius: 未注解; L68; initial=disruption_radius
    ...
```

```text
# L27 <module>
'fastest' => 'fastest_eta'
'shortest' => 'shortest_distance'
'passability' => 'max_passability_margin'
'economy' => 'minimum_travel_cost'
'resilient' => 'independent_backup'

# L34 <module>
'fastest_eta' => 'eta'
'shortest_distance' => 'distance'
'max_passability_margin' => 'passability_then_terrain_risk'
'minimum_travel_cost' => 'travel_cost'
'independent_backup' => 'resilient_eta'

# L545 _assign_metric_roles
'fastest_eta' => min(values, key=_fastest_key)
'shortest_distance' => min(values, key=_shortest_key)
'max_passability_margin' => min(values, key=_passability_key)
'minimum_travel_cost' => min(values, key=_travel_cost_key)

# L241 CandidateAggregator._independent_backup
'reference_candidate_id' => candidate_id_for_path(reference.h3_path)
'core_kind' => core_kind
'blocked_core_parents' => core_parents
'blocked_core_cells' => core_cells
'masked_parents' => sorted(masked_parents)
'blocked_cells_count' => len(blocked)
'survived_disruption' => True
'candidate_corridor' => list(self._corridor_signature(independent.h3_path))

# L307 CandidateAggregator._route_geojson
'type' => 'Feature'
'properties' => { 'h3_path' => list(path) }
'geometry' => { 'type' => 'LineString'; 'coordinates' => coordinates }

# L454 select_robust_candidates
'length_reference_scope' => 'candidate_pool'
'length_reference_m' => length_reference
'detour_ratio' => policy.detour_ratio
'length_budget_m' => limit
'geometry_valid_count' => len(valid)
'budget_candidate_count' => len(budgeted)
'clearance_target_m' => policy.clearance_target_m
'switch_reason' => switch_reason
'previous_candidate_id' => current_candidate_id
'request_pressures' => list(request_pressures)

# L389 select_robust_candidates
'length_reference_scope' => 'candidate_pool'
'length_reference_m' => None
'geometry_valid_count' => 0

# L126 CandidateAggregator.aggregate
'raw_count' => len(raw_candidates)
'unique_count' => len(validated)
'pareto_count' => len(pareto)
'cluster_representative_count' => len(representatives)
'returned_count' => len(candidates)
'independent_backup_available' => independent is not None
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from dataclasses import dataclass, replace
from math import isclose, isfinite
from h3_offroad_planner.factor_model import PHYSICAL_EVIDENCE_WARNING, DecisionConfig, PathMetrics, evaluate_path_metrics
from h3_offroad_planner.models import H3Graph, PlanningFailedError, PlanningInputError
from h3_offroad_planner.planners.deterministic_pareto import GeneratedPath
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile
from h3_offroad_planner.route_models import MISSION_PROFILES, PATH_ROLES, RouteCandidate, candidate_id_for_path

# AggregationResult — L44
@dataclass(frozen=True)
class AggregationResult:
    """Unique role candidates or a bounded pre-display candidate pool."""

# CandidateAggregator — L54
class CandidateAggregator:
    """Aggregate raw deterministic paths into five fixed product roles."""

    def __init__(self, graph: H3Graph, context: PortsMapSearchContext, disruption_radius: int=0) -> None:
        """Initialize corridor and disruption analysis for one immutable graph."""
        ...

    def aggregate(self, raw_candidates: list[GeneratedPath], mission_profile: str, max_candidates: int=5, *, preserve_pool: bool=False) -> AggregationResult:
        """Return exact unique candidates, merged roles, and mission recommendation."""
        ...

    def _evidence_warnings(self, candidates: tuple[RouteCandidate, ...]) -> tuple[str, ...]:
        ...

    def _validated_unique(self, raw_candidates: list[GeneratedPath]) -> dict[tuple[str, ...], GeneratedPath]:
        ...

    def _cluster_representatives(self, candidates: dict[tuple[str, ...], GeneratedPath]) -> dict[tuple[str, ...], GeneratedPath]:
        ...

    def _independent_backup(self, reference: GeneratedPath, existing: dict[tuple[str, ...], GeneratedPath]) -> tuple[GeneratedPath | None, dict[str, object]]:
        ...

    def _independence_key(self, reference: GeneratedPath, candidate: GeneratedPath) -> tuple[int, int, float, float, float, tuple[int, ...]]:
        ...

    def _route_candidates(self, representatives: dict[tuple[str, ...], GeneratedPath], roles: dict[tuple[str, ...], list[str]], evidence: dict[str, object], *, include_unassigned: bool=False) -> tuple[RouteCandidate, ...]:
        ...

    def _route_geojson(self, path: tuple[str, ...]) -> dict[str, object]:
        ...

    def _corridor_signature(self, path: tuple[str, ...]) -> tuple[str, ...]:
        ...

    def _corridor_core(self, path: tuple[str, ...]) -> tuple[str, set[str]]:
        """Return a maskable independence core for short and long corridors.

        Parent-level signatures become empty for paths that cross two or fewer
        parent cells.  For those short corridors we fall back to fine H3 cells so
        the independence search has a non-empty disruption set.  Start and goal
        parent cells are never treated as interior corridor parents.
        """
        ...

    def _dilated_parents(self, parents: set[str]) -> set[str]:
        ...

    def _parent(self, cell_id: str) -> str:
        ...

# select_robust_candidates — L373
def select_robust_candidates(candidates: tuple[RouteCandidate, ...], policy: DecisionConfig, current_candidate_id: str | None=None, request_pressures: tuple[float, ...]=()) -> tuple[tuple[RouteCandidate, ...], str, dict[str, object], tuple[str, ...]]:
    """Apply the candidate-pool detour budget, robust order, and optional hysteresis."""
    ...

# _robust_key — L470
def _robust_key(candidate: RouteCandidate, policy: DecisionConfig, request_pressures: tuple[float, ...]=()) -> tuple[float, float, float, str]:
    ...

# _clearance_bucket — L483
def _clearance_bucket(candidate: RouteCandidate, policy: DecisionConfig) -> int:
    ...

# _worst_environment_distance — L491
def _worst_environment_distance(candidate: RouteCandidate, request_pressures: tuple[float, ...]=()) -> float:
    ...

# _pressure_key — L507
def _pressure_key(pressure_kpa: float) -> str:
    ...

# _trajectory_number — L511
def _trajectory_number(candidate: RouteCandidate, field: str) -> float:
    ...

# _pareto_candidates — L518
def _pareto_candidates(candidates: dict[tuple[str, ...], GeneratedPath]) -> dict[tuple[str, ...], GeneratedPath]:
    ...

# _dominates — L531
def _dominates(first: GeneratedPath, second: GeneratedPath) -> bool:
    ...

# _assign_metric_roles — L539
def _assign_metric_roles(candidates: dict[tuple[str, ...], GeneratedPath]) -> dict[tuple[str, ...], list[str]]:
    ...

# _recommendation — L557
def _recommendation(mission_profile: str, candidates: tuple[RouteCandidate, ...], fastest_candidate_id: str) -> tuple[str, str | None, tuple[str, ...]]:
    ...

# _truncate_candidates — L572
def _truncate_candidates(candidates: tuple[RouteCandidate, ...], recommended: str, limit: int) -> tuple[RouteCandidate, ...]:
    ...

# _same_metrics — L592
def _same_metrics(first: PathMetrics, second: PathMetrics) -> bool:
    ...

# _balanced_tie_key — L623
def _balanced_tie_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    ...

# _fastest_key — L633
def _fastest_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    ...

# _shortest_key — L637
def _shortest_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    ...

# _passability_key — L641
def _passability_key(path: GeneratedPath) -> tuple[float, float, float, float, tuple[str, ...]]:
    ...

# _travel_cost_key — L651
def _travel_cost_key(path: GeneratedPath) -> tuple[float, float, float, tuple[str, ...]]:
    ...

# _route_candidate_sort_key — L660
def _route_candidate_sort_key(candidate: RouteCandidate) -> tuple[int, float, float, tuple[str, ...]]:
    ...

# _truncate_candidate_pool — L670
def _truncate_candidate_pool(candidates: tuple[RouteCandidate, ...], recommended: str, limit: int) -> tuple[RouteCandidate, ...]:
    """Bound an internal pool while preserving its selected candidate."""
    ...
```
