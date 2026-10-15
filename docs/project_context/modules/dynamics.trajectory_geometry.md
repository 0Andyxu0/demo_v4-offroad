# 模块参考：dynamics.trajectory_geometry

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/dynamics/trajectory_geometry.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`d342f178e96aa642c6c45d69b572b75bf9aecb0e1f1803bba00d04da714bab2f`；类 3 个，函数/方法 31 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `models`。
- 直接导入本模块者：`replanning`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L28
PointXY = tuple[float, float]

# TrajectoryPrimitive — src/h3_offroad_planner/dynamics/trajectory_geometry.py:32
@dataclass(frozen=True)
class TrajectoryPrimitive:
    'One tangent-continuous line or circular-arc primitive in local meters.'
    kind: str
    start_xy: PointXY
    end_xy: PointXY
    heading_start_rad: float
    heading_end_rad: float
    length_m: float
    curvature_per_m: float
    center_xy: PointXY | None = None
    turn_angle_rad: float = 0.0
    ...

# TrajectoryResult — src/h3_offroad_planner/dynamics/trajectory_geometry.py:62
@dataclass(frozen=True)
class TrajectoryResult:
    'Geometry state and continuous final-route metrics for one H3 guide.'
    trajectory_id: str
    status: str
    failure_reasons: tuple[str, ...]
    coordinates_wgs84: tuple[tuple[float, float], ...]
    primitives: tuple[TrajectoryPrimitive, ...]
    length_m: float
    environment_distance_m: Mapping[str, float]
    min_clearance_m: float | None
    max_curvature_per_m: float
    auxiliary_eta_s: float
    unknown_coverage_m: float
    swept_dependency_cells: tuple[str, ...]
    reference_point: str = 'rear_axle_center'
    crs: str = 'LOCAL_EQUIRECTANGULAR_METERS'
    ...

# _LocalProjection — src/h3_offroad_planner/dynamics/trajectory_geometry.py:199
@dataclass(frozen=True)
class _LocalProjection:
    lat0: float
    lng0: float
    ...
```

校验 `TrajectoryPrimitive.__post_init__`：

- `L46 if self.kind not in {'line', 'arc'}` → `raise ValueError('trajectory primitive kind must be line or arc.')`
- `L48 if not isfinite(self.length_m) or self.length_m < 0.0` → `raise ValueError('trajectory primitive length must be finite and non-negative.')`
- `L50 if self.kind == 'arc' and (self.center_xy is None or abs(self.curvature_per_m) <= EPSILON)` → `raise ValueError('arc primitive requires a center and non-zero curvature.')`

校验 `TrajectoryResult.__post_init__`：

- `L81 if self.status not in {'valid', 'invalid', 'not_evaluated', 'incomplete'}` → `raise ValueError('trajectory status is invalid.')`
- `L83 if any((not isfinite(value) or value < 0.0 for value in (self.length_m, self.max_curvature_per_m, self.auxiliary_eta_s, self.unknown_coverage_m)))` → `raise ValueError('trajectory metrics must be finite and non-negative.')`

```text
# L563 _result
'h3_path' => list(path)
'status' => status
'primitives' => [primitive.to_dict() for primitive in primitives]

# L100 TrajectoryResult.to_dict
'trajectory_id' => self.trajectory_id
'status' => self.status
'failure_reasons' => list(self.failure_reasons)
'coordinates_wgs84' => [list(point) for point in self.coordinates_wgs84]
'primitives' => [primitive.to_dict() for primitive in self.primitives]
'length_m' => self.length_m
'environment_distance_m' => dict(sorted(self.environment_distance_m.items()))
'min_clearance_m' => self.min_clearance_m
'max_curvature_per_m' => self.max_curvature_per_m
'auxiliary_eta_s' => self.auxiliary_eta_s
'unknown_coverage_m' => self.unknown_coverage_m
'swept_dependency_cells' => list(self.swept_dependency_cells)
'reference_point' => self.reference_point
'crs' => self.crs
'field_state' => 'unverified'
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import atan2, ceil, cos, hypot, isfinite, pi, radians, sin, tan
from types import MappingProxyType
import h3
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from h3_offroad_planner.factor_model import EnvironmentConfig, FactorEvaluation, GeometryConfig, canonical_hash, environment_multiplier, evaluate_path_metrics
from h3_offroad_planner.models import H3Graph, PlanningInputError, VehicleProfile

