# 模块参考：preprocessing.gis_preprocessor

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/preprocessing/gis_preprocessor.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`4a76b584fed242e3f793cba3658e15c61663a637af6489c5cfaae08d77c1697f`；类 3 个，函数/方法 22 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`preprocessing`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# RasterLayer — src/h3_offroad_planner/preprocessing/gis_preprocessor.py:70
@dataclass(frozen=True)
class RasterLayer:
    'Lazy raster descriptor used for large GIS layers.\n\n    Attributes:\n        path: Raster file path. Unit: filesystem path.\n        crs: Coordinate reference system string.\n        width: Raster width. Unit: pixels.\n        height: Raster height. Unit: pixels.\n        bounds: Raster bounds as `(left, bottom, right, top)`.\n        nodata: Optional nodata value.\n        dtype: First-band data type.\n    '
    path: Path
    crs: str
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    nodata: float | None
    dtype: str
    ...

# RasterQuality — src/h3_offroad_planner/preprocessing/gis_preprocessor.py:93
@dataclass(frozen=True)
class RasterQuality:
    'Finite-value and metadata summary for one raster source.'
    crs: str
    finite_max: float | None
    finite_min: float | None
    height: int
    nodata_ratio: float
    width: int
    ...

# GISPreprocessor — src/h3_offroad_planner/preprocessing/gis_preprocessor.py:104
class GISPreprocessor:
    'Load and normalize GIS sources for the H3 graph builder.'
    # self.target_crs: 未注解; L111; initial=target_crs
    ...
```

```python
# L25
DEGREES_TO_METERS: float = 111320.0
# L26
TARGET_CRS: str = 'EPSG:4326'
# L27
WATER_SOIL_CODES: frozenset[int] = frozenset({18, 85})
# L28
URBAN_SOIL_CODES: frozenset[int] = frozenset({84})
# L29
PADDY_SOIL_CODES: frozenset[int] = frozenset({44, 55, 64, 80, 82, 90})
# L30
ALLUVIAL_SOIL_CODES: frozenset[int] = frozenset({26, 27, 72})
# L31
BROWN_RED_SOIL_CODES: frozenset[int] = frozenset({14, 22, 48, 49, 50, 58, 73, 74, 92, 184})
# L32
LITHIC_SOIL_CODES: frozenset[int] = frozenset({38, 47, 53, 96})
# L33
MARSH_SOIL_CODES: frozenset[int] = frozenset({17})
# L38
SOIL_USCS_OVERRIDES: dict[int, tuple[str | None, str | None, str | None, bool]] = {14: ('Lo', 'CL', 'loam', True), 17: (None, None, None, False), 18: (None, None, None, False), 22: ('Lo', 'CL', 'loam', True), 26: ('SiLo', 'ML', 'loam', True), 27: ('SiLo', 'ML', 'loam', True), 38: ('Lo', 'CL', 'loam', True), 44: ('ClLo', 'CL', 'clayloam', True), 47: ('Lo', 'CL', 'loam', True), 48: ('Lo', 'CL', 'loam', True), 49: ('Lo', 'CL', 'loam', True), 50: ('ClLo', 'CL', 'clayloam', True), 53: ('Lo', 'CL', 'loam', True), 55: ('ClLo', 'CL', 'clayloam', True), 58: ('Lo', 'CL', 'loam', True), 64: ('ClLo', 'CL', 'clayloam', True), 72: ('SiLo', 'ML', 'loam', True), 73: ('ClLo', 'CL', 'clayloam', True), 74: ('ClLo', 'CL', 'clayloam', True), 80: ('ClLo', 'CL', 'clayloam', True), 82: ('ClLo', 'CL', 'clayloam', True), 84: (None, None, None, False), 85: (None, None, None, False), 90: ('ClLo', 'CL', 'clayloam', True), 92: ('ClLo', 'CL', 'clayloam', True), 96: ('Lo', 'CL', 'loam', True), 184: ('Lo', 'CL', 'loam', True)}
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import csv
from dataclasses import dataclass
from math import cos, radians
from pathlib import Path
from typing import cast
import geopandas as gpd
import numpy as np
import numpy.typing as npt
import pandas as pd
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from h3_offroad_planner.models import GISInputError, SoilProfile

# RasterLayer — L70
@dataclass(frozen=True)
class RasterLayer:
    """Lazy raster descriptor used for large GIS layers.

    Attributes:
        path: Raster file path. Unit: filesystem path.
        crs: Coordinate reference system string.
        width: Raster width. Unit: pixels.
        height: Raster height. Unit: pixels.
        bounds: Raster bounds as `(left, bottom, right, top)`.
        nodata: Optional nodata value.
        dtype: First-band data type.
    """

