"""Spec-derived tests for MVP-7.1 GIS-to-route delivery CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml

from h3_offroad_planner.cli import main
from h3_offroad_planner.models import RouteRequest, TileBuildRequest


def test_t098_cli_run_composes_tile_build_and_route(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    """T-098: Combined CLI request routes through the generated tile manifest."""
    request_path = tmp_path / "delivery.yaml"
    tile_output = tmp_path / "tiles"
    _write_yaml(request_path, _delivery_payload(tile_output))
    calls: dict[str, object] = {}

    def fake_build(request: TileBuildRequest) -> dict[str, object]:
        calls["tile"] = request
        return {"artifact_kind": "tile_h3_cache", "output_dir": request.output_dir}

    class FakePlan:
        def to_dict(self) -> dict[str, object]:
            return {"planned_path_length": 3}

    def fake_route(request: RouteRequest) -> FakePlan:
        calls["route"] = request
        return FakePlan()

    monkeypatch.setattr("h3_offroad_planner.cli.build_h3_tile_cache", fake_build)
    monkeypatch.setattr("h3_offroad_planner.cli.run_route_plan", fake_route)

    assert main(["run", "--request", str(request_path)]) == 0

    route_request = cast(RouteRequest, calls["route"])
    assert route_request.parquet_path == str(tile_output / "tile_manifest.json")
    output = json.loads(capsys.readouterr().out)
    assert output["tile_manifest"]["artifact_kind"] == "tile_h3_cache"
    assert output["route_manifest"]["planned_path_length"] == 3


def test_t099_cli_rejects_missing_request(tmp_path: Path, capsys: object) -> None:
    """T-099: Missing CLI request returns the explicit request-error exit code."""
    missing = tmp_path / "missing.yaml"

    assert main(["plan", "--request", str(missing)]) == 2

    assert "error:" in capsys.readouterr().err


def test_t100_cli_dispatches_build_and_plan_requests(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    """T-100: Build and plan commands delegate to their existing domain APIs."""
    tile_request_path = tmp_path / "tile.yaml"
    route_request_path = tmp_path / "route.yaml"
    _write_yaml(tile_request_path, _tile_payload(tmp_path / "tile_out"))
    _write_yaml(route_request_path, _route_payload(tmp_path / "route_out"))
    calls: list[str] = []

    def fake_build(request: TileBuildRequest) -> dict[str, object]:
        calls.append(request.output_dir)
        return {"kind": "tile"}

    class FakePlan:
        def to_dict(self) -> dict[str, object]:
            return {"kind": "route"}

    def fake_route(request: RouteRequest) -> FakePlan:
        calls.append(request.output_dir)
        return FakePlan()

    monkeypatch.setattr("h3_offroad_planner.cli.build_h3_tile_cache", fake_build)
    monkeypatch.setattr("h3_offroad_planner.cli.run_route_plan", fake_route)

    assert main(["build-tiles", "--request", str(tile_request_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"kind": "tile"}
    assert main(["plan", "--request", str(route_request_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"kind": "route"}
    assert calls == [str(tmp_path / "tile_out"), str(tmp_path / "route_out")]


def _delivery_payload(tile_output: Path) -> dict[str, object]:
    return {"tile_build": _tile_payload(tile_output), "route": _route_payload(Path("route"))}


def _tile_payload(output_dir: Path) -> dict[str, object]:
    return {
        "dem_path": "dem.tif",
        "landcover_path": "landcover.tif",
        "output_dir": str(output_dir),
        "roi_layer_path": "roi.geojson",
    }


def _route_payload(output_dir: Path) -> dict[str, object]:
    return {
        "goal_lat": 32.1,
        "goal_lng": 118.1,
        "input_mode": "coordinates",
        "output_dir": str(output_dir),
        "parquet_path": "ignored.parquet",
        "planner_config_path": "planner.yaml",
        "start_lat": 32.0,
        "start_lng": 118.0,
        "vehicle_path": "vehicle.yaml",
        "factor_model_path": "static_factor_model.yaml",
    }


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=False), encoding="utf-8")
