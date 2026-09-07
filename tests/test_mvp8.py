"""Spec-derived tests for the MVP-8 local Web console."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import h3
import pandas as pd
import pytest

from h3_offroad_planner import desktop_client, web_console
from h3_offroad_planner.desktop_client import _candidate_label
from h3_offroad_planner.desktop_map import _MAP_TEMPLATE
from h3_offroad_planner.desktop_project import DesktopProjectState, load_project_yaml
from h3_offroad_planner.web_console import create_web_console


def test_t104_web_console_runs_valid_delivery_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-104: a valid YAML delivery returns manifests and route GeoJSON."""
    route_path = tmp_path / "planned_path.geojson"
    route_geojson = _route_geojson()
    route_path.write_text(json.dumps(route_geojson), encoding="utf-8")
    received: list[dict[str, object]] = []

    def fake_delivery(payload: dict[str, object]) -> dict[str, object]:
        received.append(payload)
        return {
            "route_manifest": {"output_path_geojson": str(route_path)},
            "tile_manifest": {"artifact_kind": "tile_h3_cache"},
        }

    monkeypatch.setattr("h3_offroad_planner.web_console.run_delivery_payload", fake_delivery)
    request_yaml = "tile_build:\n  dem_path: dem.tif\nroute:\n  input_mode: coordinates\n"

    with _running_console() as server:
        status, body = _request(server, "POST", "/api/run", _json_bytes(request_yaml))

    response = json.loads(body)
    assert status == 200
    assert received == [
        {"tile_build": {"dem_path": "dem.tif"}, "route": {"input_mode": "coordinates"}}
    ]
    assert response["delivery"]["tile_manifest"]["artifact_kind"] == "tile_h3_cache"
    assert response["route_geojson"] == route_geojson


def test_t105_web_console_serves_tianditu_webgis_controls() -> None:
    """T-105: the local page exposes the MVP-8.1 TianDiTu WebGIS controls."""
    with _running_console() as server:
        status, body = _request(server, "GET", "/")

    assert status == 200
    assert '<textarea id="request"' in body
    assert 'id="map"' in body
    assert 'id="backend-log"' in body
    assert "L.Control.Draw" in body
    assert "tianditu.gov.cn" in body
    assert "run-stream" in body


def test_cl037_web_state_endpoints_select_and_return_replanned_active_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup Web uses the same explicit selection/replan business endpoints as Client."""
    active = _route_feature()
    (tmp_path / "active_route.geojson").write_text(json.dumps(active), encoding="utf-8")
    monkeypatch.setattr(
        web_console,
        "run_select_payload",
        lambda payload: {"candidate_id": payload["candidate_id"], "state": "active"},
    )
    monkeypatch.setattr(
        web_console,
        "run_replan_payload",
        lambda payload: {
            "candidate_id": "route-a",
            "algorithm": "DStarLite",
            "status": "active",
            "replan_version": 1,
            "metrics_after": {
                "eta_lower_s": 1.0,
                "eta_s": 2.0,
                "eta_upper_s": 3.0,
                "distance_m": 10.0,
                "score_lower_min": 0.7,
                "terrain_risk": 4.0,
                "travel_cost": 5.0,
            },
            "warnings": [],
        },
    )
    with _running_console() as server:
        select_status, select_body = _request(
            server,
            "POST",
            "/api/select",
            json.dumps({"plan_path": "plan.json", "candidate_id": "route-a"}).encode(),
        )
        replan_status, replan_body = _request(
            server,
            "POST",
            "/api/replan",
            json.dumps(
                {
                    "selection_path": str(tmp_path / "route_selection.json"),
                    "current_h3": "cell",
                    "now_epoch_s": 1.0,
                }
            ).encode(),
        )

    assert select_status == 200
    assert json.loads(select_body)["candidate_id"] == "route-a"
    assert replan_status == 200
    rendered = json.loads(replan_body)
    assert rendered["route_geojson"]["type"] == "FeatureCollection"
    assert rendered["route_geojson"]["features"][0]["geometry"] == active["geometry"]
    assert rendered["route_evaluation"]["eta_s"] == 2.0


def test_t122_to_t124_serializer_exposes_selectable_candidate_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-122/T-123/T-124: candidates retain geometry, five metrics, and objective labels."""
    route_path = tmp_path / "planned_path.geojson"
    route_path.write_text(json.dumps(_route_geojson()), encoding="utf-8")
    rows = _candidate_rows()
    monkeypatch.setattr(
        web_console,
        "_grid_layers",
        lambda manifest: (_collection(), _collection(), rows),
    )
    monkeypatch.setattr(
        web_console,
        "load_vehicle",
        lambda path: SimpleNamespace(max_speed_kmh=36.0, min_turn_radius_m=4.0),
    )

    response = web_console.serialize_webgis_result(
        {"tile_manifest": {}, "route_manifest": _candidate_manifest(route_path)}
    )

    candidates = response["candidate_routes"]
    assert isinstance(candidates, list)
    assert len(candidates) == 2
    first, second = candidates
    assert first["candidate_index"] == 0
    assert second["candidate_index"] == 1
    assert first["geojson"]["features"][0]["geometry"]["coordinates"] == [
        [118.8, 31.9],
        [118.81, 31.91],
    ]
    assert set(first["objectives"]) == {
        "distance",
        "trafficability",
        "travel_cost",
        "slope",
        "roughness",
    }
    assert first["evaluation"]["selection_reason"] == ["shortest distance"]
    assert second["evaluation"]["selection_reason"] == ["minimum travel cost"]


