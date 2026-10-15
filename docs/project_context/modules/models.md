# 模块参考：models

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/models.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`3bc162848051d5a25493ce6d40dc51ceb92e018a13b8b8dfc6b112cf77461326`；类 20 个，函数/方法 21 个（含嵌套定义）。
- 项目内导入依赖：无。
- 直接导入本模块者：`assessment.trafficability`, `candidate_aggregation`, `cli`, `config`, `coordination.interfaces`, `desktop_client`, `desktop_project`, `dynamics.bekker`, `dynamics.cost_function`, `dynamics.los_path_smoother`, `dynamics.trajectory_geometry`, `exporting.gis_exporter`, `factor_model`, `grid.h3_grid_builder`, `h3_offroad_planner`, `offline_pairs`, `planners.deterministic_pareto`, `planners.dstar_lite`, `planners.facade`, `planners.factory`, `planners.h3_astar`, `planners.interfaces`, `portsmap`, `preprocessing.gis_preprocessor`, `preprocessing.hydrology`, `reachability`, `replanning`, `route_persistence`, `route_planning`, `routing`, `routing_index`, `tiling`, `vectorized_factor`, `vectorized_soil`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L8
Coordinate = tuple[float, float]

# ConfigError — src/h3_offroad_planner/models.py:52
class ConfigError(ValueError):
    'Raised when project configuration is missing or invalid.'
    ...

# GISInputError — src/h3_offroad_planner/models.py:56
class GISInputError(ValueError):
    'Raised when GIS source data cannot be loaded or normalized.'
    ...

# GridBuildError — src/h3_offroad_planner/models.py:60
class GridBuildError(ValueError):
    'Raised when H3 graph construction input is invalid or empty.'
    ...

# AssessmentError — src/h3_offroad_planner/models.py:64
class AssessmentError(ValueError):
    'Raised when trafficability assessment cannot be completed.'
    ...

# PlanningInputError — src/h3_offroad_planner/models.py:68
class PlanningInputError(ValueError):
    'Raised when a planner request violates the public input contract.'
    ...

# PlanningFailedError — src/h3_offroad_planner/models.py:72
class PlanningFailedError(RuntimeError):
    'Raised when no finite path can be produced for a valid request.'
    ...

# SoilProfile — src/h3_offroad_planner/models.py:108
@dataclass
class SoilProfile:
    'Soil catalog record used by offline Bekker assessment.\n\n    Attributes:\n        code: Raster soil class code. Unit: category code. Valid range: > 0.\n        name_zh: Chinese soil subclass name. Unit: none. Must be non-empty.\n        soil_texture: Soil texture class, such as `Lo`, `ClLo`, or `SaLo`.\n        uscs: USCS soil class, such as `CL`, `ML`, or `SM`.\n        bekker_soil: Bekker model group, currently `loam` or `clayloam`.\n        soil_moisture: Volumetric water content. Unit: ratio. Valid range: (0, 1].\n        is_passable: Whether this soil class is physically passable before vehicle checks.\n    '
    code: int
    name_zh: str
    soil_texture: str | None = None
    uscs: str | None = None
    bekker_soil: str | None = None
    soil_moisture: float | None = None
    is_passable: bool = True
    ...

# VehicleProfile — src/h3_offroad_planner/models.py:141
@dataclass
class VehicleProfile:
    'Physical vehicle profile used by all single-vehicle planner stages.\n\n    Attributes:\n        name: Vehicle name. Unit: none. Must be non-empty.\n        mass_kg: Total vehicle mass. Unit: kilogram (kg). Valid range: > 0.\n        max_climb_angle_deg: Maximum safe uphill pitch. Unit: degree. Range: (0, 90].\n        max_speed_kmh: Maximum road speed. Unit: kilometer per hour. Valid range: > 0.\n        tire_width_m: Tire width. Unit: meter (m). Valid range: > 0.\n        ground_clearance_m: Ground clearance. Unit: meter (m). Valid range: > 0.\n        max_thrust_n: Maximum engine thrust. Unit: newton (N). Valid range: > 0.\n        tire_radius_m: Tire radius. Unit: meter (m). Valid range: > 0.\n        min_turn_radius_m: Minimum turning radius. Unit: meter (m). Valid range: > 0.\n    '
    name: str
    mass_kg: float
    max_climb_angle_deg: float
    max_speed_kmh: float
    tire_width_m: float
    ground_clearance_m: float
    max_thrust_n: float
    tire_radius_m: float
    min_turn_radius_m: float
    width_m: float | None = None
    wheelbase_m: float | None = None
    front_overhang_m: float | None = None
    rear_overhang_m: float | None = None
    reference_point: str = 'rear_axle_center'
    ...

