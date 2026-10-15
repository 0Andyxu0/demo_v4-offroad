# 模块参考：factor_model

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/factor_model.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`d8045e702909c6c42c01ed869097c7fbae8ab251a3c3fa419552626ccab71e5c`；类 12 个，函数/方法 77 个（含嵌套定义）。
- 项目内导入依赖：`dynamics.bekker`, `models`, `vectorized_factor`, `vectorized_soil`。
- 直接导入本模块者：`candidate_aggregation`, `cli`, `dynamics.trajectory_geometry`, `environment`, `h3_offroad_planner`, `offline_pairs`, `planners.deterministic_pareto`, `portsmap`, `reachability`, `replanning`, `route_models`, `route_persistence`, `route_planning`, `routing_index`, `tiling`, `vectorized_factor`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# FactorInterval — src/h3_offroad_planner/factor_model.py:126
@dataclass(frozen=True, slots=True)
class FactorInterval:
    'Ordered ratio interval on the closed unit range.'
    lower: float
    nominal: float
    upper: float
    ...

# NodeFactorMetrics — src/h3_offroad_planner/factor_model.py:146
@dataclass(frozen=True, slots=True)
class NodeFactorMetrics:
    'Frozen speed factors, physical safety margin, and evidence for one node.'
    h3index: str
    slope: FactorInterval
    landcover: FactorInterval
    soil: FactorInterval
    tri: FactorInterval
    road: FactorInterval
    safety_margin: FactorInterval
    speed_lower_mps: float
    speed_nominal_mps: float
    speed_upper_mps: float
    is_passable: bool
    confidence: float
    reason_codes: tuple[str, ...] = ()
    cone_index_kpa: float | None = None
    sinkage_m: float | None = None
    ...

# DirectedEdgeMetrics — src/h3_offroad_planner/factor_model.py:216
@dataclass(frozen=True, slots=True)
class DirectedEdgeMetrics:
    'Frozen metrics for one directed graph edge.'
    from_h3: str
    to_h3: str
    distance_m: float
    eta_lower_s: float
    eta_s: float
    eta_upper_s: float | None
    eta_upper_bounded: bool
    terrain_risk: float
    travel_cost: float
    safety_margin_lower: float
    safety_margin_nominal: float
    safety_margin_upper: float
    directed_slope_deg: float
    environment_distance_m: Mapping[str, float] = _EMPTY_ENV
    ...

# PathMetrics — src/h3_offroad_planner/factor_model.py:312
@dataclass(frozen=True)
class PathMetrics:
    'Exact path aggregates recomputed from frozen directed-edge metrics.'
    distance_m: float
    eta_lower_s: float
    eta_s: float
    eta_upper_s: float | None
    eta_upper_bounded: bool
    terrain_risk: float
    travel_cost: float
    safety_margin_min: float
    safety_margin_mean: float
    edge_count: int
    environment_distance_m: Mapping[str, float] = MappingProxyType({})
    ...

# EnvironmentConfig — src/h3_offroad_planner/factor_model.py:389
@dataclass(frozen=True)
class EnvironmentConfig:
    'Static surface/drainage multiplier policy and request pressure scenarios.'
    comparison_pressures: tuple[float, ...] = (0.0, 0.5, 1.0)
    request_pressures: tuple[float, ...] = (0.5, 1.0)
    unknown_drainage_range: tuple[float, float] = (0.0, 1.0)
    unknown_surface_range: tuple[float, float] = (0.0, 1.0)
    shared_sensitivity: float = 1.0
    model: str = 'surface_drainage_multiplier_v1'
    pressure_basis: str = 'synthetic_scenario'
    ...

# WeatherConfig — src/h3_offroad_planner/factor_model.py:441
@dataclass(frozen=True)
class WeatherConfig:
    'Bounded request-time weather lookup and optional moisture calibration.'
    enabled: bool = False
    provider: str = 'open-meteo'
    endpoint: str = 'https://api.open-meteo.com/v1/forecast'
    model: str = 'best_match'
    timeout_s: float = 3.0
    ttl_s: float = 1800.0
    failure_ttl_s: float = 60.0
    max_age_s: float = 10800.0
    theta_dry: float | None = None
    theta_wet: float | None = None
    calibration_status: str = 'unspecified'
    api_reference_mm: float | None = None
    ...

# GeometryConfig — src/h3_offroad_planner/factor_model.py:489
@dataclass(frozen=True)
class GeometryConfig:
    'Continuous trajectory construction and validation tolerances.'
    simplify_tolerance_m: float = 0.05
    geometry_tolerance_m: float = 0.01
    map_error_m: float = 0.0
    arc_step_deg: float = 10.0
    max_arc_segments: int = 720
    ...

