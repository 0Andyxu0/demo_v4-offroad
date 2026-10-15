"""Produce the M0 real-data baseline without changing planning-model behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import yaml

from h3_offroad_planner.environment import load_environment_snapshot
from h3_offroad_planner.factor_model import load_static_planning_config
from h3_offroad_planner.orthophoto_preview import create_orthophoto_preview
from h3_offroad_planner.scene import prepare_static_scene

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST = ROOT / "configs" / "manned_offroad_m0.yaml"
DEFAULT_SCENE = ROOT / "configs" / "scenes" / "m0_qdx_scene.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "m0_qdx_baseline"


def main(argv: list[str] | None = None) -> int:
    """Generate visual, attribute, and route artifacts for the fixed M0 scene."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    request_path = _resolve(args.request)
    scene_path = _resolve(args.scene)
    output_dir = _resolve(args.output_dir)
    request = _load_yaml(request_path)
    scene = _load_json(scene_path)
    _validate_scene_request(request, scene)
    output_dir.mkdir(parents=True, exist_ok=True)

    route = _mapping(request, "route")
    tile_build = _mapping(request, "tile_build")
    map_display = _mapping(request, "map_display")
    study_bounds = _study_bounds(tile_build)
    preview = create_orthophoto_preview(
        _required_path(map_display, "orthophoto_source_path"),
        output_dir / "orthophoto_preview.png",
        study_bounds,
    )
    preview_metadata = preview.to_dict()
    _write_json(output_dir / "orthophoto_preview.json", preview_metadata)
    attribute_audit = _audit_key_attributes(tile_build, scene)
    _write_json(output_dir / "landcover_attribute_audit.json", attribute_audit)
    static_scene = prepare_static_scene(
        inputs=request_path,
        weather_snapshot=_required_path(route, "environment_snapshot_path"),
        build_config={
            "scene_id": scene["scene_id"],
            "metric_crs": scene.get("metric_crs", "EPSG:4528"),
            "baseline_source_commit": scene.get("baseline_source_commit", "986bd58"),
            "assets_config_path": ROOT / "configs" / "manned_assets.private.yaml",
            "primary_od": scene.get("primary_od"),
            "vehicle": scene.get("vehicle"),
            "quality_and_budget_status": scene.get("quality_and_budget_status"),
        },
    )
    static_scene.save_json(output_dir / "static_scene.json")
    frozen_weather = _load_frozen_weather(route)

    plan_result = _run_plan(request_path)
    route_output = _required_output_directory(route, "output_dir")
    performance = _load_performance(route_output)
    baseline = {
        "schema_version": "m0_reproducible_baseline_v1",
        "scene_id": scene["scene_id"],
        "baseline_source_commit": scene["baseline_source_commit"],
        "execution_commit": _git_head(),
        "request_path": _relative(request_path),
        "scene_path": _relative(scene_path),
        "static_scene_path": _relative(output_dir / "static_scene.json"),
        "request_sha256": _sha256(request_path),
        "scene_sha256": _sha256(scene_path),
        "static_scene_sha256": _sha256(output_dir / "static_scene.json"),
        "vehicle_sha256": _sha256(_required_path(route, "vehicle_path")),
        "weather_snapshot_sha256": _sha256(_required_path(route, "environment_snapshot_path")),
        "tile_manifest_sha256": _sha256(_required_path(route, "parquet_path")),
        "study_bounds_wgs84": list(study_bounds),
        "primary_od": {
            "start_wgs84": [route["start_lat"], route["start_lng"]],
            "goal_wgs84": [route["goal_lat"], route["goal_lng"]],
        },
        "frozen_weather": frozen_weather,
        "orthophoto_preview": preview_metadata,
        "attribute_audit": _relative(output_dir / "landcover_attribute_audit.json"),
        "route_output": _relative(route_output),
        "plan_summary": _plan_summary(plan_result, performance),
        "interpretation_boundary": (
            "The route is a reproducible baseline_original result. Its legacy trajectory status "
            "does not establish manned-vehicle passability, and the orthophoto preview does "
            "not alter map physics."
        ),
    }
    _write_json(output_dir / "m0_baseline.json", baseline)
    print(
        json.dumps(
            {
                "status": "passed",
                "scene_id": scene["scene_id"],
                "baseline": _relative(output_dir / "m0_baseline.json"),
                "static_scene": _relative(output_dir / "static_scene.json"),
                "orthophoto_preview": _relative(output_dir / "orthophoto_preview.png"),
                "attribute_audit": _relative(output_dir / "landcover_attribute_audit.json"),
                "route_output": _relative(route_output),
                "candidate_count": baseline["plan_summary"]["candidate_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"M0 request must be a mapping: {path}")
    return cast(dict[str, object], payload)


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"M0 scene must be an object: {path}")
    return cast(dict[str, object], payload)


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"M0 request requires a {key} mapping.")
    return cast(dict[str, object], value)


def _required_path(payload: dict[str, object], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"M0 field {key} must be a non-empty path string.")
    path = _resolve(Path(value))
    if not path.is_file():
        raise FileNotFoundError(f"M0 input does not exist: {path}")
    return path


def _study_bounds(tile_build: dict[str, object]) -> tuple[float, float, float, float]:
    roi_path = _required_path(tile_build, "roi_layer_path")
    roi = gpd.read_file(roi_path)
    if roi.empty or roi.crs is None:
        raise ValueError("M0 study boundary is empty or lacks a CRS.")
    west, south, east, north = roi.to_crs("EPSG:4326").total_bounds
    return float(west), float(south), float(east), float(north)


def _audit_key_attributes(
    tile_build: dict[str, object], scene: dict[str, object]
) -> dict[str, object]:
    landcover_directory = _required_path(tile_build, "roi_layer_path").parent
    study_area = gpd.read_file(_required_path(tile_build, "roi_layer_path"))
    study_geometry = study_area.geometry.union_all()
    entries = scene.get("key_landcover_attributes")
    if not isinstance(entries, list):
        raise ValueError("M0 scene lacks key_landcover_attributes.")
    checks: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("M0 key-landcover attribute entry must be an object.")
        layer = entry.get("layer")
        field = entry.get("field")
        if not isinstance(layer, str) or not isinstance(field, str):
            raise ValueError("M0 key-landcover entry needs layer and field strings.")
        path = (
            _required_path(tile_build, "road_path")
            if layer == "road_fina.shp"
            else landcover_directory / layer
        )
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError(f"landcover layer lacks a CRS: {path}")
        if str(frame.crs) != str(study_area.crs):
            frame = frame.to_crs(study_area.crs)
        if field not in frame.columns:
            raise ValueError(f"landcover field {field!r} is absent from {path}")
        selected = frame.loc[frame.geometry.intersects(study_geometry), field].dropna()
        if selected.empty:
            raise ValueError(f"landcover field {field!r} has no populated features in M0 area")
        values = [str(value) for value in selected.head(5).tolist()]
        numeric = pd.to_numeric(selected, errors="coerce").dropna()
        checks.append(
            {
                "layer": layer,
                "field": field,
                "features_in_study_area": int(selected.size),
                "non_null": int(selected.size),
                "sample_raw_values": values,
                "numeric_min": None if numeric.empty else float(numeric.min()),
                "numeric_max": None if numeric.empty else float(numeric.max()),
                "semantic_status": entry.get("semantic_status"),
            }
        )
    return {"study_layer": str(_required_path(tile_build, "roi_layer_path")), "checks": checks}


def _load_frozen_weather(route: dict[str, object]) -> dict[str, object]:
    static_config = load_static_planning_config(str(_required_path(route, "static_planning_path")))
    snapshot_path = _required_path(route, "environment_snapshot_path")
    weather = load_environment_snapshot(
        str(snapshot_path),
        static_config.weather,
        (float(route["start_lat"]) + float(route["goal_lat"])) / 2.0,
        (float(route["start_lng"]) + float(route["goal_lng"])) / 2.0,
    )
    if weather.degraded:
        raise ValueError("M0 frozen weather snapshot is degraded.")
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("M0 frozen weather snapshot must be a JSON object.")
    return cast(dict[str, object], raw)


def _run_plan(request_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_local.py"),
            "cli",
            "plan",
            "--request",
            str(request_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "M0 route baseline failed:\n" + (completed.stderr.strip() or completed.stdout.strip())
        )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("M0 route baseline did not return a JSON object.")
    return cast(dict[str, object], payload)


def _validate_scene_request(request: dict[str, object], scene: dict[str, object]) -> None:
    route = _mapping(request, "route")
    primary_od = scene.get("primary_od")
    if not isinstance(primary_od, dict):
        raise ValueError("M0 scene lacks primary_od.")
    if [route.get("start_lat"), route.get("start_lng")] != primary_od.get("start_wgs84"):
        raise ValueError("M0 request start does not match the fixed scene OD.")
    if [route.get("goal_lat"), route.get("goal_lng")] != primary_od.get("goal_wgs84"):
        raise ValueError("M0 request goal does not match the fixed scene OD.")
    weather = scene.get("weather")
    vehicle = scene.get("vehicle")
    if not isinstance(weather, dict) or not isinstance(vehicle, dict):
        raise ValueError("M0 scene lacks weather or vehicle metadata.")
    route_snap = Path(str(route.get("environment_snapshot_path"))).as_posix()
    weather_snap = Path(str(weather.get("snapshot_path"))).as_posix()
    if route_snap != weather_snap:
        raise ValueError("M0 request does not use the fixed weather snapshot.")
    route_veh = Path(str(route.get("vehicle_path"))).as_posix()
    veh_cfg = Path(str(vehicle.get("config_path"))).as_posix()
    if route_veh != veh_cfg:
        raise ValueError("M0 request does not use the fixed vehicle profile.")


def _load_performance(route_output: Path) -> dict[str, object]:
    path = route_output / "performance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("M0 route performance artifact must be a JSON object.")
    return cast(dict[str, object], payload)


def _plan_summary(result: dict[str, object], performance: dict[str, object]) -> dict[str, object]:
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("M0 route result lacks candidate routes.")
    return {
        "candidate_count": len(candidates),
        "recommended_candidate_id": result.get("recommended_candidate_id"),
        "trajectory_statuses": [
            candidate.get("trajectory", {}).get("status")
            for candidate in candidates
            if isinstance(candidate, dict)
        ],
        "plan_ready_s": performance.get("plan_ready_s"),
        "candidate_search_s": performance.get("candidate_search_s"),
        "cell_count": performance.get("cell_count"),
        "edge_count": performance.get("edge_count"),
    }


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _required_output_directory(payload: dict[str, object], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"M0 field {key} must be a non-empty path string.")
    path = _resolve(Path(value))
    if not path.is_dir():
        raise FileNotFoundError(f"M0 output directory was not created: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
