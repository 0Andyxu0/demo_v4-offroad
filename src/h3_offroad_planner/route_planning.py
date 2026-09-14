"""End-to-end vehicle-aware RoutePlan orchestration over existing static Tiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from math import atan2, cos, inf, radians, sin, sqrt
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from h3_offroad_planner.candidate_aggregation import (
    CandidateAggregator,
    select_robust_candidates,
)
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.dynamics.trajectory_geometry import (
    TrajectoryResult,
    build_and_validate_trajectory,
)
from h3_offroad_planner.factor_model import (
    FactorEvaluation,
    canonical_hash,
    evaluate_factor_model,
    load_factor_model,
    load_static_planning_config,
    write_effective_snapshots,
    write_static_planning_snapshot,
)
from h3_offroad_planner.models import (
    ConfigError,
    GridBuildError,
    H3Graph,
    PlanningInputError,
    RouteEndpoint,
    RouteRequest,
)
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.reachability import check_route_reachability
from h3_offroad_planner.route_models import RouteCandidate, RoutePlan, plan_id_for_payload
from h3_offroad_planner.route_persistence import (
    delivery_output_paths,
    write_route_plan_outputs,
)
from h3_offroad_planner.routing import (
    _load_route_graph,
    _oversize_message,
    _request_endpoints,
    _resolve_roi,
    _single_endpoint,
    _source_metadata,
    estimate_h3_cells_for_roi,
)

__all__ = ["run_route_plan"]


ProgressCallback = Callable[[str, int, str], None]


def run_route_plan(
    request: RouteRequest,
    progress: ProgressCallback | None = None,
    progress_range: tuple[int, int] = (75, 95),
) -> RoutePlan:
    """Create and persist a complete RoutePlan without activating any candidate."""
    if request.factor_model_path is None:
        raise PlanningInputError("factor_model_path is required for the RoutePlan flow.")
    _validate_route_plan_planner(request.planner_config_path)
    endpoints = _request_endpoints(request)
    roi_geometry, _ = _resolve_roi(request, endpoints)
    estimated_cells = estimate_h3_cells_for_roi(roi_geometry, request.res_fine)
    if estimated_cells > request.max_estimated_cells:
        raise GridBuildError(_oversize_message(estimated_cells, request.max_estimated_cells))
    start_pct, end_pct = progress_range
    if progress is not None:
        progress("global_plan", start_pct, "loading route graph and corridor tiles")
    source_metadata = _source_metadata(request.parquet_path)
    graph, source_metadata = _load_route_graph(
        request,
        roi_geometry,
        source_metadata,
        progress=progress,
        progress_range=(start_pct, start_pct + 9),
    )
    _restore_static_authority(graph, source_metadata)
    vehicle = load_vehicle(request.vehicle_path)
    factor_config = load_factor_model(request.factor_model_path)
    static_planning = (
        load_static_planning_config(request.static_planning_path)
        if request.static_planning_path is not None
        else None
    )
    if static_planning is not None and (
        request.candidate_limit != static_planning.decision.candidate_limit
        or request.max_candidate_paths != static_planning.decision.display_limit
    ):
        raise PlanningInputError(
            "route candidate limits must match the versioned static planning policy."
        )
    if progress is not None:
        progress(
            "global_plan",
            start_pct + 10,
            f"evaluating factor model on {len(graph.cells)} cells",
        )
    evaluation = evaluate_factor_model(
        graph,
        vehicle,
        factor_config,
        None if static_planning is None else static_planning.environment,
    )
    start = _snap_evaluated(
        graph,
        evaluation,
        _single_endpoint(endpoints, "start"),
        request.max_snap_distance_m,
    )
    goal = _snap_evaluated(
        graph,
        evaluation,
        _single_endpoint(endpoints, "goal"),
        request.max_snap_distance_m,
    )
    check_route_reachability(graph, evaluation, start, goal, progress=progress)
    context = PortsMapSearchContext(
        graph,
        evaluation,
        max_ports=factor_config.max_ports,
        max_port_pairs=factor_config.max_port_pairs,
    )
    if progress is not None:
        progress("global_plan", start_pct + 14, "searching Pareto candidate routes")
    raw_candidates = DeterministicParetoPlanner(
        context,
        max_paths=request.max_candidate_paths,
        candidate_limit=request.candidate_limit,
        penalty_factor=request.penalty_factor,
        environment_pressures=(
            () if static_planning is None else static_planning.environment.request_pressures
        ),
    ).plan(start, goal, progress=progress)
    if progress is not None:
        progress(
            "global_plan",
            start_pct + 17,
            f"aggregating {len(raw_candidates)} candidate routes",
        )
    aggregation = CandidateAggregator(graph, context).aggregate(
        raw_candidates,
        request.mission_profile,
        request.max_candidate_paths,
        preserve_pool=static_planning is not None,
    )
    candidates = aggregation.candidates
    recommended_candidate_id = aggregation.recommended_candidate_id
    robust_statistics: dict[str, object] = {}
    robust_warnings: tuple[str, ...] = ()
    if static_planning is not None:
        candidates = tuple(
            _with_trajectory(
                candidate,
                build_and_validate_trajectory(
                    candidate.h3_path,
                    graph,
                    evaluation,
                    vehicle,
                    static_planning.environment,
                    static_planning.geometry,
                ),
            )
            for candidate in candidates
        )
        candidates, recommended_candidate_id, robust_statistics, robust_warnings = (
            select_robust_candidates(
                candidates,
                static_planning.decision,
                request_pressures=static_planning.environment.request_pressures,
            )
        )
    context.clear_pair_cache()
    if progress is not None:
        progress("evaluation", end_pct, "exporting route plan and thematic layers")
    paths = delivery_output_paths(request.output_dir)
    schema_version = 2 if static_planning is not None else 1
    policy_hash = "" if static_planning is None else canonical_hash(static_planning.to_dict())
    scenario_hash = (
        ""
        if static_planning is None
        else canonical_hash(list(static_planning.environment.request_pressures))
    )
    identity = {
        "schema_version": schema_version,
        "mission_profile": request.mission_profile,
        "recommended_candidate_id": recommended_candidate_id,
        "independence_reference_candidate_id": aggregation.independence_reference_candidate_id,
        "vehicle_hash": evaluation.vehicle_hash,
        "factor_model_hash": evaluation.factor_model_hash,
        "static_input_hash": evaluation.static_input_hash,
        "graph_topology_hash": evaluation.graph_topology_hash,
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "candidate_roles": [list(candidate.roles) for candidate in candidates],
    }
    if static_planning is not None:
        identity.update(
            {
                "planning_policy_hash": policy_hash,
                "scenario_hash": scenario_hash,
                "trajectory_ids": [
                    candidate.trajectory.get("trajectory_id") for candidate in candidates
                ],
            }
        )
    plan = RoutePlan(
        plan_id=plan_id_for_payload(identity),
        mission_profile=request.mission_profile,
        recommended_candidate_id=recommended_candidate_id,
        independence_reference_candidate_id=aggregation.independence_reference_candidate_id,
        vehicle_hash=evaluation.vehicle_hash,
        factor_model_hash=evaluation.factor_model_hash,
        static_input_hash=evaluation.static_input_hash,
        graph_topology_hash=evaluation.graph_topology_hash,
        candidates=candidates,
        planning_policy_hash=policy_hash,
        scenario_hash=scenario_hash,
        aggregation_stats={
            **aggregation.statistics,
            "max_candidate_paths": request.max_candidate_paths,
            "candidate_limit": request.candidate_limit,
            "penalty_factor": request.penalty_factor,
            **robust_statistics,
        },
        output_files=paths,
        warnings=tuple(dict.fromkeys((*aggregation.warnings, *robust_warnings))),
        schema_version=schema_version,
    )
    write_effective_snapshots(request.output_dir, vehicle, factor_config)
    if static_planning is not None:
        write_static_planning_snapshot(request.output_dir, static_planning)
    write_route_plan_outputs(plan, graph, request.output_dir, source_metadata)
    return plan


def _with_trajectory(
    candidate: RouteCandidate,
    trajectory: TrajectoryResult,
) -> RouteCandidate:
    payload = trajectory.to_dict()
    coordinates = payload["coordinates_wgs84"]
    geojson = candidate.geojson
    if isinstance(coordinates, list) and len(coordinates) >= 2:
        geojson = {
            "type": "Feature",
            "properties": {
                "h3_path": list(candidate.h3_path),
                "trajectory_id": trajectory.trajectory_id,
            },
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }
    return replace(candidate, trajectory=payload, geojson=geojson)


def _validate_route_plan_planner(path: str) -> None:
    """Require the unique new-flow planner name and reject stale configuration."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"planner config file does not exist: {path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid planner YAML: {path}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("planner config must contain a mapping.")
    config = cast(dict[str, object], loaded)
    unknown = sorted(set(config) - {"global_planner"})
    if unknown:
        raise ConfigError(
            f"RoutePlan planner config contains task-owned or unsupported fields: {unknown}"
        )
    planner = config.get("global_planner")
    if planner != "DeterministicParetoPlanner":
        raise ConfigError("RoutePlan requires global_planner: DeterministicParetoPlanner.")


def _snap_evaluated(
    graph: H3Graph,
    evaluation: FactorEvaluation,
    endpoint: RouteEndpoint,
    max_distance_m: float,
) -> str:
    if max_distance_m <= 0.0:
        raise ValueError("max_distance_m must be positive.")
    best_cell = ""
    best_distance = inf
    for cell_id in sorted(graph.cells):
        if not evaluation.node_metrics[cell_id].is_passable:
            continue
        cell = graph.cells[cell_id]
        distance = _haversine_m(endpoint.lat, endpoint.lng, cell.lat, cell.lng)
        if distance < best_distance:
            best_cell = cell_id
            best_distance = distance
    if not best_cell:
        raise PlanningInputError("factor evaluation has no passable cell for endpoint snapping.")
    if best_distance > max_distance_m:
        raise PlanningInputError(
            f"endpoint role={endpoint.role!r} exceeds max snap distance: "
            f"{best_distance:.1f} m > {max_distance_m:.1f} m."
        )
    return best_cell


def _restore_static_authority(graph: H3Graph, source_metadata: dict[str, object]) -> None:
    authority = source_metadata.get("tile_fact_authority")
    if authority == "vehicle_independent":
        return
    for cell in graph.cells.values():
        cell.is_passable = cell.lc_factor != inf and (cell.landcover_type or "").lower() != "water"


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_m = 6_371_000.0
    delta_lat = radians(lat_b - lat_a)
    delta_lng = radians(lng_b - lng_a)
    first_lat = radians(lat_a)
    second_lat = radians(lat_b)
    root = sin(delta_lat / 2.0) ** 2
    root += cos(first_lat) * cos(second_lat) * sin(delta_lng / 2.0) ** 2
    return 2.0 * earth_radius_m * atan2(sqrt(root), sqrt(max(0.0, 1.0 - root)))
