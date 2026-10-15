# 模块参考：route_persistence

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/route_persistence.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`aa04eb2c2e3f34b308c4a7084f6e57de15e795b83d6e3c650e97a2b29749dd8c`；类 0 个，函数/方法 59 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`, `route_models`, `routing_index`。
- 直接导入本模块者：`cli`, `desktop_client`, `replanning`, `route_planning`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L43
CRS_WGS84: str = 'EPSG:4326'
# L44
GRAPH_EDGE_TABLE: str = 'h3_edges'
# L45
LEGACY_DUPLICATE_OUTPUTS: tuple[str, ...] = ('route_candidates.geojson', 'route_recommended.geojson', 'style_manifest.json', 'selected_route.geojson', 'active_route.geojson')
```

```text
# L57 delivery_output_paths
'effective_vehicle' => str(root / 'effective_vehicle.yaml')
'effective_factor_model' => str(root / 'effective_factor_model.yaml')
'tile_manifest' => str(root / 'tile_manifest.json')
'route_manifest' => str(root / 'route_manifest.json')
'route_plan' => str(root / 'route_plan.json')
'routes' => str(root / 'routes.gpkg')
'routes_geojson' => str(root / 'routes.geojson')
'route_selection' => str(root / 'route_selection.json')
'replan_history' => str(root / 'replan_history.jsonl')

# L205 _route_manifest_payload
'schema_version' => 3
'plan_id' => plan.plan_id
'planner_name' => plan.planner_name
'candidate_count' => len(plan.candidates)
'recommended_candidate_id' => plan.recommended_candidate_id
'routing_index_build_id' => source_metadata.get('build_id')
'active_parent_h3' => _object_list(source_metadata, 'active_parent_h3')
'evidence_status' => source_metadata.get('evidence_status', 'INCOMPLETE')
'missing_physical_inputs' => _object_list(source_metadata, 'missing_physical_inputs')
'vehicle_hash' => plan.vehicle_hash
'factor_model_hash' => plan.factor_model_hash
'static_input_hash' => plan.static_input_hash
'graph_topology_hash' => plan.graph_topology_hash
'planning_policy_hash' => plan.planning_policy_hash
'scenario_hash' => plan.scenario_hash
'environment_snapshot' => environment_snapshot
'environment_snapshot_hash' => environment_snapshot_hash
'selection_basis' => dict(plan.aggregation_stats)
'output_files' => dict(output_files)
'graph_storage' => dict(graph_storage)

# L654 _active_feature
'type' => 'Feature'
'properties' => { 'plan_id' => selection.plan_id; 'candidate_id' => selection.candidate_id; 'selected_role' => selection.selected_role; 'state' => selection.state; 'replan_version' => selection.replan_version; ** => selection.active_metrics.to_dict() }
'geometry' => { 'type' => 'LineString'; 'coordinates' => coordinates }

# L855 _candidate_collection
'type' => 'FeatureCollection'
'features' => [_candidate_feature(candidate) for candidate in candidates]

# L923 _candidate_feature
'type' => 'Feature'
'properties' => { 'candidate_id' => candidate.candidate_id; 'roles' => ','.join(candidate.roles); 'is_recommended' => candidate.is_recommended; 'is_selected' => False; 'is_active' => False; 'eta_s' => candidate.metrics.eta_s; 'eta_lower_s' => candidate.metrics.eta_lower_s; 'eta_upper_s' => candidate.metrics.eta_upper_s; 'distance_m' => candidate.metrics.distance_m; 'score_lower_min' => candidate.metrics.safety_margin_min; 'terrain_risk' => candidate.metrics.terrain_risk; 'travel_cost' => candidate.metrics.travel_cost; 'trajectory_status' => candidate.trajectory.get('status', 'not_evaluated'); 'environment_distance_m' => json.dumps(candidate.trajectory.get('environment_distance_m', {}), sort_keys=True, separators=(',', ':')) }
'geometry' => geometry

# L124 write_route_plan_outputs
'format' => 'routing_index'
'path' => str(tile_manifest.get('routing_index_manifest', tile_manifest['source_manifest']))
'build_id' => str(tile_manifest['build_id'])
'active_parent_h3' => _object_list(tile_manifest, 'active_parent_h3')
'resolution_fine' => graph.resolution_fine
'resolution_coarse' => graph.resolution_coarse

# L152 write_route_plan_outputs
'schema_version' => 2
'plan_id' => plan.plan_id
'planner_name' => plan.planner_name
'candidate_count' => len(plan.candidates)
'recommended_candidate_id' => plan.recommended_candidate_id
'vehicle_hash' => plan.vehicle_hash
'factor_model_hash' => plan.factor_model_hash
'static_input_hash' => plan.static_input_hash
'graph_topology_hash' => plan.graph_topology_hash
'planning_policy_hash' => plan.planning_policy_hash
'scenario_hash' => plan.scenario_hash
'selection_basis' => dict(plan.aggregation_stats)
'output_files' => output_files
'graph_storage' => { 'format' => 'gpkg'; 'path' => Path(actual_routes_path).name; 'cells_layer' => 'h3_static_facts'; 'edges_table' => GRAPH_EDGE_TABLE; 'resolution_fine' => graph.resolution_fine; 'resolution_coarse' => graph.resolution_coarse }

# L895 _update_route_collection
'type' => 'FeatureCollection'
'features' => updated

# L900 _empty_route_gdf
'candidate_id' => pd.Series(dtype='str')
'roles' => pd.Series(dtype='str')

# L911 _empty_blockage_gdf
'blockage_id' => pd.Series(dtype='str')
'h3index' => pd.Series(dtype='str')
'state' => pd.Series(dtype='str')

# L690 _blockage_gdf
'blockage_id' => record.blockage_id
'h3index' => record.h3index
'state' => record.state
'confirmation_count' => record.confirmation_count
'source' => record.source

# L810 _static_facts_gdf
'h3index' => cell.h3index
'parent_h3' => cell.parent_h3
'elevation' => cell.elevation
'slope' => cell.slope
'tri' => cell.tri
'lc_factor' => None if cell.lc_factor == float('inf') else cell.lc_factor
'lc_factor_infinite' => cell.lc_factor == float('inf')
'landcover_code' => cell.landcover_code
'landcover_type' => cell.landcover_type
'soil_code' => cell.soil_code
'soil_type' => cell.soil_type
'soil_texture' => cell.soil_texture
'uscs' => cell.uscs
'soil_moisture' => cell.soil_moisture
'soil_source' => cell.soil_source
'source_support_m' => cell.source_support_m
'twi' => cell.twi
'drainage_sensitivity' => cell.drainage_sensitivity
'drainage_valid' => cell.drainage_valid
'drainage_boundary_affected' => cell.drainage_boundary_affected
'surface_response' => cell.surface_response
'surface_evidence' => cell.surface_evidence
'has_road' => cell.has_road
'static_passable' => cell.is_passable
'authority_for_new_routing' => True
```

