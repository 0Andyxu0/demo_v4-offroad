# 模块参考：route_planning

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/route_planning.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`6abf09c6a45060024dcf010c6c2c2221cfa0c54c36ef14b584bc5ff69f3f9295`；类 0 个，函数/方法 13 个（含嵌套定义）。
- 项目内导入依赖：`candidate_aggregation`, `config`, `dynamics.trajectory_geometry`, `environment`, `factor_model`, `grid.h3_grid_builder`, `models`, `offline_pairs`, `planners.deterministic_pareto`, `portsmap`, `reachability`, `route_models`, `route_persistence`, `routing`, `routing_index`。
- 直接导入本模块者：`cli`, `h3_offroad_planner`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L85
ProgressCallback = Callable[[str, int, str], None]
```

```text
# L594 _run_route_plan_once
'route_plan' => paths['route_plan']
'routes_geojson' => paths['routes_geojson']

# L603 _run_route_plan_once
'schema_version' => schema_version
'mission_profile' => request.mission_profile
'recommended_candidate_id' => recommended_candidate_id
'independence_reference_candidate_id' => aggregation.independence_reference_candidate_id
'vehicle_hash' => evaluation.vehicle_hash
'factor_model_hash' => evaluation.factor_model_hash
'static_input_hash' => evaluation.static_input_hash
'graph_topology_hash' => evaluation.graph_topology_hash
'candidate_ids' => [candidate.candidate_id for candidate in candidates]
'candidate_roles' => [list(candidate.roles) for candidate in candidates]

# L694 _run_route_plan_once
** => {key: round(value, 6) for key, value in timings.items()}
'loaded_file_count' => _mapping_int(source_metadata, 'source_loaded_file_count', 1)
'raw_row_count' => _mapping_int(source_metadata, 'source_raw_row_count', len(graph.cells))
'cell_count' => len(graph.cells)
'edge_count' => len(graph.edges)
'candidate_pool_count' => _mapping_int(aggregation.statistics, 'raw_count', 0)
'returned_candidate_count' => len(candidates)
'corridor_ring' => _mapping_int(source_metadata, 'corridor_ring', 0)
'active_parent_count' => _mapping_list_len(source_metadata, 'active_parent_h3')
'targeted_repair_attempts' => repair_attempts
'repaired_parent_count' => len(added_repair_parents)
'search_policy' => search_policy
'profile_search_count' => planner.profile_search_count
'fine_search_calls' => context.fine_search_calls
'visited_parent_count' => context.visited_parent_count
'coarse_widest_included' => source_metadata.get('coarse_widest_included')
'coarse_widest_parent_count' => source_metadata.get('coarse_widest_parent_count')
'pair_cache_hits' => context.cache_hits
'base_pair_cache_hits' => context.base_cache_hits
'base_pair_cache_misses' => context.base_cache_misses
'base_pair_cache_entries' => context.base_cache_size
'offline_pair_hits' => context.offline_cache_hits
'output_bytes' => output_bytes

# L801 _scenario_hash
'request_pressures' => list(static_planning.environment.request_pressures)
'environment_snapshot_hash' => environment_snapshot_hash

# L826 _with_trajectory
'type' => 'Feature'
'properties' => { 'h3_path' => list(candidate.h3_path); 'trajectory_id' => trajectory.trajectory_id }
'geometry' => { 'type' => 'LineString'; 'coordinates' => coordinates }

# L477 _run_route_plan_once
'routing_index_build_id' => source_metadata.get('build_id')
'vehicle_hash' => evaluation.vehicle_hash
'factor_model_hash' => evaluation.factor_model_hash
'scenario_hash' => _scenario_hash(static_planning, environment_snapshot_hash)

# L617 _run_route_plan_once
'planning_policy_hash' => policy_hash
'scenario_hash' => scenario_hash
'trajectory_ids' => [candidate.trajectory.get('trajectory_id') for candidate in candidates]

