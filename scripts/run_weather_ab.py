"""Run dry/medium/wet weather A/B scenarios for a route request.

Usage:
    python scripts/run_weather_ab.py \
        --request configs/qdx_hydrology_pilot_route.yaml \
        --output outputs/weather_ab
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {
    "dry": 0.25,
    "medium": 0.30,
    "wet": 0.35,
}


def _snapshot(moisture: float, lat: float, lng: float) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "provider": "open-meteo",
        "model": "best_match",
        "requested_at": now.isoformat(),
        "valid_at": (now - timedelta(minutes=30)).isoformat(),
        "latitude": lat,
        "longitude": lng,
        "spatial_support": "route_endpoint_centroid",
        "spatial_support_km": None,
        "precipitation_24h_mm": 0.0,
        "soil_moisture_surface_m3_m3": moisture,
        "soil_moisture_support_cm": "0-5_estimated_from_0-1_1-3_3-9",
        "et0_24h_mm": 3.0,
        "age_s": 1800.0,
        "degraded": False,
        "degradation_reason": None,
        "cache_hit": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = yaml.safe_load(args.request.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("route request must be a YAML mapping")
    lat = (float(payload["start_lat"]) + float(payload["goal_lat"])) / 2.0
    lng = (float(payload["start_lng"]) + float(payload["goal_lng"])) / 2.0

    summary: dict[str, object] = {}
    for name, moisture in SCENARIOS.items():
        out = args.output / name
        out.mkdir(parents=True, exist_ok=True)
        snapshot_path = out / "environment_snapshot.json"
        snapshot_path.write_text(
            json.dumps(_snapshot(moisture, lat, lng), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        request = dict(payload)
        request["output_dir"] = str(out)
        request["environment_snapshot_path"] = str(snapshot_path)
        request_yaml = out / "request.yaml"
        request_yaml.write_text(yaml.safe_dump(request, allow_unicode=True), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "h3_offroad_planner", "plan", "--request", str(request_yaml)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            summary[name] = {"status": "failed", "stderr": result.stderr.strip()}
            continue
        plan = json.loads(result.stdout)
        performance_path = out / "performance.json"
        performance = json.loads(performance_path.read_text(encoding="utf-8"))
        summary[name] = {
            "status": "ok",
            "moisture": moisture,
            "derived_pressure": plan["aggregation_stats"]["environment_snapshot"].get(
                "derived_pressure"
            ),
            "plan_ready_s": performance["plan_ready_s"],
            "candidate_count": len(plan["candidates"]),
            "warnings": list(plan.get("warnings", [])),
        }

    summary_path = args.output / "weather_ab_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