# H3Cell — src/h3_offroad_planner/models.py:208
@dataclass
class H3Cell:
    'Single fine-resolution planning cell in an in-memory H3-style graph.'
    h3index: str
    lat: float
    lng: float
    elevation: float
    slope: float
    tri: float
    lc_factor: float
    landcover_code: int | None = None
    landcover_type: str | None = None
    soil_code: int | None = None
    soil_type: str | None = None
    soil_texture: str | None = None
    uscs: str | None = None
    soil_moisture: float | None = None
    depth: float | None = None
    rowspacing: float | None = None
    cone_index_kpa: float | None = None
    sinkage_m: float | None = None
    sinkage_resistance: float | None = None
    soil_mobility: float | None = None
    soil_source: str | None = None
    source_support_m: float | None = None
    twi: float | None = None
    drainage_sensitivity: float | None = None
    drainage_valid: bool = False
    drainage_boundary_affected: bool = False
    surface_response: float | None = None
    surface_evidence: str | None = None
    has_road: bool = False
    parent_h3: str = ''
    is_passable: bool = True
    score: float = 0.0
    cost_score: float | None = None
    ...

# RouteEndpoint — src/h3_offroad_planner/models.py:292
@dataclass
class RouteEndpoint:
    'User-provided route point before H3 snapping.\n\n    Attributes:\n        role: Endpoint role. Unit: none. Valid values: start, goal, end, blockage.\n            The role `end` is normalized to `goal`.\n        lat: Latitude. Unit: degrees. Valid range: [-90, 90].\n        lng: Longitude. Unit: degrees. Valid range: [-180, 180].\n        source_id: Optional source feature id. Unit: none.\n    '
    role: str
    lat: float
    lng: float
    source_id: str | None = None
    ...

# RouteRequest — src/h3_offroad_planner/models.py:319
@dataclass
class RouteRequest:
    'Parameterized route request for MVP-3.1.\n\n    Attributes:\n        input_mode: Endpoint input mode. Unit: none. Valid values: coordinates, layer.\n        parquet_path: Persisted H3 table path. Unit: filesystem path. Must be non-empty.\n        planner_config_path: Planner YAML path. Unit: filesystem path. Must be non-empty.\n        vehicle_path: Vehicle YAML path. Unit: filesystem path. Must be non-empty.\n        output_dir: Output directory. Unit: filesystem path. Must be non-empty.\n        start_lat/start_lng/goal_lat/goal_lng: Coordinate input endpoint values.\n            Unit: degrees. Required when `input_mode="coordinates"`.\n        endpoint_layer_path: Point layer path with a `role` field. Required for layer mode.\n        roi_layer_path: Optional polygon ROI layer. Unit: filesystem path.\n        res_fine: Fine H3 resolution. Unit: H3 resolution. Must exceed `res_coarse`.\n        res_coarse: Parent H3 resolution. Unit: H3 resolution. Must be >= 0.\n        theme_attributes: H3 cell attributes exported as thematic map layers.\n        max_snap_distance_m: Endpoint snapping tolerance. Unit: meters. Must be > 0.\n        corridor_buffer_deg: Auto corridor buffer. Unit: degrees. Must be > 0.\n        max_estimated_cells: Upper bound for estimated H3 cells. Unit: count. Must be > 0.\n        roi_strategy: ROI fallback strategy. Unit: none. Valid values: auto_corridor, layer.\n        max_candidate_paths: Maximum returned alternatives. Unit: count. Valid range: [1, 5].\n        candidate_limit: Maximum raw candidate pool. Unit: count. Valid range:\n            [max_candidate_paths, 24].\n        penalty_factor: Multiplicative path-reuse penalty coefficient. Unit:\n            dimensionless. Must be finite and >= 0.\n    '
    input_mode: str
    parquet_path: str
    planner_config_path: str
    vehicle_path: str
    output_dir: str
    start_lat: float | None = None
    start_lng: float | None = None
    goal_lat: float | None = None
    goal_lng: float | None = None
    endpoint_layer_path: str | None = None
    roi_layer_path: str | None = None
    res_fine: int = 14
    res_coarse: int = 11
    theme_attributes: list[str] = field(default_factory=lambda: list(DEFAULT_ROUTE_THEMES))
    max_snap_distance_m: float = 20000.0
    corridor_buffer_deg: float = 0.15
    max_estimated_cells: int = 500000
    roi_strategy: str = 'auto_corridor'
    objectives: list[str] = field(default_factory=lambda: ['distance'])
    candidate_index: int = 0
    blocked_cells: list[str] = field(default_factory=list)
    factor_model_path: str | None = None
    mission_profile: str = 'fastest'
    max_candidate_paths: int = 5
    candidate_limit: int = 24
    penalty_factor: float = 0.25
    static_planning_path: str | None = None
    environment_snapshot_path: str | None = None
    ...

