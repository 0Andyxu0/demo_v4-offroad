"""Command-line orchestration for the GIS-to-route delivery workflow."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import evaluate_factor_model, load_factor_model
from h3_offroad_planner.models import (
    ConfigError,
    GISInputError,
    GridBuildError,
    PlanningFailedError,
    PlanningInputError,
    RouteRequest,
    TileBuildRequest,
)
from h3_offroad_planner.preprocessing.hydrology import (
    HydrologyConfig,
    preprocess_hydrology,
)
from h3_offroad_planner.replanning import ReplanPolicy, replan_route
from h3_offroad_planner.route_models import BlockageRecord, ReplanRequest, ReplanResult
from h3_offroad_planner.route_persistence import load_route_graph_snapshot, select_route
from h3_offroad_planner.route_planning import run_route_plan
from h3_offroad_planner.tiling import TILE_MANIFEST_NAME, build_h3_tile_cache

__all__ = [
    "main",
    "run_delivery_payload",
    "run_hydrology_payload",
    "run_route_payload",
    "run_replan_payload",
    "run_select_payload",
    "run_tile_payload",
]

EXIT_REQUEST_ERROR: int = 2
HYDROLOGY_FIELDS: frozenset[str] = frozenset(
    {
        "analysis_resolution_m",
        "backend",
        "dem_path",
        "flow_method",
        "grass_executable",
        "mapping_t0",
        "mapping_t1",
        "output_dir",
        "upstream_complete",
        "version",
    }
)
TILE_BUILD_FIELDS: frozenset[str] = frozenset(
    {
        "continue_on_error",
        "dem_path",
        "landcover_path",
        "max_cells_per_tile",
        "max_tiles",
        "output_dir",
        "overwrite",
        "res_fine",
        "road_path",
        "roi_layer_path",
        "sampling_mode",
        "soil_catalog_path",
        "soil_path",
        "twi_path",
        "drainage_path",
        "drainage_validity_path",
        "drainage_boundary_path",
        "tile_res",
        "vehicle_path",
        "factor_model_path",
        "static_planning_path",
    }
)
ROUTE_FIELDS: frozenset[str] = frozenset(
    {
        "corridor_buffer_deg",
        "candidate_index",
        "blocked_cells",
        "endpoint_layer_path",
        "goal_lat",
        "goal_lng",
        "input_mode",
        "max_estimated_cells",
        "max_snap_distance_m",
        "output_dir",
        "parquet_path",
        "planner_config_path",
        "res_coarse",
        "res_fine",
        "roi_layer_path",
        "roi_strategy",
        "start_lat",
        "start_lng",
        "theme_attributes",
        "objectives",
        "vehicle_path",
        "factor_model_path",
        "mission_profile",
        "max_candidate_paths",
        "candidate_limit",
        "penalty_factor",
        "static_planning_path",
        "environment_snapshot_path",
    }
)
SELECT_FIELDS: frozenset[str] = frozenset(
    {"candidate_id", "expected_selection_version", "plan_path", "role"}
)
REPLAN_FIELDS: frozenset[str] = frozenset(
    {
        "blockage_observations",
        "current_h3",
        "current_lat",
        "current_lng",
        "now_epoch_s",
        "policy",
        "selection_path",
        "snap_distance_m",
    }
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one GIS build, route, or combined delivery request.

    Args:
        argv: Optional command arguments excluding the executable name. Unit: none.
            When omitted, process command arguments are used.

    Returns:
        Process status code: zero for a completed request and two for a validated
        input, GIS, construction, or planning error.
    """
    args = _build_parser().parse_args(argv)
    try:
        result = _dispatch(args.command, Path(args.request))
    except _REQUEST_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REQUEST_ERROR
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Create the delivery CLI parser."""
    parser = argparse.ArgumentParser(prog="h3-offroad-planner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "preprocess-hydrology",
        "build-tiles",
        "plan",
        "run",
        "select",
        "replan",
    ):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--request", required=True, help="YAML request file path")
    return parser


def _console_progress(module: str, percent: int, message: str) -> None:
    """Stream real-time CLI progress to stderr without polluting JSON stdout."""
    print(f"[{module}] {percent:>3}%: {message}", file=sys.stderr, flush=True)


def _call_with_progress(
    func: Callable[..., object],
    request: object,
    progress: ProgressCallback | None = None,
    **kwargs: object,
) -> object:
    if progress is None:
        return func(request)
    try:
        sig = inspect.signature(func)
        if "progress" in sig.parameters:
            return func(request, progress=progress, **kwargs)
    except (TypeError, ValueError):
        pass
    return func(request)


def _normalize_route_payload(payload: dict[str, object]) -> dict[str, object]:
    """Extract nested route configuration from delivery request if present."""
    if "route" in payload and isinstance(payload["route"], dict):
        tile_payload = payload.get("tile_build")
        route_payload = dict(cast(dict[str, object], payload["route"]))
        if "parquet_path" not in route_payload and isinstance(tile_payload, dict):
            output_dir = tile_payload.get("output_dir")
            if isinstance(output_dir, str) and output_dir:
                route_payload["parquet_path"] = str(Path(output_dir) / TILE_MANIFEST_NAME)
        return route_payload
    return payload


def _dispatch(command: str, request_path: Path) -> dict[str, object]:
    """Dispatch one validated CLI command from a YAML request file."""
    payload = _load_yaml_mapping(request_path)
    if command == "preprocess-hydrology":
        return run_hydrology_payload(payload)
    if command == "build-tiles":
        return cast(
            dict[str, object],
            _call_with_progress(
                build_h3_tile_cache, _tile_request(payload), progress=_console_progress
            ),
        )
    if command == "plan":
        route_payload = _normalize_route_payload(payload)
        plan = _call_with_progress(
            run_route_plan,
            _route_request(route_payload),
            progress=_console_progress,
            export_gpkg=True,
        )
        return cast(dict[str, object], plan.to_dict())  # type: ignore[attr-defined]
    if command == "run":
        return run_delivery_payload(payload, progress=_console_progress, export_gpkg=True)
    if command == "select":
        return run_select_payload(payload)
    if command == "replan":
        return run_replan_payload(payload)
    raise ConfigError(f"unsupported CLI command: {command!r}")


ProgressCallback = Callable[[str, int, str], None]


def run_hydrology_payload(payload: dict[str, object]) -> dict[str, object]:
    """Run the configured offline GRASS hydrology preprocessing request."""
    _reject_unknown_fields(payload, HYDROLOGY_FIELDS)
    config = HydrologyConfig(
        backend=_string_or_default(payload, "backend", "grass_r_watershed"),
        flow_method=_string_or_default(payload, "flow_method", "mfd"),
        analysis_resolution_m=_optional_float(payload, "analysis_resolution_m"),
        mapping_t0=_optional_float(payload, "mapping_t0"),
        mapping_t1=_optional_float(payload, "mapping_t1"),
        upstream_complete=_optional_bool(payload, "upstream_complete"),
        version=_string_or_default(payload, "version", "twi_drainage_v1"),
    )
    artifacts = preprocess_hydrology(
        _required_string(payload, "dem_path"),
        _required_string(payload, "output_dir"),
        config,
        grass_executable=_string_or_default(payload, "grass_executable", "grass"),
    )
    return {name: str(value) for name, value in vars(artifacts).items()}


def run_tile_payload(
    payload: dict[str, object],
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    """Build one tile-cache request decoded from a YAML mapping."""
    return cast(
        dict[str, object],
        _call_with_progress(build_h3_tile_cache, _tile_request(payload), progress=progress),
    )


def run_route_payload(
    payload: dict[str, object],
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    """Plan one route request decoded from a YAML mapping."""
    route_payload = _normalize_route_payload(payload)
    plan = _call_with_progress(run_route_plan, _route_request(route_payload), progress=progress)
    return cast(dict[str, object], plan.to_dict())  # type: ignore[attr-defined]


def run_select_payload(payload: dict[str, object]) -> dict[str, object]:
    """Explicitly activate one persisted RoutePlan candidate."""
    _reject_unknown_fields(payload, SELECT_FIELDS)
    expected = (
        _integer_or_default(payload, "expected_selection_version", 0)
        if "expected_selection_version" in payload
        else None
    )
    selection = select_route(
        plan_path=_required_string(payload, "plan_path"),
        candidate_id=_optional_string(payload, "candidate_id"),
        role=_optional_string(payload, "role"),
        expected_selection_version=expected,
    )
    return selection.to_dict()


def run_replan_payload(payload: dict[str, object]) -> dict[str, object]:
    """Restore persisted graph/config state and execute one D* Lite product replan."""
    _reject_unknown_fields(payload, REPLAN_FIELDS)
    selection_path = _required_string(payload, "selection_path")
    root = Path(selection_path).parent
    graph = load_route_graph_snapshot(str(root / "route_manifest.json"))
    vehicle = load_vehicle(str(root / "effective_vehicle.yaml"))
    factor_model = load_factor_model(str(root / "effective_factor_model.yaml"))
    evaluation = evaluate_factor_model(graph, vehicle, factor_model)
    now_epoch_s = _required_float(payload, "now_epoch_s")
    request = ReplanRequest(
        selection_path=selection_path,
        current_h3=_optional_string(payload, "current_h3"),
        current_lat=_optional_float(payload, "current_lat"),
        current_lng=_optional_float(payload, "current_lng"),
        snap_distance_m=_float_or_default(payload, "snap_distance_m", 20_000.0),
        now_epoch_s=now_epoch_s,
        blockage_observations=_blockage_records(payload, now_epoch_s),
    )
    policy = _replan_policy(payload)
    return _replan_result_payload(replan_route(request, graph, evaluation, policy))


def run_delivery_payload(
    payload: dict[str, object],
    progress: ProgressCallback | None = None,
    *,
    export_gpkg: bool = False,
) -> dict[str, object]:
    """Build a tile cache and route through its manifest in one delivery request."""
    _report_progress(progress, "validate", 5, "validated combined delivery request")
    route_payload = dict(_required_mapping(payload, "route"))
    tile_payload = dict(_required_mapping(payload, "tile_build"))
    for key in ("vehicle_path", "factor_model_path", "static_planning_path"):
        if key in route_payload:
            tile_payload[key] = route_payload[key]
    tile_request = _tile_request(tile_payload)
    _report_progress(progress, "build_map", 10, "started trafficability-map build")
    tile_manifest = cast(
        dict[str, object],
        _call_with_progress(
            build_h3_tile_cache,
            tile_request,
            progress=progress,
            progress_range=(10, 50),
        ),
    )
    _report_progress(progress, "build_map", 50, "completed trafficability-map build")
    route_payload["parquet_path"] = str(Path(tile_request.output_dir) / TILE_MANIFEST_NAME)
    _report_progress(progress, "global_plan", 75, "started global route planning")
    plan = _call_with_progress(
        run_route_plan,
        _route_request(route_payload),
        progress=progress,
        progress_range=(75, 95),
        export_gpkg=export_gpkg,
    )
    route_manifest = cast(dict[str, object], plan.to_dict())  # type: ignore[attr-defined]
    _report_progress(progress, "evaluation", 95, "exported route and thematic outputs")
    return {"route_manifest": route_manifest, "tile_manifest": tile_manifest}


def _report_progress(
    progress: ProgressCallback | None,
    module: str,
    percent: int,
    message: str,
) -> None:
    """Publish one bounded progress event when a caller requested it."""
    if progress is not None:
        progress(module, percent, message)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    """Load a non-empty YAML mapping from a readable filesystem path."""
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML request: {path}") from exc
    if not isinstance(payload, dict) or not payload:
        raise ConfigError(f"request file must contain a non-empty mapping: {path}")
    return cast(dict[str, object], payload)


def _required_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    """Return a required nested request mapping or raise a configuration error."""
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"request field {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _tile_request(payload: dict[str, object]) -> TileBuildRequest:
    """Construct a validated tile-build request from decoded YAML fields."""
    _reject_unknown_fields(payload, TILE_BUILD_FIELDS)
    try:
        return TileBuildRequest(
            dem_path=_required_string(payload, "dem_path"),
            landcover_path=_required_string(payload, "landcover_path"),
            roi_layer_path=_required_string(payload, "roi_layer_path"),
            output_dir=_required_string(payload, "output_dir"),
            soil_path=_optional_string(payload, "soil_path"),
            soil_catalog_path=_optional_string(payload, "soil_catalog_path"),
            twi_path=_optional_string(payload, "twi_path"),
            drainage_path=_optional_string(payload, "drainage_path"),
            drainage_validity_path=_optional_string(payload, "drainage_validity_path"),
            drainage_boundary_path=_optional_string(payload, "drainage_boundary_path"),
            vehicle_path=_optional_string(payload, "vehicle_path"),
            factor_model_path=_optional_string(payload, "factor_model_path"),
            static_planning_path=_optional_string(payload, "static_planning_path"),
            road_path=_optional_string(payload, "road_path"),
            res_fine=_integer_or_default(payload, "res_fine", 14),
            tile_res=_integer_or_default(payload, "tile_res", 11),
            max_tiles=_integer_or_default(payload, "max_tiles", 1_000),
            max_cells_per_tile=_integer_or_default(payload, "max_cells_per_tile", 100_000),
            sampling_mode=_string_or_default(payload, "sampling_mode", "center"),
            continue_on_error=_bool_or_default(payload, "continue_on_error", True),
            overwrite=_bool_or_default(payload, "overwrite", True),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid tile_build request: {exc}") from exc


def _route_request(payload: dict[str, object]) -> RouteRequest:
    """Construct a validated route request from decoded YAML fields."""
    _reject_unknown_fields(payload, ROUTE_FIELDS)
    try:
        return RouteRequest(
            input_mode=_required_string(payload, "input_mode"),
            parquet_path=_required_string(payload, "parquet_path"),
            planner_config_path=_required_string(payload, "planner_config_path"),
            vehicle_path=_required_string(payload, "vehicle_path"),
            output_dir=_required_string(payload, "output_dir"),
            start_lat=_optional_float(payload, "start_lat"),
            start_lng=_optional_float(payload, "start_lng"),
            goal_lat=_optional_float(payload, "goal_lat"),
            goal_lng=_optional_float(payload, "goal_lng"),
            endpoint_layer_path=_optional_string(payload, "endpoint_layer_path"),
            roi_layer_path=_optional_string(payload, "roi_layer_path"),
            res_fine=_integer_or_default(payload, "res_fine", 14),
            res_coarse=_integer_or_default(payload, "res_coarse", 11),
            theme_attributes=_string_list_or_default(
                payload, "theme_attributes", ["score", "cost_score"]
            ),
            max_snap_distance_m=_float_or_default(payload, "max_snap_distance_m", 20_000.0),
            corridor_buffer_deg=_float_or_default(payload, "corridor_buffer_deg", 0.15),
            max_estimated_cells=_integer_or_default(payload, "max_estimated_cells", 500_000),
            roi_strategy=_string_or_default(payload, "roi_strategy", "auto_corridor"),
            objectives=_string_list_or_default(payload, "objectives", ["distance"]),
            candidate_index=_integer_or_default(payload, "candidate_index", 0),
            blocked_cells=_string_list_or_default(payload, "blocked_cells", []),
            factor_model_path=_optional_string(payload, "factor_model_path"),
            mission_profile=_string_or_default(payload, "mission_profile", "fastest"),
            max_candidate_paths=_integer_or_default(payload, "max_candidate_paths", 5),
            candidate_limit=_integer_or_default(payload, "candidate_limit", 24),
            penalty_factor=_float_or_default(payload, "penalty_factor", 0.25),
            static_planning_path=_optional_string(payload, "static_planning_path"),
            environment_snapshot_path=_optional_string(payload, "environment_snapshot_path"),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid route request: {exc}") from exc


def _reject_unknown_fields(payload: dict[str, object], allowed: frozenset[str]) -> None:
    """Reject YAML fields not owned by the target request contract."""
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ConfigError(f"request contains unsupported fields: {unknown}")


def _required_string(payload: dict[str, object], key: str) -> str:
    """Return a required string field from a decoded request mapping."""
    value = payload.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"request field {key!r} must be a string.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    """Return an optional string field, preserving an explicit null."""
    if key not in payload:
        return None
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"request field {key!r} must be a string or null.")
    return value


def _integer_or_default(payload: dict[str, object], key: str, default: int) -> int:
    """Return an integer field or its contract default."""
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"request field {key!r} must be an integer.")
    return value


def _optional_float(payload: dict[str, object], key: str) -> float | None:
    """Return an optional numeric field normalized to float."""
    if key not in payload or payload[key] is None:
        return None
    return _number_as_float(payload[key], key)


def _float_or_default(payload: dict[str, object], key: str, default: float) -> float:
    """Return a numeric field normalized to float or its contract default."""
    if key not in payload:
        return default
    return _number_as_float(payload[key], key)


def _number_as_float(value: object, key: str) -> float:
    """Validate one YAML number without accepting boolean values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"request field {key!r} must be numeric.")
    return float(value)


