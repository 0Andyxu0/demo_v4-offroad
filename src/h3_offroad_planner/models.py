"""Core data models and domain exceptions for the MVP planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, isinf

Coordinate = tuple[float, float]

__all__ = [
    "AssessmentError",
    "ConfigError",
    "Coordinate",
    "FleetPlan",
    "FleetPlanningInput",
    "FleetTask",
    "GISInputError",
    "GridBuildError",
    "H3Cell",
    "H3Edge",
    "H3Graph",
    "Path",
    "PlannerInput",
    "PlannerOutput",
    "PLANNER_OBJECTIVES",
    "PlanningFailedError",
    "PlanningInputError",
    "RouteEndpoint",
    "RouteRequest",
    "SoilProfile",
    "TileBuildRequest",
    "VehicleProfile",
]

ROUTE_ENDPOINT_ROLES: frozenset[str] = frozenset({"start", "goal", "end", "blockage"})
ROUTE_INPUT_MODES: frozenset[str] = frozenset({"coordinates", "layer"})
ROI_STRATEGIES: frozenset[str] = frozenset({"auto_corridor", "layer"})
DEFAULT_ROUTE_THEMES: tuple[str, ...] = ("score", "cost_score")
TILE_SAMPLING_MODES: frozenset[str] = frozenset({"center"})
PLANNER_OBJECTIVES: frozenset[str] = frozenset(
    {
        "distance",
        "environment_distance",
        "roughness",
        "slope",
        "trafficability",
        "travel_cost",
    }
)


class ConfigError(ValueError):
    """Raised when project configuration is missing or invalid."""


class GISInputError(ValueError):
    """Raised when GIS source data cannot be loaded or normalized."""


class GridBuildError(ValueError):
    """Raised when H3 graph construction input is invalid or empty."""


class AssessmentError(ValueError):
    """Raised when trafficability assessment cannot be completed."""


class PlanningInputError(ValueError):
    """Raised when a planner request violates the public input contract."""


class PlanningFailedError(RuntimeError):
    """Raised when no finite path can be produced for a valid request."""


def _require_positive(name: str, value: float) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric, got {type(value).__name__}.")
    if not isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{name} must be a finite positive value, got {value!r}.")


def _require_finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric, got {type(value).__name__}.")
    if not isfinite(float(value)):
        raise ValueError(f"{name} must be finite, got {value!r}.")


def _require_optional_nonnegative(name: str, value: float | None) -> None:
    if value is None:
        return
    _require_finite(name, value)
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative when provided.")


def _require_lat_lng(lat: float, lng: float) -> None:
    _require_finite("lat", lat)
    if not -90.0 <= lat <= 90.0:
        raise ValueError("lat must be in [-90, 90] degrees.")
    _require_finite("lng", lng)
    if not -180.0 <= lng <= 180.0:
        raise ValueError("lng must be in [-180, 180] degrees.")


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

    code: int
    name_zh: str
    soil_texture: str | None = None
    uscs: str | None = None
    bekker_soil: str | None = None
    soil_moisture: float | None = None
    is_passable: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.code, int) or self.code <= 0:
            raise ValueError("soil profile code must be a positive integer.")
        if not isinstance(self.name_zh, str) or not self.name_zh.strip():
            raise ValueError("soil profile name_zh must be a non-empty string.")
        if self.soil_moisture is not None:
            _require_positive("soil_moisture", self.soil_moisture)
            if self.soil_moisture > 1.0:
                raise ValueError("soil_moisture must be in (0, 1].")


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
    reference_point: str = "rear_axle_center"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string.")
        _require_positive("mass_kg", self.mass_kg)
        _require_positive("max_climb_angle_deg", self.max_climb_angle_deg)
        if self.max_climb_angle_deg > 90.0:
            raise ValueError("max_climb_angle_deg must be in (0, 90].")
        _require_positive("max_speed_kmh", self.max_speed_kmh)
        _require_positive("tire_width_m", self.tire_width_m)
        _require_positive("ground_clearance_m", self.ground_clearance_m)
        _require_positive("max_thrust_n", self.max_thrust_n)
        _require_positive("tire_radius_m", self.tire_radius_m)
        _require_positive("min_turn_radius_m", self.min_turn_radius_m)
        for name in ("width_m", "wheelbase_m"):
            value = getattr(self, name)
            if value is not None:
                _require_positive(name, value)
        _require_optional_nonnegative("front_overhang_m", self.front_overhang_m)
        _require_optional_nonnegative("rear_overhang_m", self.rear_overhang_m)
        if self.reference_point != "rear_axle_center":
            raise ValueError("reference_point must be 'rear_axle_center'.")

    @property
    def has_complete_geometry(self) -> bool:
        """Whether continuous whole-vehicle validation can be performed."""
        return all(
            value is not None
            for value in (
                self.width_m,
                self.wheelbase_m,
                self.front_overhang_m,
                self.rear_overhang_m,
            )
        )


@dataclass
class H3Cell:
    """Single fine-resolution planning cell in an in-memory H3-style graph."""

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
    parent_h3: str = ""
    is_passable: bool = True
    score: float = 0.0
    cost_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.h3index, str) or not self.h3index:
            raise ValueError("h3index must be a non-empty string.")
        _require_lat_lng(self.lat, self.lng)
        _require_finite("elevation", self.elevation)
        _require_finite("slope", self.slope)
        _require_finite("tri", self.tri)
        if self.tri < 0.0:
            raise ValueError("tri must be non-negative.")
        if not (self.lc_factor > 0.0 or isinf(self.lc_factor)):
            raise ValueError("lc_factor must be positive or infinity.")
        if self.landcover_code is not None and self.landcover_code < 0:
            raise ValueError("landcover_code must be non-negative when provided.")
        if self.soil_code is not None and self.soil_code <= 0:
            raise ValueError("soil_code must be positive when provided.")
        if self.soil_moisture is not None:
            _require_positive("soil_moisture", self.soil_moisture)
            if self.soil_moisture > 1.0:
                raise ValueError("soil_moisture must be in (0, 1].")
        _require_optional_nonnegative("depth", self.depth)
        _require_optional_nonnegative("rowspacing", self.rowspacing)
        _require_optional_nonnegative("cone_index_kpa", self.cone_index_kpa)
        _require_optional_nonnegative("sinkage_m", self.sinkage_m)
        _require_optional_nonnegative("sinkage_resistance", self.sinkage_resistance)
        if self.soil_mobility is not None and not 0.0 <= self.soil_mobility <= 1.0:
            raise ValueError("soil_mobility must be in [0, 1] when provided.")
        _require_optional_nonnegative("source_support_m", self.source_support_m)
        if self.twi is not None:
            _require_finite("twi", self.twi)
        for name in ("drainage_sensitivity", "surface_response"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1] when provided.")
        if self.drainage_valid != (self.drainage_sensitivity is not None):
            raise ValueError("drainage_valid must match drainage_sensitivity presence.")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1].")
        expected_cost_score = 1.0 - self.score
        if self.cost_score is None:
            self.cost_score = expected_cost_score
        if not 0.0 <= self.cost_score <= 1.0:
            raise ValueError("cost_score must be in [0, 1].")
        if abs(self.cost_score - expected_cost_score) > 1e-9:
            raise ValueError("cost_score must equal 1 - score.")


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

    role: str
    lat: float
    lng: float
    source_id: str | None = None

    def __post_init__(self) -> None:
        role = self.role.strip().lower() if isinstance(self.role, str) else ""
        if role not in ROUTE_ENDPOINT_ROLES:
            raise ValueError(f"role must be one of {sorted(ROUTE_ENDPOINT_ROLES)}.")
        self.role = "goal" if role == "end" else role
        _require_lat_lng(self.lat, self.lng)
        if self.source_id is not None and not str(self.source_id).strip():
            raise ValueError("source_id must be non-empty when provided.")


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
    max_snap_distance_m: float = 20_000.0
    corridor_buffer_deg: float = 0.15
    max_estimated_cells: int = 500_000
    roi_strategy: str = "auto_corridor"
    objectives: list[str] = field(default_factory=lambda: ["distance"])
    candidate_index: int = 0
    blocked_cells: list[str] = field(default_factory=list)
    factor_model_path: str | None = None
    mission_profile: str = "fastest"
    max_candidate_paths: int = 5
    candidate_limit: int = 24
    penalty_factor: float = 0.25
    static_planning_path: str | None = None
    environment_snapshot_path: str | None = None

    def __post_init__(self) -> None:
        if self.input_mode not in ROUTE_INPUT_MODES:
            raise ValueError(f"input_mode must be one of {sorted(ROUTE_INPUT_MODES)}.")
        _require_non_empty_path("parquet_path", self.parquet_path)
        _require_non_empty_path("planner_config_path", self.planner_config_path)
        _require_non_empty_path("vehicle_path", self.vehicle_path)
        _require_non_empty_path("output_dir", self.output_dir)
        if self.res_coarse < 0 or self.res_fine <= self.res_coarse:
            raise ValueError("res_fine must be greater than res_coarse >= 0.")
        _require_positive("max_snap_distance_m", self.max_snap_distance_m)
        _require_positive("corridor_buffer_deg", self.corridor_buffer_deg)
        if self.max_estimated_cells <= 0:
            raise ValueError("max_estimated_cells must be positive.")
        if self.roi_strategy not in ROI_STRATEGIES:
            raise ValueError(f"roi_strategy must be one of {sorted(ROI_STRATEGIES)}.")
        if not self.objectives or len(set(self.objectives)) != len(self.objectives):
            raise ValueError("objectives must be non-empty and contain no duplicates.")
        unknown_objectives = set(self.objectives).difference(PLANNER_OBJECTIVES)
        if unknown_objectives:
            raise ValueError(f"unknown planner objectives: {sorted(unknown_objectives)}")
        if not isinstance(self.candidate_index, int):
            raise TypeError("candidate_index must be an integer.")
        if isinstance(self.candidate_index, bool) or self.candidate_index < 0:
            raise ValueError("candidate_index must be a non-negative integer.")
        if len(set(self.blocked_cells)) != len(self.blocked_cells) or any(
            not isinstance(cell_id, str) or not cell_id for cell_id in self.blocked_cells
        ):
            raise ValueError("blocked_cells must contain unique non-empty H3 ids.")
        _require_optional_path("factor_model_path", self.factor_model_path)
        _require_optional_path("static_planning_path", self.static_planning_path)
        _require_optional_path("environment_snapshot_path", self.environment_snapshot_path)
        if self.mission_profile not in {
            "fastest",
            "shortest",
            "passability",
            "economy",
            "resilient",
        }:
            raise ValueError("mission_profile is invalid.")
        if not 1 <= self.max_candidate_paths <= 5:
            raise ValueError("max_candidate_paths must be in [1, 5].")
        if not self.max_candidate_paths <= self.candidate_limit <= 24:
            raise ValueError("candidate_limit must be in [max_candidate_paths, 24].")
        if not isfinite(self.penalty_factor) or self.penalty_factor < 0.0:
            raise ValueError("penalty_factor must be finite and non-negative.")
        self._validate_endpoint_mode()
        if not self.theme_attributes or any(not attr.strip() for attr in self.theme_attributes):
            raise ValueError("theme_attributes must contain non-empty attribute names.")

    def _validate_endpoint_mode(self) -> None:
        if self.input_mode == "coordinates":
            if None in (self.start_lat, self.start_lng, self.goal_lat, self.goal_lng):
                raise ValueError("coordinate mode requires start and goal latitude/longitude.")
            start_lat = self.start_lat
            start_lng = self.start_lng
            goal_lat = self.goal_lat
            goal_lng = self.goal_lng
            if start_lat is None or start_lng is None or goal_lat is None or goal_lng is None:
                raise ValueError("coordinate mode requires start and goal latitude/longitude.")
            _require_lat_lng(float(start_lat), float(start_lng))
            _require_lat_lng(float(goal_lat), float(goal_lng))
            return
        if self.endpoint_layer_path is None or not self.endpoint_layer_path.strip():
            raise ValueError("layer mode requires endpoint_layer_path.")


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
    max_tiles: int = 1_000
    max_cells_per_tile: int = 100_000
    sampling_mode: str = "center"
    continue_on_error: bool = True
    overwrite: bool = True

    def __post_init__(self) -> None:
        _require_non_empty_path("dem_path", self.dem_path)
        _require_non_empty_path("landcover_path", self.landcover_path)
        _require_non_empty_path("roi_layer_path", self.roi_layer_path)
        _require_non_empty_path("output_dir", self.output_dir)
        _require_optional_path("soil_path", self.soil_path)
        _require_optional_path("soil_catalog_path", self.soil_catalog_path)
        _require_optional_path("road_path", self.road_path)
        _require_optional_path("drainage_path", self.drainage_path)
        _require_optional_path("twi_path", self.twi_path)
        _require_optional_path("drainage_validity_path", self.drainage_validity_path)
        _require_optional_path("drainage_boundary_path", self.drainage_boundary_path)
        _require_optional_path("vehicle_path", self.vehicle_path)
        _require_optional_path("factor_model_path", self.factor_model_path)
        _require_optional_path("static_planning_path", self.static_planning_path)
        if self.drainage_path is None and any(
            value is not None
            for value in (self.twi_path, self.drainage_validity_path, self.drainage_boundary_path)
        ):
            raise ValueError("drainage_path is required with drainage mask paths.")
        if self.soil_path is not None and self.soil_catalog_path is None:
            raise ValueError("soil_catalog_path is required when soil_path is provided.")
        if self.tile_res < 0 or self.res_fine <= self.tile_res:
            raise ValueError("res_fine must be greater than tile_res >= 0.")
        if self.max_tiles <= 0:
            raise ValueError("max_tiles must be positive.")
        if self.max_cells_per_tile <= 0:
            raise ValueError("max_cells_per_tile must be positive.")
        if self.sampling_mode not in TILE_SAMPLING_MODES:
            raise ValueError(f"sampling_mode must be one of {sorted(TILE_SAMPLING_MODES)}.")
        if not isinstance(self.continue_on_error, bool):
            raise TypeError("continue_on_error must be bool.")
        if not isinstance(self.overwrite, bool):
            raise TypeError("overwrite must be bool.")


def _require_non_empty_path(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path string.")


def _require_optional_path(name: str, value: str | None) -> None:
    if value is not None:
        _require_non_empty_path(name, value)


@dataclass
class H3Edge:
    """Directed-slope edge between two adjacent planning cells."""

    cell_a: str
    cell_b: str
    geo_distance: float
    has_road: bool = False
    slope_a_to_b: float = 0.0
    slope_b_to_a: float = 0.0

    def __post_init__(self) -> None:
        if not self.cell_a or not self.cell_b:
            raise ValueError("cell_a and cell_b must be non-empty.")
        if self.cell_a == self.cell_b:
            raise ValueError("cell_a and cell_b must be different cells.")
        _require_positive("geo_distance", self.geo_distance)
        _require_finite("slope_a_to_b", self.slope_a_to_b)
        _require_finite("slope_b_to_a", self.slope_b_to_a)


@dataclass
class H3Graph:
    """Complete in-memory graph shared by MVP-1 planners."""

    resolution_fine: int = 13
    resolution_coarse: int = 10
    cells: dict[str, H3Cell] = field(default_factory=dict)
    edges: dict[tuple[str, str], H3Edge] = field(default_factory=dict)
    parent_children: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.resolution_coarse < 0 or self.resolution_fine <= self.resolution_coarse:
            raise ValueError("resolution_fine must be greater than resolution_coarse >= 0.")
        for key, edge in self.edges.items():
            if len(key) != 2 or key[0] not in self.cells or key[1] not in self.cells:
                raise ValueError(f"edge key {key!r} references missing cells.")
            if {key[0], key[1]} != {edge.cell_a, edge.cell_b}:
                raise ValueError(f"edge key {key!r} does not match edge endpoints.")


@dataclass
class PlannerInput:
    """Input request for a global planner invocation."""

    graph: H3Graph
    start: str
    goal: str
    vehicle: VehicleProfile
    objectives: list[str] = field(default_factory=lambda: ["distance"])

    def __post_init__(self) -> None:
        if self.start not in self.graph.cells:
            raise PlanningInputError(f"start={self.start!r} is not present in graph.")
        if self.goal not in self.graph.cells:
            raise PlanningInputError(f"goal={self.goal!r} is not present in graph.")
        if not self.objectives:
            raise PlanningInputError("objectives must be non-empty.")
        if len(set(self.objectives)) != len(self.objectives):
            raise PlanningInputError("objectives must not contain duplicates.")
        unknown = set(self.objectives).difference(PLANNER_OBJECTIVES)
        if unknown:
            raise PlanningInputError(f"unknown planner objectives: {sorted(unknown)}")


@dataclass
class Path:
    """Path result represented as H3-style cell ids and aggregate cost."""

    cells: list[str]
    total_cost: float
    coordinates: list[Coordinate] = field(default_factory=list)
    objectives: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError("cells must be non-empty.")
        if not (isfinite(self.total_cost) or isinf(self.total_cost)):
            raise ValueError("total_cost must be finite or infinity.")
        for name, value in self.objectives.items():
            if not isinstance(name, str) or not name:
                raise ValueError("objective names must be non-empty strings.")
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"objective {name!r} must be finite and non-negative.")


@dataclass
class PlannerOutput:
    """Container for successful planner paths and diagnostic metadata."""

    paths: list[Path]
    metadata: dict[str, int | float | str] = field(default_factory=dict)


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

    vehicle_id: str
    start: str
    goal: str
    vehicle: VehicleProfile
    objectives: list[str] = field(default_factory=lambda: ["distance"])

    def __post_init__(self) -> None:
        if not isinstance(self.vehicle_id, str) or not self.vehicle_id.strip():
            raise ValueError("vehicle_id must be a non-empty string.")
        self.vehicle_id = self.vehicle_id.strip()
        if not isinstance(self.start, str) or not self.start:
            raise ValueError("start must be a non-empty H3 cell id.")
        if not isinstance(self.goal, str) or not self.goal:
            raise ValueError("goal must be a non-empty H3 cell id.")
        if not self.objectives:
            raise ValueError("objectives must be non-empty.")
        if len(set(self.objectives)) != len(self.objectives):
            raise ValueError("objectives must not contain duplicates.")
        unknown = set(self.objectives).difference(PLANNER_OBJECTIVES)
        if unknown:
            raise ValueError(f"unknown planner objectives: {sorted(unknown)}")


@dataclass
class FleetPlanningInput:
    """Basic input container for an unimplemented future fleet coordinator.

    Attributes:
        graph: Shared H3 planning graph. Unit: H3Graph. Must contain all task endpoints.
        tasks: Known vehicle tasks. Unit: count. At least one task is required.
    """

    graph: H3Graph
    tasks: list[FleetTask]

    def __post_init__(self) -> None:
        if not self.tasks:
            raise PlanningInputError("fleet tasks must contain at least one task.")
        seen: set[str] = set()
        for task in self.tasks:
            if task.vehicle_id in seen:
                raise PlanningInputError(f"duplicate fleet vehicle_id: {task.vehicle_id!r}.")
            seen.add(task.vehicle_id)
            if task.start not in self.graph.cells:
                raise PlanningInputError(f"fleet task start={task.start!r} is not in graph.")
            if task.goal not in self.graph.cells:
                raise PlanningInputError(f"fleet task goal={task.goal!r} is not in graph.")


@dataclass
class FleetPlan:
    """Basic future coordinator output with one path per vehicle."""

    paths: dict[str, Path]
    metadata: dict[str, int | float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("paths must contain at least one vehicle path.")
        for vehicle_id, path in self.paths.items():
            if not isinstance(vehicle_id, str) or not vehicle_id:
                raise ValueError("fleet plan vehicle ids must be non-empty strings.")
            if not isinstance(path, Path):
                raise TypeError("fleet plan values must be Path instances.")
