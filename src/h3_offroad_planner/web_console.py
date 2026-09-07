# ruff: noqa: E501
"""Loopback TianDiTu WebGIS console for existing GIS delivery operations."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from email.message import Message
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

import h3
import pandas as pd
import yaml  # type: ignore[import-untyped]
from shapely.geometry import shape

from h3_offroad_planner.cli import (
    run_delivery_payload,
    run_replan_payload,
    run_route_payload,
    run_select_payload,
    run_tile_payload,
)
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.map_config import (
    MAP_PROVIDER_CONFIG,
    TIANDITU_KEY,
    TIANDITU_LAYER_TYPE,
)
from h3_offroad_planner.models import (
    ConfigError,
    GISInputError,
    GridBuildError,
    PlanningFailedError,
    PlanningInputError,
)

__all__ = [
    "create_web_console",
    "run_web_console",
    "serialize_tile_grid",
    "serialize_webgis_result",
]

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8765
MAX_REQUEST_BYTES: int = 1_000_000
# Temporary full-grid display ceiling for the Web backup and the PyQt map bridge.
# This does not limit H3 construction or route planning.  Replace it with
# viewport/LOD loading once the map renderer no longer serializes every fine cell.
MAX_WEB_GRID_FEATURES: int = 30_000
MAX_DESKTOP_PARENT_FEATURES: int = 10_000
MAX_DESKTOP_TILE_FEATURES: int = 10_000
MAX_CATALOG_FILES: int = 300
SCORE_SPEED_FLOOR: float = 0.10
EARTH_RADIUS_M: float = 6_371_000.0
OBJECTIVE_LABELS: dict[str, str] = {
    "distance": "shortest distance",
    "trafficability": "lowest trafficability penalty",
    "travel_cost": "minimum travel cost",
    "slope": "lowest slope exposure",
    "roughness": "lowest terrain roughness",
}
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
WEB_ROOT: Path = Path(__file__).with_name("web")
DEFAULT_DELIVERY_PATH: Path = PROJECT_ROOT / "configs" / "mvp81_delivery.example.yaml"
SESSION_ROOT: Path = PROJECT_ROOT / "outputs" / "web_sessions"
TILE_MANIFEST_NAME: str = "tile_manifest.json"
HEXGRID_ROOT: Path = Path(r"D:\Workspace\hexgrid_map\hexgrid_xw")
CATALOG_SUFFIXES: frozenset[str] = frozenset(
    {".tif", ".tiff", ".shp", ".geojson", ".yaml", ".yml", ".csv", ".nc"}
)
THEME_ATTRIBUTES: tuple[str, ...] = (
    "score",
    "cost_score",
    "elevation",
    "slope",
    "tri",
    "landcover_type",
    "soil_type",
    "has_road",
)
CATALOG_KINDS: frozenset[str] = frozenset(
    {"dem", "landcover", "soil", "road", "vehicle", "planner"}
)
ProgressCallback = Callable[[str, int, str], None]


def run_web_console(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the loopback WebGIS console until process interruption."""
    server = create_web_console(host, port)
    with server:
        server.serve_forever()