# DecisionConfig — src/h3_offroad_planner/factor_model.py:510
@dataclass(frozen=True)
class DecisionConfig:
    'Candidate-pool detour budget, robust ordering, and switch hysteresis.'
    detour_ratio: float = 0.15
    clearance_target_m: float = 0.0
    clearance_tolerance_m: float = 0.01
    switch_relative_improvement: float = 0.05
    candidate_limit: int = 24
    display_limit: int = 5
    require_independent_backup: bool = False
    ...

# StaticPlanningConfig — src/h3_offroad_planner/factor_model.py:537
@dataclass(frozen=True)
class StaticPlanningConfig:
    'Versioned request policy for the three static-GIS planning increments.'
    environment: EnvironmentConfig = EnvironmentConfig()
    weather: WeatherConfig = WeatherConfig()
    geometry: GeometryConfig = GeometryConfig()
    decision: DecisionConfig = DecisionConfig()
    soil: Mapping[str, object] = MappingProxyType({})
    hydrology: Mapping[str, object] = MappingProxyType({})
    version: str = 'static_gis_route_v2'
    ...

# FactorModelConfig — src/h3_offroad_planner/factor_model.py:597
@dataclass(frozen=True)
class FactorModelConfig:
    'Validated physical-margin and speed configuration for route evaluation.'
    landcover_speed_by_code: Mapping[int, float] = MappingProxyType({})
    soil_speed_by_uscs: Mapping[str, float] = MappingProxyType({})
    tri_best: float = 0.0
    tri_worst: float = 8.0
    missing_speed_lower: float = 0.25
    missing_speed_nominal: float = 0.6
    missing_speed_upper: float = 0.85
    missing_confidence: float = 0.5
    offroad_speed_factor: float = 0.7
    road_speed_factor: float = 1.0
    speed_floor_ratio: float = 0.05
    directed_slope_speed_min_factor: float = 0.2
    min_cone_index_kpa: float = 185.73
    max_sinkage_clearance_ratio: float = 1.0
    epsilon: float = 1e-06
    tri_coefficient: float = 0.1
    gravity_coefficient: float = 5.0
    max_ports: int = 20000
    max_port_pairs: int = 200000
    ...

# FactorEvaluation — src/h3_offroad_planner/factor_model.py:704
@dataclass(frozen=True)
class FactorEvaluation:
    'Complete immutable route-time evaluation context.'
    node_metrics: Mapping[str, NodeFactorMetrics]
    directed_edges: Mapping[tuple[str, str], DirectedEdgeMetrics]
    vehicle_hash: str
    factor_model_hash: str
    static_input_hash: str
    graph_topology_hash: str
    ...

# _RawNodeEvidence — src/h3_offroad_planner/factor_model.py:1194
@dataclass(frozen=True)
class _RawNodeEvidence:
    speed_factors: tuple[FactorInterval, ...]
    safety_margin: FactorInterval
    passable: bool
    confidence: float
    reasons: tuple[str, ...]
    cone_index_kpa: float | None
    sinkage_m: float | None
    ...