def test_t125_web_console_page_contains_candidate_metric_switching_controls() -> None:
    """T-125: the browser renders objective cards and switches cached GeoJSON locally."""
    with _running_console() as server:
        status, body = _request(server, "GET", "/")

    assert status == 200
    assert "OBJECTIVE_META" in body
    assert "selectCandidate(candidate)" in body
    assert "candidate.candidate_index" in body


def test_t126_replanned_result_only_exposes_active_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-126: D* Lite output never presents stale Pareto objective values as current."""
    route_path = tmp_path / "replanned_path.geojson"
    route_path.write_text(json.dumps(_route_geojson()), encoding="utf-8")
    monkeypatch.setattr(
        web_console,
        "load_vehicle",
        lambda path: SimpleNamespace(max_speed_kmh=36.0, min_turn_radius_m=4.0),
    )
    manifest = _candidate_manifest(route_path)
    manifest["candidate_index"] = 1
    manifest["replanned"] = True
    manifest["planned_path"] = ["a", "c"]

    response = web_console.serialize_webgis_result(
        {"tile_manifest": {"tiles": []}, "route_manifest": manifest}
    )

    candidates = response["candidate_routes"]
    assert isinstance(candidates, list)
    assert len(candidates) == 1
    assert candidates[0]["candidate_index"] == 1
    assert candidates[0]["objectives"] == {}
    assert candidates[0]["total_cost"] is None
    assert candidates[0]["evaluation"]["selection_reason"] == [
        "D* Lite replanned active route"
    ]


def test_route_plan_feature_is_normalized_for_map_rendering() -> None:
    """A persisted single-route Feature becomes a map-safe FeatureCollection."""
    feature = {
        "type": "Feature",
        "properties": {"h3_path": ["a", "b"]},
        "geometry": {
            "type": "LineString",
            "coordinates": [[118.8, 31.9], [118.81, 31.91]],
        },
    }
    response = web_console.serialize_webgis_result(
        {
            "route_manifest": {
                "candidates": [
                    {
                        "candidate_id": "route-1",
                        "roles": ["fastest_eta"],
                        "is_recommended": True,
                        "geojson": feature,
                        "metrics": {"eta_s": 120.0},
                    }
                ]
            }
        },
        parent_only=True,
    )

    expected = {"type": "FeatureCollection", "features": [feature]}
    assert response["route_geojson"] == expected
    assert response["candidate_routes"][0]["geojson"] == expected


def test_t127_legacy_route_remains_available_when_candidate_geometry_cannot_be_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-127: missing tile rows degrade to legacy selected-route rendering without failure."""
    route_path = tmp_path / "legacy_path.geojson"
    expected_route = _route_geojson()
    route_path.write_text(json.dumps(expected_route), encoding="utf-8")
    monkeypatch.setattr(
        web_console,
        "load_vehicle",
        lambda path: SimpleNamespace(max_speed_kmh=36.0, min_turn_radius_m=4.0),
    )

    response = web_console.serialize_webgis_result(
        {"tile_manifest": {"tiles": []}, "route_manifest": _candidate_manifest(route_path)}
    )

    route_geojson = response["route_geojson"]
    assert isinstance(route_geojson, dict)
    assert route_geojson["features"][0]["geometry"] == expected_route["features"][0]["geometry"]
    assert isinstance(response["route_evaluation"], dict)
    assert response["candidate_routes"][0]["geojson"] is None


