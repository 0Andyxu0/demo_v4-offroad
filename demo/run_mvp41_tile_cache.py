"""Build a bounded tile cache from raw GIS inputs for MVP-4.1."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from affine import Affine
from shapely.geometry import Polygon, box

from h3_offroad_planner.models import TileBuildRequest
from h3_offroad_planner.preprocessing import GISPreprocessor
from h3_offroad_planner.tiling import build_h3_tile_cache

DATA_DIR: Path = Path("data")
DEFAULT_OUTPUT_DIR: Path = Path("outputs/mvp41")
DEFAULT_ROI_NAME: str = "mvp41_tile_roi.geojson"
SOIL_CATALOG_CANDIDATES: tuple[Path, ...] = (
    DATA_DIR / "Export_Output.txt",
    Path("D:/Download/geosptial/Export_Output.txt"),
)
RES_FINE: int = 9
TILE_RES: int = 7
MAX_TILES: int = 80
MAX_CELLS_PER_TILE: int = 500
DEFAULT_ROI_HALF_SIZE_DEG: float = 0.02


def run_tile_cache_build(
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
    res_fine: int = RES_FINE,
    tile_res: int = TILE_RES,
    max_tiles: int = MAX_TILES,
    max_cells_per_tile: int = MAX_CELLS_PER_TILE,
    roi_layer_path: str | None = None,
) -> dict[str, object]:
    """Build a small real-data tile cache smoke artifact.

    The public API defaults remain production-oriented (`res13/res10`). This demo keeps
    resolutions lower so local verification can finish quickly while exercising the same
    parent-tile cache layout and manifest semantics.
    """
    output_root = Path(output_dir)
    roi_path = (
        Path(roi_layer_path)
        if roi_layer_path is not None
        else output_root / DEFAULT_ROI_NAME
    )
    if roi_layer_path is None:
        _write_default_roi(roi_path)
    soil_path = _optional_path(DATA_DIR / "soil_nanjing.tif")
    soil_catalog_path = _first_existing(SOIL_CATALOG_CANDIDATES)
    if soil_catalog_path is None:
        soil_path = None
    road_path = _optional_path(DATA_DIR / "road_nanjing.shp")
    request = TileBuildRequest(
        dem_path=str(DATA_DIR / "dem_nanjing.tif"),
        landcover_path=str(DATA_DIR / "land_nanjing.tif"),
        roi_layer_path=str(roi_path),
        output_dir=str(output_root),
        soil_path=str(soil_path) if soil_path is not None else None,
        soil_catalog_path=str(soil_catalog_path) if soil_catalog_path is not None else None,
        road_path=str(road_path) if road_path is not None else None,
        res_fine=res_fine,
        tile_res=tile_res,
        max_tiles=max_tiles,
        max_cells_per_tile=max_cells_per_tile,
    )
    return build_h3_tile_cache(request)


def _write_default_roi(path: Path) -> None:
    preprocessor = GISPreprocessor()
    dem, affine, _ = preprocessor.load_dem(str(DATA_DIR / "dem_nanjing.tif"))
    geometry = _center_roi(dem.shape, affine)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame({"name": ["mvp41_tile_roi"]}, geometry=[geometry], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def _center_roi(shape: tuple[int, int], affine: Affine) -> Polygon:
    center_lng, center_lat = affine * (shape[1] / 2.0, shape[0] / 2.0)
    return box(
        center_lng - DEFAULT_ROI_HALF_SIZE_DEG,
        center_lat - DEFAULT_ROI_HALF_SIZE_DEG,
        center_lng + DEFAULT_ROI_HALF_SIZE_DEG,
        center_lat + DEFAULT_ROI_HALF_SIZE_DEG,
    )


def _optional_path(path: Path) -> Path | None:
    return path if path.exists() else None


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def main() -> None:
    """Run the default bounded MVP-4.1 tile cache build."""
    manifest = run_tile_cache_build()
    status_counts = manifest["status_counts"]
    print(
        " ".join(
            [
                f"tiles={len(manifest['tiles'])}",
                f"cells={manifest['cells_count']}",
                f"edges={manifest['edges_count']}",
                f"status={status_counts}",
                f"output_dir={manifest['output_dir']}",
            ]
        )
    )


if __name__ == "__main__":
    main()
