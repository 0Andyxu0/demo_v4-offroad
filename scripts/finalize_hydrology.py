"""Finalize hydrology outputs from GRASS rasters without rerunning GRASS.

Reads existing twi/accumulation rasters and writes:
  - drainage_sensitivity.tif
  - drainage_validity.tif
  - boundary_influence.tif

Then updates hydrology_manifest.json with frozen thresholds and upstream flag.

Usage:
    python scripts/finalize_hydrology.py outputs/qdx_hydrology_upstream_v1 \
        --t0 4.387526936194684 --t1 18.25971731959038 --upstream-complete
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from h3_offroad_planner.preprocessing.hydrology import HydrologyConfig, _write_masks_and_drainage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hydrology_dir", type=Path)
    parser.add_argument("--t0", type=float, required=True)
    parser.add_argument("--t1", type=float, required=True)
    parser.add_argument("--upstream-complete", action="store_true")
    args = parser.parse_args()

    out = args.hydrology_dir
    paths = {
        "twi": out / "twi.tif",
        "accumulation": out / "accumulation.tif",
        "drainage_sensitivity": out / "drainage_sensitivity.tif",
        "validity": out / "drainage_validity.tif",
        "boundary": out / "boundary_influence.tif",
    }
    for key, path in paths.items():
        if key == "drainage_sensitivity" and path.exists():
            path.unlink()
        if not path.exists() and key != "drainage_sensitivity":
            raise SystemExit(f"missing {key}: {path}")

    config = HydrologyConfig(
        mapping_t0=args.t0,
        mapping_t1=args.t1,
        upstream_complete=args.upstream_complete,
        version="twi_drainage_upstream_v1",
    )
    _write_masks_and_drainage(paths, config)

    manifest_path = out / "hydrology_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["mapping_t0"] = args.t0
    manifest["config"]["mapping_t1"] = args.t1
    manifest["config"]["upstream_complete"] = args.upstream_complete
    manifest["boundary_influence"] = (
        "complete_upstream_declared" if args.upstream_complete else "potential_boundary_influence"
    )
    manifest["drainage_mapping_status"] = "frozen"
    manifest.setdefault("outputs", {})["drainage_sensitivity"] = str(paths["drainage_sensitivity"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"finalized {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