```

校验 `FactorInterval.__post_init__`：

- `L135 if not all((isfinite(value) for value in values))` → `raise ValueError('factor interval values must be finite.')`
- `L137 if not 0.0 <= self.lower <= self.nominal <= self.upper <= 1.0` → `raise ValueError('factor interval must satisfy 0 <= lower <= nominal <= upper <= 1.')`

校验 `NodeFactorMetrics.__post_init__`：

- `L166 if not self.h3index` → `raise ValueError('h3index must be non-empty.')`
- `L169 if not all((isfinite(value) and value >= 0.0 for value in speeds))` → `raise ValueError('node speeds must be finite and non-negative.')`
- `L171 if not self.speed_lower_mps <= self.speed_nominal_mps <= self.speed_upper_mps` → `raise ValueError('node speed interval must be ordered.')`
- `L173 if not 0.0 <= self.confidence <= 1.0` → `raise ValueError('confidence must be in [0, 1].')`

校验 `DirectedEdgeMetrics.__post_init__`：

- `L242 if not self.from_h3 or not self.to_h3 or self.from_h3 == self.to_h3` → `raise ValueError('directed edge endpoints must be distinct non-empty ids.')`
- `L244 if not all((isfinite(value) and value >= 0.0 for value in finite_nonnegative))` → `raise ValueError('directed edge metrics must be finite and non-negative.')`
- `L246 if self.distance_m <= 0.0` → `raise ValueError('distance_m must be positive.')`
- `L248 if self.eta_upper_bounded != (self.eta_upper_s is not None)` → `raise ValueError('eta_upper_bounded must match eta_upper_s presence.')`
- `L250 if self.eta_upper_s is not None and self.eta_upper_s < self.eta_s` → `raise ValueError('eta_upper_s must not be below eta_s.')`
- `L252 if not 0.0 <= self.safety_margin_lower <= self.safety_margin_nominal <= self.safety_margin_upper <= 1.0` → `raise ValueError('directed edge safety-margin interval must be ordered in [0, 1].')`
- `L260 if any((not isfinite(value) or value < self.distance_m for value in self.environment_distance_m.values()))` → `raise ValueError('environment edge distances must be finite and >= geometry distance.')`

校验 `PathMetrics.__post_init__`：

- `L335 if not all((isfinite(value) and value >= 0.0 for value in values))` → `raise ValueError('path metrics must be finite and non-negative.')`
- `L337 if self.edge_count < 0` → `raise ValueError('edge_count must be non-negative.')`
- `L339 if not 0.0 <= self.safety_margin_min <= self.safety_margin_mean <= 1.0` → `raise ValueError('path safety-margin aggregates must be ordered in [0, 1].')`
- `L341 if self.eta_upper_bounded != (self.eta_upper_s is not None)` → `raise ValueError('eta_upper_bounded must match eta_upper_s presence.')`
- `L343 if any((not isfinite(value) or value < self.distance_m for value in self.environment_distance_m.values()))` → `raise ValueError('environment path distances must be finite and >= geometry distance.')`

校验 `EnvironmentConfig.__post_init__`：

- `L401 if self.model != 'surface_drainage_multiplier_v1'` → `raise ConfigError('unsupported environment model version.')`
- `L403 if self.pressure_basis not in {'synthetic_scenario', 'model_snapshot_v1', 'precipitation_apiv1'}` → `raise ConfigError('unsupported environment pressure_basis.')`
- `L417 if not set(self.request_pressures).issubset(self.comparison_pressures)` → `raise ConfigError('request_pressures must be a subset of comparison_pressures.')`
- `L425 if not isfinite(self.shared_sensitivity) or self.shared_sensitivity < 0.0` → `raise ConfigError('shared_sensitivity must be finite and non-negative.')`
- `L413 if not values or len(set(values)) != len(values)` → `raise ConfigError(f'{name} must contain unique pressure values.')`
- `L415 if any((not isfinite(value) or value < 0.0 for value in values))` → `raise ConfigError(f'{name} must contain finite non-negative values.')`
- `L423 if len(bounds) != 2 or not 0.0 <= bounds[0] <= bounds[1] <= 1.0` → `raise ConfigError(f'{name} must be an ordered [0, 1] interval.')`

校验 `WeatherConfig.__post_init__`：

- `L458 if self.provider != 'open-meteo'` → `raise ConfigError('unsupported weather provider.')`
- `L460 if not self.endpoint.startswith('https://')` → `raise ConfigError('weather endpoint must use https.')`
- `L462 if not self.model` → `raise ConfigError('weather model must be non-empty.')`
- `L468 if (self.theta_dry is None) != (self.theta_wet is None)` → `raise ConfigError('theta_dry and theta_wet must be provided together.')`
- `L470 if self.theta_dry is not None and self.theta_wet is not None and (not 0.0 <= self.theta_dry < self.theta_wet <= 1.0)` → `raise ConfigError('theta calibration must satisfy 0 <= dry < wet <= 1.')`
- `L476 if self.api_reference_mm is not None and (not isfinite(self.api_reference_mm) or self.api_reference_mm <= 0.0)` → `raise ConfigError('api_reference_mm must be finite and positive.')`
- `L480 if self.calibration_status not in {'unspecified', 'provisional_cldas_spatial_20260101', 'field_validated'}` → `raise ConfigError('unsupported weather calibration_status.')`
- `L466 if not isfinite(value) or value <= 0.0` → `raise ConfigError(f'{name} must be finite and positive.')`

校验 `GeometryConfig.__post_init__`：

- `L503 if not isfinite(self.map_error_m) or self.map_error_m < 0.0` → `raise ConfigError('map_error_m must be finite and non-negative.')`
- `L505 if not isinstance(self.max_arc_segments, int) or self.max_arc_segments <= 0` → `raise ConfigError('max_arc_segments must be a positive integer.')`
- `L501 if not isfinite(value) or value <= 0.0` → `raise ConfigError(f'{name} must be finite and positive.')`

校验 `DecisionConfig.__post_init__`：

- `L526 if not 0.0 <= self.switch_relative_improvement < 1.0` → `raise ConfigError('switch_relative_improvement must be in [0, 1).')`
- `L528 if not 1 <= self.display_limit <= 5` → `raise ConfigError('display_limit must be in [1, 5].')`
- `L530 if not self.display_limit <= self.candidate_limit <= 24` → `raise ConfigError('candidate_limit must be in [display_limit, 24].')`
- `L532 if not isinstance(self.require_independent_backup, bool)` → `raise ConfigError('require_independent_backup must be a boolean.')`
- `L524 if not isfinite(value) or value < 0.0` → `raise ConfigError(f'{name} must be finite and non-negative.')`

校验 `StaticPlanningConfig.__post_init__`：

- `L549 if self.version != 'static_gis_route_v2'` → `raise ConfigError('unsupported static planning version.')`

校验 `FactorModelConfig.__post_init__`：

- `L621 if not isfinite(self.tri_best) or not isfinite(self.tri_worst) or (not self.tri_worst > self.tri_best >= 0.0)` → `raise ValueError('tri thresholds must satisfy tri_worst > tri_best >= 0.')`
- `L632 _require_ratio('missing_confidence', self.missing_confidence)`
- `L633 _require_ratio('offroad_speed_factor', self.offroad_speed_factor)`
- `L634 _require_ratio('road_speed_factor', self.road_speed_factor)`
- `L635 _require_ratio('speed_floor_ratio', self.speed_floor_ratio, allow_zero=True)`
- `L636 _require_ratio('directed_slope_speed_min_factor', self.directed_slope_speed_min_factor, allow_zero=True)`
- `L641 _require_positive('min_cone_index_kpa', self.min_cone_index_kpa)`
- `L642 _require_positive('max_sinkage_clearance_ratio', self.max_sinkage_clearance_ratio)`
- `L643 _require_ratio('epsilon', self.epsilon)`
- `L644 _require_nonnegative('tri_coefficient', self.tri_coefficient)`
- `L645 _require_nonnegative('gravity_coefficient', self.gravity_coefficient)`
- `L647 if any((isinstance(value, bool) or not isinstance(value, int) for value in limits))` → `raise ValueError('PortsMap limits must be integers.')`
- `L649 if self.max_ports <= 0 or self.max_port_pairs <= 0` → `raise ValueError('PortsMap limits must be positive integers.')`
- `L663 _require_ratio('configured speed factor', value, allow_zero=True)`

校验 `FactorEvaluation.__post_init__`：

- `L721 if any((not value for value in hashes))` → `raise ValueError('factor evaluation hashes must be non-empty.')`

```python
# L63
GRAVITY_MPS2: float = 9.81
# L64
MODEL_SCHEMA_VERSION: int = 2
# L65
PHYSICAL_EVIDENCE_WARNING: str = 'PHYSICAL_EVIDENCE_INCOMPLETE'
# L66
MISSING_REASON_PREFIX: str = 'MISSING_'
# L67
_EMPTY_ENV: MappingProxyType[str, float] = MappingProxyType({})
# L68
SCHEMA_V2_SECTIONS: frozenset[str] = frozenset({'schema_version', 'uncertainty', 'speed', 'hard_constraints', 'risk', 'cost', 'portsmap'})
# L79
SCHEMA_V2_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({'uncertainty': frozenset({'missing_speed_interval', 'missing_confidence'}), 'speed': frozenset({'landcover_by_code', 'soil_by_uscs', 'tri_best', 'tri_worst', 'offroad_factor', 'road_factor', 'floor_ratio', 'directed_slope_min_factor'}), 'hard_constraints': frozenset({'min_cone_index_kpa', 'max_sinkage_clearance_ratio'}), 'risk': frozenset({'epsilon'}), 'cost': frozenset({'tri_coefficient', 'gravity_coefficient'}), 'portsmap': frozenset({'max_ports', 'max_port_pairs'})})
# L100
LEGACY_ACTIVE_SECTIONS: frozenset[str] = frozenset({'schema_version', 'benefit', 'uncertainty', 'speed', 'hard_constraints', 'risk', 'cost', 'portsmap'})
# L112
LEGACY_ACTIVE_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({'benefit': frozenset({'tri_best', 'tri_worst'}), 'uncertainty': frozenset({'missing_interval', 'missing_confidence'}), 'speed': SCHEMA_V2_FIELDS['speed'] - {'tri_best', 'tri_worst'}, 'hard_constraints': SCHEMA_V2_FIELDS['hard_constraints'], 'risk': SCHEMA_V2_FIELDS['risk'], 'cost': SCHEMA_V2_FIELDS['cost'], 'portsmap': SCHEMA_V2_FIELDS['portsmap']})
# L141
_ROAD_INTERVAL_1_0 = FactorInterval(1.0, 1.0, 1.0)
# L142
_OFFROAD_INTERVAL_0_7 = FactorInterval(0.7, 0.7, 0.7)
# L1332
_DEFAULT_BEKKER = BekkerChecker()
# L1333
_ORIGINAL_BEKKER_ENRICH_CELL = BekkerChecker.enrich_cell
```

```text
# L80 <module>
'uncertainty' => frozenset({'missing_speed_interval', 'missing_confidence'})
'speed' => frozenset({'landcover_by_code', 'soil_by_uscs', 'tri_best', 'tri_worst', 'offroad_factor', 'road_factor', 'floor_ratio', 'directed_slope_min_factor'})
'hard_constraints' => frozenset({'min_cone_index_kpa', 'max_sinkage_clearance_ratio'})
'risk' => frozenset({'epsilon'})
'cost' => frozenset({'tri_coefficient', 'gravity_coefficient'})
'portsmap' => frozenset({'max_ports', 'max_port_pairs'})