def test_desktop_parent_only_serializer_never_reads_fine_tile_parquet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop overview is bounded by parent records and performs no fine-grid I/O."""
    parent = str(h3.latlng_to_cell(32.0, 119.0, 10))
    neighbor = next(cell for cell in h3.grid_disk(parent, 1) if cell != parent)
    manifest = {
        "tiles": [
            {
                "parent_h3": parent,
                "status": "completed",
                "path": "must-not-be-read.parquet",
                "cells_count": 49,
                "error": None,
                "statistics": {"elevation": {"q50": 12.5}},
            },
            {
                "parent_h3": str(neighbor),
                "status": "failed",
                "path": None,
                "cells_count": 0,
                "error": "missing terrain",
                "statistics": {},
            },
        ]
    }
    monkeypatch.setattr(
        web_console.pd,
        "read_parquet",
        lambda path: (_ for _ in ()).throw(AssertionError(f"unexpected read: {path}")),
    )

    response = web_console.serialize_webgis_result(
        {"tile_manifest": manifest}, parent_only=True
    )

    assert response["fine_grid_geojson"]["features"] == []
    features = response["parent_grid_geojson"]["features"]
    assert len(features) == 2
    assert features[0]["properties"]["selectable"] is True
    assert features[0]["properties"]["elevation"] == 12.5
    assert features[1]["properties"]["status"] == "failed"
    assert features[1]["properties"]["selectable"] is False
    monkeypatch.setattr(web_console, "MAX_DESKTOP_PARENT_FEATURES", 1)
    with pytest.raises(web_console.GridBuildError, match="display limit"):
        web_console.serialize_webgis_result({"tile_manifest": manifest}, parent_only=True)


def test_desktop_tile_serializer_reads_only_selected_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop drill-down validates the manifest and loads exactly one parent tile."""
    parent = str(h3.latlng_to_cell(32.0, 119.0, 10))
    children = sorted(str(cell) for cell in h3.cell_to_children(parent, 12))
    tile_path = tmp_path / "selected.parquet"
    pd.DataFrame(
        {
            "h3index": children,
            "parent_h3": [parent] * len(children),
            "elevation": [10.0] * len(children),
        }
    ).to_parquet(tile_path, index=False)
    manifest = {
        "output_dir": str(tmp_path),
        "tiles": [
            {
                "parent_h3": parent,
                "status": "completed",
                "path": tile_path.name,
                "cells_count": len(children),
            }
        ],
    }
    original_read = pd.read_parquet
    reads: list[Path] = []

    def tracked_read(path: object) -> pd.DataFrame:
        reads.append(Path(str(path)))
        return original_read(path)

    monkeypatch.setattr(web_console.pd, "read_parquet", tracked_read)
    result = {"tile_manifest": manifest}

    grid = web_console.serialize_tile_grid(result, parent)

    assert len(grid["features"]) == len(children)
    assert reads == [tile_path]
    assert {feature["properties"]["parent_h3"] for feature in grid["features"]} == {parent}
    with pytest.raises(web_console.GridBuildError, match="not present"):
        web_console.serialize_tile_grid(result, "8a0000000000000")
    monkeypatch.setattr(web_console, "MAX_DESKTOP_TILE_FEATURES", 1)
    with pytest.raises(web_console.GridBuildError, match="drill-down limit"):
        web_console.serialize_tile_grid(result, parent)