# TileBuildRequest — src/h3_offroad_planner/models.py:442
@dataclass
class TileBuildRequest:
    'Raw-GIS tile cache build request for MVP-4.1.\n\n    Attributes:\n        dem_path: DEM raster path. Unit: filesystem path. Must be non-empty.\n        landcover_path: Landcover raster/vector path. Unit: filesystem path. Must be non-empty.\n        roi_layer_path: Polygon ROI layer path. Unit: filesystem path. Must be non-empty.\n        output_dir: Tile cache output directory. Unit: filesystem path. Must be non-empty.\n        soil_path: Optional soil raster path. Unit: filesystem path.\n        soil_catalog_path: Soil catalog path. Required when `soil_path` is provided.\n        road_path: Optional road vector path. Unit: filesystem path.\n        res_fine: Fine H3 resolution. Unit: H3 resolution. Must exceed `tile_res`.\n        tile_res: Parent H3 tile resolution. Unit: H3 resolution. Must be >= 0.\n        max_tiles: Maximum parent tiles per run. Unit: count. Must be > 0.\n        max_cells_per_tile: Maximum fine cells per tile. Unit: count. Must be > 0.\n        sampling_mode: Attribute sampling mode. MVP-4.1 supports only `center`.\n        continue_on_error: Whether tile failures are recorded instead of aborting.\n        overwrite: Whether existing tile Parquet files are rebuilt.\n    '
    dem_path: str
    landcover_path: str
    roi_layer_path: str
    output_dir: str
    soil_path: str | None = None
    soil_catalog_path: str | None = None
    road_path: str | None = None
    drainage_path: str | None = None
    twi_path: str | None = None
    drainage_validity_path: str | None = None
    drainage_boundary_path: str | None = None
    vehicle_path: str | None = None
    factor_model_path: str | None = None
    static_planning_path: str | None = None
    res_fine: int = 14
    tile_res: int = 11
    max_tiles: int = 1000
    max_cells_per_tile: int = 100000
    sampling_mode: str = 'center'
    continue_on_error: bool = True
    overwrite: bool = True
    ...

# H3Edge — src/h3_offroad_planner/models.py:531
@dataclass
class H3Edge:
    'Directed-slope edge between two adjacent planning cells.'
    cell_a: str
    cell_b: str
    geo_distance: float
    has_road: bool = False
    slope_a_to_b: float = 0.0
    slope_b_to_a: float = 0.0
    ...

# H3Graph — src/h3_offroad_planner/models.py:552
@dataclass
class H3Graph:
    'Complete in-memory graph shared by MVP-1 planners.'
    resolution_fine: int = 13
    resolution_coarse: int = 10
    cells: dict[str, H3Cell] = field(default_factory=dict)
    edges: dict[tuple[str, str], H3Edge] = field(default_factory=dict)
    parent_children: dict[str, set[str]] = field(default_factory=dict)
    ...

# PlannerInput — src/h3_offroad_planner/models.py:572
@dataclass
class PlannerInput:
    'Input request for a global planner invocation.'
    graph: H3Graph
    start: str
    goal: str
    vehicle: VehicleProfile
    objectives: list[str] = field(default_factory=lambda: ['distance'])
    ...

# Path — src/h3_offroad_planner/models.py:596
@dataclass
class Path:
    'Path result represented as H3-style cell ids and aggregate cost.'
    cells: list[str]
    total_cost: float
    coordinates: list[Coordinate] = field(default_factory=list)
    objectives: dict[str, float] = field(default_factory=dict)
    ...

# PlannerOutput — src/h3_offroad_planner/models.py:617
@dataclass
class PlannerOutput:
    'Container for successful planner paths and diagnostic metadata.'
    paths: list[Path]
    metadata: dict[str, int | float | str] = field(default_factory=dict)
    ...

# FleetTask — src/h3_offroad_planner/models.py:625
@dataclass
class FleetTask:
    'Basic uncoordinated vehicle task data for a future fleet implementation.\n\n    Attributes:\n        vehicle_id: Unique vehicle identifier. Unit: none. Must be non-empty.\n        start: Start H3 cell id. Unit: H3 index string. Must be present in graph.\n        goal: Goal H3 cell id. Unit: H3 index string. Must be present in graph.\n        vehicle: Physical vehicle profile for edge-cost evaluation.\n        objectives: Planner objective whitelist shared with `PlannerInput`.\n    '
    vehicle_id: str
    start: str
    goal: str
    vehicle: VehicleProfile
    objectives: list[str] = field(default_factory=lambda: ['distance'])
    ...

# FleetPlanningInput — src/h3_offroad_planner/models.py:660
@dataclass
class FleetPlanningInput:
    'Basic input container for an unimplemented future fleet coordinator.\n\n    Attributes:\n        graph: Shared H3 planning graph. Unit: H3Graph. Must contain all task endpoints.\n        tasks: Known vehicle tasks. Unit: count. At least one task is required.\n    '
    graph: H3Graph
    tasks: list[FleetTask]
    ...