# L113 <module>
'benefit' => frozenset({'tri_best', 'tri_worst'})
'uncertainty' => frozenset({'missing_interval', 'missing_confidence'})
'speed' => SCHEMA_V2_FIELDS['speed'] - {'tri_best', 'tri_worst'}
'hard_constraints' => SCHEMA_V2_FIELDS['hard_constraints']
'risk' => SCHEMA_V2_FIELDS['risk']
'cost' => SCHEMA_V2_FIELDS['cost']
'portsmap' => SCHEMA_V2_FIELDS['portsmap']

# L356 PathMetrics.to_dict
'distance_m' => self.distance_m
'eta_lower_s' => self.eta_lower_s
'eta_s' => self.eta_s
'eta_upper_s' => self.eta_upper_s
'eta_upper_bounded' => self.eta_upper_bounded
'terrain_risk' => self.terrain_risk
'travel_cost' => self.travel_cost
'score_lower_min' => self.safety_margin_min
'score_nominal_mean' => self.safety_margin_mean
'edge_count' => self.edge_count
'environment_distance_m' => dict(sorted(self.environment_distance_m.items()))

# L429 EnvironmentConfig.to_dict
'model' => self.model
'pressure_basis' => self.pressure_basis
'comparison_pressures' => list(self.comparison_pressures)
'request_pressures' => list(self.request_pressures)
'unknown_drainage_range' => list(self.unknown_drainage_range)
'unknown_surface_range' => list(self.unknown_surface_range)
'shared_sensitivity' => self.shared_sensitivity