@pytest.mark.parametrize(
    ("status", "path", "message"),
    [
        ("failed", None, "not available"),
        ("empty", None, "not available"),
        ("completed", None, "no readable path"),
        ("completed", "missing.parquet", "failed to read"),
    ],
)
def test_desktop_tile_serializer_reports_unavailable_parent_records(
    tmp_path: Path,
    status: str,
    path: str | None,
    message: str,
) -> None:
    """Unavailable drill-down records remain recoverable Python errors."""
    parent = str(h3.latlng_to_cell(32.0, 119.0, 10))
    result = {
        "tile_manifest": {
            "output_dir": str(tmp_path),
            "tiles": [
                {
                    "parent_h3": parent,
                    "status": status,
                    "path": path,
                    "cells_count": 0,
                }
            ],
        }
    }

    with pytest.raises(web_console.GridBuildError, match=message):
        web_console.serialize_tile_grid(result, parent)


def test_t128_desktop_candidate_label_contains_old_objectives_and_real_index() -> None:
    """T-128: desktop selection is no longer a total-cost-only label."""
    label = _candidate_label(
        {
            "objectives": {
                "distance": 1.0,
                "trafficability": 2.0,
                "travel_cost": 3.0,
                "slope": 4.0,
                "roughness": 5.0,
            },
            "total_cost": 3.0,
        },
        4,
    )

    assert "候选 5" in label
    assert all(name in label for name in ("距离", "通行惩罚", "行驶代价", "坡度暴露", "粗糙度暴露"))


def test_t117_web_console_renders_map_config_without_catalog_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-117: first page render has static map config and no eager root scan."""
    calls = 0

    def forbidden_catalog(kind: str) -> tuple[dict[str, str], ...]:
        nonlocal calls
        calls += 1
        raise AssertionError(f"unexpected startup catalog request: {kind}")

    monkeypatch.setattr("h3_offroad_planner.web_console._catalog", forbidden_catalog)
    with _running_console() as server:
        status, body = _request(server, "GET", "/")

    assert status == 200
    assert calls == 0
    assert "__TIANDITU_KEY__" not in body
    assert "__DEFAULT_REQUEST_YAML__" not in body
    assert "cia_w/wmts" in body
    assert "cva_w/wmts" in body
    assert "/api/bootstrap" not in body


def test_t118_web_console_lists_only_requested_data_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-118: the lazy catalog validates type and delegates only that type."""
    received: list[str] = []

    def fake_catalog(kind: str) -> tuple[dict[str, str], ...]:
        received.append(kind)
        return ({"path": "data/dem.tif", "kind": kind},)

    monkeypatch.setattr("h3_offroad_planner.web_console._catalog", fake_catalog)
    with _running_console() as server:
        status, body = _request(server, "GET", "/api/data-catalog?kind=dem")
        invalid_status, invalid_body = _request(server, "GET", "/api/data-catalog?kind=other")

    assert status == 200
    assert json.loads(body)["data_catalog"] == [{"path": "data/dem.tif", "kind": "dem"}]
    assert received == ["dem"]
    assert invalid_status == 400
    assert "kind must be one of" in json.loads(invalid_body)["error"]


def test_t119_desktop_payload_applies_native_map_selection(
    tmp_path: Path,
) -> None:
    """T-119: the canonical desktop project materializes all map selections."""
    project = DesktopProjectState.from_mapping(
        {
            "tile_build": {"output_dir": "outputs/tiles"},
            "route": {"input_mode": "coordinates"},
        }
    )
    project.set_study_area(
        {
            "type": "Polygon",
            "coordinates": [[[118.8, 31.9], [118.81, 31.9], [118.81, 31.91], [118.8, 31.9]]],
        }
    )
    project.set_endpoint("start", 31.901, 118.801)
    project.set_endpoint("goal", 31.909, 118.809)
    project.toggle_blocked_cell("8928308280fffff")
    project.set_candidate_index(1)
    payload = project.build_run_payload(tmp_path)

    tile = payload["tile_build"]
    route = payload["route"]
    assert isinstance(tile, dict)
    assert isinstance(route, dict)
    assert Path(str(tile["roi_layer_path"])).exists()
    assert route["roi_layer_path"] == tile["roi_layer_path"]
    assert route["start_lat"] == 31.901
    assert route["goal_lng"] == 118.809
    assert route["blocked_cells"] == ["8928308280fffff"]
    assert route["candidate_index"] == 1


