"""Curvature-bounded trajectory construction and continuous whole-vehicle checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import atan2, ceil, cos, hypot, isfinite, pi, radians, sin, tan
from types import MappingProxyType

import h3
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from h3_offroad_planner.factor_model import (
    EnvironmentConfig,
    FactorEvaluation,
    GeometryConfig,
    canonical_hash,
    environment_multiplier,
    evaluate_path_metrics,
)
from h3_offroad_planner.models import H3Graph, PlanningInputError, VehicleProfile

__all__ = ["TrajectoryPrimitive", "TrajectoryResult", "build_and_validate_trajectory"]

EPSILON = 1.0e-9
PointXY = tuple[float, float]


@dataclass(frozen=True)
class TrajectoryPrimitive:
    """One tangent-continuous line or circular-arc primitive in local meters."""

    kind: str
    start_xy: PointXY
    end_xy: PointXY
    heading_start_rad: float
    heading_end_rad: float
    length_m: float
    curvature_per_m: float
    center_xy: PointXY | None = None
    turn_angle_rad: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in {"line", "arc"}:
            raise ValueError("trajectory primitive kind must be line or arc.")
        if not isfinite(self.length_m) or self.length_m < 0.0:
            raise ValueError("trajectory primitive length must be finite and non-negative.")
        if self.kind == "arc" and (self.center_xy is None or abs(self.curvature_per_m) <= EPSILON):
            raise ValueError("arc primitive requires a center and non-zero curvature.")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_xy"] = list(self.start_xy)
        payload["end_xy"] = list(self.end_xy)
        payload["center_xy"] = None if self.center_xy is None else list(self.center_xy)
        return payload


@dataclass(frozen=True)
class TrajectoryResult:
    """Geometry state and continuous final-route metrics for one H3 guide."""

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
    reference_point: str = "rear_axle_center"
    crs: str = "LOCAL_EQUIRECTANGULAR_METERS"

    def __post_init__(self) -> None:
        if self.status not in {"valid", "invalid", "not_evaluated", "incomplete"}:
            raise ValueError("trajectory status is invalid.")
        if any(
            not isfinite(value) or value < 0.0
            for value in (
                self.length_m,
                self.max_curvature_per_m,
                self.auxiliary_eta_s,
                self.unknown_coverage_m,
            )
        ):
            raise ValueError("trajectory metrics must be finite and non-negative.")
        object.__setattr__(
            self,
            "environment_distance_m",
            MappingProxyType(dict(self.environment_distance_m)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "trajectory_id": self.trajectory_id,
            "status": self.status,
            "failure_reasons": list(self.failure_reasons),
            "coordinates_wgs84": [list(point) for point in self.coordinates_wgs84],
            "primitives": [primitive.to_dict() for primitive in self.primitives],
            "length_m": self.length_m,
            "environment_distance_m": dict(sorted(self.environment_distance_m.items())),
            "min_clearance_m": self.min_clearance_m,
            "max_curvature_per_m": self.max_curvature_per_m,
            "auxiliary_eta_s": self.auxiliary_eta_s,
            "unknown_coverage_m": self.unknown_coverage_m,
            "swept_dependency_cells": list(self.swept_dependency_cells),
            "reference_point": self.reference_point,
            "crs": self.crs,
            "field_state": "unverified",
        }


def build_and_validate_trajectory(
    h3_path: tuple[str, ...] | list[str],
    graph: H3Graph,
    evaluation: FactorEvaluation,
    vehicle: VehicleProfile,
    environment: EnvironmentConfig,
    geometry: GeometryConfig,
) -> TrajectoryResult:
    """Correct one H3 guide and validate the continuous whole-vehicle sweep."""
    path = tuple(h3_path)
    if not path or any(cell_id not in graph.cells for cell_id in path):
        raise PlanningInputError("trajectory guide must reference graph cells.")
    center_lat = sum(graph.cells[cell_id].lat for cell_id in path) / len(path)
    center_lng = sum(graph.cells[cell_id].lng for cell_id in path) / len(path)
    local = _LocalProjection(center_lat, center_lng)
    guide_xy = _simplify_points(
        [local.forward(graph.cells[cell_id].lat, graph.cells[cell_id].lng) for cell_id in path],
        geometry.simplify_tolerance_m,
    )
    guide_wgs84 = tuple((graph.cells[cell_id].lng, graph.cells[cell_id].lat) for cell_id in path)
    if not vehicle.has_complete_geometry:
        metrics = evaluate_path_metrics(path, evaluation)
        return _result(
            path,
            "not_evaluated",
            ("MISSING_VEHICLE_GEOMETRY",),
            guide_wgs84,
            (),
            metrics.distance_m,
            metrics.environment_distance_m,
            None,
            0.0,
            metrics.eta_s,
            _unknown_h3_length(path, graph, environment),
            (),
        )
    last_failure: tuple[str, ...] = ("TURNING_SPACE_INSUFFICIENT",)
    last_checked: TrajectoryResult | None = None
    for radius in (
        vehicle.min_turn_radius_m,
        vehicle.min_turn_radius_m * 1.25,
        vehicle.min_turn_radius_m * 1.5,
    ):
        primitives, failure = _fillet_polyline(guide_xy, radius)
        if failure:
            last_failure = failure
            continue
        checked = _validate_primitives(
            primitives,
            path,
            graph,
            evaluation,
            vehicle,
            environment,
            geometry,
            local,
        )
        if checked.status == "valid":
            return checked
        last_checked = checked
        last_failure = checked.failure_reasons
    if last_checked is not None:
        return last_checked
    return _result(
        path,
        "invalid",
        last_failure,
        guide_wgs84,
        (),
        0.0,
        {},
        0.0,
        0.0,
        0.0,
        0.0,
        (),
    )


@dataclass(frozen=True)
class _LocalProjection:
    lat0: float
    lng0: float

    @property
    def x_scale(self) -> float:
        return 111_320.0 * max(cos(radians(self.lat0)), 0.01)

    def forward(self, lat: float, lng: float) -> PointXY:
        return ((lng - self.lng0) * self.x_scale, (lat - self.lat0) * 111_320.0)

    def inverse(self, point: PointXY) -> tuple[float, float]:
        return (self.lng0 + point[0] / self.x_scale, self.lat0 + point[1] / 111_320.0)


def _simplify_points(points: list[PointXY], tolerance: float) -> list[PointXY]:
    unique: list[PointXY] = []
    for point in points:
        if not unique or _distance(point, unique[-1]) > EPSILON:
            unique.append(point)
    if len(unique) <= 2:
        return unique
    simplified = [unique[0]]
    for index in range(1, len(unique) - 1):
        previous = simplified[-1]
        current = unique[index]
        following = unique[index + 1]
        line = LineString([previous, following])
        if (
            line.distance(Point(current)) <= tolerance
            and _dot_direction(previous, current, following) > 0
        ):
            continue
        simplified.append(current)
    simplified.append(unique[-1])
    return simplified


def _fillet_polyline(
    points: list[PointXY], radius: float
) -> tuple[tuple[TrajectoryPrimitive, ...], tuple[str, ...]]:
    if not points:
        return (), ("DATA_INSUFFICIENT",)
    if len(points) == 1:
        return (), ()
    corners: dict[int, tuple[PointXY, PointXY, PointXY, float, float]] = {}
    for index in range(1, len(points) - 1):
        previous, current, following = points[index - 1 : index + 2]
        incoming = _unit(_subtract(current, previous))
        outgoing = _unit(_subtract(following, current))
        turn = atan2(_cross(incoming, outgoing), _dot(incoming, outgoing))
        if abs(turn) < 1.0e-6:
            continue
        if abs(abs(turn) - pi) < 1.0e-6:
            return (), ("TURNING_SPACE_INSUFFICIENT",)
        tangent = radius * tan(abs(turn) / 2.0)
        start = _subtract(current, _scale(incoming, tangent))
        end = _add(current, _scale(outgoing, tangent))
        center = _add(start, _scale(_left_normal(incoming), (1.0 if turn > 0 else -1.0) * radius))
        corners[index] = (start, end, center, turn, tangent)
    for segment in range(len(points) - 1):
        start_trim = corners.get(segment, (None, None, None, 0.0, 0.0))[4]
        end_trim = corners.get(segment + 1, (None, None, None, 0.0, 0.0))[4]
        if start_trim + end_trim > _distance(points[segment], points[segment + 1]) + EPSILON:
            return (), ("TURNING_SPACE_INSUFFICIENT",)
    primitives: list[TrajectoryPrimitive] = []
    cursor = points[0]
    for index in range(1, len(points) - 1):
        corner = corners.get(index)
        if corner is None:
            continue
        start, end, center, turn, _ = corner
        _append_line(primitives, cursor, start)
        heading_in = atan2(start[1] - cursor[1], start[0] - cursor[0])
        primitives.append(
            TrajectoryPrimitive(
                kind="arc",
                start_xy=start,
                end_xy=end,
                heading_start_rad=heading_in,
                heading_end_rad=heading_in + turn,
                length_m=radius * abs(turn),
                curvature_per_m=(1.0 if turn > 0 else -1.0) / radius,
                center_xy=center,
                turn_angle_rad=turn,
            )
        )
        cursor = end
    _append_line(primitives, cursor, points[-1])
    return tuple(primitives), ()


def _append_line(primitives: list[TrajectoryPrimitive], start: PointXY, end: PointXY) -> None:
    length = _distance(start, end)
    if length <= EPSILON:
        return
    heading = atan2(end[1] - start[1], end[0] - start[0])
    primitives.append(TrajectoryPrimitive("line", start, end, heading, heading, length, 0.0))


def _validate_primitives(
    primitives: tuple[TrajectoryPrimitive, ...],
    path: tuple[str, ...],
    graph: H3Graph,
    evaluation: FactorEvaluation,
    vehicle: VehicleProfile,
    environment: EnvironmentConfig,
    geometry: GeometryConfig,
    projection: _LocalProjection,
) -> TrajectoryResult:
    obstacles, domain, cell_polygons = _graph_geometries(graph, evaluation, projection)
    envelopes: list[Polygon] = []
    sampled_points: list[PointXY] = []
    segment_budget = 0
    for primitive in primitives:
        envelope, samples, used = _primitive_sweep(primitive, vehicle, geometry)
        segment_budget += used
        if segment_budget > geometry.max_arc_segments:
            return _result(
                path,
                "incomplete",
                ("RESOURCE_EXHAUSTED",),
                (),
                primitives,
                0.0,
                {},
                None,
                0.0,
                0.0,
                0.0,
                (),
            )
        envelopes.append(envelope)
        if not sampled_points:
            sampled_points.extend(samples)
        else:
            sampled_points.extend(samples[1:])
    if not envelopes:
        heading = 0.0
        envelope = _vehicle_footprint((0.0, 0.0), heading, vehicle)
        envelopes = [envelope]
        sampled_points = [(0.0, 0.0)]
    swept = unary_union(envelopes)
    obstacle_margin = obstacles.buffer(geometry.map_error_m + geometry.geometry_tolerance_m)
    failures: list[str] = []
    if not obstacles.is_empty and swept.intersects(obstacle_margin):
        failures.append("COLLISION")
    valid_domain = domain.buffer(-(geometry.map_error_m + geometry.geometry_tolerance_m))
    if valid_domain.is_empty or not valid_domain.covers(swept):
        failures.append("MAP_BOUNDARY")
    length = sum(primitive.length_m for primitive in primitives)
    dependencies = tuple(
        sorted(cell_id for cell_id, polygon in cell_polygons.items() if polygon.intersects(swept))
    )
    environment_distance, unknown_length = _continuous_environment_metrics(
        sampled_points,
        length,
        dependencies,
        graph,
        cell_polygons,
        environment,
    )
    legacy = evaluate_path_metrics(path, evaluation)
    eta = legacy.eta_s * length / legacy.distance_m if legacy.distance_m > 0.0 else 0.0
    clearance = _clearance(swept, obstacles, valid_domain)
    coordinates = tuple(projection.inverse(point) for point in sampled_points)
    status = "invalid" if failures else "valid"
    return _result(
        path,
        status,
        tuple(failures),
        coordinates,
        primitives,
        length,
        environment_distance,
        clearance,
        max((abs(item.curvature_per_m) for item in primitives), default=0.0),
        eta,
        unknown_length,
        dependencies,
    )


def _primitive_sweep(
    primitive: TrajectoryPrimitive,
    vehicle: VehicleProfile,
    geometry: GeometryConfig,
) -> tuple[Polygon, list[PointXY], int]:
    if primitive.kind == "line":
        first = _vehicle_footprint(primitive.start_xy, primitive.heading_start_rad, vehicle)
        second = _vehicle_footprint(primitive.end_xy, primitive.heading_end_rad, vehicle)
        return unary_union([first, second]).convex_hull, [primitive.start_xy, primitive.end_xy], 1
    if primitive.center_xy is None:
        raise AssertionError("arc center is required.")
    count = max(1, int(ceil(abs(primitive.turn_angle_rad) / radians(geometry.arc_step_deg))))
    if count > geometry.max_arc_segments:
        return Polygon(), [], count
    start_angle = atan2(
        primitive.start_xy[1] - primitive.center_xy[1],
        primitive.start_xy[0] - primitive.center_xy[0],
    )
    radius = 1.0 / abs(primitive.curvature_per_m)
    poses: list[tuple[PointXY, float]] = []
    for index in range(count + 1):
        fraction = index / count
        angle = start_angle + primitive.turn_angle_rad * fraction
        point = (
            primitive.center_xy[0] + radius * cos(angle),
            primitive.center_xy[1] + radius * sin(angle),
        )
        heading = primitive.heading_start_rad + primitive.turn_angle_rad * fraction
        poses.append((point, heading))
    parts: list[Polygon] = []
    rho_max = _vehicle_corner_radius(vehicle, radius, primitive.curvature_per_m > 0.0)
    delta = abs(primitive.turn_angle_rad) / count
    sagitta = rho_max * (1.0 - cos(delta / 2.0))
    for first, second in zip(poses[:-1], poses[1:], strict=True):
        hull = unary_union(
            [
                _vehicle_footprint(first[0], first[1], vehicle),
                _vehicle_footprint(second[0], second[1], vehicle),
            ]
        ).convex_hull
        parts.append(hull.buffer(sagitta))
    return unary_union(parts), [pose[0] for pose in poses], count


def _vehicle_footprint(point: PointXY, heading: float, vehicle: VehicleProfile) -> Polygon:
    width = _required_geometry(vehicle.width_m)
    wheelbase = _required_geometry(vehicle.wheelbase_m)
    front = _required_geometry(vehicle.front_overhang_m)
    rear = _required_geometry(vehicle.rear_overhang_m)
    corners = (
        (-rear, -width / 2),
        (wheelbase + front, -width / 2),
        (wheelbase + front, width / 2),
        (-rear, width / 2),
    )
    return Polygon([_transform_body(corner, point, heading) for corner in corners])


def _vehicle_corner_radius(vehicle: VehicleProfile, radius: float, left: bool) -> float:
    width = _required_geometry(vehicle.width_m)
    wheelbase = _required_geometry(vehicle.wheelbase_m)
    front = _required_geometry(vehicle.front_overhang_m)
    rear = _required_geometry(vehicle.rear_overhang_m)
    center_y = radius if left else -radius
    return max(
        hypot(x, y - center_y)
        for x, y in (
            (-rear, -width / 2),
            (wheelbase + front, -width / 2),
            (wheelbase + front, width / 2),
            (-rear, width / 2),
        )
    )


def _graph_geometries(
    graph: H3Graph,
    evaluation: FactorEvaluation,
    projection: _LocalProjection,
) -> tuple[BaseGeometry, BaseGeometry, dict[str, Polygon]]:
    polygons = {
        cell_id: Polygon(
            [projection.forward(lat, lng) for lat, lng in h3.cell_to_boundary(cell_id)]
        )
        for cell_id in graph.cells
    }
    domain = unary_union(list(polygons.values()))
    obstacles = unary_union(
        [
            polygon
            for cell_id, polygon in polygons.items()
            if not evaluation.node_metrics[cell_id].is_passable
        ]
    )
    return obstacles, domain, polygons


def _continuous_environment_metrics(
    sampled_points: list[PointXY],
    trajectory_length_m: float,
    dependency_cells: tuple[str, ...],
    graph: H3Graph,
    cell_polygons: Mapping[str, Polygon],
    environment: EnvironmentConfig,
) -> tuple[dict[str, float], float]:
    totals = {f"{pressure:g}": 0.0 for pressure in environment.comparison_pressures}
    if len(sampled_points) < 2 or trajectory_length_m <= EPSILON:
        return totals, 0.0
    centerline = LineString(sampled_points)
    if centerline.length <= EPSILON:
        return totals, 0.0
    scale = trajectory_length_m / centerline.length
    unknown = 0.0
    covered = 0.0
    for cell_id in dependency_cells:
        portion = float(centerline.intersection(cell_polygons[cell_id]).length) * scale
        if portion <= EPSILON:
            continue
        covered += portion
        cell = graph.cells[cell_id]
        cell_unknown = False
        for pressure in environment.comparison_pressures:
            multiplier, is_unknown = environment_multiplier(cell, pressure, environment)
            totals[f"{pressure:g}"] += portion * multiplier
            cell_unknown = cell_unknown or is_unknown
        if cell_unknown:
            unknown += portion
    uncovered = max(0.0, trajectory_length_m - covered)
    if uncovered > EPSILON:
        unknown += uncovered
        for pressure in environment.comparison_pressures:
            multiplier = 1.0 + (
                pressure
                * environment.unknown_surface_range[1]
                * environment.shared_sensitivity
                * (1.0 + environment.unknown_drainage_range[1])
            )
            totals[f"{pressure:g}"] += uncovered * multiplier
    return totals, unknown


def _unknown_h3_length(
    path: tuple[str, ...], graph: H3Graph, environment: EnvironmentConfig
) -> float:
    total = 0.0
    for first, second in zip(path[:-1], path[1:], strict=True):
        edge = graph.edges.get((first, second) if first < second else (second, first))
        if edge is None:
            continue
        _, first_unknown = environment_multiplier(graph.cells[first], 0.0, environment)
        _, second_unknown = environment_multiplier(graph.cells[second], 0.0, environment)
        if first_unknown or second_unknown:
            total += edge.geo_distance
    return total


def _clearance(
    swept: BaseGeometry,
    obstacles: BaseGeometry,
    domain: BaseGeometry,
) -> float:
    obstacle_clearance = float("inf") if obstacles.is_empty else swept.distance(obstacles)
    boundary_clearance = swept.distance(domain.boundary) if domain.covers(swept) else 0.0
    result = min(obstacle_clearance, boundary_clearance)
    return result if isfinite(result) else boundary_clearance


def _result(
    path: tuple[str, ...],
    status: str,
    failures: tuple[str, ...],
    coordinates: tuple[tuple[float, float], ...],
    primitives: tuple[TrajectoryPrimitive, ...],
    length: float,
    environment_distance: Mapping[str, float],
    clearance: float | None,
    curvature: float,
    eta: float,
    unknown: float,
    dependencies: tuple[str, ...],
) -> TrajectoryResult:
    identity = {
        "h3_path": list(path),
        "status": status,
        "primitives": [primitive.to_dict() for primitive in primitives],
    }
    return TrajectoryResult(
        trajectory_id=f"trajectory-{canonical_hash(identity)[:16]}",
        status=status,
        failure_reasons=failures,
        coordinates_wgs84=coordinates,
        primitives=primitives,
        length_m=length,
        environment_distance_m=environment_distance,
        min_clearance_m=clearance,
        max_curvature_per_m=curvature,
        auxiliary_eta_s=eta,
        unknown_coverage_m=unknown,
        swept_dependency_cells=dependencies,
    )


def _required_geometry(value: float | None) -> float:
    if value is None:
        raise AssertionError("complete vehicle geometry was required.")
    return value


def _transform_body(point: PointXY, origin: PointXY, heading: float) -> PointXY:
    return (
        origin[0] + point[0] * cos(heading) - point[1] * sin(heading),
        origin[1] + point[0] * sin(heading) + point[1] * cos(heading),
    )


def _unit(vector: PointXY) -> PointXY:
    length = hypot(*vector)
    if length <= EPSILON:
        raise ValueError("trajectory contains duplicate points after simplification.")
    return (vector[0] / length, vector[1] / length)


def _distance(first: PointXY, second: PointXY) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


def _add(first: PointXY, second: PointXY) -> PointXY:
    return (first[0] + second[0], first[1] + second[1])


def _subtract(first: PointXY, second: PointXY) -> PointXY:
    return (first[0] - second[0], first[1] - second[1])


def _scale(vector: PointXY, factor: float) -> PointXY:
    return (vector[0] * factor, vector[1] * factor)


def _left_normal(vector: PointXY) -> PointXY:
    return (-vector[1], vector[0])


def _dot(first: PointXY, second: PointXY) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _cross(first: PointXY, second: PointXY) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _dot_direction(previous: PointXY, current: PointXY, following: PointXY) -> float:
    return _dot(_subtract(current, previous), _subtract(following, current))
