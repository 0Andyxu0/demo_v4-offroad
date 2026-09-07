"""Build a sampled real-data Nanjing H3 graph for MVP-2 verification."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from h3_offroad_planner.assessment import TrafficabilityAssessor
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import H3Graph, VehicleProfile
from h3_offroad_planner.preprocessing import GISPreprocessor

DATA_DIR: Path = Path("data")
OUTPUT_DIR: Path = Path("outputs")
OUTPUT_PARQUET: Path = OUTPUT_DIR / "nanjing_h3_sample.parquet"
OUTPUT_MANIFEST: Path = OUTPUT_PARQUET.with_suffix(".manifest.json")
SOIL_CATALOG_CANDIDATES: tuple[Path, ...] = (
    DATA_DIR / "Export_Output.txt",
    Path("D:/Download/geosptial/Export_Output.txt"),
)
SAMPLE_STRIDE: int = 60
MAX_CELLS: int = 5000
RES_FINE: int = 7
RES_COARSE: int = 5
SAMPLE_WARNING: str = (
    "Sampled cache for MVP smoke tests; not a continuous ROI H3 polyfill. "
    "Missing-looking polygons are expected until MVP-4 dense ROI construction."
)


def main() -> None:
    """Run MVP-2 sampled Nanjing GIS-to-H3 graph construction."""
    preprocessor = GISPreprocessor()
    dem, affine, _ = preprocessor.load_dem(str(DATA_DIR / "dem_nanjing.tif"))
    slope = preprocessor.compute_slope(dem, affine)
    tri = preprocessor.compute_tri(dem)
    landcover = preprocessor.load_landcover(str(DATA_DIR / "land_nanjing.tif"))
    soil = preprocessor.load_soil(str(DATA_DIR / "soil_nanjing.tif"))
    soil_catalog = preprocessor.load_soil_catalog(str(_first_existing(SOIL_CATALOG_CANDIDATES)))
    roads = preprocessor.load_road_network(str(DATA_DIR / "road_nanjing.shp"))

    builder = H3GridBuilder(
        res_fine=RES_FINE,
        res_coarse=RES_COARSE,
        sample_stride=SAMPLE_STRIDE,
        max_cells=MAX_CELLS,
    )
    h3_df = builder.raster_to_h3(dem, slope, tri, affine)
    h3_df = builder.attach_landcover(h3_df, landcover)
    h3_df = builder.attach_soil(h3_df, soil, soil_catalog)
    h3_df = builder.attach_roads(h3_df, roads)
    graph = builder.build_graph(h3_df)

    vehicle = VehicleProfile(
        name="mvp2_truck",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=8000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )
    assessed = TrafficabilityAssessor(
        vehicle=vehicle,
        weights={"slope": 0.30, "lc_factor": 0.25, "tri": 0.15, "soil": 0.15, "road_bonus": 0.15},
    ).assess(graph)
    h3_df = _copy_assessment_fields(h3_df, assessed)
    builder.save_parquet(h3_df, str(OUTPUT_PARQUET))
    _write_sample_manifest(OUTPUT_MANIFEST, assessed)
    print(
        " ".join(
            [
                f"cells={len(assessed.cells)}",
                f"edges={len(assessed.edges)}",
                f"output={OUTPUT_PARQUET}",
                f"manifest={OUTPUT_MANIFEST}",
            ]
        )
    )


def _first_existing(paths: tuple[Path, ...]) -> Path:
    """Return the first existing path from a small configured candidate list."""
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError("No soil catalog file found in configured paths.")


def _copy_assessment_fields(h3_df: pd.DataFrame, graph: H3Graph) -> pd.DataFrame:
    """Copy assessed graph cell fields back into a persisted H3 table."""
    frame = h3_df.copy()
    for column in (
        "cone_index_kpa",
        "cost_score",
        "is_passable",
        "score",
        "sinkage_m",
        "sinkage_resistance",
        "soil_mobility",
    ):
        frame[column] = [
            getattr(graph.cells[str(row.h3index)], column)
            for row in frame.itertuples()
        ]
    return frame


def _write_sample_manifest(path: Path, graph: H3Graph) -> None:
    GISExporter.write_manifest(str(path), _sample_manifest(graph))


def _sample_manifest(graph: H3Graph) -> dict[str, object]:
    return {
        "artifact_kind": "sampled_h3_graph",
        "cells_count": len(graph.cells),
        "coverage_mode": "sampled_dem_stride",
        "edges_count": len(graph.edges),
        "generator": "demo/run_mvp2_nanjing.py",
        "is_continuous_coverage": False,
        "max_cells": MAX_CELLS,
        "res_coarse": graph.resolution_coarse,
        "res_fine": graph.resolution_fine,
        "sample_stride": SAMPLE_STRIDE,
        "source_data_dir": str(DATA_DIR),
        "warning": SAMPLE_WARNING,
    }


if __name__ == "__main__":
    main()