def _required_float(payload: dict[str, object], key: str) -> float:
    if key not in payload:
        raise ConfigError(f"request field {key!r} is required.")
    return _number_as_float(payload[key], key)


def _bool_or_default(payload: dict[str, object], key: str, default: bool) -> bool:
    """Return a boolean field or its contract default."""
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ConfigError(f"request field {key!r} must be bool.")
    return value


def _optional_bool(payload: dict[str, object], key: str) -> bool | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, bool):
        raise ConfigError(f"request field {key!r} must be bool or null.")
    return value


def _string_or_default(payload: dict[str, object], key: str, default: str) -> str:
    """Return a string field or its contract default."""
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, str):
        raise ConfigError(f"request field {key!r} must be a string.")
    return value


def _string_list_or_default(payload: dict[str, object], key: str, default: list[str]) -> list[str]:
    """Return a list of strings or a new copy of its contract default."""
    if key not in payload:
        return list(default)
    value = payload[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"request field {key!r} must be a list of strings.")
    return cast(list[str], value)


def _blockage_records(
    payload: dict[str, object],
    now_epoch_s: float,
) -> tuple[BlockageRecord, ...]:
    raw = payload.get("blockage_observations", [])
    if not isinstance(raw, list):
        raise ConfigError("blockage_observations must be an array.")
    records = []
    for item in raw:
        if not isinstance(item, dict):
            raise ConfigError("blockage observations must be mappings.")
        observation = cast(dict[str, object], item)
        records.append(
            BlockageRecord(
                blockage_id=_required_string(observation, "blockage_id"),
                h3index=_required_string(observation, "h3index"),
                state=_string_or_default(observation, "state", "tentative"),
                confirmation_count=_integer_or_default(observation, "confirmation_count", 1),
                trusted_source=_bool_or_default(observation, "trusted_source", False),
                observed_at_epoch_s=_float_or_default(
                    observation,
                    "observed_at_epoch_s",
                    now_epoch_s,
                ),
                expires_at_epoch_s=_optional_float(observation, "expires_at_epoch_s"),
                mission_lifetime=_bool_or_default(observation, "mission_lifetime", False),
                source=_string_or_default(observation, "source", "user"),
            )
        )
    return tuple(records)


