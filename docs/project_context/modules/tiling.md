# 模块参考：tiling

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/tiling.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`2c8a3dadf05ca941458b53993728610d034466e538169660f6bddb41f11cbd47`；类 0 个，函数/方法 24 个（含嵌套定义）。
- 项目内导入依赖：`exporting`, `factor_model`, `grid`, `models`, `preprocessing`, `routing_index`。
- 直接导入本模块者：`cli`, `desktop_client`, `h3_offroad_planner`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# L39
TerrainLayers = tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64], Affine]

# L47
ProgressCallback = Callable[[str, int, str], None]
```

```python
# L35
CRS_WGS84: str = 'EPSG:4326'
# L36
TILE_MANIFEST_NAME: str = 'tile_manifest.json'
# L37
TILE_CACHE_KIND: str = 'tile_h3_cache'
# L38
TILE_COVERAGE_MODE: str = 'h3_polyfill_tile_cache'
```

```text
# L320 _tile_record
'bounds' => list(bounds)
'cells_count' => cells_count
'edges_count' => edges_count
'error' => error
'parent_h3' => tile_id
'path' => path
'static_input_hash' => static_hash
'statistics' => statistics or {}
'status' => status

# L405 _tile_manifest
'artifact_kind' => TILE_CACHE_KIND
'cells_count' => sum((_record_int(record, 'cells_count') for record in tile_records))
'coverage_mode' => TILE_COVERAGE_MODE
'dem_quality' => _quality_payload(dem_quality)
'edges_count' => sum((_record_int(record, 'edges_count') for record in tile_records))
'is_continuous_coverage' => True
'max_cells_per_tile' => request.max_cells_per_tile
'max_tiles' => request.max_tiles
'output_dir' => request.output_dir
'res_fine' => request.res_fine
'sampling_mode' => request.sampling_mode
'static_sources' => { 'dem' => request.dem_path; 'landcover' => request.landcover_path; 'road' => request.road_path; 'soil' => request.soil_path; 'soil_catalog' => request.soil_catalog_path; 'twi' => request.twi_path; 'drainage' => request.drainage_path; 'drainage_validity' => request.drainage_validity_path; 'drainage_boundary' => request.drainage_boundary_path }
'schema_version' => 2
'tile_fact_authority' => 'vehicle_independent'
'authority_for_new_routing' => { 'score' => False; 'cost_score' => False; 'sinkage_m' => False; 'is_passable' => 'physical_static_only' }
'static_input_hash' => canonical_hash([record.get('static_input_hash') for record in tile_records if record.get('static_input_hash') is not None])
'status_counts' => dict(statuses)
'tile_res' => request.tile_res
'tiles' => tile_records

# L451 _quality_payload
'crs' => quality.crs
'finite_max' => quality.finite_max
'finite_min' => quality.finite_min
'height' => quality.height
'nodata_ratio' => quality.nodata_ratio
'width' => quality.width

# L381 _static_statistics
'q50' => float(values.quantile(0.5))
'q90' => float(values.quantile(0.9))
'missing_ratio' => float(values.isna().mean())
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import cast
import geopandas as gpd
import h3
import numpy as np
import numpy.typing as npt
import pandas as pd
from affine import Affine
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from h3_offroad_planner.exporting import GISExporter
from h3_offroad_planner.factor_model import canonical_hash, static_input_hash
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GISInputError, GridBuildError, H3Graph, SoilProfile, TileBuildRequest
from h3_offroad_planner.preprocessing import GISPreprocessor, RasterLayer, RasterQuality
from h3_offroad_planner.routing_index import build_routing_index

# build_h3_tile_cache — L50
def build_h3_tile_cache(request: TileBuildRequest, progress: ProgressCallback | None=None, progress_range: tuple[int, int]=(10, 50)) -> dict[str, object]:
    """Build a resumable H3 tile cache from raw GIS inputs.

    Args:
        request: Valid tile build request. Unit: file paths and H3 resolutions.
        progress: Optional callback for real-time tile build status updates.
        progress_range: Bounded percentage interval (start, end) for progress mapping.

    Returns:
        JSON-serializable tile manifest.

    Raises:
        FileNotFoundError: If any required source path is missing.
        GridBuildError: If ROI tiling exceeds limits or a tile fails while
            `continue_on_error=False`.
        GISInputError: If GIS source layers cannot be read.
    """
    ...

