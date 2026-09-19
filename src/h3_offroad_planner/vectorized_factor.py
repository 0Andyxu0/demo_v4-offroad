"""Vectorized factor evaluation engine and directed edge computation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from h3_offroad_planner.dynamics.bekker import GRAVITY_MPS2
from h3_offroad_planner.factor_model import (
    _EMPTY_ENV,
    DirectedEdgeMetrics,
    EnvironmentConfig,
    FactorModelConfig,
    NodeFactorMetrics,
    _pressure_key,
    environment_multiplier,
)
from h3_offroad_planner.models import H3Graph, PlanningInputError, VehicleProfile
from h3_offroad_planner.vectorized_soil import (
    vectorized_bekker_sinkage,
    vectorized_cone_index_kpa,
)

__all__ = [
    "VectorizedEdgeArrays",
    "compute_vectorized_edge_arrays",
    "evaluate_directed_edges_vectorized",
    "scalar_speed_multiplier",
    "vectorized_bekker_sinkage",
    "vectorized_cone_index_kpa",
    "vectorized_speed_multiplier",
]


def scalar_speed_multiplier(
    landcover_code: int | None,
    uscs: str | None,
    tri: float,
    config: FactorModelConfig,
) -> float:
    """Return one terrain speed multiplier for a single cell."""
    lc_factor = (
        config.landcover_speed_by_code.get(landcover_code, config.missing_speed_nominal)
        if landcover_code is not None
        else config.missing_speed_nominal
    )
    soil_factor = (
        config.soil_speed_by_uscs.get(uscs, config.missing_speed_nominal)
        if uscs is not None
        else config.missing_speed_nominal
    )
    tri_span = max(config.tri_worst - config.tri_best, 1.0e-9)
    tri_factor = max(0.0, min(1.0, 1.0 - (tri - config.tri_best) / tri_span))
    return float(lc_factor * soil_factor * tri_factor)


def vectorized_speed_multiplier(
    landcover_codes: npt.NDArray[np.float64],
    uscs_values: npt.NDArray[np.str_],
    tri_values: npt.NDArray[np.float64],
    config: FactorModelConfig,
) -> npt.NDArray[np.float64]:
    """Return terrain speed multipliers for arrays of cells."""
    def _lc_lookup(code: float) -> float:
        if np.isfinite(code):
            return config.landcover_speed_by_code.get(
                int(code), config.missing_speed_nominal
            )
        return config.missing_speed_nominal

    def _soil_lookup(uscs: str) -> float:
        if uscs:
            return config.soil_speed_by_uscs.get(
                str(uscs), config.missing_speed_nominal
            )
        return config.missing_speed_nominal

    lc = np.vectorize(_lc_lookup, otypes=[np.float64])(landcover_codes)
    soil = np.vectorize(_soil_lookup, otypes=[np.float64])(uscs_values)
    tri_span = max(config.tri_worst - config.tri_best, 1.0e-9)
    tri = np.clip(1.0 - (tri_values - config.tri_best) / tri_span, 0.0, 1.0)
    return lc * soil * tri


@dataclass(frozen=True)
class VectorizedEdgeArrays:
    """Container holding continuous arrays of batch directed edge computations."""

    u_keys: list[str]
    v_keys: list[str]
    u_indices: npt.NDArray[np.int32]
    v_indices: npt.NDArray[np.int32]
    distances_m: npt.NDArray[np.float64]
    slopes_deg: npt.NDArray[np.float64]
    grade_force_n: npt.NDArray[np.float64]
    speed_lower_mps: npt.NDArray[np.float64]
    speed_nominal_mps: npt.NDArray[np.float64]
    speed_upper_mps: npt.NDArray[np.float64]
    safety_margin: npt.NDArray[np.float64]
    travel_cost: npt.NDArray[np.float64]
    is_passable: npt.NDArray[np.bool_]


def compute_vectorized_edge_arrays(
    graph: H3Graph,
    node_metrics: Mapping[str, NodeFactorMetrics],
    vehicle: VehicleProfile,
    config: FactorModelConfig,
) -> VectorizedEdgeArrays:
    """Compute dense continuous NumPy arrays for all potential directed edges in graph."""
    if set(node_metrics) != set(graph.cells):
        raise PlanningInputError("node metrics must cover every graph cell exactly once.")

    cell_ids = list(graph.cells.keys())
    cell_to_idx = {cid: idx for idx, cid in enumerate(cell_ids)}
    num_cells = len(cell_ids)

    node_passable = np.fromiter(
        (node_metrics[cid].is_passable for cid in cell_ids),
        dtype=np.bool_,
        count=num_cells,
    )
    node_speed_lower = np.fromiter(
        (node_metrics[cid].speed_lower_mps for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    node_speed_nominal = np.fromiter(
        (node_metrics[cid].speed_nominal_mps for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    node_speed_upper = np.fromiter(
        (node_metrics[cid].speed_upper_mps for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    node_margin_lower = np.fromiter(
        (node_metrics[cid].safety_margin.lower for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    cell_elevation = np.fromiter(
        (graph.cells[cid].elevation for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    cell_lc_factor = np.fromiter(
        (graph.cells[cid].lc_factor for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )
    cell_tri = np.fromiter(
        (graph.cells[cid].tri for cid in cell_ids),
        dtype=np.float64,
        count=num_cells,
    )

    sorted_edges = sorted(
        graph.edges.values(), key=lambda item: (item.cell_a, item.cell_b)
    )
    num_edges = len(sorted_edges)
    num_directed = 2 * num_edges

    u_indices = np.empty(num_directed, dtype=np.int32)
    v_indices = np.empty(num_directed, dtype=np.int32)
    distances = np.empty(num_directed, dtype=np.float64)
    slopes = np.empty(num_directed, dtype=np.float64)
    u_keys: list[str] = [None] * num_directed  # type: ignore[list-item]
    v_keys: list[str] = [None] * num_directed  # type: ignore[list-item]

    for i, edge in enumerate(sorted_edges):
        a = edge.cell_a
        b = edge.cell_b
        d = edge.geo_distance
        idx1 = 2 * i
        idx2 = idx1 + 1
        ua = cell_to_idx[a]
        ub = cell_to_idx[b]

        u_indices[idx1] = ua
        v_indices[idx1] = ub
        distances[idx1] = d
        slopes[idx1] = edge.slope_a_to_b
        u_keys[idx1] = a
        v_keys[idx1] = b

        u_indices[idx2] = ub
        v_indices[idx2] = ua
        distances[idx2] = d
        slopes[idx2] = edge.slope_b_to_a
        u_keys[idx2] = b
        v_keys[idx2] = a

    passable = node_passable[u_indices] & node_passable[v_indices]
    abs_slope = np.abs(slopes)
    slope_passable = abs_slope <= vehicle.max_climb_angle_deg

    rad_slope = np.radians(slopes)
    uphill = np.maximum(np.sin(rad_slope), 0.0)
    grade_force = (vehicle.mass_kg * GRAVITY_MPS2) * uphill
    thrust_passable = grade_force <= vehicle.max_thrust_n

    valid = passable & slope_passable & thrust_passable

    divisor = np.where(
        slopes >= 0.0,
        vehicle.max_climb_angle_deg,
        2.0 * vehicle.max_climb_angle_deg,
    )
    nominal_slope_factor = np.maximum(
        config.directed_slope_speed_min_factor, 1.0 - abs_slope / divisor
    )
    spread = (1.0 - config.missing_confidence) * 0.1
    dir_lower = np.maximum(0.0, nominal_slope_factor - spread)
    dir_nominal = nominal_slope_factor
    dir_upper = np.minimum(1.0, nominal_slope_factor + spread)

    speed_lower = (
        np.minimum(node_speed_lower[u_indices], node_speed_lower[v_indices]) * dir_lower
    )
    speed_nominal = (
        np.minimum(node_speed_nominal[u_indices], node_speed_nominal[v_indices])
        * dir_nominal
    )
    speed_upper = (
        np.minimum(node_speed_upper[u_indices], node_speed_upper[v_indices]) * dir_upper
    )

    speed_passable = (speed_nominal > 0.0) & (speed_upper > 0.0)
    valid = valid & speed_passable

    slope_margin = np.clip(1.0 - abs_slope / vehicle.max_climb_angle_deg, 0.0, 1.0)
    thrust_margin = 1.0 - grade_force / vehicle.max_thrust_n
    node_margin = np.minimum(node_margin_lower[u_indices], node_margin_lower[v_indices])
    edge_margin = np.clip(
        np.minimum(np.minimum(node_margin, slope_margin), thrust_margin), 0.0, 1.0
    )

    slope_util = abs_slope / vehicle.max_climb_angle_deg
    terrain_factor = 1.0 + slope_util**2 + config.tri_coefficient * cell_tri[v_indices]
    delta_h = cell_elevation[v_indices] - cell_elevation[u_indices]
    elevation_gain = np.maximum(delta_h, 0.0)
    travel_cost = (
        distances * cell_lc_factor[v_indices] * terrain_factor
        + config.gravity_coefficient * elevation_gain
    )

    cost_passable = np.isfinite(travel_cost)
    valid = valid & cost_passable

    return VectorizedEdgeArrays(
        u_keys=u_keys,
        v_keys=v_keys,
        u_indices=u_indices,
        v_indices=v_indices,
        distances_m=distances,
        slopes_deg=slopes,
        grade_force_n=grade_force,
        speed_lower_mps=speed_lower,
        speed_nominal_mps=speed_nominal,
        speed_upper_mps=speed_upper,
        safety_margin=edge_margin,
        travel_cost=travel_cost,
        is_passable=valid,
    )


def evaluate_directed_edges_vectorized(
    graph: H3Graph,
    node_metrics: Mapping[str, NodeFactorMetrics],
    vehicle: VehicleProfile,
    config: FactorModelConfig,
    environment: EnvironmentConfig | None = None,
) -> dict[tuple[str, str], DirectedEdgeMetrics]:
    """Build the authoritative directed metrics using NumPy batch vectorization."""
    if not graph.edges:
        if set(node_metrics) != set(graph.cells):
            raise PlanningInputError(
                "node metrics must cover every graph cell exactly once."
            )
        return {}

    arrays = compute_vectorized_edge_arrays(graph, node_metrics, vehicle, config)
    valid_indices = np.flatnonzero(arrays.is_passable)
    if len(valid_indices) == 0:
        return {}

    v_dists = arrays.distances_m[valid_indices]
    v_speed_upper = arrays.speed_upper_mps[valid_indices]
    v_speed_nom = arrays.speed_nominal_mps[valid_indices]
    v_speed_lower = arrays.speed_lower_mps[valid_indices]
    v_margin = arrays.safety_margin[valid_indices]
    v_slopes = arrays.slopes_deg[valid_indices]
    v_cost = arrays.travel_cost[valid_indices]

    v_severity = -np.log(np.maximum(v_margin, config.epsilon))
    v_terrain_risk = v_dists * v_severity
    v_eta_lower = v_dists / v_speed_upper
    v_eta_nom = v_dists / v_speed_nom
    v_eta_upper_bounded = v_speed_lower > 0.0

    fast_create = DirectedEdgeMetrics._fast_create
    cache: dict[tuple[str, str], DirectedEdgeMetrics] = {}

    if environment is None:
        for k, idx in enumerate(valid_indices):
            u = arrays.u_keys[idx]
            v = arrays.v_keys[idx]
            bounded = bool(v_eta_upper_bounded[k])
            eu = float(v_dists[k] / v_speed_lower[k]) if bounded else None
            cache[(u, v)] = fast_create(
                u,
                v,
                float(v_dists[k]),
                float(v_eta_lower[k]),
                float(v_eta_nom[k]),
                eu,
                bounded,
                float(v_terrain_risk[k]),
                float(v_cost[k]),
                float(v_margin[k]),
                float(v_margin[k]),
                float(v_margin[k]),
                float(v_slopes[k]),
                _EMPTY_ENV,
            )
    else:
        pressures = environment.comparison_pressures
        if not pressures:
            for k, idx in enumerate(valid_indices):
                u = arrays.u_keys[idx]
                v = arrays.v_keys[idx]
                bounded = bool(v_eta_upper_bounded[k])
                eu = float(v_dists[k] / v_speed_lower[k]) if bounded else None
                cache[(u, v)] = fast_create(
                    u,
                    v,
                    float(v_dists[k]),
                    float(v_eta_lower[k]),
                    float(v_eta_nom[k]),
                    eu,
                    bounded,
                    float(v_terrain_risk[k]),
                    float(v_cost[k]),
                    float(v_margin[k]),
                    float(v_margin[k]),
                    float(v_margin[k]),
                    float(v_slopes[k]),
                    _EMPTY_ENV,
                )
        else:
            p_keys = [_pressure_key(p) for p in pressures]
            num_pressures = len(pressures)
            cell_keys = list(graph.cells.keys())
            u_valid_idx = arrays.u_indices[valid_indices]
            v_valid_idx = arrays.v_indices[valid_indices]

            env_dist_arrays: list[npt.NDArray[np.float64]] = []
            for p in pressures:
                cm = {
                    cid: environment_multiplier(cell, p, environment)[0]
                    for cid, cell in graph.cells.items()
                }
                m_arr = np.fromiter(
                    (cm[cid] for cid in cell_keys),
                    dtype=np.float64,
                    count=len(cell_keys),
                )
                env_d = v_dists * (m_arr[u_valid_idx] + m_arr[v_valid_idx]) * 0.5
                env_dist_arrays.append(env_d)

            if num_pressures == 3:
                pk0, pk1, pk2 = p_keys[0], p_keys[1], p_keys[2]
                ed0, ed1, ed2 = env_dist_arrays[0], env_dist_arrays[1], env_dist_arrays[2]
                for k, idx in enumerate(valid_indices):
                    u = arrays.u_keys[idx]
                    v = arrays.v_keys[idx]
                    bounded = bool(v_eta_upper_bounded[k])
                    eu = float(v_dists[k] / v_speed_lower[k]) if bounded else None
                    env_map = {
                        pk0: float(ed0[k]),
                        pk1: float(ed1[k]),
                        pk2: float(ed2[k]),
                    }
                    cache[(u, v)] = fast_create(
                        u,
                        v,
                        float(v_dists[k]),
                        float(v_eta_lower[k]),
                        float(v_eta_nom[k]),
                        eu,
                        bounded,
                        float(v_terrain_risk[k]),
                        float(v_cost[k]),
                        float(v_margin[k]),
                        float(v_margin[k]),
                        float(v_margin[k]),
                        float(v_slopes[k]),
                        MappingProxyType(env_map),
                    )
            else:
                for k, idx in enumerate(valid_indices):
                    u = arrays.u_keys[idx]
                    v = arrays.v_keys[idx]
                    bounded = bool(v_eta_upper_bounded[k])
                    eu = float(v_dists[k] / v_speed_lower[k]) if bounded else None
                    env_map = {
                        p_keys[pi]: float(env_dist_arrays[pi][k])
                        for pi in range(num_pressures)
                    }
                    cache[(u, v)] = fast_create(
                        u,
                        v,
                        float(v_dists[k]),
                        float(v_eta_lower[k]),
                        float(v_eta_nom[k]),
                        eu,
                        bounded,
                        float(v_terrain_risk[k]),
                        float(v_cost[k]),
                        float(v_margin[k]),
                        float(v_margin[k]),
                        float(v_margin[k]),
                        float(v_slopes[k]),
                        MappingProxyType(env_map),
                    )

    return cache