# FleetPlan — src/h3_offroad_planner/models.py:686
@dataclass
class FleetPlan:
    'Basic future coordinator output with one path per vehicle.'
    paths: dict[str, Path]
    metadata: dict[str, int | float | str] = field(default_factory=dict)
    ...
```

校验 `SoilProfile.__post_init__`：

- `L130 if not isinstance(self.code, int) or self.code <= 0` → `raise ValueError('soil profile code must be a positive integer.')`
- `L132 if not isinstance(self.name_zh, str) or not self.name_zh.strip()` → `raise ValueError('soil profile name_zh must be a non-empty string.')`
- `L135 _require_positive('soil_moisture', self.soil_moisture)`
- `L136 if self.soil_moisture > 1.0` → `raise ValueError('soil_moisture must be in (0, 1].')`

校验 `VehicleProfile.__post_init__`：

- `L172 if not isinstance(self.name, str) or not self.name.strip()` → `raise ValueError('name must be a non-empty string.')`
- `L174 _require_positive('mass_kg', self.mass_kg)`
- `L175 _require_positive('max_climb_angle_deg', self.max_climb_angle_deg)`
- `L176 if self.max_climb_angle_deg > 90.0` → `raise ValueError('max_climb_angle_deg must be in (0, 90].')`
- `L178 _require_positive('max_speed_kmh', self.max_speed_kmh)`
- `L179 _require_positive('tire_width_m', self.tire_width_m)`
- `L180 _require_positive('ground_clearance_m', self.ground_clearance_m)`
- `L181 _require_positive('max_thrust_n', self.max_thrust_n)`
- `L182 _require_positive('tire_radius_m', self.tire_radius_m)`
- `L183 _require_positive('min_turn_radius_m', self.min_turn_radius_m)`
- `L188 _require_optional_nonnegative('front_overhang_m', self.front_overhang_m)`
- `L189 _require_optional_nonnegative('rear_overhang_m', self.rear_overhang_m)`
- `L190 if self.reference_point != 'rear_axle_center'` → `raise ValueError("reference_point must be 'rear_axle_center'.")`
- `L187 _require_positive(name, value)`

校验 `H3Cell.__post_init__`：

- `L246 if not isinstance(self.h3index, str) or not self.h3index` → `raise ValueError('h3index must be a non-empty string.')`
- `L248 _require_lat_lng(self.lat, self.lng)`
- `L249 _require_finite('elevation', self.elevation)`
- `L250 _require_finite('slope', self.slope)`
- `L251 _require_finite('tri', self.tri)`
- `L252 if self.tri < 0.0` → `raise ValueError('tri must be non-negative.')`
- `L254 if not (self.lc_factor > 0.0 or isinf(self.lc_factor))` → `raise ValueError('lc_factor must be positive or infinity.')`
- `L256 if self.landcover_code is not None and self.landcover_code < 0` → `raise ValueError('landcover_code must be non-negative when provided.')`
- `L258 if self.soil_code is not None and self.soil_code <= 0` → `raise ValueError('soil_code must be positive when provided.')`
- `L264 _require_optional_nonnegative('depth', self.depth)`
- `L265 _require_optional_nonnegative('rowspacing', self.rowspacing)`
- `L266 _require_optional_nonnegative('cone_index_kpa', self.cone_index_kpa)`
- `L267 _require_optional_nonnegative('sinkage_m', self.sinkage_m)`
- `L268 _require_optional_nonnegative('sinkage_resistance', self.sinkage_resistance)`
- `L269 if self.soil_mobility is not None and (not 0.0 <= self.soil_mobility <= 1.0)` → `raise ValueError('soil_mobility must be in [0, 1] when provided.')`
- `L271 _require_optional_nonnegative('source_support_m', self.source_support_m)`
- `L278 if self.drainage_valid != (self.drainage_sensitivity is not None)` → `raise ValueError('drainage_valid must match drainage_sensitivity presence.')`
- `L280 if not 0.0 <= self.score <= 1.0` → `raise ValueError('score must be in [0, 1].')`
- `L285 if not 0.0 <= self.cost_score <= 1.0` → `raise ValueError('cost_score must be in [0, 1].')`
- `L287 if abs(self.cost_score - expected_cost_score) > 1e-09` → `raise ValueError('cost_score must equal 1 - score.')`
- `L261 _require_positive('soil_moisture', self.soil_moisture)`
- `L262 if self.soil_moisture > 1.0` → `raise ValueError('soil_moisture must be in (0, 1].')`
- `L273 _require_finite('twi', self.twi)`
- `L276 if value is not None and (not 0.0 <= value <= 1.0)` → `raise ValueError(f'{name} must be in [0, 1] when provided.')`

校验 `RouteEndpoint.__post_init__`：

- `L310 if role not in ROUTE_ENDPOINT_ROLES` → `raise ValueError(f'role must be one of {sorted(ROUTE_ENDPOINT_ROLES)}.')`
- `L313 _require_lat_lng(self.lat, self.lng)`
- `L314 if self.source_id is not None and (not str(self.source_id).strip())` → `raise ValueError('source_id must be non-empty when provided.')`

校验 `RouteRequest.__post_init__`：

- `L376 if self.input_mode not in ROUTE_INPUT_MODES` → `raise ValueError(f'input_mode must be one of {sorted(ROUTE_INPUT_MODES)}.')`
- `L378 _require_non_empty_path('parquet_path', self.parquet_path)`
- `L379 _require_non_empty_path('planner_config_path', self.planner_config_path)`
- `L380 _require_non_empty_path('vehicle_path', self.vehicle_path)`
- `L381 _require_non_empty_path('output_dir', self.output_dir)`
- `L382 if self.res_coarse < 0 or self.res_fine <= self.res_coarse` → `raise ValueError('res_fine must be greater than res_coarse >= 0.')`
- `L384 _require_positive('max_snap_distance_m', self.max_snap_distance_m)`
- `L385 _require_positive('corridor_buffer_deg', self.corridor_buffer_deg)`
- `L386 if self.max_estimated_cells <= 0` → `raise ValueError('max_estimated_cells must be positive.')`
- `L388 if self.roi_strategy not in ROI_STRATEGIES` → `raise ValueError(f'roi_strategy must be one of {sorted(ROI_STRATEGIES)}.')`
- `L390 if not self.objectives or len(set(self.objectives)) != len(self.objectives)` → `raise ValueError('objectives must be non-empty and contain no duplicates.')`
- `L393 if unknown_objectives` → `raise ValueError(f'unknown planner objectives: {sorted(unknown_objectives)}')`
- `L395 if not isinstance(self.candidate_index, int)` → `raise TypeError('candidate_index must be an integer.')`
- `L397 if isinstance(self.candidate_index, bool) or self.candidate_index < 0` → `raise ValueError('candidate_index must be a non-negative integer.')`
- `L399 if len(set(self.blocked_cells)) != len(self.blocked_cells) or any((not isinstance(cell_id, str) or not cell_id for cell_id in self.blocked_cells))` → `raise ValueError('blocked_cells must contain unique non-empty H3 ids.')`
- `L403 _require_optional_path('factor_model_path', self.factor_model_path)`
- `L404 _require_optional_path('static_planning_path', self.static_planning_path)`
- `L405 _require_optional_path('environment_snapshot_path', self.environment_snapshot_path)`
- `L406 if self.mission_profile not in {'fastest', 'shortest', 'passability', 'economy', 'resilient'}` → `raise ValueError('mission_profile is invalid.')`
- `L414 if not 1 <= self.max_candidate_paths <= 5` → `raise ValueError('max_candidate_paths must be in [1, 5].')`
- `L416 if not self.max_candidate_paths <= self.candidate_limit <= 24` → `raise ValueError('candidate_limit must be in [max_candidate_paths, 24].')`
- `L418 if not isfinite(self.penalty_factor) or self.penalty_factor < 0.0` → `raise ValueError('penalty_factor must be finite and non-negative.')`
- `L421 if not self.theme_attributes or any((not attr.strip() for attr in self.theme_attributes))` → `raise ValueError('theme_attributes must contain non-empty attribute names.')`

校验 `TileBuildRequest.__post_init__`：

- `L485 _require_non_empty_path('dem_path', self.dem_path)`
- `L486 _require_non_empty_path('landcover_path', self.landcover_path)`
- `L487 _require_non_empty_path('roi_layer_path', self.roi_layer_path)`
- `L488 _require_non_empty_path('output_dir', self.output_dir)`
- `L489 _require_optional_path('soil_path', self.soil_path)`
- `L490 _require_optional_path('soil_catalog_path', self.soil_catalog_path)`
- `L491 _require_optional_path('road_path', self.road_path)`
- `L492 _require_optional_path('drainage_path', self.drainage_path)`
- `L493 _require_optional_path('twi_path', self.twi_path)`
- `L494 _require_optional_path('drainage_validity_path', self.drainage_validity_path)`
- `L495 _require_optional_path('drainage_boundary_path', self.drainage_boundary_path)`
- `L496 _require_optional_path('vehicle_path', self.vehicle_path)`
- `L497 _require_optional_path('factor_model_path', self.factor_model_path)`
- `L498 _require_optional_path('static_planning_path', self.static_planning_path)`
- `L499 if self.drainage_path is None and any((value is not None for value in (self.twi_path, self.drainage_validity_path, self.drainage_boundary_path)))` → `raise ValueError('drainage_path is required with drainage mask paths.')`
- `L504 if self.soil_path is not None and self.soil_catalog_path is None` → `raise ValueError('soil_catalog_path is required when soil_path is provided.')`
- `L506 if self.tile_res < 0 or self.res_fine <= self.tile_res` → `raise ValueError('res_fine must be greater than tile_res >= 0.')`
- `L508 if self.max_tiles <= 0` → `raise ValueError('max_tiles must be positive.')`
- `L510 if self.max_cells_per_tile <= 0` → `raise ValueError('max_cells_per_tile must be positive.')`
- `L512 if self.sampling_mode not in TILE_SAMPLING_MODES` → `raise ValueError(f'sampling_mode must be one of {sorted(TILE_SAMPLING_MODES)}.')`
- `L514 if not isinstance(self.continue_on_error, bool)` → `raise TypeError('continue_on_error must be bool.')`
- `L516 if not isinstance(self.overwrite, bool)` → `raise TypeError('overwrite must be bool.')`

校验 `H3Edge.__post_init__`：

- `L542 if not self.cell_a or not self.cell_b` → `raise ValueError('cell_a and cell_b must be non-empty.')`
- `L544 if self.cell_a == self.cell_b` → `raise ValueError('cell_a and cell_b must be different cells.')`
- `L546 _require_positive('geo_distance', self.geo_distance)`
- `L547 _require_finite('slope_a_to_b', self.slope_a_to_b)`
- `L548 _require_finite('slope_b_to_a', self.slope_b_to_a)`

校验 `H3Graph.__post_init__`：

- `L562 if self.resolution_coarse < 0 or self.resolution_fine <= self.resolution_coarse` → `raise ValueError('resolution_fine must be greater than resolution_coarse >= 0.')`
- `L565 if len(key) != 2 or key[0] not in self.cells or key[1] not in self.cells` → `raise ValueError(f'edge key {key!r} references missing cells.')`
- `L567 if {key[0], key[1]} != {edge.cell_a, edge.cell_b}` → `raise ValueError(f'edge key {key!r} does not match edge endpoints.')`

校验 `PlannerInput.__post_init__`：

- `L582 if self.start not in self.graph.cells` → `raise PlanningInputError(f'start={self.start!r} is not present in graph.')`
- `L584 if self.goal not in self.graph.cells` → `raise PlanningInputError(f'goal={self.goal!r} is not present in graph.')`
- `L586 if not self.objectives` → `raise PlanningInputError('objectives must be non-empty.')`
- `L588 if len(set(self.objectives)) != len(self.objectives)` → `raise PlanningInputError('objectives must not contain duplicates.')`
- `L591 if unknown` → `raise PlanningInputError(f'unknown planner objectives: {sorted(unknown)}')`

校验 `Path.__post_init__`：

- `L605 if not self.cells` → `raise ValueError('cells must be non-empty.')`
- `L607 if not (isfinite(self.total_cost) or isinf(self.total_cost))` → `raise ValueError('total_cost must be finite or infinity.')`
- `L610 if not isinstance(name, str) or not name` → `raise ValueError('objective names must be non-empty strings.')`
- `L612 if not isfinite(value) or value < 0.0` → `raise ValueError(f'objective {name!r} must be finite and non-negative.')`

校验 `FleetTask.__post_init__`：

- `L643 if not isinstance(self.vehicle_id, str) or not self.vehicle_id.strip()` → `raise ValueError('vehicle_id must be a non-empty string.')`
- `L646 if not isinstance(self.start, str) or not self.start` → `raise ValueError('start must be a non-empty H3 cell id.')`
- `L648 if not isinstance(self.goal, str) or not self.goal` → `raise ValueError('goal must be a non-empty H3 cell id.')`
- `L650 if not self.objectives` → `raise ValueError('objectives must be non-empty.')`
- `L652 if len(set(self.objectives)) != len(self.objectives)` → `raise ValueError('objectives must not contain duplicates.')`
- `L655 if unknown` → `raise ValueError(f'unknown planner objectives: {sorted(unknown)}')`

校验 `FleetPlanningInput.__post_init__`：

- `L672 if not self.tasks` → `raise PlanningInputError('fleet tasks must contain at least one task.')`
- `L676 if task.vehicle_id in seen` → `raise PlanningInputError(f'duplicate fleet vehicle_id: {task.vehicle_id!r}.')`
- `L679 if task.start not in self.graph.cells` → `raise PlanningInputError(f'fleet task start={task.start!r} is not in graph.')`
- `L681 if task.goal not in self.graph.cells` → `raise PlanningInputError(f'fleet task goal={task.goal!r} is not in graph.')`

校验 `FleetPlan.__post_init__`：

- `L693 if not self.paths` → `raise ValueError('paths must contain at least one vehicle path.')`
- `L696 if not isinstance(vehicle_id, str) or not vehicle_id` → `raise ValueError('fleet plan vehicle ids must be non-empty strings.')`
- `L698 if not isinstance(path, Path)` → `raise TypeError('fleet plan values must be Path instances.')`

```python
# L35
ROUTE_ENDPOINT_ROLES: frozenset[str] = frozenset({'start', 'goal', 'end', 'blockage'})
# L36
ROUTE_INPUT_MODES: frozenset[str] = frozenset({'coordinates', 'layer'})
# L37
ROI_STRATEGIES: frozenset[str] = frozenset({'auto_corridor', 'layer'})
# L38
DEFAULT_ROUTE_THEMES: tuple[str, ...] = ('score', 'cost_score')
# L39
TILE_SAMPLING_MODES: frozenset[str] = frozenset({'center'})
# L40
PLANNER_OBJECTIVES: frozenset[str] = frozenset({'distance', 'environment_distance', 'roughness', 'slope', 'trafficability', 'travel_cost'})
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from dataclasses import dataclass, field
from math import isfinite, isinf