# RasterQuality — L93
@dataclass(frozen=True)
class RasterQuality:
    """Finite-value and metadata summary for one raster source."""

# GISPreprocessor — L104
class GISPreprocessor:
    """Load and normalize GIS sources for the H3 graph builder."""

    def __init__(self, target_crs: str=TARGET_CRS) -> None:
        """Initialize the preprocessor with a target CRS string."""
        ...

    def load_dem(self, path: str) -> tuple[npt.NDArray[np.float64], Affine, CRS]:
        """Load a DEM raster into memory and normalize it to the target CRS."""
        ...

    def inspect_raster(self, path: str) -> RasterQuality:
        """Summarize raster CRS, dimensions, finite range, and nodata ratio."""
        ...

    def load_landcover(self, path: str) -> RasterLayer | gpd.GeoDataFrame:
        """Load landcover as a lazy raster layer or WGS84 vector GeoDataFrame.

        Args:
            path: Raster file path, single vector file path, or directory containing shapefiles.
                Unit: filesystem path. Must exist.

        Returns:
            RasterLayer for TIF rasters or GeoDataFrame for normalized WGS84 vectors.

        Raises:
            FileNotFoundError: If the path does not exist.
            GISInputError: If vectors have no CRS or directory contains no vector files.
        """
        ...

    def load_soil(self, path: str | None) -> RasterLayer | None:
        """Load optional soil raster metadata without reading the full raster."""
        ...

    def load_soil_catalog(self, path: str) -> dict[int, SoilProfile]:
        """Load raw categorical soil codes and names without engineering inference."""
        ...

    def load_road_network(self, path: str | None) -> gpd.GeoDataFrame | None:
        """Load optional road network vectors into the target CRS."""
        ...

    def compute_slope(self, dem: npt.NDArray[np.float64], affine: Affine) -> npt.NDArray[np.float64]:
        """Compute slope in degrees from a DEM matrix."""
        ...

    def compute_tri(self, dem: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Compute terrain ruggedness index as mean absolute neighbor difference."""
        ...

    def _raster_layer(self, path: Path) -> RasterLayer:
        ...

    def _vector_layer(self, path: Path) -> gpd.GeoDataFrame:
        ...

    def _vector_directory(self, path: Path) -> gpd.GeoDataFrame:
        ...

    def _reproject_dem(self, data: npt.NDArray[np.float64], src: rasterio.io.DatasetReader, path: str) -> tuple[npt.NDArray[np.float64], Affine, CRS]:
        ...

# _require_existing_path — L299
def _require_existing_path(path: str) -> Path:
    ...

# _read_soil_catalog_rows — L306
def _read_soil_catalog_rows(path: Path) -> list[dict[str, str]]:
    ...

# _parse_soil_catalog_row — L318
def _parse_soil_catalog_row(row: dict[str, str]) -> tuple[int, str]:
    ...

# _profile_from_soil_code — L329
def _profile_from_soil_code(code: int, name_zh: str) -> SoilProfile:
    """Create a SoilProfile with a provisional engineering USCS inference.

    The mapping uses an explicit Nanjing soil-code table first, then falls back
    to soil-name keyword heuristics for regions where only soil type names are
    available.  It is not a substitute for laboratory or field classification.
    """
    ...

# _read_dbf_rows — L348
def _read_dbf_rows(path: Path) -> list[dict[str, str]]:
    """Read the small categorical DBF table, including UTF-8 field names."""
    ...

# _soil_texture_mapping — L398
def _soil_texture_mapping(code: int, name_zh: str) -> tuple[str | None, str | None, str | None, bool]:
    """Map soil code/name to provisional USCS, texture, Bekker group, passability.

    Priority:
    1. Explicit Nanjing soil-code table.
    2. Keyword fallback from Chinese soil type name.
    3. Conservative default: loam/CL.
    """
    ...

# _require_non_empty_matrix — L443
def _require_non_empty_matrix(name: str, matrix: npt.NDArray[np.float64]) -> None:
    ...

# _center_latitude — L448
def _center_latitude(matrix: npt.NDArray[np.float64], affine: Affine) -> float:
    ...

# _accumulate_neighbor_difference — L453
def _accumulate_neighbor_difference(dem: npt.NDArray[np.float64], tri_sum: npt.NDArray[np.float64], counts: npt.NDArray[np.float64], dy: int, dx: int) -> None:
    ...
```