# L555 StaticPlanningConfig.to_dict
'version' => self.version
'soil' => dict(self.soil)
'hydrology' => dict(self.hydrology)
'environment' => self.environment.to_dict()
'weather' => asdict(self.weather)
'geometry' => asdict(self.geometry)
'decision' => asdict(self.decision)

# L667 FactorModelConfig.to_dict
'schema_version' => MODEL_SCHEMA_VERSION
'uncertainty' => { 'missing_speed_interval' => [self.missing_speed_lower, self.missing_speed_nominal, self.missing_speed_upper]; 'missing_confidence' => self.missing_confidence }
'speed' => { 'landcover_by_code' => dict(sorted(self.landcover_speed_by_code.items())); 'soil_by_uscs' => dict(sorted(self.soil_speed_by_uscs.items())); 'tri_best' => self.tri_best; 'tri_worst' => self.tri_worst; 'offroad_factor' => self.offroad_speed_factor; 'road_factor' => self.road_speed_factor; 'floor_ratio' => self.speed_floor_ratio; 'directed_slope_min_factor' => self.directed_slope_speed_min_factor }
'hard_constraints' => { 'min_cone_index_kpa' => self.min_cone_index_kpa; 'max_sinkage_clearance_ratio' => self.max_sinkage_clearance_ratio }
'risk' => { 'epsilon' => self.epsilon }
'cost' => { 'tri_coefficient' => self.tri_coefficient; 'gravity_coefficient' => self.gravity_coefficient }
'portsmap' => { 'max_ports' => self.max_ports; 'max_port_pairs' => self.max_port_pairs }

# L1142 graph_topology_hash
'a' => edge.cell_a
'b' => edge.cell_b
'distance_m' => edge.geo_distance
'slope_a_to_b' => edge.slope_a_to_b
'slope_b_to_a' => edge.slope_b_to_a

# L1152 graph_topology_hash
'resolution_fine' => graph.resolution_fine
'resolution_coarse' => graph.resolution_coarse
'cells' => sorted(graph.cells)
'edges' => edges

