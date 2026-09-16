"""End-to-end vehicle-aware RoutePlan orchestration over existing static Tiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from math import atan2, cos, inf, radians, sin, sqrt
from pathlib import Path
from time import perf_counter
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
from h3_offroad_planner.environment import resolve_request_environment
from h3_offroad_planner.factor_model import (
    FactorEvaluation,
    StaticPlanningConfig,
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
    PlanningFailedError,
    PlanningInputError,
    RouteEndpoint,
    RouteRequest,
    VehicleProfile,
)
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.reachability import check_route_reachability
from h3_offroad_planner.route_models import RouteCandidate, RoutePlan, plan_id_for_payload
from h3_offroad_planner.route_persistence import (
    atomic_write_json,
    delivery_output_paths,
    write_route_plan_outputs,
    write_routes_gpkg,
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
    *,
    export_gpkg: bool = False,
) -> RoutePlan:
    """Plan through a 1-ring indexed corridor, with one bounded 2-ring retry."""
    request_started = perf_counter()
    try:
        return _run_route_plan_once(
            request,
            progress,
            progress_range,
            corridor_ring=1,
            request_started=request_started,
            export_gpkg=export_gpkg,
        )
    except (GridBuildError, PlanningFailedError):
        if not _routing_index_available(request.parquet_path):
            raise
        return _run_route_plan_once(
            request,
            progress,
            progress_range,
            corridor_ring=2,
            request_started=request_started,
            extra_warning="CORRIDOR_EXPANDED_TO_2_RING",
            export_gpkg=export_gpkg,
        )


def _run_route_plan_once(
    request: RouteRequest,
    progress: ProgressCallback | None,
    progress_range: tuple[int, int],
    *,
    corridor_ring: int,
    request_started: float,
    extra_warning: str | None = None,
    export_gpkg: bool = False,
) -> RoutePlan:
    """Create and persist a complete RoutePlan without activating any candidate."""
    timings: dict[str, float] = {}
    if request.factor_model_path is None:
        raise PlanningInputError("factor_model_path is required for the RoutePlan flow.")
    _validate_route_plan_planner(request.planner_config_path)
    static_planning = (
        load_static_planning_config(request.static_planning_path)
        if request.static_planning_path is not None
        else None
    )
    environment_snapshot: dict[str, object] = {}
    environment_snapshot_hash = ""
    environment_warnings: tuple[str, ...] = ()
    if static_planning is not None and (
        request.candidate_limit != static_planning.decision.candidate_limit
        or request.max_candidate_paths != static_planning.decision.display_limit
    ):
        raise PlanningInputError(
            "route candidate limits must match the versioned static planning policy."
        )
    endpoints = _request_endpoints(request)
    phase_started = perf_counter()
    if static_planning is not None:
        start_endpoint = _single_endpoint(endpoints, "start")
        goal_endpoint = _single_endpoint(endpoints, "goal")
        environment, environment_snapshot, environment_snapshot_hash, environment_warnings = (
            resolve_request_environment(
                static_planning.environment,
                static_planning.weather,
                (start_endpoint.lat + goal_endpoint.lat) / 2.0,
                (start_endpoint.lng + goal_endpoint.lng) / 2.0,
                replay_path=request.environment_snapshot_path,
            )
        )
        static_planning = replace(static_planning, environment=environment)
    timings["environment_fetch_s"] = perf_counter() - phase_started
    roi_geometry, _ = _resolve_roi(request, endpoints)
    estimated_cells = estimate_h3_cells_for_roi(roi_geometry, request.res_fine)
    if estimated_cells > request.max_estimated_cells:
        raise GridBuildError(_oversize_message(estimated_cells, request.max_estimated_cells))
    start_pct, end_pct = progress_range
    if progress is not None:
        progress("global_plan", start_pct, "loading route graph and corridor tiles")
    phase_started = perf_counter()
    source_metadata = _source_metadata(request.parquet_path)
    fast_five = source_metadata.get("artifact_kind") == "h3_routing_index"
    search_policy = "fast_five_v1" if fast_five else "full_pareto_v1"
    timings["index_open_s"] = perf_counter() - phase_started
    graph, source_metadata = _load_route_graph(
        request,
        roi_geometry,
        source_metadata,
        progress=progress,
        progress_range=(start_pct, start_pct + 9),
        corridor_ring=corridor_ring,
        max_widest_detour_ratio=(
            static_planning.decision.detour_ratio
            if fast_five and static_planning is not None
            else None
        ),
    )
    source_timings = source_metadata.get("performance", {})
    if isinstance(source_timings, dict):
        timings.update(
            {
                key: float(value)
                for key, value in source_timings.items()
                if key
                in {"index_open_s", "coarse_search_s", "corridor_load_s", "graph_build_s"}
                and isinstance(value, (int, float))
            }
        )
    _restore_static_authority(graph, source_metadata)
    vehicle = load_vehicle(request.vehicle_path)
    factor_config = load_factor_model(request.factor_model_path)
    if progress is not None:
        progress(
            "global_plan",
            start_pct + 10,
            f"evaluating factor model on {len(graph.cells)} cells",
        )
    phase_started = perf_counter()
    evaluation = evaluate_factor_model(
        graph,
        vehicle,
        factor_config,
        None if static_planning is None else static_planning.environment,
    )
    _bind_loaded_index_identity(
        source_metadata,
        evaluation,
        vehicle,
        static_planning,
        environment_snapshot_hash,
    )
    timings["factor_eval_s"] = perf_counter() - phase_started
    phase_started = perf_counter()
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
    base_cache_identity = None
    if source_metadata.get("artifact_kind") == "h3_routing_index":
        base_cache_identity = canonical_hash(
            {
                "routing_index_build_id": source_metadata.get("build_id"),
                "vehicle_hash": evaluation.vehicle_hash,
                "factor_model_hash": evaluation.factor_model_hash,
                "scenario_hash": _scenario_hash(
                    static_planning, environment_snapshot_hash
                ),
            }
        )
    context = PortsMapSearchContext(
        graph,
        evaluation,
        max_ports=factor_config.max_ports,
        max_port_pairs=factor_config.max_port_pairs,
        base_cache_identity=base_cache_identity,
    )
    if progress is not None:
        progress("global_plan", start_pct + 14, "searching Pareto candidate routes")
    planner = DeterministicParetoPlanner(
        context,
        max_paths=request.max_candidate_paths,
        candidate_limit=request.candidate_limit,
        penalty_factor=request.penalty_factor,
        environment_pressures=(
            ()
            if fast_five or static_planning is None
            else static_planning.environment.request_pressures
        ),
        attempts_per_profile=1 if fast_five else None,
    )
    raw_candidates = planner.plan(start, goal, progress=progress)
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
    timings["candidate_search_s"] = perf_counter() - phase_started
    candidates = aggregation.candidates
    recommended_candidate_id = aggregation.recommended_candidate_id
    robust_statistics: dict[str, object] = {}
    robust_warnings: tuple[str, ...] = ()
    if static_planning is not None:
        phase_started = perf_counter()
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
        timings["geometry_s"] = perf_counter() - phase_started
    else:
        timings["geometry_s"] = 0.0
    context.clear_pair_cache()
    if source_metadata.get("artifact_kind") == "h3_routing_index":
        missing_roles = sorted(
            {
                "fastest_eta",
                "shortest_distance",
                "max_passability_margin",
                "minimum_travel_cost",
                "independent_backup",
            }.difference(role for candidate in candidates for role in candidate.roles)
        )
        if missing_roles:
            raise PlanningFailedError(f"ROUTING_INDEX_ROLE_COVERAGE_INSUFFICIENT:{missing_roles}")
    if progress is not None:
        progress("evaluation", end_pct, "exporting route plan and thematic layers")
    paths = delivery_output_paths(request.output_dir)
    output_files = {
        "route_plan": paths["route_plan"],
        "routes_geojson": paths["routes_geojson"],
    }
    if export_gpkg:
        output_files["routes"] = paths["routes"]
    schema_version = 2 if static_planning is not None else 1
    policy_hash = "" if static_planning is None else canonical_hash(static_planning.to_dict())
    scenario_hash = _scenario_hash(static_planning, environment_snapshot_hash)
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
            "search_policy": search_policy,
            "profile_search_count": planner.profile_search_count,
            "environment_snapshot": environment_snapshot,
            "environment_snapshot_hash": environment_snapshot_hash,
            "environment_pressure_basis": (
                None if static_planning is None else static_planning.environment.pressure_basis
            ),
            **robust_statistics,
        },
        output_files=output_files,
        warnings=tuple(
            dict.fromkeys(
                (
                    *aggregation.warnings,
                    *robust_warnings,
                    *environment_warnings,
                    *((extra_warning,) if extra_warning is not None else ()),
                )
            )
        ),
        schema_version=schema_version,
    )
    write_effective_snapshots(request.output_dir, vehicle, factor_config)
    if static_planning is not None:
        write_static_planning_snapshot(request.output_dir, static_planning)
    timings.setdefault("corridor_load_s", 0.0)
    timings.setdefault("graph_build_s", 0.0)
    timings.setdefault("coarse_search_s", 0.0)
    write_route_plan_outputs(
        plan,
        graph,
        request.output_dir,
        source_metadata,
        export_gpkg=False,
    )
    timings["plan_ready_s"] = perf_counter() - request_started
    if export_gpkg and source_metadata.get("artifact_kind") == "h3_routing_index":
        export_started = perf_counter()
        write_routes_gpkg(paths["routes"], plan)
        timings["heavy_export_s"] = perf_counter() - export_started
    else:
        timings["heavy_export_s"] = 0.0
    output_bytes = sum(
        path.stat().st_size
        for path in Path(request.output_dir).iterdir()
        if path.is_file()
    )
    atomic_write_json(
        Path(request.output_dir) / "performance.json",
        {
            **{key: round(value, 6) for key, value in timings.items()},
            "loaded_file_count": _mapping_int(source_metadata, "source_loaded_file_count", 1),
            "raw_row_count": _mapping_int(
                source_metadata, "source_raw_row_count", len(graph.cells)
            ),
            "cell_count": len(graph.cells),
            "edge_count": len(graph.edges),
            "candidate_pool_count": _mapping_int(aggregation.statistics, "raw_count", 0),
            "returned_candidate_count": len(candidates),
            "corridor_ring": _mapping_int(source_metadata, "corridor_ring", 0),
            "active_parent_count": _mapping_list_len(source_metadata, "active_parent_h3"),
            "search_policy": search_policy,
            "profile_search_count": planner.profile_search_count,
            "fine_search_calls": context.fine_search_calls,
            "visited_parent_count": context.visited_parent_count,
            "coarse_widest_included": source_metadata.get("coarse_widest_included"),
            "coarse_widest_parent_count": source_metadata.get("coarse_widest_parent_count"),
            "pair_cache_hits": context.cache_hits,
            "base_pair_cache_hits": context.base_cache_hits,
            "base_pair_cache_misses": context.base_cache_misses,
            "base_pair_cache_entries": context.base_cache_size,
            "output_bytes": output_bytes,
        },
    )
    return plan


def _routing_index_available(source: str) -> bool:
    path = Path(source)
    if path.name == "current.json" and path.parent.name == "routing_index":
        return path.is_file()
    return (path.parent / "routing_index" / "current.json").is_file()


def _bind_loaded_index_identity(
    source_metadata: dict[str, object],
    evaluation: FactorEvaluation,
    vehicle: VehicleProfile,
    static_planning: StaticPlanningConfig | None,
    environment_snapshot_hash: str = "",
) -> None:
    if source_metadata.get("artifact_kind") != "h3_routing_index":
        return
    source_metadata["vehicle_hash"] = evaluation.vehicle_hash
    source_metadata["factor_model_hash"] = evaluation.factor_model_hash
    if static_planning is not None:
        source_metadata["scenario_hash"] = _scenario_hash(
            static_planning, environment_snapshot_hash
        )

    raw_missing = source_metadata.get("missing_physical_inputs", [])
    missing = (
        {
            item
            for item in raw_missing
            if isinstance(item, str)
            and not item.startswith("vehicle.")
            and item != "soil.default_theta_v"
        }
        if isinstance(raw_missing, list)
        else set()
    )
    for field in ("width_m", "wheelbase_m", "front_overhang_m", "rear_overhang_m"):
        if getattr(vehicle, field) is None:
            missing.add(f"vehicle.{field}")
    source_metadata["missing_physical_inputs"] = sorted(missing)
    source_metadata["evidence_status"] = "COMPLETE" if not missing else "INCOMPLETE"


def _scenario_hash(
    static_planning: StaticPlanningConfig | None,
    environment_snapshot_hash: str,
) -> str:
    if static_planning is None:
        return ""
    return canonical_hash(
        {
            "request_pressures": list(static_planning.environment.request_pressures),
            "environment_snapshot_hash": environment_snapshot_hash,
        }
    )


def _mapping_int(payload: dict[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _mapping_list_len(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, [])
    return len(value) if isinstance(value, list) else 0


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