def create_web_console(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Create a loopback-only HTTP server for the WebGIS console."""
    if host != DEFAULT_HOST:
        raise ValueError(f"host must be loopback {DEFAULT_HOST!r}.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ValueError("port must be an integer in [1, 65535].")
    return ThreadingHTTPServer((host, port), _ConsoleHandler)


class _ConsoleHandler(BaseHTTPRequestHandler):
    """Serve static WebGIS content, bootstrap metadata, and delivery operations."""

    def do_GET(self) -> None:  # noqa: N802
        """Handle page and bootstrap requests."""
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", _read_index())
        elif parsed.path == "/api/bootstrap":
            self._send_json(HTTPStatus.OK, _bootstrap_payload())
        elif parsed.path == "/api/data-catalog":
            try:
                self._send_json(HTTPStatus.OK, {"data_catalog": _catalog_query(parsed.query)})
            except ConfigError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """Handle compatible JSON and incremental NDJSON delivery requests."""
        body = self.rfile.read(_content_length(self.headers))
        if self.path == "/api/run":
            self._run_compatible(body)
        elif self.path == "/api/run-stream":
            self._run_stream(body)
        elif self.path == "/api/select":
            self._run_state_operation(body, run_select_payload)
        elif self.path == "/api/replan":
            self._run_state_operation(body, _run_replan_operation)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _run_state_operation(
        self,
        body: bytes,
        operation: Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        try:
            self._send_json(HTTPStatus.OK, operation(_decode_json_mapping(body)))
        except _WEB_ERRORS as exc:
            self._send_json(_error_status(exc), {"error": str(exc)})

    def _run_compatible(self, body: bytes) -> None:
        try:
            result = _run_operation(_decode_web_request(body), None)
            self._send_json(HTTPStatus.OK, result)
        except _WEB_ERRORS as exc:
            self._send_json(_error_status(exc), {"error": str(exc)})

    def _run_stream(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            request = _decode_web_request(body)
            self._write_event("progress", "validate", 0, "INFO", "accepted WebGIS request")
            result = _run_operation(request, self._progress)
            self._write_event("result", "complete", 100, "INFO", "operation completed", result)
        except _WEB_ERRORS as exc:
            self._write_event("error", "failed", 100, "ERROR", str(exc))

    def _progress(self, module: str, percent: int, message: str) -> None:
        self._write_event("progress", module, percent, "INFO", message)

    def _write_event(
        self,
        event_type: str,
        module: str,
        percent: int,
        level: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        event: dict[str, object] = {
            "type": event_type,
            "module": module,
            "percent": percent,
            "level": level,
            "message": message,
        }
        if payload is not None:
            event["payload"] = payload
        self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default request logging; structured events are shown in the UI."""

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_operation(
    request: dict[str, object], progress: ProgressCallback | None
) -> dict[str, object]:
    operation = cast(str, request["operation"])
    payload = cast(dict[str, object], request["payload"])
    _apply_map_selection(payload, request)
    result: dict[str, object]
    if operation == "build":
        _report(progress, "build_map", 10, "started trafficability-map build")
        try:
            tile_manifest = run_tile_payload(_mapping(payload, "tile_build"), progress=progress)
        except TypeError:
            tile_manifest = run_tile_payload(_mapping(payload, "tile_build"))
        result = {"tile_manifest": tile_manifest}
        _report(progress, "build_map", 75, "completed trafficability-map build")
    elif operation in {"plan", "replan"}:
        _set_route_tile_manifest(payload)
        route_cfg = _mapping(payload, "route")
        manifest_path = Path(str(route_cfg.get("parquet_path", "")))
        if not manifest_path.is_file() and operation == "plan":
            _report(progress, "build_map", 10, "底图尚未构建，正在自动构建底图...")
            result = (
                run_delivery_payload(payload)
                if progress is None
                else run_delivery_payload(payload, progress)
            )
        else:
            _report(progress, "global_plan", 70, "started route planning")
            try:
                route_manifest = run_route_payload(route_cfg, progress=progress)
            except TypeError:
                route_manifest = run_route_payload(route_cfg)
            result = {"route_manifest": route_manifest}
    else:
        # Keep the original synchronous endpoint monkeypatch-compatible.
        result = (
            run_delivery_payload(payload)
            if progress is None
            else run_delivery_payload(payload, progress)
        )
    _report(progress, "evaluation", 95, "serializing WebGIS layers and evaluation")
    return serialize_webgis_result(result)


def _run_replan_operation(payload: dict[str, object]) -> dict[str, object]:
    """Execute a persisted replan and return its active geometry for Web rendering."""
    result = run_replan_payload(payload)
    selection_path = payload.get("selection_path")
    if not isinstance(selection_path, str) or not selection_path:
        raise ConfigError("selection_path must be a non-empty string.")
    active_path = Path(selection_path).parent / "active_route.geojson"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("replan active_route.geojson is unavailable or invalid.") from exc
    if not isinstance(active, dict):
        raise ConfigError("replan active_route.geojson must contain an object.")
    return serialize_webgis_result(
        {"replan_result": result, "active_route_geojson": cast(dict[str, object], active)}
    )


def _set_route_tile_manifest(payload: dict[str, object]) -> None:
    """Use the configured tile-cache manifest for a route-only WebGIS action."""
    route = _mapping(payload, "route")
    if isinstance(route.get("parquet_path"), str) and route["parquet_path"]:
        return
    tile = _mapping(payload, "tile_build")
    output_dir = tile.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        raise ConfigError(
            "route-only operations require route.parquet_path or tile_build.output_dir."
        )
    route["parquet_path"] = str(Path(output_dir) / TILE_MANIFEST_NAME)


def _apply_map_selection(payload: dict[str, object], request: dict[str, object]) -> None:
    tile = _mapping(payload, "tile_build")
    route = _mapping(payload, "route")
    geometry = request.get("study_area_geojson")
    if geometry is not None:
        roi_path = _write_study_area(geometry)
        tile["roi_layer_path"] = roi_path
        route["roi_layer_path"] = roi_path
    for role in ("start", "goal"):
        point = request.get(role)
        if point is not None:
            lat, lng = _point_lat_lng(point, role)
            route[f"{role}_lat"] = lat
            route[f"{role}_lng"] = lng
            route["input_mode"] = "coordinates"
    if request.get("blocked_cells") is not None:
        route["blocked_cells"] = request["blocked_cells"]
    if request.get("candidate_index") is not None:
        route["candidate_index"] = request["candidate_index"]


def serialize_webgis_result(
    result: dict[str, object], *, parent_only: bool = False
) -> dict[str, object]:
    """Serialize existing tile and route artifacts for Web or QWebEngine display."""
    replan_result = result.get("replan_result")
    active_route = result.get("active_route_geojson")
    if isinstance(replan_result, dict) and isinstance(active_route, dict):
        render_route = _route_feature_collection(active_route)
        metrics = replan_result.get("metrics_after")
        evaluation = dict(cast(dict[str, object], metrics)) if isinstance(metrics, dict) else None
        if evaluation is not None:
            evaluation["selection_reason"] = [replan_result.get("algorithm", "DStarLite")]
            evaluation["candidate_id"] = replan_result.get("candidate_id")
            evaluation["route_state"] = replan_result.get("status")
            evaluation["replan_version"] = replan_result.get("replan_version")
            evaluation["warnings"] = replan_result.get("warnings", [])
            _attach_evaluation(render_route, evaluation)
        return {
            "delivery": result,
            "fine_grid_geojson": _collection(),
            "parent_grid_geojson": _collection(),
            "route_geojson": render_route,
            "route_evaluation": evaluation,
            "candidate_routes": [],
        }
    manifest = _tile_manifest(result)
    rows: dict[str, dict[str, object]]
    if manifest is None:
        fine_grid, parent_grid, rows = _collection(), _collection(), {}
    elif parent_only:
        fine_grid, parent_grid, rows = _collection(), _desktop_parent_grid(manifest), {}
    else:
        fine_grid, parent_grid, rows = _grid_layers(manifest)
    route_manifest = result.get("route_manifest")
    if isinstance(route_manifest, dict) and isinstance(route_manifest.get("candidates"), list):
        return _serialize_route_plan(result, route_manifest, fine_grid, parent_grid)
    route_geojson = (
        _route_feature_collection(_route_geojson(route_manifest))
        if isinstance(route_manifest, dict)
        else None
    )
    evaluation = (
        _route_evaluation(cast(dict[str, object], route_manifest), rows)
        if isinstance(route_manifest, dict)
        else None
    )
    if route_geojson is not None and evaluation is not None:
        _attach_evaluation(route_geojson, evaluation)
    candidate_routes = (
        _candidate_routes(cast(dict[str, object], route_manifest), rows, route_geojson, evaluation)
        if isinstance(route_manifest, dict)
        else []
    )
    return {
        "delivery": result,
        "fine_grid_geojson": fine_grid,
        "parent_grid_geojson": parent_grid,
        "route_geojson": route_geojson,
        "route_evaluation": evaluation,
        "candidate_routes": candidate_routes,
    }


def serialize_tile_grid(result: dict[str, object], parent_h3: str) -> dict[str, object]:
    """Load one manifest-authorized parent tile for desktop drill-down display."""
    if not isinstance(parent_h3, str) or not parent_h3:
        raise GridBuildError("parent_h3 must be a non-empty H3 id.")
    manifest = _tile_manifest(result)
    if manifest is None:
        raise GridBuildError("desktop result has no tile manifest for grid drill-down.")
    matches = [
        record
        for record in _all_tile_records(manifest)
        if record.get("parent_h3") == parent_h3
    ]
    if not matches:
        raise GridBuildError(f"parent tile is not present in the current manifest: {parent_h3}")
    if len(matches) != 1:
        raise GridBuildError(f"parent tile appears more than once in the manifest: {parent_h3}")
    record = matches[0]
    status = record.get("status")
    if status not in {"completed", "skipped"}:
        raise GridBuildError(f"parent tile {parent_h3} is not available for drill-down: {status}")
    cells_count = _record_non_negative_int(record, "cells_count")
    if cells_count > MAX_DESKTOP_TILE_FEATURES:
        raise GridBuildError(
            f"parent tile {parent_h3} contains {cells_count} fine cells; "
            f"desktop drill-down limit is {MAX_DESKTOP_TILE_FEATURES}."
        )
    path = _manifest_tile_path(manifest, record, parent_h3)
    try:
        frame = pd.read_parquet(path)
    except (ImportError, OSError, ValueError) as exc:
        raise GridBuildError(f"failed to read parent tile {parent_h3}: {path}") from exc
    if len(frame) > MAX_DESKTOP_TILE_FEATURES:
        raise GridBuildError(
            f"parent tile {parent_h3} contains {len(frame)} fine cells; "
            f"desktop drill-down limit is {MAX_DESKTOP_TILE_FEATURES}."
        )
    rows: dict[str, dict[str, object]] = {}
    for raw in frame.to_dict(orient="records"):
        row = {str(key): _json_scalar(value) for key, value in raw.items()}
        cell_id = row.get("h3index")
        row_parent = row.get("parent_h3")
        if not isinstance(cell_id, str) or not cell_id:
            raise GridBuildError(f"parent tile {parent_h3} contains an invalid H3 cell id.")
        if not isinstance(row_parent, str) or not row_parent:
            raise GridBuildError(f"parent tile {parent_h3} contains an invalid logical parent id.")
        rows[cell_id] = row
    if len(rows) != len(frame):
        raise GridBuildError(f"parent tile {parent_h3} contains duplicate H3 cell ids.")
    return _collection([_cell_feature(cell_id, row) for cell_id, row in rows.items()])


def _serialize_route_plan(
    result: dict[str, object],
    plan: dict[str, object],
    fine_grid: dict[str, object],
    parent_grid: dict[str, object],
) -> dict[str, object]:
    raw_candidates = cast(list[object], plan["candidates"])
    candidates = [cast(dict[str, object], item) for item in raw_candidates if isinstance(item, dict)]
    candidate_routes = []
    recommended_geojson = None
    recommended_evaluation = None
    for index, candidate in enumerate(candidates):
        geojson = candidate.get("geojson")
        metrics = candidate.get("metrics")
        roles = candidate.get("roles", [])
        if not isinstance(geojson, dict) or not isinstance(metrics, dict):
            continue
        render_geojson = _route_feature_collection(cast(dict[str, object], geojson))
        evaluation = dict(cast(dict[str, object], metrics))
        evaluation["selection_reason"] = list(roles) if isinstance(roles, list) else []
        evaluation["candidate_id"] = candidate.get("candidate_id")
        candidate_routes.append(
            {
                "candidate_index": index,
                "candidate_id": candidate.get("candidate_id"),
                "roles": roles,
                "is_recommended": candidate.get("is_recommended", False),
                "geojson": render_geojson,
                "evaluation": evaluation,
            }
        )
        if candidate.get("is_recommended") is True:
            recommended_geojson = render_geojson
            recommended_evaluation = evaluation
    return {
        "delivery": result,
        "fine_grid_geojson": fine_grid,
        "parent_grid_geojson": parent_grid,
        "route_geojson": recommended_geojson,
        "route_evaluation": recommended_evaluation,
        "candidate_routes": candidate_routes,
    }


def _grid_layers(
    manifest: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, dict[str, object]]]:
    rows: dict[str, dict[str, object]] = {}
    if not isinstance(manifest.get("tiles"), list):
        return _collection(), _collection(), rows
    for record in _tile_records(manifest):
        frame = pd.read_parquet(str(record["path"]))
        for raw in frame.to_dict(orient="records"):
            cell_id = str(raw["h3index"])
            rows[cell_id] = {str(key): _json_scalar(value) for key, value in raw.items()}
            if len(rows) > MAX_WEB_GRID_FEATURES:
                raise GridBuildError(
                    f"Web map exceeds {MAX_WEB_GRID_FEATURES} fine H3 cells; reduce resolution or ROI."
                )
    fine = [_cell_feature(cell_id, row) for cell_id, row in rows.items()]
    parents: dict[str, list[dict[str, object]]] = {}
    for row in rows.values():
        parents.setdefault(str(row["parent_h3"]), []).append(row)
    parent = [_parent_feature(parent_id, values) for parent_id, values in parents.items()]
    return _collection(fine), _collection(parent), rows