# ConfigError — L52
class ConfigError(ValueError):
    """Raised when project configuration is missing or invalid."""

# GISInputError — L56
class GISInputError(ValueError):
    """Raised when GIS source data cannot be loaded or normalized."""

# GridBuildError — L60
class GridBuildError(ValueError):
    """Raised when H3 graph construction input is invalid or empty."""

# AssessmentError — L64
class AssessmentError(ValueError):
    """Raised when trafficability assessment cannot be completed."""

# PlanningInputError — L68
class PlanningInputError(ValueError):
    """Raised when a planner request violates the public input contract."""

# PlanningFailedError — L72
class PlanningFailedError(RuntimeError):
    """Raised when no finite path can be produced for a valid request."""

# _require_positive — L76
def _require_positive(name: str, value: float) -> None:
    ...

# _require_finite — L83
def _require_finite(name: str, value: float) -> None:
    ...

# _require_optional_nonnegative — L90
def _require_optional_nonnegative(name: str, value: float | None) -> None:
    ...

# _require_lat_lng — L98
def _require_lat_lng(lat: float, lng: float) -> None:
    ...

# SoilProfile — L108
@dataclass
class SoilProfile:
    """Soil catalog record used by offline Bekker assessment.

    Attributes:
        code: Raster soil class code. Unit: category code. Valid range: > 0.
        name_zh: Chinese soil subclass name. Unit: none. Must be non-empty.
        soil_texture: Soil texture class, such as `Lo`, `ClLo`, or `SaLo`.
        uscs: USCS soil class, such as `CL`, `ML`, or `SM`.
        bekker_soil: Bekker model group, currently `loam` or `clayloam`.
        soil_moisture: Volumetric water content. Unit: ratio. Valid range: (0, 1].
        is_passable: Whether this soil class is physically passable before vehicle checks.
    """

    def __post_init__(self) -> None:
        ...