def test_t120_desktop_operation_uses_existing_tile_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-120: desktop build dispatches to existing payload APIs and reports progress."""
    calls: list[dict[str, object]] = []
    progress: list[tuple[str, int, str]] = []

    def fake_tile(payload: dict[str, object]) -> dict[str, object]:
        calls.append(payload)
        return {"artifact_kind": "tile_h3_cache"}

    monkeypatch.setattr(desktop_client, "run_tile_payload", fake_tile)
    result = desktop_client._execute_desktop_operation(
        "build",
        {"tile_build": {"dem_path": "data/dem.tif"}, "route": {}},
        lambda module, percent, message: progress.append((module, percent, message)),
    )

    assert calls == [{"dem_path": "data/dem.tif"}]
    assert result == {"tile_manifest": {"artifact_kind": "tile_h3_cache"}}
    assert [event[1] for event in progress] == [10, 85]


def test_desktop_replan_dispatch_uses_active_route_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop replanning dispatches directly and returns the persisted active route."""
    active = _route_feature()
    (tmp_path / "active_route.geojson").write_text(json.dumps(active), encoding="utf-8")
    request = {
        "selection_path": str(tmp_path / "route_selection.json"),
        "current_h3": "cell-current",
        "now_epoch_s": 10.0,
    }
    backend = {
        "candidate_id": "route-a",
        "algorithm": "DStarLite",
        "status": "active",
        "replan_version": 2,
        "warnings": [],
    }
    monkeypatch.setattr(desktop_client, "run_replan_payload", lambda payload: backend)

    result = desktop_client._execute_desktop_operation(
        "replan",
        {"replan_request": request},
        lambda *args: None,
    )

    assert result["replan_result"] == backend
    assert result["active_route_geojson"] == active


def test_t121_desktop_map_template_has_tianditu_toolbar_and_event_bridge() -> None:
    """T-121: QWebEngine map offers the map-first toolbar and sequenced bridge."""
    assert "img_w/wmts" in _MAP_TEMPLATE
    assert "cia_w/wmts" in _MAP_TEMPLATE
    assert "vec_w/wmts" in _MAP_TEMPLATE
    assert "cva_w/wmts" in _MAP_TEMPLATE
    assert "new L.Draw.Polygon" in _MAP_TEMPLATE
    assert "map-tools" in _MAP_TEMPLATE
    assert "setBlockageSelectionEnabled" in _MAP_TEMPLATE
    assert "eventSequence" in _MAP_TEMPLATE
    assert "desktop:${eventSequence}" in _MAP_TEMPLATE
    assert "clear_endpoints" in _MAP_TEMPLATE
    assert "clear_blocked" in _MAP_TEMPLATE


def test_desktop_project_state_keeps_one_canonical_map_and_route_state(tmp_path: Path) -> None:
    """Map actions update the route mapping that is used directly for execution."""
    project = DesktopProjectState.from_mapping(
        {
            "tile_build": {"output_dir": "outputs/tiles"},
            "route": {
                "input_mode": "layer",
                "endpoint_layer_path": "data/endpoints.geojson",
                "blocked_cells": ["8928308280fffff"],
                "candidate_index": 2,
            },
        }
    )

    project.set_endpoint("start", 31.901, 118.801)
    project.set_endpoint("goal", 31.909, 118.809)
    assert project.route["input_mode"] == "coordinates"
    assert project.endpoint("start") == (31.901, 118.801)
    assert project.toggle_blocked_cell("8928308280fffff") is False
    assert project.toggle_blocked_cell("8928308281fffff") is True
    project.set_candidate_index(1)

    payload = project.build_run_payload(tmp_path)
    route = payload["route"]
    assert isinstance(route, dict)
    assert route["blocked_cells"] == ["8928308281fffff"]
    assert route["candidate_index"] == 1
    assert route["endpoint_layer_path"] == "data/endpoints.geojson"