def _desktop_parent_grid(manifest: dict[str, object]) -> dict[str, object]:
    """Build a lightweight parent overview without reading any tile Parquet."""
    records = _all_tile_records(manifest)
    if len(records) > MAX_DESKTOP_PARENT_FEATURES:
        raise GridBuildError(
            f"desktop parent grid contains {len(records)} tiles; "
            f"display limit is {MAX_DESKTOP_PARENT_FEATURES}."
        )
    return _collection([_parent_record_feature(record) for record in records])


def _parent_record_feature(record: dict[str, object]) -> dict[str, object]:
    parent_h3 = record.get("parent_h3")
    status = record.get("status")
    if not isinstance(parent_h3, str) or not parent_h3:
        raise GridBuildError("tile manifest record has no valid parent_h3.")
    if not isinstance(status, str) or not status:
        raise GridBuildError(f"parent tile {parent_h3} has no valid status.")
    properties: dict[str, object] = {
        "h3index": parent_h3,
        "parent_h3": parent_h3,
        "resolution": "parent",
        "status": status,
        "selectable": status in {"completed", "skipped"}
        and isinstance(record.get("path"), str)
        and bool(cast(str, record.get("path"))),
        "cell_count": _record_non_negative_int(record, "cells_count"),
        "error": record.get("error") if isinstance(record.get("error"), str) else None,
        "score": None,
        "cost_score": None,
        "landcover_type": None,
        "soil_type": None,
        "has_road": None,
        "is_passable": None,
    }
    statistics = record.get("statistics")
    for theme in ("elevation", "slope", "tri"):
        properties[theme] = _parent_statistic(statistics, theme)
    return {"type": "Feature", "geometry": _h3_geometry(parent_h3), "properties": properties}