# VehicleProfile — L141
@dataclass
class VehicleProfile:
    """Physical vehicle profile used by all single-vehicle planner stages.

    Attributes:
        name: Vehicle name. Unit: none. Must be non-empty.
        mass_kg: Total vehicle mass. Unit: kilogram (kg). Valid range: > 0.
        max_climb_angle_deg: Maximum safe uphill pitch. Unit: degree. Range: (0, 90].
        max_speed_kmh: Maximum road speed. Unit: kilometer per hour. Valid range: > 0.
        tire_width_m: Tire width. Unit: meter (m). Valid range: > 0.
        ground_clearance_m: Ground clearance. Unit: meter (m). Valid range: > 0.
        max_thrust_n: Maximum engine thrust. Unit: newton (N). Valid range: > 0.
        tire_radius_m: Tire radius. Unit: meter (m). Valid range: > 0.
        min_turn_radius_m: Minimum turning radius. Unit: meter (m). Valid range: > 0.
    """

    def __post_init__(self) -> None:
        ...

    @property
    def has_complete_geometry(self) -> bool:
        """Whether continuous whole-vehicle validation can be performed."""
        ...

# H3Cell — L208
@dataclass
class H3Cell:
    """Single fine-resolution planning cell in an in-memory H3-style graph."""

    def __post_init__(self) -> None:
        ...

