# 模块参考：grid.h3_grid_builder

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/grid/h3_grid_builder.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`7f3ea6e498a4d6f1aa4cd34caa4e8cafb1ad2e367aa5fc06845fc271af371306`；类 2 个，函数/方法 68 个（含嵌套定义）。
- 项目内导入依赖：`models`, `preprocessing`。
- 直接导入本模块者：`grid`, `route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# _SpatialIndex — src/h3_offroad_planner/grid/h3_grid_builder.py:92
class _SpatialIndex(Protocol):
    ...

# H3GridBuilder — src/h3_offroad_planner/grid/h3_grid_builder.py:97
class H3GridBuilder:
    'Build sampled or ROI-continuous H3 graphs from normalized GIS layers.'
    COMPACT: bool = False
    # self.res_fine: 未注解; L123; initial=res_fine
    # self.res_coarse: 未注解; L124; initial=res_coarse
    # self.sample_stride: 未注解; L125; initial=sample_stride
    # self.max_cells: 未注解; L126; initial=max_cells
    # self.road_buffer_deg: 未注解; L127; initial=road_buffer_deg
    # self.land_cover_factors: 未注解; L128; initial=_landcover_factors(land_cover_factors)
    # self.default_landcover_factor: 未注解; L129; initial=default_landcover_factor
    ...
```

```python
# L28
EARTH_RADIUS_M: float = 6371000.0
# L29
DEFAULT_ROAD_BUFFER_DEG: float = 0.001
# L30
AREA_DOMINANCE_MAX_PIXELS: int = 250000
# L31
LOGGER = logging.getLogger(__name__)
# L32
CRS_WGS84: str = 'EPSG:4326'
# L33
LANDCOVER_CODE_COLUMNS: tuple[str, ...] = ('fclass', 'FCLASS', 'landcover_code', 'lc_code', 'code', 'value', 'DN', 'gridcode', 'type', 'Type')
# L45
FCLASS_CODE_MAPPING: dict[str, int] = {'water': 5, '01': 5, 'forest': 2, '02': 2, 'grass': 3, 'grassland': 3, '03': 3, 'plowland': 1, 'cropland': 1, '04': 1, 'shrubwood': 4, 'shrubland': 4, '05': 4, 'building': 6, '06': 6, 'wasteland': 7, 'barren': 7, '07': 7, 'road': 8}
# L66
LAND_COVER_FACTORS: dict[int, float] = {0: inf, 1: 1.2, 2: 1.35, 3: 1.3, 4: 1.1, 5: inf, 6: inf, 7: 1.5, 8: 0.85, 9: 1.6}
# L78
LAND_COVER_TYPES: dict[int, str] = {0: 'unclassified', 1: 'cropland', 2: 'forest', 3: 'grassland', 4: 'shrubland', 5: 'water', 6: 'building', 7: 'barren', 8: 'impervious', 9: 'other'}
```

```text
# L45 <module>
'water' => 5
'01' => 5
'forest' => 2
'02' => 2
'grass' => 3
'grassland' => 3
'03' => 3
'plowland' => 1
'cropland' => 1
'04' => 1
'shrubwood' => 4
'shrubland' => 4
'05' => 4
'building' => 6
'06' => 6
'wasteland' => 7
'barren' => 7
'07' => 7
'road' => 8

# L479 _require_h3_frame
'soil_source' => None
'source_support_m' => None
'twi' => None
'drainage_sensitivity' => None
'drainage_valid' => False
'drainage_boundary_affected' => False
'surface_response' => None
'surface_evidence' => None

# L393 H3GridBuilder._record_from_pixel
'h3index' => str(cell_id)
'lat' => float(lat)
'lng' => float(lng)
'elevation' => elevation
'slope' => slope_value
'tri' => tri_value
'parent_h3' => str(h3.cell_to_parent(cell_id, self.res_coarse))

# L422 H3GridBuilder._record_from_cell_center
'elevation' => elevation
'h3index' => str(cell_id)
'lat' => float(lat)
'lng' => float(lng)
'parent_h3' => str(h3.cell_to_parent(cell_id, self.res_coarse))
'slope' => slope_value
'tri' => tri_value
```