def _replan_policy(payload: dict[str, object]) -> ReplanPolicy:
    raw = payload.get("policy", {})
    if not isinstance(raw, dict):
        raise ConfigError("replan policy must be a mapping.")
    policy = cast(dict[str, object], raw)
    return ReplanPolicy(
        confirmation_threshold=_integer_or_default(policy, "confirmation_threshold", 2),
        debounce_window_s=_float_or_default(policy, "debounce_window_s", 1.0),
        cooldown_s=_float_or_default(policy, "cooldown_s", 2.0),
        recent_failed_corridor_ttl_s=_float_or_default(
            policy,
            "recent_failed_corridor_ttl_s",
            120.0,
        ),
        global_fallback_window_s=_float_or_default(
            policy,
            "global_fallback_window_s",
            300.0,
        ),
        max_global_fallbacks=_integer_or_default(policy, "max_global_fallbacks", 3),
    )


def _replan_result_payload(typed: ReplanResult) -> dict[str, object]:
    return {
        "plan_id": typed.plan_id,
        "candidate_id": typed.candidate_id,
        "algorithm": typed.algorithm,
        "status": typed.status,
        "replan_version": typed.replan_version,
        "old_path_hash": typed.old_path_hash,
        "new_path_hash": typed.new_path_hash,
        "metrics_before": typed.metrics_before.to_dict(),
        "metrics_after": None if typed.metrics_after is None else typed.metrics_after.to_dict(),
        "warnings": list(typed.warnings),
    }


_REQUEST_ERRORS = (
    ConfigError,
    FileNotFoundError,
    GISInputError,
    GridBuildError,
    OSError,
    PlanningFailedError,
    PlanningInputError,
    ValueError,
)