# RouteEndpoint — L292
@dataclass
class RouteEndpoint:
    """User-provided route point before H3 snapping.

    Attributes:
        role: Endpoint role. Unit: none. Valid values: start, goal, end, blockage.
            The role `end` is normalized to `goal`.
        lat: Latitude. Unit: degrees. Valid range: [-90, 90].
        lng: Longitude. Unit: degrees. Valid range: [-180, 180].
        source_id: Optional source feature id. Unit: none.
    """

    def __post_init__(self) -> None:
        ...

# RouteRequest — L319
@dataclass
class RouteRequest:
    """Parameterized route request for MVP-3.1.

    Attributes:
        input_mode: Endpoint input mode. Unit: none. Valid values: coordinates, layer.
        parquet_path: Persisted H3 table path. Unit: filesystem path. Must be non-empty.
        planner_config_path: Planner YAML path. Unit: filesystem path. Must be non-empty.
        vehicle_path: Vehicle YAML path. Unit: filesystem path. Must be non-empty.
        output_dir: Output directory. Unit: filesystem path. Must be non-empty.
        start_lat/start_lng/goal_lat/goal_lng: Coordinate input endpoint values.
            Unit: degrees. Required when `input_mode="coordinates"`.
        endpoint_layer_path: Point layer path with a `role` field. Required for layer mode.
        roi_layer_path: Optional polygon ROI layer. Unit: filesystem path.
        res_fine: Fine H3 resolution. Unit: H3 resolution. Must exceed `res_coarse`.
        res_coarse: Parent H3 resolution. Unit: H3 resolution. Must be >= 0.
        theme_attributes: H3 cell attributes exported as thematic map layers.
        max_snap_distance_m: Endpoint snapping tolerance. Unit: meters. Must be > 0.
        corridor_buffer_deg: Auto corridor buffer. Unit: degrees. Must be > 0.
        max_estimated_cells: Upper bound for estimated H3 cells. Unit: count. Must be > 0.
        roi_strategy: ROI fallback strategy. Unit: none. Valid values: auto_corridor, layer.
        max_candidate_paths: Maximum returned alternatives. Unit: count. Valid range: [1, 5].
        candidate_limit: Maximum raw candidate pool. Unit: count. Valid range:
            [max_candidate_paths, 24].
        penalty_factor: Multiplicative path-reuse penalty coefficient. Unit:
            dimensionless. Must be finite and >= 0.
    """

    def __post_init__(self) -> None:
        ...

    def _validate_endpoint_mode(self) -> None:
        ...