def _parent_statistic(statistics: object, theme: str) -> float | None:
    if not isinstance(statistics, dict):
        return None
    payload = statistics.get(theme)
    if not isinstance(payload, dict):
        return None
    value = payload.get("q50")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _cell_feature(cell_id: str, row: dict[str, object]) -> dict[str, object]:
    properties = {
        key: row.get(key)
        for key in (
            "h3index",
            "parent_h3",
            "score",
            "cost_score",
            "elevation",
            "slope",
            "tri",
            "landcover_type",
            "soil_type",
            "has_road",
            "is_passable",
        )
    }
    return {"type": "Feature", "geometry": _h3_geometry(cell_id), "properties": properties}


def _parent_feature(parent_id: str, values: list[dict[str, object]]) -> dict[str, object]:
    scores = [
        float(score)
        for row in values
        if isinstance(score := row.get("score"), (int, float))
    ]
    properties = {
        "h3index": parent_id,
        "cell_count": len(values),
        "score": sum(scores) / len(scores) if scores else None,
        "resolution": "parent",
    }
    return {"type": "Feature", "geometry": _h3_geometry(parent_id), "properties": properties}


def _route_evaluation(
    manifest: dict[str, object], rows: dict[str, dict[str, object]]
) -> dict[str, object] | None:
    """Return evaluation only for a complete route manifest."""
    vehicle_path = manifest.get("vehicle_path")
    if not isinstance(vehicle_path, str) or not vehicle_path:
        return None
    cells = [str(cell) for cell in cast(list[object], manifest.get("planned_path", []))]
    return _candidate_evaluation(manifest, rows, cells, _selected_candidate_index(manifest))


