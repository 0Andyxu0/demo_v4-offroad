"""Measure QDX TWI quality and candidate mapping thresholds from GRASS rasters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask


def analyze(hydrology_dir: Path, roi_path: Path) -> dict[str, object]:
    with rasterio.open(hydrology_dir / "twi.tif") as source:
        twi = source.read(1, masked=True).astype(np.float64).filled(np.nan)
        roi = gpd.read_file(roi_path).to_crs(source.crs)
        inside = geometry_mask(
            list(roi.geometry), out_shape=twi.shape, transform=source.transform, invert=True
        )
        grid = {
            "crs": str(source.crs),
            "resolution_m": list(source.res),
            "width": source.width,
            "height": source.height,
            "bounds": list(source.bounds),
        }
    with rasterio.open(hydrology_dir / "drainage_validity.tif") as source:
        valid = source.read(1) == 1
    with rasterio.open(hydrology_dir / "boundary_influence.tif") as source:
        boundary = source.read(1) == 1
    finite = valid & np.isfinite(twi)
    reference = finite & ~boundary
    values = twi[reference]
    if not len(values):
        raise ValueError("no unaffected valid TWI pixels")
    quantiles = {str(q): float(np.percentile(values, q)) for q in (5, 10, 25, 50, 75, 90, 95)}
    threshold_pairs = {
        "q05_q95": (quantiles["5"], quantiles["95"]),
        "q10_q90": (quantiles["10"], quantiles["90"]),
        "q25_q75": (quantiles["25"], quantiles["75"]),
    }
    mappings: dict[str, object] = {}
    for name, (t0, t1) in threshold_pairs.items():
        mappings[name] = {
            "t0": t0,
            "t1": t1,
            "zero_fraction": float(np.mean(values <= t0)),
            "one_fraction": float(np.mean(values >= t1)),
            "mean_d": float(np.mean(np.clip((values - t0) / (t1 - t0), 0.0, 1.0))),
        }
    return {
        "grid": grid,
        "counts": {
            "total_pixels": int(twi.size),
            "valid_twi_pixels": int(finite.sum()),
            "boundary_affected_pixels": int(boundary.sum()),
            "boundary_affected_valid_pixels": int((finite & boundary).sum()),
            "unaffected_valid_pixels": int(reference.sum()),
            "roi_pixels": int(inside.sum()),
            "roi_valid_pixels": int((inside & finite).sum()),
            "roi_boundary_affected_pixels": int((inside & boundary).sum()),
            "roi_unaffected_valid_pixels": int((inside & reference).sum()),
        },
        "unaffected_twi_quantiles": quantiles,
        "candidate_mappings": mappings,
        "chosen_mapping": "q05_q95",
        "upstream_complete": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hydrology_dir", type=Path)
    parser.add_argument("roi_path", type=Path)
    args = parser.parse_args()
    result = analyze(args.hydrology_dir, args.roi_path)
    output = args.hydrology_dir / "twi_threshold_analysis.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