# TileBuildRequest — L442
@dataclass
class TileBuildRequest:
    """Raw-GIS tile cache build request for MVP-4.1.

    Attributes:
        dem_path: DEM raster path. Unit: filesystem path. Must be non-empty.
        landcover_path: Landcover raster/vector path. Unit: filesystem path. Must be non-empty.
        roi_layer_path: Polygon ROI layer path. Unit: filesystem path. Must be non-empty.
        output_dir: Tile cache output directory. Unit: filesystem path. Must be non-empty.
        soil_path: Optional soil raster path. Unit: filesystem path.
        soil_catalog_path: Soil catalog path. Required when `soil_path` is provided.
        road_path: Optional road vector path. Unit: filesystem path.
        res_fine: Fine H3 resolution. Unit: H3 resolution. Must exceed `tile_res`.
        tile_res: Parent H3 tile resolution. Unit: H3 resolution. Must be >= 0.
        max_tiles: Maximum parent tiles per run. Unit: count. Must be > 0.
        max_cells_per_tile: Maximum fine cells per tile. Unit: count. Must be > 0.
        sampling_mode: Attribute sampling mode. MVP-4.1 supports only `center`.
        continue_on_error: Whether tile failures are recorded instead of aborting.
        overwrite: Whether existing tile Parquet files are rebuilt.
    """

    def __post_init__(self) -> None:
        ...

# _require_non_empty_path — L520
def _require_non_empty_path(name: str, value: str) -> None:
    ...

# _require_optional_path — L525
def _require_optional_path(name: str, value: str | None) -> None:
    ...

# H3Edge — L531
@dataclass
class H3Edge:
    """Directed-slope edge between two adjacent planning cells."""

    def __post_init__(self) -> None:
        ...

# H3Graph — L552
@dataclass
class H3Graph:
    """Complete in-memory graph shared by MVP-1 planners."""

    def __post_init__(self) -> None:
        ...

# PlannerInput — L572
@dataclass
class PlannerInput:
    """Input request for a global planner invocation."""

    def __post_init__(self) -> None:
        ...

# Path — L596
@dataclass
class Path:
    """Path result represented as H3-style cell ids and aggregate cost."""

    def __post_init__(self) -> None:
        ...

# PlannerOutput — L617
@dataclass
class PlannerOutput:
    """Container for successful planner paths and diagnostic metadata."""

# FleetTask — L625
@dataclass
class FleetTask:
    """Basic uncoordinated vehicle task data for a future fleet implementation.

    Attributes:
        vehicle_id: Unique vehicle identifier. Unit: none. Must be non-empty.
        start: Start H3 cell id. Unit: H3 index string. Must be present in graph.
        goal: Goal H3 cell id. Unit: H3 index string. Must be present in graph.
        vehicle: Physical vehicle profile for edge-cost evaluation.
        objectives: Planner objective whitelist shared with `PlannerInput`.
    """

    def __post_init__(self) -> None:
        ...

# FleetPlanningInput — L660
@dataclass
class FleetPlanningInput:
    """Basic input container for an unimplemented future fleet coordinator.

    Attributes:
        graph: Shared H3 planning graph. Unit: H3Graph. Must contain all task endpoints.
        tasks: Known vehicle tasks. Unit: count. At least one task is required.
    """

    def __post_init__(self) -> None:
        ...

# FleetPlan — L686
@dataclass
class FleetPlan:
    """Basic future coordinator output with one path per vehicle."""

    def __post_init__(self) -> None:
        ...
```