```text
L560: frame['landcover_code'] <- codes
L561: frame['landcover_type'] <- types
L562: frame['lc_factor'] <- lc_factors
L563: frame['is_passable'] <- passable
L564: frame['depth'] <- depths
L565: frame['rowspacing'] <- rowspacings
L670: grouped['lc_factor'] <- 1.0
L671: grouped['landcover_code'] <- None
L672: grouped['landcover_type'] <- None
L673: grouped['soil_code'] <- None
L674: grouped['soil_type'] <- None
L675: grouped['soil_texture'] <- None
L676: grouped['uscs'] <- None
L677: grouped['soil_moisture'] <- None
L678: grouped['soil_source'] <- None
L679: grouped['source_support_m'] <- None
L680: grouped['twi'] <- None
L681: grouped['drainage_sensitivity'] <- None
L682: grouped['drainage_valid'] <- False
L683: grouped['drainage_boundary_affected'] <- False
L684: grouped['surface_response'] <- None
L685: grouped['surface_evidence'] <- None
L686: grouped['has_road'] <- False
L687: grouped['is_passable'] <- True
L688: grouped['score'] <- 0.0
L689: grouped['cost_score'] <- 1.0
L839: frame['soil_source'] <- None
L840: frame['source_support_m'] <- None
L849: frame['soil_code'] <- codes
L850: frame['soil_type'] <- [_soil_name(code, soil_catalog) for code in codes]
L851: frame['soil_texture'] <- [_soil_attr(code, soil_catalog, 'soil_texture') for code in codes]
L852: frame['uscs'] <- [_soil_attr(code, soil_catalog, 'uscs') for code in codes]
L853: frame['soil_moisture'] <- [_soil_moisture(code, soil_catalog) for code in codes]
L854: frame['is_passable'] <- [bool(frame.iloc[index].is_passable) and _soil_passable(code, soil_catalog) for index, code in enumerate(codes)]
L1118: frame['surface_response'] <- responses
L1119: frame['surface_evidence'] <- evidence
L249: frame['soil_source'] <- str(soil.path)
L250: frame['source_support_m'] <- _raster_support_m(soil, frame)
L292: frame['twi'] <- twi_output
L293: frame['drainage_sensitivity'] <- sensitivities
L294: frame['drainage_valid'] <- valid_output
L295: frame['drainage_boundary_affected'] <- [bool(isfinite(value) and value > 0.0) for value in boundary_values]
L312: frame['has_road'] <- [_point_near_road(Point(row.lng, row.lat), roads_wgs84, spatial_index, self.road_buffer_deg) for row in frame.itertuples(index=False)]
L464: frame['has_road'] <- False
L466: frame['is_passable'] <- True
L468: frame['landcover_code'] <- None
L470: frame['landcover_type'] <- None
L472: frame['depth'] <- None
L474: frame['rowspacing'] <- None
L476: frame['score'] <- 0.0
L478: frame['cost_score'] <- 1.0 - frame['score'].astype(float)
L220: frame['landcover_code'] <- codes
L221: frame['landcover_type'] <- [_landcover_type(code) for code in codes]
L222: frame['lc_factor'] <- factors
L223: frame['is_passable'] <- [bool(row.is_passable) and factor != inf for row, factor in zip(frame.itertuples(index=False), factors, strict=True)]
L304: frame['has_road'] <- False
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import logging
from math import asin, atan2, cos, degrees, inf, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import Any, Protocol, cast
import geopandas as gpd
import h3
import numpy as np
import numpy.typing as npt
import pandas as pd
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as transform_coordinates
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from h3_offroad_planner.models import GridBuildError, H3Cell, H3Edge, H3Graph, SoilProfile
from h3_offroad_planner.preprocessing import RasterLayer

# _SpatialIndex — L92
class _SpatialIndex(Protocol):

    def query(self, geometry: object, predicate: str | None=None) -> npt.NDArray[np.intp]:
        """Return spatial index matches for a geometry."""
        ...

# H3GridBuilder — L97
class H3GridBuilder:
    """Build sampled or ROI-continuous H3 graphs from normalized GIS layers."""

    def __init__(self, res_fine: int=14, res_coarse: int=11, sample_stride: int=1, max_cells: int | None=None, road_buffer_deg: float=DEFAULT_ROAD_BUFFER_DEG, land_cover_factors: dict[int, float] | None=None, default_landcover_factor: float=1.4) -> None:
        """Initialize a sampled H3 grid builder."""
        ...

    def raster_to_h3(self, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine) -> pd.DataFrame:
        """Convert sampled DEM-derived matrices into a fine-resolution H3 table."""
        ...

    def roi_to_h3(self, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine, roi_geometry: BaseGeometry, *, allow_uncovered: bool=False) -> pd.DataFrame:
        """Convert a WGS84 ROI polygon into a continuous fine-resolution H3 table."""
        ...

    def tile_to_h3(self, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine, tile_id: str, roi_geometry: BaseGeometry | None=None) -> pd.DataFrame:
        """Convert a parent H3 tile into a fine-resolution H3 table using exact hierarchy."""
        ...

    def attach_landcover(self, h3_df: pd.DataFrame, landcover: RasterLayer | gpd.GeoDataFrame) -> pd.DataFrame:
        """Attach landcover resistance factors to an H3 table."""
        ...

    def attach_soil(self, h3_df: pd.DataFrame, soil: RasterLayer | None, soil_catalog: dict[int, SoilProfile] | None=None) -> pd.DataFrame:
        """Attach optional soil type codes to an H3 table."""
        ...

    def attach_drainage(self, h3_df: pd.DataFrame, drainage: RasterLayer | None, twi: RasterLayer | None=None, validity: RasterLayer | None=None, boundary: RasterLayer | None=None) -> pd.DataFrame:
        """Attach cached static TWI/D evidence without a request pressure scenario."""
        ...

    def attach_roads(self, h3_df: pd.DataFrame, roads: gpd.GeoDataFrame | None) -> pd.DataFrame:
        """Mark sampled cells that intersect a road proximity buffer."""
        ...

    def build_graph(self, h3_df: pd.DataFrame) -> H3Graph:
        """Build an H3Graph with directional-slope edges from an H3 table."""
        ...

    def save_parquet(self, h3_df: pd.DataFrame, path: str) -> None:
        """Persist an H3 table as Parquet."""
        ...

    def load_parquet(self, path: str) -> pd.DataFrame:
        """Load and validate an H3 table from a Parquet cache."""
        ...

    def load_graph(self, path: str) -> H3Graph:
        """Load a persisted H3 table and rebuild an in-memory graph."""
        ...

    def _sample_dem_records(self, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine) -> list[dict[str, float | str]]:
        ...

    def _record_from_pixel(self, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine, row: int, col: int) -> dict[str, float | str] | None:
        ...

    def _record_from_cell_center(self, cell_id: str, dem: npt.NDArray[np.float64], slope: npt.NDArray[np.float64], tri: npt.NDArray[np.float64], affine: Affine) -> dict[str, float | str] | None:
        ...

    def _edges_from_cells(self, cells: dict[str, H3Cell]) -> dict[tuple[str, str], H3Edge]:
        ...

# _require_h3_frame — L446
def _require_h3_frame(h3_df: pd.DataFrame) -> pd.DataFrame:
    ...

# _landcover_factors — L495
def _landcover_factors(overrides: dict[int, float] | None) -> dict[int, float]:
    ...

# _valid_landcover_factor — L508
def _valid_landcover_factor(value: float) -> bool:
    ...

# _attach_vector_landcover — L515
def _attach_vector_landcover(frame: pd.DataFrame, landcover: gpd.GeoDataFrame, factors: dict[int, float], default_factor: float) -> pd.DataFrame:
    ...

# _dominant_vector_landcover_code — L569
def _dominant_vector_landcover_code(h3index: str, landcover: gpd.GeoDataFrame, spatial_index: _SpatialIndex) -> int | None:
    ...

# _dominant_vector_landcover_details — L578
def _dominant_vector_landcover_details(h3index: str, landcover: gpd.GeoDataFrame, spatial_index: _SpatialIndex) -> tuple[int | None, float | None, float | None]:
    ...

# _feature_geometry — L630
def _feature_geometry(feature: pd.Series) -> BaseGeometry | None:
    ...

# _feature_landcover_code — L635
def _feature_landcover_code(feature: pd.Series) -> int | None:
    ...

# _h3_frame_from_records — L660
def _h3_frame_from_records(records: list[dict[str, float | str]]) -> pd.DataFrame:
    ...

# _roi_polyfill_cells — L693
def _roi_polyfill_cells(roi_geometry: BaseGeometry, resolution: int, max_cells: int | None) -> list[str]:
    ...

# _polygon_cells — L711
def _polygon_cells(roi_geometry: BaseGeometry, resolution: int) -> set[str]:
    ...

# _single_polygon_cells — L722
def _single_polygon_cells(polygon: Polygon, resolution: int) -> set[str]:
    ...

# _estimate_roi_cell_count — L728
def _estimate_roi_cell_count(geometry: BaseGeometry, resolution: int) -> int:
    ...

# _approx_wgs84_area_m2 — L734
def _approx_wgs84_area_m2(geometry: BaseGeometry) -> float:
    ...

# _oversize_roi_message — L741
def _oversize_roi_message(cell_count: int, max_cells: int) -> str:
    ...

# _sample_raster_values — L748
def _sample_raster_values(layer: RasterLayer, frame: pd.DataFrame) -> list[float]:
    ...

# _dominant_soil_codes_or_fallback — L758
def _dominant_soil_codes_or_fallback(layer: RasterLayer, frame: pd.DataFrame) -> list[int | None]:
    ...

# _dominant_soil_codes — L771
def _dominant_soil_codes(layer: RasterLayer, frame: pd.DataFrame) -> list[int | None]:
    ...

# _bounded_window — L787
def _bounded_window(src: rasterio.io.DatasetReader, bounds: tuple[float, float, float, float]) -> Window:
    ...

# _dominant_code_in_window — L799
def _dominant_code_in_window(array: np.ma.MaskedArray, transform: Affine, cell_polygon: Polygon) -> int | None:
    ...

# _pixel_intersection_area — L820
def _pixel_intersection_area(transform: Affine, row: int, col: int, cell_polygon: Polygon) -> float:
    ...

# _h3_polygon — L832
def _h3_polygon(h3index: str) -> Polygon:
    ...

# _attach_empty_soil_columns — L836
def _attach_empty_soil_columns(frame: pd.DataFrame) -> pd.DataFrame:
    ...

# _apply_soil_catalog — L844
def _apply_soil_catalog(frame: pd.DataFrame, codes: list[int | None], soil_catalog: dict[int, SoilProfile]) -> pd.DataFrame:
    ...

# _soil_name — L861
def _soil_name(code: int | None, catalog: dict[int, SoilProfile]) -> str | None:
    ...

# _soil_attr — L868
def _soil_attr(code: int | None, catalog: dict[int, SoilProfile], attr_name: str) -> str | None:
    ...

# _soil_moisture — L878
def _soil_moisture(code: int | None, catalog: dict[int, SoilProfile]) -> float | None:
    ...

# _soil_passable — L884
def _soil_passable(code: int | None, catalog: dict[int, SoilProfile]) -> bool:
    ...

# _to_int — L890
def _to_int(value: float) -> int:
    ...

# _is_nodata — L896
def _is_nodata(value: float, nodata: float | None) -> bool:
    ...

# _landcover_code — L900
def _landcover_code(value: float, nodata: float | None) -> int | None:
    ...

# _landcover_factor_for_code — L904
def _landcover_factor_for_code(code: int | None, factors: dict[int, float], default_factor: float) -> float:
    ...

# _landcover_type — L912
def _landcover_type(code: int | None) -> str | None:
    ...

# _point_near_road — L918
def _point_near_road(point: Point, roads: gpd.GeoDataFrame, spatial_index: _SpatialIndex, buffer_deg: float) -> bool:
    ...

# _cells_from_frame — L930
def _cells_from_frame(frame: pd.DataFrame) -> dict[str, H3Cell]:
    ...

# _cells_from_frame.col_list — L935
def col_list(c: str, default: object=None) -> list[object]:
    ...

# _cells_from_frame.opt_f — L972
def opt_f(val: object) -> float | None:
    ...

# _cells_from_frame.opt_s — L975
def opt_s(val: object) -> str | None:
    ...

# _cells_from_frame.opt_i — L978
def opt_i(val: object) -> int | None:
    ...

# _optional_str — L1028
def _optional_str(value: object) -> str | None:
    ...

# _optional_int — L1032
def _optional_int(value: object) -> int | None:
    ...

# _optional_float — L1040
def _optional_float(value: object) -> float | None:
    ...

# _row_float — L1048
def _row_float(row: object, name: str) -> float:
    ...

# _required_float — L1052
def _required_float(name: str, value: object) -> float:
    ...

# _is_missing — L1060
def _is_missing(value: object) -> bool:
    ...

# _parent_children — L1066
def _parent_children(cells: dict[str, H3Cell]) -> dict[str, set[str]]:
    ...

# _safe_neighbors — L1073
def _safe_neighbors(h3index: str) -> list[str]:
    ...

# _edge_from_cells — L1082
def _edge_from_cells(cell: H3Cell, neighbor: H3Cell, distance_m: float) -> H3Edge:
    ...

# _haversine_m — L1095
def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    ...

# _attach_surface_response — L1104
def _attach_surface_response(frame: pd.DataFrame) -> pd.DataFrame:
    ...

# _raster_support_m — L1123
def _raster_support_m(layer: RasterLayer, frame: pd.DataFrame) -> float:
    ...
```