def test_desktop_project_export_writes_paired_relative_roi_geojson(tmp_path: Path) -> None:
    """A map ROI is exported beside YAML instead of pointing at a transient session path."""
    project = DesktopProjectState.from_mapping(
        {
            "tile_build": {
                "output_dir": "outputs/tiles",
                "roi_layer_path": "data/original.geojson",
            },
            "route": {"input_mode": "coordinates", "blocked_cells": [], "candidate_index": 0},
        }
    )
    project.set_study_area(
        {
            "type": "Polygon",
            "coordinates": [[[118.8, 31.9], [118.81, 31.9], [118.81, 31.91], [118.8, 31.9]]],
        }
    )

    target = tmp_path / "delivery.yaml"
    roi_path = project.export_yaml(target)
    exported = load_project_yaml(target)

    assert roi_path == tmp_path / "delivery.roi.geojson"
    assert roi_path.exists()
    assert exported.tile_build["roi_layer_path"] == "delivery.roi.geojson"
    assert exported.route["roi_layer_path"] == "delivery.roi.geojson"


def test_desktop_project_preserves_but_blocks_backend_unsupported_fields() -> None:
    """Unsupported imported fields survive export but cannot be silently executed."""
    project = DesktopProjectState.from_mapping(
        {
            "tile_build": {"output_dir": "outputs/tiles", "future_tile_flag": True},
            "route": {"input_mode": "coordinates"},
            "future_top_level": {"keep": True},
        }
    )

    assert project.unsupported_fields() == ["future_top_level", "tile_build.future_tile_flag"]
    with pytest.raises(Exception, match="backend-unsupported fields"):
        project.ensure_runnable()


@pytest.mark.parametrize(
    "body",
    [b"{not-json", json.dumps({"request_yaml": "tile_build: ["}).encode("utf-8")],
)
def test_t106_web_console_rejects_malformed_requests_without_delivery_execution(
    body: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-106: malformed JSON and YAML receive HTTP 400 before any delivery call."""
    calls = 0

    def fake_delivery(payload: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return payload

    monkeypatch.setattr("h3_offroad_planner.web_console.run_delivery_payload", fake_delivery)

    with _running_console() as server:
        status, response = _request(server, "POST", "/api/run", body)

    assert status == 400
    assert "error" in json.loads(response)
    assert calls == 0


@contextmanager
def _running_console() -> Iterator[ThreadingHTTPServer]:
    server = create_web_console(port=_available_port())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    body: bytes | None = None,
) -> tuple[int, str]:
    connection = HTTPConnection(str(server.server_address[0]), server.server_port)
    headers = {} if body is None else {"Content-Type": "application/json"}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        connection.close()


def _json_bytes(request_yaml: str) -> bytes:
    return json.dumps({"request_yaml": request_yaml}).encode("utf-8")


def _route_geojson() -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [_route_feature()],
    }


def _route_feature() -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "LineString",
            "coordinates": [[118.8, 31.9], [118.81, 31.91]],
        },
    }


def _candidate_manifest(route_path: Path) -> dict[str, object]:
    return {
        "output_path_geojson": str(route_path),
        "vehicle_path": "vehicle.yaml",
        "candidate_index": 0,
        "requested_objectives": ["distance", "travel_cost"],
        "planned_path": ["a", "b"],
        "candidate_paths": [
            {
                "cells": ["a", "b"],
                "objectives": {
                    "distance": 1.0,
                    "trafficability": 2.0,
                    "travel_cost": 9.0,
                    "slope": 4.0,
                    "roughness": 5.0,
                },
                "total_cost": 9.0,
            },
            {
                "cells": ["a", "c"],
                "objectives": {
                    "distance": 2.0,
                    "trafficability": 1.0,
                    "travel_cost": 3.0,
                    "slope": 6.0,
                    "roughness": 7.0,
                },
                "total_cost": 3.0,
            },
        ],
    }


def _candidate_rows() -> dict[str, dict[str, object]]:
    return {
        "a": {"lat": 31.9, "lng": 118.8, "score": 0.9, "landcover_type": "road"},
        "b": {"lat": 31.91, "lng": 118.81, "score": 0.8, "landcover_type": "road"},
        "c": {"lat": 31.92, "lng": 118.82, "score": 0.7, "landcover_type": "grass"},
    }


def _collection() -> dict[str, object]:
    return {"type": "FeatureCollection", "features": []}
