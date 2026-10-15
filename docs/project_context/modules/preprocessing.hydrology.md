# 模块参考：preprocessing.hydrology

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/preprocessing/hydrology.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`f43a5274f2d12347ed86ae43b193c9b69ded98385c1f449aba9d590397cee578`；类 2 个，函数/方法 11 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`cli`, `preprocessing`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# HydrologyConfig — src/h3_offroad_planner/preprocessing/hydrology.py:32
@dataclass(frozen=True)
class HydrologyConfig:
    'Frozen, region-independent GRASS/TWI processing policy.'
    backend: str = 'grass_r_watershed'
    flow_method: str = 'mfd'
    analysis_resolution_m: float | None = None
    mapping_t0: float | None = None
    mapping_t1: float | None = None
    upstream_complete: bool | None = None
    version: str = 'twi_drainage_v1'
    ...

# HydrologyArtifacts — src/h3_offroad_planner/preprocessing/hydrology.py:64
@dataclass(frozen=True)
class HydrologyArtifacts:
    'Paths produced by one immutable static hydrology run.'
    accumulation_path: str
    drainage_direction_path: str
    twi_path: str
    drainage_sensitivity_path: str | None
    validity_path: str
    boundary_influence_path: str
    manifest_path: str
    ...
```

校验 `HydrologyConfig.__post_init__`：

- `L44 if self.backend != 'grass_r_watershed'` → `raise ConfigError("hydrology backend must be 'grass_r_watershed'.")`
- `L46 if self.flow_method not in {'mfd', 'd8'}` → `raise ConfigError("hydrology flow_method must be 'mfd' or 'd8'.")`
- `L48 if self.analysis_resolution_m is not None and (not isfinite(self.analysis_resolution_m) or self.analysis_resolution_m <= 0.0)` → `raise ConfigError('analysis_resolution_m must be finite and positive.')`
- `L52 if (self.mapping_t0 is None) != (self.mapping_t1 is None)` → `raise ConfigError('mapping_t0 and mapping_t1 must be provided together.')`
- `L59 if not self.version` → `raise ConfigError('hydrology version must be non-empty.')`
- `L55 if not all((isfinite(value) for value in (self.mapping_t0, self.mapping_t1)))` → `raise ConfigError('TWI mapping thresholds must be finite.')`
- `L57 if self.mapping_t1 <= self.mapping_t0` → `raise ConfigError('mapping_t1 must be greater than mapping_t0.')`

```text
# L125 preprocess_hydrology
'accumulation' => output / 'accumulation.tif'
'drainage_direction' => output / 'drainage_direction.tif'
'twi' => output / 'twi.tif'
'drainage_sensitivity' => output / 'drainage_sensitivity.tif'
'validity' => output / 'drainage_validity.tif'
'boundary' => output / 'boundary_influence.tif'
'manifest' => output / 'hydrology_manifest.json'

# L313 _manifest_payload
'schema_version' => 1
'artifact_kind' => 'static_hydrology_cache'
'backend' => config.backend
'backend_executable' => executable
'config' => asdict(config)
'dem_path' => str(dem)
'dem_sha256' => _file_hash(dem)
'analysis_dem_path' => str(analysis_dem)
'analysis_dem_sha256' => _file_hash(analysis_dem)
'analysis_dem_crs' => _raster_crs(analysis_dem)
'outputs' => {key: str(path) for key, path in paths.items() if key != 'manifest' and path.exists()}
'boundary_influence' => 'complete_upstream_declared' if config.upstream_complete is True else 'potential_boundary_influence'
'drainage_mapping_status' => 'frozen' if config.mapping_t0 is not None else 'diagnostic_only'

# L301 _write_mask
'dtype' => 'uint8'
'nodata' => 255
'count' => 1

# L295 _write_masks_and_drainage
'dtype' => 'float32'
'nodata' => np.nan
'count' => 1
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from h3_offroad_planner.models import ConfigError, GISInputError

# HydrologyConfig — L32
@dataclass(frozen=True)
class HydrologyConfig:
    """Frozen, region-independent GRASS/TWI processing policy."""

    def __post_init__(self) -> None:
        ...

# HydrologyArtifacts — L64
@dataclass(frozen=True)
class HydrologyArtifacts:
    """Paths produced by one immutable static hydrology run."""

# map_twi_to_drainage — L76
def map_twi_to_drainage(twi: npt.NDArray[np.floating], valid: npt.NDArray[np.bool_], t0: float, t1: float) -> npt.NDArray[np.float32]:
    """Map valid TWI values to D in [0, 1], preserving invalid cells as NaN."""
    ...

# preprocess_hydrology — L93
def preprocess_hydrology(dem_path: str, output_dir: str, config: HydrologyConfig, *, grass_executable: str='grass') -> HydrologyArtifacts:
    """Run one offline GRASS r.watershed backend and persist TWI/D provenance."""
    ...

# _run_grass — L200
def _run_grass(command: list[str]) -> None:
    ...

# _require_metric_dem — L209
def _require_metric_dem(path: Path) -> None:
    ...

# _prepare_metric_dem — L220
def _prepare_metric_dem(source_path: Path, output_dir: Path, resolution_m: float | None) -> Path:
    """Return a meter-projected DEM, persisting an auditable reprojection when needed."""
    ...

# _write_masks_and_drainage — L277
def _write_masks_and_drainage(paths: dict[str, Path], config: HydrologyConfig) -> None:
    ...

# _write_mask — L300
def _write_mask(path: Path, values: npt.NDArray[np.bool_], profile: dict[str, object]) -> None:
    ...

# _manifest_payload — L306
def _manifest_payload(dem: Path, analysis_dem: Path, paths: dict[str, Path], config: HydrologyConfig, executable: str) -> dict[str, object]:
    ...

# _file_hash — L338
def _file_hash(path: Path) -> str:
    ...

# _raster_crs — L346
def _raster_crs(path: Path) -> str:
    ...
```