def _candidate_evaluation(
    manifest: dict[str, object],
    rows: dict[str, dict[str, object]],
    cells: list[str],
    candidate_index: int,
) -> dict[str, object] | None:
    """Evaluate one rendered route using the same tile rows as the Web map."""
    vehicle_path = manifest.get("vehicle_path")
    if not isinstance(vehicle_path, str) or not vehicle_path:
        return None
    distance, shares = _route_distance_and_landcover(cells, rows)
    scores = [
        float(score)
        for cell in cells
        if cell in rows and isinstance(score := rows[cell].get("score"), (int, float))
    ]
    score = sum(scores) / len(scores) if scores else 0.0
    vehicle = load_vehicle(vehicle_path)
    speed_mps = vehicle.max_speed_kmh / 3.6 * max(score, SCORE_SPEED_FLOOR)
    return {
        "quality_score": score,
        "distance_m": distance,
        "estimated_time_s": distance / speed_mps if speed_mps > 0.0 else None,
        "landcover_distance_share": shares,
        "min_turn_radius_m": vehicle.min_turn_radius_m,
        "candidate_index": candidate_index,
        "selection_reason": _selection_reason(manifest, candidate_index),
        "replanned": manifest.get("replanned", False),
    }


def _candidate_routes(
    manifest: dict[str, object],
    rows: dict[str, dict[str, object]],
    active_geojson: dict[str, object] | None,
    active_evaluation: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Build independently selectable route entries without changing legacy outputs."""
    selected_index = _selected_candidate_index(manifest)
    if manifest.get("replanned", False):
        return _replanned_candidate_route(selected_index, active_geojson, active_evaluation)
    routes: list[dict[str, object]] = []
    for index, candidate in enumerate(_manifest_candidates(manifest)):
        cells = _candidate_cells(candidate)
        objectives = _candidate_objectives(candidate)
        geojson = _candidate_geojson(cells, rows, index, objectives, candidate.get("total_cost"))
        evaluation = _candidate_evaluation(manifest, rows, cells, index)
        if geojson is not None and evaluation is not None:
            _attach_evaluation(geojson, evaluation)
        routes.append(
            {
                "candidate_index": index,
                "geojson": geojson,
                "objectives": objectives,
                "total_cost": candidate.get("total_cost"),
                "evaluation": evaluation,
                "is_selected": index == selected_index,
                "replanned": False,
            }
        )
    return routes


def _replanned_candidate_route(
    selected_index: int,
    active_geojson: dict[str, object] | None,
    active_evaluation: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Expose only the active D* Lite route so stale Pareto values are never displayed."""
    if active_geojson is None:
        return []
    evaluation = dict(active_evaluation) if active_evaluation is not None else {}
    evaluation["selection_reason"] = ["D* Lite replanned active route"]
    evaluation["candidate_index"] = selected_index
    _attach_evaluation(active_geojson, evaluation)
    return [
        {
            "candidate_index": selected_index,
            "geojson": active_geojson,
            "objectives": {},
            "total_cost": None,
            "evaluation": evaluation,
            "is_selected": True,
            "replanned": True,
        }
    ]


def _manifest_candidates(manifest: dict[str, object]) -> list[dict[str, object]]:
    candidates = manifest.get("candidate_paths")
    if not isinstance(candidates, list):
        return []
    return [cast(dict[str, object], candidate) for candidate in candidates if isinstance(candidate, dict)]


def _candidate_cells(candidate: dict[str, object]) -> list[str]:
    cells = candidate.get("cells")
    if not isinstance(cells, list):
        return []
    return [cell for cell in cells if isinstance(cell, str) and cell]


def _candidate_objectives(candidate: dict[str, object]) -> dict[str, float]:
    objectives = candidate.get("objectives")
    if not isinstance(objectives, dict):
        return {}
    return {
        name: float(value)
        for name, value in objectives.items()
        if isinstance(name, str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) >= 0.0
    }


def _candidate_geojson(
    cells: list[str],
    rows: dict[str, dict[str, object]],
    candidate_index: int,
    objectives: dict[str, float],
    total_cost: object,
) -> dict[str, object] | None:
    """Build WGS84 GeoJSON for one candidate when every cell has loaded map coordinates."""
    if not cells or any(cell not in rows for cell in cells):
        return None
    coordinates = [[_numeric(rows[cell], "lng"), _numeric(rows[cell], "lat")] for cell in cells]
    geometry: dict[str, object] = (
        {"type": "Point", "coordinates": coordinates[0]}
        if len(coordinates) == 1
        else {"type": "LineString", "coordinates": coordinates}
    )
    return _collection(
        [
            {
                "type": "Feature",
                "properties": {
                    "candidate_index": candidate_index,
                    "objectives": objectives,
                    "total_cost": total_cost,
                },
                "geometry": geometry,
            }
        ]
    )


def _selected_candidate_index(manifest: dict[str, object]) -> int:
    value = manifest.get("candidate_index", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _selection_reason(manifest: dict[str, object], candidate_index: int) -> list[str]:
    """Explain one candidate relative to the minimum requested old objectives."""
    candidates = _manifest_candidates(manifest)
    if not 0 <= candidate_index < len(candidates):
        return ["single-route result"]
    selected = candidates[candidate_index]
    objectives = _candidate_objectives(selected)
    if not objectives:
        return ["Pareto-front compromise"]
    reasons: list[str] = []
    for objective in _requested_objectives(manifest, objectives):
        value = objectives.get(objective)
        values = [
            _candidate_objectives(item).get(objective)
            for item in candidates
        ]
        finite = [item for item in values if item is not None]
        if value is not None and finite and value <= min(finite):
            reasons.append(OBJECTIVE_LABELS[objective])
    return reasons or ["Pareto-front compromise"]


def _requested_objectives(
    manifest: dict[str, object], objectives: dict[str, float]
) -> list[str]:
    requested = manifest.get("requested_objectives")
    if isinstance(requested, list):
        return [
            objective
            for objective in requested
            if isinstance(objective, str) and objective in OBJECTIVE_LABELS and objective in objectives
        ]
    return [objective for objective in OBJECTIVE_LABELS if objective in objectives]


def _route_distance_and_landcover(
    cells: list[str], rows: dict[str, dict[str, object]]
) -> tuple[float, dict[str, float]]:
    total = 0.0
    shares: dict[str, float] = {}
    for first, second in zip(cells, cells[1:], strict=False):
        if first not in rows or second not in rows:
            continue
        distance = _haversine(rows[first], rows[second])
        total += distance
        label = str(rows[second].get("landcover_type") or "unknown")
        shares[label] = shares.get(label, 0.0) + distance
    return total, {label: value / total for label, value in shares.items()} if total else {}


def _haversine(first: dict[str, object], second: dict[str, object]) -> float:
    lat1, lng1, lat2, lng2 = (
        _numeric(first, "lat"),
        _numeric(first, "lng"),
        _numeric(second, "lat"),
        _numeric(second, "lng"),
    )
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    value = sin(dlat / 2.0) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * asin(sqrt(value))


def _numeric(row: dict[str, object], key: str) -> float:
    """Read one finite numeric map attribute for route evaluation."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GridBuildError(f"tile grid attribute {key!r} must be numeric.")
    return float(value)


def _attach_evaluation(geojson: dict[str, object], evaluation: dict[str, object]) -> None:
    for feature in cast(list[dict[str, object]], geojson.get("features", [])):
        properties = feature.get("properties")
        if isinstance(properties, dict):
            properties["route_evaluation"] = evaluation


def _decode_web_request(body: bytes) -> dict[str, object]:
    envelope = _decode_envelope(body)
    operation = envelope.get("operation", "combined")
    if operation not in {"build", "plan", "replan", "combined"}:
        raise ConfigError("operation must be build, plan, replan, or combined.")
    payload = _load_request_yaml(envelope)
    result: dict[str, object] = {"operation": operation, "payload": payload}
    for key in ("study_area_geojson", "start", "goal", "blocked_cells", "candidate_index"):
        if key in envelope:
            result[key] = envelope[key]
    return result


def _decode_envelope(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError("request body must be UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("request_yaml"), str):
        raise ConfigError("request JSON must contain string field 'request_yaml'.")
    return cast(dict[str, object], payload)


def _decode_json_mapping(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError("request body must be a UTF-8 JSON object.") from exc
    if not isinstance(payload, dict):
        raise ConfigError("request body must be a JSON object.")
    return cast(dict[str, object], payload)


def _load_request_yaml(envelope: dict[str, object]) -> dict[str, object]:
    loaded = yaml.safe_load(cast(str, envelope["request_yaml"]))
    if not isinstance(loaded, dict) or not loaded:
        raise ConfigError("request_yaml must contain a non-empty mapping.")
    return cast(dict[str, object], loaded)


def _write_study_area(value: object) -> str:
    if not isinstance(value, dict):
        raise ConfigError("study_area_geojson must be a GeoJSON object.")
    geometry = shape(value.get("geometry", value))
    if (
        geometry.geom_type not in {"Polygon", "MultiPolygon"}
        or not geometry.is_valid
        or geometry.area <= 0.0
    ):
        raise ConfigError("study area must be a valid non-empty Polygon or MultiPolygon.")
    output = SESSION_ROOT / uuid.uuid4().hex / "study_area.geojson"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": value.get("geometry", value)}
                ],
            }
        ),
        encoding="utf-8",
    )
    return str(output)


def _point_lat_lng(value: object, role: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise ConfigError(f"{role} must be an object with lat/lng.")
    lat, lng = value.get("lat"), value.get("lng")
    if (
        isinstance(lat, bool)
        or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
    ):
        raise ConfigError(f"{role} lat/lng must be numeric.")
    if not -90.0 <= float(lat) <= 90.0 or not -180.0 <= float(lng) <= 180.0:
        raise ConfigError(f"{role} coordinates are outside WGS84 bounds.")
    return float(lat), float(lng)


def _bootstrap_payload() -> dict[str, object]:
    return {
        "map_provider": MAP_PROVIDER_CONFIG.provider,
        "map_layer_type": MAP_PROVIDER_CONFIG.layer_type,
        "map_token_source": MAP_PROVIDER_CONFIG.token_source,
        "tianditu_key": TIANDITU_KEY,
        "default_request_yaml": DEFAULT_DELIVERY_PATH.read_text(encoding="utf-8"),
        "data_catalog": [],
        "theme_attributes": list(THEME_ATTRIBUTES),
        "max_web_grid_features": MAX_WEB_GRID_FEATURES,
    }


def _catalog_query(query: str) -> list[dict[str, str]]:
    """Validate a lazy data-catalog query and return its cached controlled files."""
    try:
        values = parse_qs(query, strict_parsing=True).get("kind", [])
    except ValueError as exc:
        raise ConfigError("data catalog query must contain kind=<supported-kind>.") from exc
    if len(values) != 1 or values[0] not in CATALOG_KINDS:
        raise ConfigError(f"kind must be one of {sorted(CATALOG_KINDS)}.")
    return list(_catalog(values[0]))


@lru_cache(maxsize=len(CATALOG_KINDS))
def _catalog(kind: str) -> tuple[dict[str, str], ...]:
    """Discover one bounded, controlled data category once per server lifetime."""
    paths: list[dict[str, str]] = []
    for root in (PROJECT_ROOT / "data", PROJECT_ROOT / "configs", HEXGRID_ROOT):
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if (
                candidate.is_file()
                and candidate.suffix.lower() in CATALOG_SUFFIXES
                and _catalog_kind(candidate) == kind
            ):
                paths.append({"path": str(candidate), "kind": kind})
                if len(paths) >= MAX_CATALOG_FILES:
                    return tuple(paths)
    return tuple(paths)


def _catalog_kind(path: Path) -> str:
    name = path.name.lower()
    if "dem" in name:
        return "dem"
    if "land" in name or "cover" in name:
        return "landcover"
    if "soil" in name:
        return "soil"
    if "road" in name:
        return "road"
    if "vehicle" in name or "car" in name:
        return "vehicle"
    if "planner" in name:
        return "planner"
    return "other"


def _tile_manifest(result: dict[str, object]) -> dict[str, object] | None:
    tile = result.get("tile_manifest")
    if isinstance(tile, dict):
        return cast(dict[str, object], tile)
    route = result.get("route_manifest")
    if not isinstance(route, dict):
        return None
    path = route.get("parquet_path")
    if not isinstance(path, str) or not path.endswith(".json"):
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return cast(dict[str, object], payload) if isinstance(payload, dict) else None


def _tile_records(manifest: dict[str, object]) -> list[dict[str, object]]:
    return [
        record
        for record in _all_tile_records(manifest)
        if record.get("status") in {"completed", "skipped"}
        and isinstance(record.get("path"), str)
    ]


def _all_tile_records(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = manifest.get("tiles")
    if not isinstance(records, list):
        raise GridBuildError("tile manifest must contain a tiles list.")
    if any(not isinstance(record, dict) for record in records):
        raise GridBuildError("tile manifest records must be JSON objects.")
    return [cast(dict[str, object], record) for record in records]


def _record_non_negative_int(record: dict[str, object], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        parent_h3 = record.get("parent_h3")
        raise GridBuildError(f"parent tile {parent_h3} field {key!r} must be non-negative integer.")
    return value


def _manifest_tile_path(
    manifest: dict[str, object], record: dict[str, object], parent_h3: str
) -> Path:
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise GridBuildError(f"parent tile {parent_h3} has no readable path.")
    candidate = Path(raw_path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    output_dir = manifest.get("output_dir")
    if isinstance(output_dir, str) and output_dir:
        return Path(output_dir) / candidate
    return candidate


def _route_geojson(route_manifest: dict[str, object]) -> dict[str, object]:
    path = route_manifest.get("output_path_geojson")
    if not isinstance(path, str) or not path:
        raise PlanningInputError("route manifest is missing output_path_geojson.")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanningInputError("planned route GeoJSON must be an object.")
    return cast(dict[str, object], payload)


def _h3_geometry(cell_id: str) -> dict[str, object]:
    coordinates = [[float(lng), float(lat)] for lat, lng in h3.cell_to_boundary(cell_id)]
    coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


def _collection(features: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"type": "FeatureCollection", "features": [] if features is None else features}


def _route_feature_collection(geojson: dict[str, object]) -> dict[str, object]:
    """Normalize one persisted route at the WebGIS display boundary."""
    geojson_type = geojson.get("type")
    if geojson_type == "FeatureCollection":
        return geojson
    if geojson_type == "Feature":
        return _collection([geojson])
    raise PlanningInputError("route GeoJSON must be a Feature or FeatureCollection.")


def _json_scalar(value: object) -> object:
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"request field {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _report(progress: ProgressCallback | None, module: str, percent: int, message: str) -> None:
    if progress is not None:
        progress(module, percent, message)


def _content_length(headers: Message) -> int:
    raw_value = headers.get("Content-Length")
    try:
        length = int(raw_value) if raw_value is not None else 0
    except ValueError as exc:
        raise ConfigError("Content-Length must be an integer.") from exc
    if length <= 0 or length > MAX_REQUEST_BYTES:
        raise ConfigError(f"request body must be in [1, {MAX_REQUEST_BYTES}] bytes.")
    return length


def _read_index() -> bytes:
    try:
        template = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("local Web console asset is unavailable.") from exc
    rendered = (
        template.replace("__TIANDITU_KEY__", TIANDITU_KEY)
        .replace("__TIANDITU_LAYER__", TIANDITU_LAYER_TYPE)
        .replace(
            "__DEFAULT_REQUEST_YAML__",
            json.dumps(DEFAULT_DELIVERY_PATH.read_text(encoding="utf-8"), ensure_ascii=False),
        )
    )
    return rendered.encode("utf-8")


def _error_status(exc: Exception) -> HTTPStatus:
    return (
        HTTPStatus.BAD_REQUEST
        if isinstance(exc, (ConfigError, ValueError, yaml.YAMLError))
        else HTTPStatus.UNPROCESSABLE_ENTITY
    )


_WEB_ERRORS = (
    ConfigError,
    FileNotFoundError,
    GISInputError,
    GridBuildError,
    OSError,
    PlanningFailedError,
    PlanningInputError,
    ValueError,
    yaml.YAMLError,
)


if __name__ == "__main__":
    run_web_console()