# TrajectoryPrimitive — L32
@dataclass(frozen=True)
class TrajectoryPrimitive:
    """One tangent-continuous line or circular-arc primitive in local meters."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        ...

# TrajectoryResult — L62
@dataclass(frozen=True)
class TrajectoryResult:
    """Geometry state and continuous final-route metrics for one H3 guide."""

    def __post_init__(self) -> None:
        ...

    def to_dict(self) -> dict[str, object]:
        ...

# build_and_validate_trajectory — L119
def build_and_validate_trajectory(h3_path: tuple[str, ...] | list[str], graph: H3Graph, evaluation: FactorEvaluation, vehicle: VehicleProfile, environment: EnvironmentConfig, geometry: GeometryConfig) -> TrajectoryResult:
    """Correct one H3 guide and validate the continuous whole-vehicle sweep."""
    ...

# _LocalProjection — L199
@dataclass(frozen=True)
class _LocalProjection:

    @property
    def x_scale(self) -> float:
        ...

    def forward(self, lat: float, lng: float) -> PointXY:
        ...

    def inverse(self, point: PointXY) -> tuple[float, float]:
        ...

# _simplify_points — L214
def _simplify_points(points: list[PointXY], tolerance: float) -> list[PointXY]:
    ...

# _fillet_polyline — L237
def _fillet_polyline(points: list[PointXY], radius: float) -> tuple[tuple[TrajectoryPrimitive, ...], tuple[str, ...]]:
    ...

# _append_line — L291
def _append_line(primitives: list[TrajectoryPrimitive], start: PointXY, end: PointXY) -> None:
    ...

# _validate_primitives — L299
def _validate_primitives(primitives: tuple[TrajectoryPrimitive, ...], path: tuple[str, ...], graph: H3Graph, evaluation: FactorEvaluation, vehicle: VehicleProfile, environment: EnvironmentConfig, geometry: GeometryConfig, projection: _LocalProjection) -> TrajectoryResult:
    ...

# _primitive_sweep — L382
def _primitive_sweep(primitive: TrajectoryPrimitive, vehicle: VehicleProfile, geometry: GeometryConfig) -> tuple[Polygon, list[PointXY], int]:
    ...

# _vehicle_footprint — L426
def _vehicle_footprint(point: PointXY, heading: float, vehicle: VehicleProfile) -> Polygon:
    ...

# _vehicle_corner_radius — L440
def _vehicle_corner_radius(vehicle: VehicleProfile, radius: float, left: bool) -> float:
    ...

# _graph_geometries — L457
def _graph_geometries(graph: H3Graph, evaluation: FactorEvaluation, projection: _LocalProjection) -> tuple[BaseGeometry, BaseGeometry, dict[str, Polygon]]:
    ...

# _continuous_environment_metrics — L479
def _continuous_environment_metrics(sampled_points: list[PointXY], trajectory_length_m: float, dependency_cells: tuple[str, ...], graph: H3Graph, cell_polygons: Mapping[str, Polygon], environment: EnvironmentConfig) -> tuple[dict[str, float], float]:
    ...

# _unknown_h3_length — L523
def _unknown_h3_length(path: tuple[str, ...], graph: H3Graph, environment: EnvironmentConfig) -> float:
    ...

# _clearance — L538
def _clearance(swept: BaseGeometry, obstacles: BaseGeometry, domain: BaseGeometry) -> float:
    ...

# _result — L549
def _result(path: tuple[str, ...], status: str, failures: tuple[str, ...], coordinates: tuple[tuple[float, float], ...], primitives: tuple[TrajectoryPrimitive, ...], length: float, environment_distance: Mapping[str, float], clearance: float | None, curvature: float, eta: float, unknown: float, dependencies: tuple[str, ...]) -> TrajectoryResult:
    ...

# _required_geometry — L584
def _required_geometry(value: float | None) -> float:
    ...

# _transform_body — L590
def _transform_body(point: PointXY, origin: PointXY, heading: float) -> PointXY:
    ...

# _unit — L597
def _unit(vector: PointXY) -> PointXY:
    ...

# _distance — L604
def _distance(first: PointXY, second: PointXY) -> float:
    ...

# _add — L608
def _add(first: PointXY, second: PointXY) -> PointXY:
    ...

# _subtract — L612
def _subtract(first: PointXY, second: PointXY) -> PointXY:
    ...

# _scale — L616
def _scale(vector: PointXY, factor: float) -> PointXY:
    ...

# _left_normal — L620
def _left_normal(vector: PointXY) -> PointXY:
    ...

# _dot — L624
def _dot(first: PointXY, second: PointXY) -> float:
    ...

# _cross — L628
def _cross(first: PointXY, second: PointXY) -> float:
    ...

# _dot_direction — L632
def _dot_direction(previous: PointXY, current: PointXY, following: PointXY) -> float:
    ...
```
