"""Calibrate theta_dry / theta_wet from a local soil-moisture climatology.

The surface-drainage multiplier needs two moisture anchors, not the current
moisture value: pressure = (theta - theta_dry) / (theta_wet - theta_dry). These
anchors must come from the map's own site and season, otherwise the "real
weather correction" is pinned at zero or drifts with the wrong climate.

This script pulls one year of Open-Meteo archive soil moisture at the study
site, takes the q05/q95 percentiles, and freezes them with full provenance.
It only writes the calibration JSON; the planner config (theta_dry/theta_wet)
is validated against this file by tests/test_m1_consolidated_regression.py.

Usage:
    python scripts/calibrate_moisture.py
    python scripts/calibrate_moisture.py --start 2025-10-18 --end 2026-10-17
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "configs" / "scenes" / "qdx_moisture_calibration.json"
ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
VARIABLE = "soil_moisture_0_to_7cm"
SITE_LAT = 31.9918777858
SITE_LNG = 118.9927309985


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = int(round(fraction * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def _fetch(lat: float, lng: float, start: str, end: str) -> dict[str, object]:
    query = urllib.parse.urlencode(
        {
            "latitude": f"{lat}",
            "longitude": f"{lng}",
            "start_date": start,
            "end_date": end,
            "hourly": VARIABLE,
            "timezone": "UTC",
        }
    )
    with urllib.request.urlopen(f"{ARCHIVE_ENDPOINT}?{query}", timeout=60) as response:
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=SITE_LAT)
    parser.add_argument("--lng", type=float, default=SITE_LNG)
    parser.add_argument("--start", default="2025-10-18")
    parser.add_argument("--end", default="2026-10-17")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    payload = _fetch(args.lat, args.lng, args.start, args.end)
    hourly = payload.get("hourly", {})
    raw = hourly.get(VARIABLE) if isinstance(hourly, dict) else None
    values = sorted(float(v) for v in (raw or []) if v is not None)
    if len(values) < 24 * 30:
        raise SystemExit(f"too few soil-moisture samples: {len(values)}")

    q05 = _percentile(values, 0.05)
    q50 = _percentile(values, 0.50)
    q95 = _percentile(values, 0.95)
    if not 0.0 < q05 < q95 <= 1.0:
        raise SystemExit(f"implausible percentiles: q05={q05} q95={q95}")

    calibration = {
        "schema_version": "moisture_calibration_v1",
        "purpose": "theta_dry/theta_wet anchors for surface_drainage_multiplier_v1",
        "site": {
            "requested_lat": args.lat,
            "requested_lng": args.lng,
            "grid_lat": payload.get("latitude"),
            "grid_lng": payload.get("longitude"),
            "grid_elevation_m": payload.get("elevation"),
        },
        "period": {
            "start": args.start,
            "end": args.end,
            "timezone": "UTC",
            "sample_count": len(values),
        },
        "variable": VARIABLE,
        "unit": "m3/m3",
        "depth": "0-7cm",
        "percentiles": {"q05": round(q05, 4), "q50": round(q50, 4), "q95": round(q95, 4)},
        "source": {
            "provider": "open-meteo",
            "endpoint": ARCHIVE_ENDPOINT,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
        "caveats": [
            "Reanalysis product (ERA5-Land derived), not a field measurement.",
            "Grid resolution is far coarser than the 30 m work area; this is a regional anchor.",
            "Re-run this script if the site or the mapping season changes.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")
    print(f"  q05={q05:.4f} q50={q50:.4f} q95={q95:.4f} (n={len(values)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