# _load_roi_geometry — L127
def _load_roi_geometry(path: str) -> BaseGeometry:
    ...

# _tile_ids_for_roi — L145
def _tile_ids_for_roi(roi_geometry: BaseGeometry, tile_res: int, max_tiles: int) -> list[str]:
    ...

# _build_tile_record — L161
def _build_tile_record(request: TileBuildRequest, tile_id: str, roi_geometry: BaseGeometry, terrain: TerrainLayers, landcover: RasterLayer | gpd.GeoDataFrame, soil: RasterLayer | None, soil_catalog: dict[int, SoilProfile], roads: gpd.GeoDataFrame | None, drainage: RasterLayer | None, twi: RasterLayer | None, drainage_validity: RasterLayer | None, drainage_boundary: RasterLayer | None) -> dict[str, object]:
    ...

# _completed_tile_record — L203
def _completed_tile_record(request: TileBuildRequest, tile_id: str, roi_geometry: BaseGeometry, terrain: TerrainLayers, landcover: RasterLayer | gpd.GeoDataFrame, soil: RasterLayer | None, soil_catalog: dict[int, SoilProfile], roads: gpd.GeoDataFrame | None, drainage: RasterLayer | None, twi: RasterLayer | None, drainage_validity: RasterLayer | None, drainage_boundary: RasterLayer | None, output_path: Path) -> dict[str, object]:
    ...

# _skipped_tile_record — L252
def _skipped_tile_record(request: TileBuildRequest, tile_id: str, output_path: Path) -> dict[str, object]:
    ...

# _failed_tile_record — L275
def _failed_tile_record(tile_id: str, error: str) -> dict[str, object]:
    ...

# _empty_tile_record — L287
def _empty_tile_record(tile_id: str, error: str) -> dict[str, object]:
    ...

# _is_empty_tile_error — L299
def _is_empty_tile_error(exc: GridBuildError) -> bool:
    ...

# _tile_record — L309
def _tile_record(tile_id: str, status: str, path: str | None, cells_count: int, edges_count: int, bounds: tuple[float, float, float, float], error: str | None=None, static_hash: str | None=None, statistics: dict[str, object] | None=None) -> dict[str, object]:
    ...

# _bounds_tuple — L333
def _bounds_tuple(bounds: tuple[float, ...]) -> tuple[float, float, float, float]:
    ...

# _static_fact_frame — L339
def _static_fact_frame(h3_df: pd.DataFrame, graph: H3Graph, sampling_mode: str, static_hash: str) -> pd.DataFrame:
    """Return vehicle-neutral facts with explicit exact adjacency metadata."""
    ...

# _mean_edge_length — L372
def _mean_edge_length(neighbors: dict[str, float]) -> float | None:
    ...

# _static_statistics — L376
def _static_statistics(frame: pd.DataFrame) -> dict[str, object]:
    """Return deterministic robust statistics and missing ratios for one Tile."""
    ...

# _tile_manifest — L399
def _tile_manifest(request: TileBuildRequest, tile_records: list[dict[str, object]], dem_quality: RasterQuality) -> dict[str, object]:
    ...

# _quality_payload — L449
def _quality_payload(quality: RasterQuality) -> dict[str, object]:
    """Return JSON-safe quality fields without coupling manifests to raster classes."""
    ...

# _record_int — L461
def _record_int(record: dict[str, object], key: str) -> int:
    ...

# _load_soil_catalog — L470
def _load_soil_catalog(preprocessor: GISPreprocessor, request: TileBuildRequest) -> dict[int, SoilProfile]:
    ...

# _tile_output_path — L479
def _tile_output_path(output_dir: str, tile_res: int, tile_id: str) -> Path:
    ...

# _polygon_cells — L483
def _polygon_cells(roi_geometry: BaseGeometry, resolution: int) -> set[str]:
    ...

# _single_polygon_cells — L494
def _single_polygon_cells(polygon: Polygon, resolution: int) -> set[str]:
    ...

# _boundary_tile_candidates — L500
def _boundary_tile_candidates(roi_geometry: BaseGeometry, tile_res: int) -> set[str]:
    ...

# _geometry_sample_points — L508
def _geometry_sample_points(geometry: BaseGeometry) -> list[tuple[float, float]]:
    ...

# _h3_polygon — L519
def _h3_polygon(h3index: str) -> Polygon:
    ...
```