# L1096 static_input_hash
'h3index' => cell.h3index
'parent_h3' => cell.parent_h3
'lat' => cell.lat
'lng' => cell.lng
'elevation' => cell.elevation
'slope' => cell.slope
'tri' => cell.tri
'lc_factor' => cell.lc_factor if isfinite(cell.lc_factor) else 'inf'
'landcover_code' => cell.landcover_code
'landcover_type' => cell.landcover_type
'soil_code' => cell.soil_code
'soil_type' => cell.soil_type
'soil_texture' => cell.soil_texture
'uscs' => cell.uscs
'soil_moisture' => cell.soil_moisture
'depth' => cell.depth
'rowspacing' => cell.rowspacing
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
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import inf, isfinite, log, radians, sin
from pathlib import Path
from types import MappingProxyType
from typing import cast
import numpy as np
import yaml
from h3_offroad_planner.dynamics.bekker import CI_THRESHOLD_KPA, BekkerChecker, _cell_bekker_soil
from h3_offroad_planner.models import AssessmentError, ConfigError, H3Cell, H3Edge, H3Graph, PlanningInputError, VehicleProfile
from h3_offroad_planner.vectorized_soil import vectorized_bekker_sinkage, vectorized_cone_index_kpa

# FactorInterval — L126
@dataclass(frozen=True, slots=True)
class FactorInterval:
    """Ordered ratio interval on the closed unit range."""

    def __post_init__(self) -> None:
        ...

# NodeFactorMetrics — L146
@dataclass(frozen=True, slots=True)
class NodeFactorMetrics:
    """Frozen speed factors, physical safety margin, and evidence for one node."""

    def __post_init__(self) -> None:
        ...

    @classmethod
    def _fast_create(cls, h3index: str, slope: FactorInterval, landcover: FactorInterval, soil: FactorInterval, tri: FactorInterval, road: FactorInterval, safety_margin: FactorInterval, speed_lower_mps: float, speed_nominal_mps: float, speed_upper_mps: float, is_passable: bool, confidence: float, reason_codes: tuple[str, ...]=(), cone_index_kpa: float | None=None, sinkage_m: float | None=None) -> NodeFactorMetrics:
        ...

# DirectedEdgeMetrics — L216
@dataclass(frozen=True, slots=True)
class DirectedEdgeMetrics:
    """Frozen metrics for one directed graph edge."""

    def __post_init__(self) -> None:
        ...

    @classmethod
    def _fast_create(cls, from_h3: str, to_h3: str, distance_m: float, eta_lower_s: float, eta_s: float, eta_upper_s: float | None, eta_upper_bounded: bool, terrain_risk: float, travel_cost: float, safety_margin_lower: float, safety_margin_nominal: float, safety_margin_upper: float, directed_slope_deg: float, environment_distance_m: Mapping[str, float]=_EMPTY_ENV) -> DirectedEdgeMetrics:
        ...

# PathMetrics — L312
@dataclass(frozen=True)
class PathMetrics:
    """Exact path aggregates recomputed from frozen directed-edge metrics."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        """Return schema-v1 metrics with compatibility names at the output boundary."""
        ...

    def __hash__(self) -> int:
        ...

# EnvironmentConfig — L389
@dataclass(frozen=True)
class EnvironmentConfig:
    """Static surface/drainage multiplier policy and request pressure scenarios."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        ...

# WeatherConfig — L441
@dataclass(frozen=True)
class WeatherConfig:
    """Bounded request-time weather lookup and optional moisture calibration."""

    def __post_init__(self) -> None:
        ...

# GeometryConfig — L489
@dataclass(frozen=True)
class GeometryConfig:
    """Continuous trajectory construction and validation tolerances."""

    def __post_init__(self) -> None:
        ...

# DecisionConfig — L510
@dataclass(frozen=True)
class DecisionConfig:
    """Candidate-pool detour budget, robust ordering, and switch hysteresis."""

    def __post_init__(self) -> None:
        ...