```text
L145: paths['routes'] <- actual_routes_path
L147: output_files['routes'] <- actual_routes_path
L889: properties['is_selected'] <- selected
L890: properties['is_active'] <- selected
L891: feature['properties'] <- properties
L741: f'\n            CREATE TABLE {GRAPH_EDGE_TABLE} (\n                cell_a TEXT NOT NULL,\n                cell_b TEXT NOT NULL,\n                geo_distance REAL NOT NULL,\n                has_road INTEGER NOT NULL,\n                slope_a_to_b REAL NOT NULL,\n                slope_b_to_a REAL NOT NULL,\n                PRIMARY KEY (cell_a, cell_b)\n            )\n            '
L888: feature['geometry'] <- dict(active_geometry)
L741: '\n            CREATE TABLE '
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
import shutil
import sqlite3
import time
import warnings
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from h3_offroad_planner.factor_model import PathMetrics
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, PlanningInputError
from h3_offroad_planner.route_models import PATH_ROLES, BlockageRecord, RouteCandidate, RoutePlan, RouteSelection
from h3_offroad_planner.routing_index import open_routing_index

# delivery_output_paths — L54
def delivery_output_paths(output_dir: str) -> dict[str, str]:
    """Return the fixed file contract for one complete delivery directory."""
    ...

# _safe_replace_file — L70
def _safe_replace_file(temporary: Path, target: Path) -> Path:
    """Replace target, or use a timestamped copy when an external process locks it."""
    ...

# atomic_write_json — L98
def atomic_write_json(path: str | Path, payload: object) -> None:
    """Write canonical ordered JSON via same-directory temporary replacement."""
    ...

# write_route_plan_outputs — L109
def write_route_plan_outputs(plan: RoutePlan, graph: H3Graph, output_dir: str, tile_manifest: Mapping[str, object] | None=None, *, export_gpkg: bool=True) -> dict[str, str]:
    """Write RoutePlan JSON, GeoJSON, GPKG and style/manifest artifacts atomically."""
    ...

# write_routes_gpkg — L183
def write_routes_gpkg(path: str, plan: RoutePlan) -> str:
    """Write the public one-layer route GeoPackage contract."""
    ...

# _route_manifest_payload — L195
def _route_manifest_payload(plan: RoutePlan, output_files: Mapping[str, str], graph_storage: Mapping[str, object], source_metadata: Mapping[str, object]) -> dict[str, object]:
    ...

# load_route_plan — L229
def load_route_plan(path: str) -> RoutePlan:
    """Load and validate a persisted RoutePlan, isolating corrupt JSON on failure."""
    ...

# load_route_selection — L259
def load_route_selection(path: str) -> RouteSelection:
    """Load and validate persisted explicit route selection state."""
    ...

# load_active_route_feature — L280
def load_active_route_feature(path: str | Path) -> dict[str, object]:
    """Return the single active feature from routes.geojson."""
    ...

# load_route_graph_snapshot — L300
def load_route_graph_snapshot(path: str) -> H3Graph:
    """Restore a graph from compact GPKG storage or a legacy JSON snapshot."""
    ...

# _graph_from_json_snapshot — L322
def _graph_from_json_snapshot(snapshot: Mapping[str, object]) -> H3Graph:
    """Restore the legacy embedded JSON graph representation."""
    ...

# _graph_from_gpkg — L347
def _graph_from_gpkg(path: Path, storage: Mapping[str, object]) -> H3Graph:
    """Restore the canonical graph from one relocatable GeoPackage."""
    ...

# _gpkg_string — L469
def _gpkg_string(value: object, key: str, *, allow_empty: bool=False) -> str:
    ...

# _gpkg_float — L475
def _gpkg_float(value: object, key: str) -> float:
    ...

# _gpkg_optional_float — L484
def _gpkg_optional_float(value: object) -> float | None:
    ...

# _gpkg_optional_int — L488
def _gpkg_optional_int(value: object) -> int | None:
    ...

# _gpkg_optional_string — L497
def _gpkg_optional_string(value: object) -> str | None:
    ...

# _is_missing_table_value — L503
def _is_missing_table_value(value: object) -> bool:
    ...

# _remove_legacy_duplicate_outputs — L509
def _remove_legacy_duplicate_outputs(root: Path) -> None:
    """Remove obsolete reproducible formats after canonical outputs succeed."""
    ...

# write_active_route_state — L515
def write_active_route_state(output_dir: str, selection: RouteSelection, graph: H3Graph, blockages: tuple[BlockageRecord, ...]) -> None:
    """Atomically update active state in the single lightweight candidate file."""
    ...

# select_route — L545
def select_route(plan_path: str, candidate_id: str | None=None, role: str | None=None, expected_selection_version: int | None=None) -> RouteSelection:
    """Explicitly activate one plan candidate by stable id or assigned role."""
    ...

# _cell_from_mapping — L607
def _cell_from_mapping(payload: Mapping[str, object]) -> H3Cell:
    ...

# _edge_from_mapping — L639
def _edge_from_mapping(payload: Mapping[str, object]) -> H3Edge:
    ...

# _active_feature — L650
def _active_feature(selection: RouteSelection, graph: H3Graph) -> dict[str, object]:
    ...

# _feature_gdf — L668
def _feature_gdf(feature: dict[str, object]) -> gpd.GeoDataFrame:
    ...

# _blockage_gdf — L679
def _blockage_gdf(records: tuple[BlockageRecord, ...], graph: H3Graph) -> gpd.GeoDataFrame:
    ...

# _write_routes_gpkg — L704
def _write_routes_gpkg(path: str, graph: H3Graph, plan: RoutePlan) -> str:
    ...

# _write_graph_edge_table — L735
def _write_graph_edge_table(path: Path, graph: H3Graph) -> None:
    """Append graph edges as one compact non-spatial GeoPackage attribute table."""
    ...

# _replace_active_gpkg_layers — L786
def _replace_active_gpkg_layers(path: Path, feature: dict[str, object]) -> None:
    ...

# _static_facts_gdf — L804
def _static_facts_gdf(graph: H3Graph) -> gpd.GeoDataFrame:
    ...

# _candidate_gdf — L842
def _candidate_gdf(candidates: tuple[RouteCandidate, ...]) -> gpd.GeoDataFrame:
    ...

# _candidate_collection — L854
def _candidate_collection(candidates: tuple[RouteCandidate, ...]) -> dict[str, object]:
    ...

# _update_route_collection — L861
def _update_route_collection(path: Path, active_candidate_id: str, active_feature: Mapping[str, object]) -> None:
    ...

# _empty_route_gdf — L898
def _empty_route_gdf() -> gpd.GeoDataFrame:
    ...

# _empty_blockage_gdf — L909
def _empty_blockage_gdf() -> gpd.GeoDataFrame:
    ...

# _candidate_feature — L921
def _candidate_feature(candidate: RouteCandidate) -> dict[str, object]:
    ...

# _candidate_from_mapping — L949
def _candidate_from_mapping(value: object) -> RouteCandidate:
    ...

# _optional_object_mapping — L969
def _optional_object_mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    ...

# _metrics_from_mapping — L976
def _metrics_from_mapping(payload: Mapping[str, object]) -> PathMetrics:
    ...

# _selected_candidate — L994
def _selected_candidate(plan: RoutePlan, candidate_id: str | None, role: str | None) -> RouteCandidate:
    ...

# _existing_selection — L1014
def _existing_selection(path: Path) -> RouteSelection | None:
    ...

# _load_json_object — L1018
def _load_json_object(path: Path, isolate_corrupt: bool) -> dict[str, object]:
    ...

# _isolate_corrupt — L1034
def _isolate_corrupt(path: Path) -> None:
    ...

# _mapping — L1043
def _mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    ...

# _object_list — L1050
def _object_list(payload: Mapping[str, object], key: str) -> list[object]:
    ...

# _required_string — L1055
def _required_string(payload: Mapping[str, object], key: str) -> str:
    ...

# _string_or_empty — L1062
def _string_or_empty(payload: Mapping[str, object], key: str) -> str:
    """Read an optional schema-v2 string while accepting legacy schema-v1 files."""
    ...

# _string_allow_empty — L1070
def _string_allow_empty(payload: Mapping[str, object], key: str) -> str:
    ...

# _optional_string — L1077
def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    ...

# _optional_int — L1086
def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    ...

# _optional_float — L1095
def _optional_float(payload: Mapping[str, object], key: str) -> float | None:
    ...

# _required_bool — L1100
def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    ...

# _required_int — L1107
def _required_int(payload: Mapping[str, object], key: str) -> int:
    ...

# _required_float — L1114
def _required_float(payload: Mapping[str, object], key: str) -> float:
    ...

# _number — L1120
def _number(value: object, key: str) -> float:
    ...

# _string_sequence — L1126
def _string_sequence(payload: Mapping[str, object], key: str) -> list[str]:
    ...

# _string_mapping — L1133
def _string_mapping(payload: Mapping[str, object], key: str) -> dict[str, str]:
    ...

# _float_mapping — L1140
def _float_mapping(payload: Mapping[str, object], key: str) -> dict[str, float]:
    ...

# _objects — L1145
def _objects(values: list[object]) -> list[dict[str, object]]:
    ...
```