# L637 _run_route_plan_once
** => aggregation.statistics
'max_candidate_paths' => request.max_candidate_paths
'candidate_limit' => request.candidate_limit
'penalty_factor' => request.penalty_factor
'search_policy' => search_policy
'profile_search_count' => planner.profile_search_count
'environment_snapshot' => environment_snapshot
'environment_snapshot_hash' => environment_snapshot_hash
'environment_pressure_basis' => None if static_planning is None else static_planning.environment.pressure_basis
** => robust_statistics
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from math import inf
from pathlib import Path
from time import perf_counter
from typing import cast
import yaml
from h3_offroad_planner.candidate_aggregation import CandidateAggregator, select_robust_candidates
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.dynamics.trajectory_geometry import TrajectoryResult, build_and_validate_trajectory
from h3_offroad_planner.environment import resolve_request_environment
from h3_offroad_planner.factor_model import EnvironmentConfig, FactorEvaluation, FactorModelConfig, StaticPlanningConfig, build_directed_edge_cache, canonical_hash, evaluate_factor_model, load_factor_model, load_static_planning_config, write_effective_snapshots, write_static_planning_snapshot
from h3_offroad_planner.grid.h3_grid_builder import H3GridBuilder, _edge_from_cells, _haversine_m, _safe_neighbors
from h3_offroad_planner.models import ConfigError, GridBuildError, H3Graph, PlanningFailedError, PlanningInputError, RouteEndpoint, RouteRequest, VehicleProfile
from h3_offroad_planner.offline_pairs import default_vehicle
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.reachability import ReachabilityDisconnectionError, check_route_reachability
from h3_offroad_planner.route_models import RouteCandidate, RoutePlan, plan_id_for_payload
from h3_offroad_planner.route_persistence import atomic_write_json, delivery_output_paths, write_route_plan_outputs, write_routes_gpkg
from h3_offroad_planner.routing import _load_route_graph, _oversize_message, _request_endpoints, _resolve_roi, _single_endpoint, _source_metadata, estimate_h3_cells_for_roi, expand_targeted_bottleneck_parents
from h3_offroad_planner.routing_index import RoutingIndex, open_routing_index

# run_route_plan — L88
def run_route_plan(request: RouteRequest, progress: ProgressCallback | None=None, progress_range: tuple[int, int]=(75, 95), *, export_gpkg: bool=True) -> RoutePlan:
    """Plan through a 1-ring indexed corridor, with one bounded 2-ring retry."""
    ...

# _incrementally_expand_route_graph — L120
def _incrementally_expand_route_graph(index: RoutingIndex, graph: H3Graph, evaluation: FactorEvaluation, vehicle: VehicleProfile, factor_config: FactorModelConfig, new_parents: set[str], environment: EnvironmentConfig | None=None) -> tuple[H3Graph, FactorEvaluation, float, float]:
    """Incrementally add new parent tiles to an existing graph and evaluation.

    Avoids full rebuild of the corridor graph.
    """
    ...

# _run_route_plan_once — L200
def _run_route_plan_once(request: RouteRequest, progress: ProgressCallback | None, progress_range: tuple[int, int], *, corridor_ring: int, request_started: float, extra_warning: str | None=None, export_gpkg: bool=False) -> RoutePlan:
    """Create and persist a complete RoutePlan without activating any candidate."""
    ...

# _routing_role_warnings — L725
def _routing_role_warnings(assigned_roles: set[str], *, require_independent_backup: bool=False) -> tuple[str, ...]:
    """Validate the four metric roles and soften independent-backup absence."""
    ...

# _routing_index_available — L752
def _routing_index_available(source: str) -> bool:
    ...

# _bind_loaded_index_identity — L759
def _bind_loaded_index_identity(source_metadata: dict[str, object], evaluation: FactorEvaluation, vehicle: VehicleProfile, static_planning: StaticPlanningConfig | None, environment_snapshot_hash: str='') -> None:
    ...

# _scenario_hash — L794
def _scenario_hash(static_planning: StaticPlanningConfig | None, environment_snapshot_hash: str) -> str:
    ...

# _mapping_int — L808
def _mapping_int(payload: dict[str, object], key: str, default: int) -> int:
    ...

# _mapping_list_len — L813
def _mapping_list_len(payload: dict[str, object], key: str) -> int:
    ...

# _with_trajectory — L818
def _with_trajectory(candidate: RouteCandidate, trajectory: TrajectoryResult) -> RouteCandidate:
    ...

# _validate_route_plan_planner — L837
def _validate_route_plan_planner(path: str) -> None:
    """Require the unique new-flow planner name and reject stale configuration."""
    ...

# _snap_evaluated — L859
def _snap_evaluated(graph: H3Graph, evaluation: FactorEvaluation, endpoint: RouteEndpoint, max_distance_m: float) -> str:
    ...

# _restore_static_authority — L887
def _restore_static_authority(graph: H3Graph, source_metadata: dict[str, object]) -> None:
    ...
```