# StaticPlanningConfig — L537
@dataclass(frozen=True)
class StaticPlanningConfig:
    """Versioned request policy for the three static-GIS planning increments."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        ...

# environment_multiplier — L566
def environment_multiplier(cell: H3Cell, pressure: float, config: EnvironmentConfig) -> tuple[float, bool]:
    """Return M=1+w*U*S*(1+D) and whether static evidence was unknown."""
    ...

# _pressure_key — L592
def _pressure_key(pressure: float) -> str:
    ...

# FactorModelConfig — L597
@dataclass(frozen=True)
class FactorModelConfig:
    """Validated physical-margin and speed configuration for route evaluation."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        """Return the complete effective schema-v2 configuration."""
        ...

# FactorEvaluation — L704
@dataclass(frozen=True)
class FactorEvaluation:
    """Complete immutable route-time evaluation context."""

    def __post_init__(self) -> None:
        ...

    def directed_adjacency(self) -> Mapping[str, list[str]]:
        """Return cached forward directed adjacency from evaluation.directed_edges."""
        ...

# load_factor_model — L737
def load_factor_model(path: str) -> FactorModelConfig:
    """Load and normalize a physical-margin factor-model YAML file."""
    ...

# load_static_planning_config — L749
def load_static_planning_config(path: str) -> StaticPlanningConfig:
    """Load the versioned soil/drainage, geometry, and robust decision policy."""
    ...

# _validate_static_source_sections — L849
def _validate_static_source_sections(data: Mapping[str, object]) -> None:
    ...

# _optional_mapping — L874
def _optional_mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    ...

# _float_tuple — L881
def _float_tuple(value: object, name: str) -> tuple[float, ...]:
    ...

# _float_pair — L889
def _float_pair(value: object, name: str) -> tuple[float, float]:
    ...

# _mapping_float — L896
def _mapping_float(data: Mapping[str, object], key: str, default: float) -> float:
    ...

# _mapping_optional_float — L903
def _mapping_optional_float(data: Mapping[str, object], key: str) -> float | None:
    ...

# _mapping_bool — L915
def _mapping_bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    ...

# _mapping_int — L922
def _mapping_int(data: Mapping[str, object], name: str, default: int) -> int:
    ...

# evaluate_factor_model — L929
def evaluate_factor_model(graph: H3Graph, vehicle: VehicleProfile, config: FactorModelConfig, environment: EnvironmentConfig | None=None) -> FactorEvaluation:
    """Evaluate physical node evidence once and freeze directed edge metrics."""
    ...

# build_directed_edge_cache — L995
def build_directed_edge_cache(graph: H3Graph, node_metrics: Mapping[str, NodeFactorMetrics], vehicle: VehicleProfile, config: FactorModelConfig, environment: EnvironmentConfig | None=None) -> dict[tuple[str, str], DirectedEdgeMetrics]:
    """Build the authoritative directed metrics used by route searches."""
    ...

# evaluate_path_metrics — L1016
def evaluate_path_metrics(h3_path: list[str] | tuple[str, ...], evaluation: FactorEvaluation) -> PathMetrics:
    """Recompute exact path aggregates from the frozen directed-edge cache."""
    ...

# _path_edges — L1065
def _path_edges(h3_path: list[str] | tuple[str, ...], evaluation: FactorEvaluation) -> list[DirectedEdgeMetrics]:
    ...

# canonical_hash — L1080
def canonical_hash(payload: object) -> str:
    """Return SHA-256 for canonical UTF-8 JSON serialization."""
    ...

# static_input_hash — L1086
def static_input_hash(graph: H3Graph) -> str:
    """Hash vehicle-independent facts only, excluding route-time score fields."""
    ...

# graph_topology_hash — L1135
def graph_topology_hash(graph: H3Graph) -> str:
    """Hash graph resolutions and deterministic undirected topology."""
    ...

# write_effective_snapshots — L1167
def write_effective_snapshots(output_dir: str, vehicle: VehicleProfile, config: FactorModelConfig) -> tuple[str, str]:
    """Write normalized vehicle and factor-model YAML snapshots."""
    ...

# write_static_planning_snapshot — L1182
def write_static_planning_snapshot(output_dir: str, config: StaticPlanningConfig) -> str:
    """Write the effective static-planning policy needed by replanning."""
    ...

# _RawNodeEvidence — L1194
@dataclass(frozen=True)
class _RawNodeEvidence:
    ...

# _raw_node_evidence — L1204
def _raw_node_evidence(cell: H3Cell, vehicle: VehicleProfile, config: FactorModelConfig, strict_static_mode: bool=False, soil_cone_cache: Mapping[str, float] | None=None, soil_sinkage_cache: Mapping[str, tuple[float, float]] | None=None) -> _RawNodeEvidence:
    ...

# _landcover_speed_interval — L1280
def _landcover_speed_interval(cell: H3Cell, vehicle: VehicleProfile, config: FactorModelConfig, missing: FactorInterval, reasons: list[str], strict_static_mode: bool) -> FactorInterval:
    ...

# _soil_speed_interval — L1336
def _soil_speed_interval(cell: H3Cell, vehicle: VehicleProfile, config: FactorModelConfig, missing: FactorInterval, reasons: list[str], *, soil_cone_cache: Mapping[str, float] | None=None, soil_sinkage_cache: Mapping[str, tuple[float, float]] | None=None) -> tuple[FactorInterval, float | None, float | None]:
    ...

# _hard_constraints — L1417
def _hard_constraints(cell: H3Cell, vehicle: VehicleProfile, config: FactorModelConfig, cone_index: float | None, sinkage: float | None, reasons: list[str], strict_static_mode: bool) -> bool:
    ...

# _node_safety_margin — L1464
def _node_safety_margin(cell: H3Cell, vehicle: VehicleProfile, config: FactorModelConfig, cone_index: float | None, sinkage: float | None, passable: bool, strict_static_mode: bool) -> float:
    ...

# _node_metrics — L1490
def _node_metrics(cell: H3Cell, evidence: _RawNodeEvidence, vehicle: VehicleProfile) -> NodeFactorMetrics:
    ...

# _node_speed_interval — L1517
def _node_speed_interval(evidence: _RawNodeEvidence, maximum_mps: float) -> tuple[float, float, float]:
    ...

# _directed_edge_metrics — L1534
def _directed_edge_metrics(graph: H3Graph, edge: H3Edge, from_h3: str, to_h3: str, nodes: Mapping[str, NodeFactorMetrics], vehicle: VehicleProfile, config: FactorModelConfig, environment: EnvironmentConfig | None) -> DirectedEdgeMetrics | None:
    ...

# _edge_speed_interval — L1594
def _edge_speed_interval(first: NodeFactorMetrics, second: NodeFactorMetrics, directed: FactorInterval) -> tuple[float, float, float]:
    ...

# _edge_safety_margin — L1606
def _edge_safety_margin(first: NodeFactorMetrics, second: NodeFactorMetrics, slope_deg: float, grade_force_n: float, vehicle: VehicleProfile) -> float:
    ...

# _travel_cost — L1623
def _travel_cost(edge: H3Edge, source_cell: H3Cell, target_cell: H3Cell, slope_deg: float, vehicle: VehicleProfile, config: FactorModelConfig) -> float:
    ...

# _directed_slope_factor — L1641
def _directed_slope_factor(slope_deg: float, vehicle: VehicleProfile, config: FactorModelConfig) -> FactorInterval:
    ...

# _slope_margin — L1652
def _slope_margin(slope_deg: float, vehicle: VehicleProfile) -> float:
    ...

# _grade_force_n — L1656
def _grade_force_n(slope_deg: float, vehicle: VehicleProfile) -> float:
    ...

# _tri_speed_factor — L1661
def _tri_speed_factor(tri: float, config: FactorModelConfig) -> float:
    ...

# _directional_slope — L1666
def _directional_slope(edge: H3Edge, from_h3: str, to_h3: str) -> float:
    ...

# _factor_model_from_mapping — L1674
def _factor_model_from_mapping(data: dict[str, object]) -> FactorModelConfig:
    ...

# _schema_version — L1719
def _schema_version(data: Mapping[str, object]) -> int:
    ...

# _validate_schema_v2 — L1729
def _validate_schema_v2(data: Mapping[str, object]) -> None:
    ...

# _warn_unused_legacy_fields — L1735
def _warn_unused_legacy_fields(data: Mapping[str, object]) -> None:
    ...

# _reject_unknown_fields — L1748
def _reject_unknown_fields(data: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    ...

# _mapping — L1758
def _mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    ...

# _sequence — L1765
def _sequence(data: Mapping[str, object], key: str, default: object) -> list[object] | tuple[object, ...]:
    ...

# _sequence_float — L1776
def _sequence_float(values: list[object] | tuple[object, ...], index: int, key: str) -> float:
    ...

# _float — L1786
def _float(data: Mapping[str, object], key: str, default: float) -> float:
    ...

# _int — L1796
def _int(data: Mapping[str, object], key: str, default: int) -> int:
    ...

# _int_float_mapping — L1806
def _int_float_mapping(data: Mapping[str, object], key: str) -> dict[int, float]:
    ...

# _str_float_mapping — L1829
def _str_float_mapping(data: Mapping[str, object], key: str) -> dict[str, float]:
    ...

# _known_interval — L1844
def _known_interval(value: float | None) -> FactorInterval:
    ...

# _floor_interval — L1851
def _floor_interval(interval: FactorInterval, floor: float) -> FactorInterval:
    ...

# _clamp_ratio — L1859
def _clamp_ratio(value: float) -> float:
    ...

# _product — L1863
def _product(values: tuple[float, ...]) -> float:
    ...

# _require_ratio — L1870
def _require_ratio(name: str, value: float, allow_zero: bool=False) -> None:
    ...

# _require_positive — L1877
def _require_positive(name: str, value: float) -> None:
    ...

# _require_nonnegative — L1882
def _require_nonnegative(name: str, value: float) -> None:
    ...

# _vehicle_payload — L1887
def _vehicle_payload(vehicle: VehicleProfile) -> dict[str, object]:
    ...

# _atomic_yaml_write — L1891
def _atomic_yaml_write(path: Path, payload: object) -> None:
    ...
```
