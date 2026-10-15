# 模块参考：routing_index

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/routing_index.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`6133f9535110368e77998774ee5854ef48383e18ab52ffcc370ddd94786ec0af`；类 1 个，函数/方法 34 个（含嵌套定义）。
- 项目内导入依赖：`config`, `factor_model`, `grid`, `models`, `offline_pairs`。
- 直接导入本模块者：`offline_pairs`, `route_persistence`, `route_planning`, `routing`, `tiling`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# RoutingIndex — src/h3_offroad_planner/routing_index.py:92
@dataclass(frozen=True)
class RoutingIndex:
    'Validated routing-index manifest and its immutable build directory.'
    pointer_path: Path
    build_dir: Path
    manifest: Mapping[str, object]
    coarse_graph: pd.DataFrame
    ...
```

```python
# L42
ROUTING_INDEX_KIND = 'h3_routing_index'
# L43
ROUTING_INDEX_SCHEMA_VERSION = 1
# L44
MAX_BOUNDARY_PORTS = 8
# L46
CELL_SCHEMA = pa.schema([pa.field('h3index', pa.string(), nullable=False), pa.field('parent_h3', pa.string(), nullable=False), pa.field('lat', pa.float64(), nullable=False), pa.field('lng', pa.float64(), nullable=False), pa.field('elevation', pa.float64(), nullable=False), pa.field('slope', pa.float64(), nullable=False), pa.field('tri', pa.float64(), nullable=False), pa.field('landcover_code', pa.int32()), pa.field('lc_factor', pa.float64(), nullable=False), pa.field('has_road', pa.bool_(), nullable=False), pa.field('is_passable', pa.bool_(), nullable=False), pa.field('depth', pa.float64()), pa.field('rowspacing', pa.float64()), pa.field('soil_code', pa.int32()), pa.field('soil_moisture', pa.float64()), pa.field('soil_source', pa.string()), pa.field('source_support_m', pa.float64()), pa.field('twi', pa.float64()), pa.field('drainage_sensitivity', pa.float64()), pa.field('drainage_valid', pa.bool_(), nullable=False), pa.field('drainage_boundary_affected', pa.bool_(), nullable=False), pa.field('surface_response', pa.float64()), pa.field('surface_evidence', pa.string())])
# L74
COARSE_SCHEMA = pa.schema([pa.field('parent_a', pa.string(), nullable=False), pa.field('parent_b', pa.string(), nullable=False), pa.field('port_a', pa.string(), nullable=False), pa.field('port_b', pa.string(), nullable=False), pa.field('distance_m', pa.float64(), nullable=False), pa.field('slope_mean', pa.float64(), nullable=False), pa.field('tri_mean', pa.float64(), nullable=False), pa.field('road_fraction', pa.float64(), nullable=False), pa.field('passable_fraction', pa.float64(), nullable=False), pa.field('risk_proxy', pa.float64(), nullable=False), pa.field('environment_proxy', pa.float64(), nullable=False)])
```

```python
# L46
pa.schema([pa.field('h3index', pa.string(), nullable=False), pa.field('parent_h3', pa.string(), nullable=False), pa.field('lat', pa.float64(), nullable=False), pa.field('lng', pa.float64(), nullable=False), pa.field('elevation', pa.float64(), nullable=False), pa.field('slope', pa.float64(), nullable=False), pa.field('tri', pa.float64(), nullable=False), pa.field('landcover_code', pa.int32()), pa.field('lc_factor', pa.float64(), nullable=False), pa.field('has_road', pa.bool_(), nullable=False), pa.field('is_passable', pa.bool_(), nullable=False), pa.field('depth', pa.float64()), pa.field('rowspacing', pa.float64()), pa.field('soil_code', pa.int32()), pa.field('soil_moisture', pa.float64()), pa.field('soil_source', pa.string()), pa.field('source_support_m', pa.float64()), pa.field('twi', pa.float64()), pa.field('drainage_sensitivity', pa.float64()), pa.field('drainage_valid', pa.bool_(), nullable=False), pa.field('drainage_boundary_affected', pa.bool_(), nullable=False), pa.field('surface_response', pa.float64()), pa.field('surface_evidence', pa.string())])
# L74
pa.schema([pa.field('parent_a', pa.string(), nullable=False), pa.field('parent_b', pa.string(), nullable=False), pa.field('port_a', pa.string(), nullable=False), pa.field('port_b', pa.string(), nullable=False), pa.field('distance_m', pa.float64(), nullable=False), pa.field('slope_mean', pa.float64(), nullable=False), pa.field('tri_mean', pa.float64(), nullable=False), pa.field('road_fraction', pa.float64(), nullable=False), pa.field('passable_fraction', pa.float64(), nullable=False), pa.field('risk_proxy', pa.float64(), nullable=False), pa.field('environment_proxy', pa.float64(), nullable=False)])
# L443
pa.schema([pa.field('landcover_code', pa.int32(), nullable=False), pa.field('landcover_type', pa.string()), pa.field('lc_factor', pa.float64(), nullable=False)])
# L461
pa.schema([pa.field('soil_code', pa.int32(), nullable=False), pa.field('soil_type', pa.string()), pa.field('soil_texture', pa.string()), pa.field('uscs', pa.string())])
```

```text
# L380 _parent_summary
'slope_mean' => float(pd.to_numeric(group['slope']).mean())
'tri_mean' => float(pd.to_numeric(group['tri']).mean())
'road_fraction' => float(group['has_road'].astype(bool).mean())
'passable_fraction' => float(group['is_passable'].astype(bool).mean())

# L586 _file_record
'path' => path.relative_to(root).as_posix()
'size_bytes' => path.stat().st_size
'sha256' => _file_sha256(path)

# L200 build_routing_index
'artifact_kind' => ROUTING_INDEX_KIND
'schema_version' => ROUTING_INDEX_SCHEMA_VERSION
'build_id' => build_id
'created_at' => datetime.now(UTC).isoformat()
'crs' => _source_crs(tile_manifest)
'res_fine' => _manifest_int(tile_manifest, 'res_fine')
'res_coarse' => _manifest_int(tile_manifest, 'tile_res')
'static_input_hash' => static_hash
'topology_hash' => topology_hash
'vehicle_hash' => project.get('vehicle_hash')
'factor_model_hash' => project.get('factor_model_hash')
'scenario_hash' => project.get('scenario_hash')
'project_config_snapshot' => project.get('snapshot', {})
'evidence_status' => 'COMPLETE' if not missing else 'INCOMPLETE'
'missing_physical_inputs' => missing
'applicability' => 'static GIS routing facts; final vehicle constraints remain online'
'cells_count' => sum((len(cells) for cells in parent_cells.values()))
'parents_count' => len(parent_cells)
'boundary_port_count' => len(coarse)
'files' => { 'cells' => _file_record(temporary, cells_path); 'coarse_graph' => _file_record(temporary, coarse_path); 'landcover_catalog' => _file_record(temporary, landcover_path); 'soil_catalog' => _file_record(temporary, soil_path) if has_soil_catalog else None; 'port_pairs' => _file_record(temporary, port_pairs_target) if has_port_pairs else None }
'column_compressed_bytes' => _compressed_column_sizes(cells_path)
'source_tile_count' => len(records)

# L451 _write_landcover_catalog
'landcover_code' => code
'landcover_type' => value[0] or None
'lc_factor' => value[1]

# L470 _write_soil_catalog
'soil_code' => code
'soil_type' => value[0]
'soil_texture' => value[1]
'uscs' => value[2]

# L192 build_routing_index
'schema_version' => ROUTING_INDEX_SCHEMA_VERSION
'static_input_hash' => static_hash
'topology_hash' => topology_hash

# L414 _coarse_rows
'parent_a' => parent_a
'parent_b' => parent_b
'port_a' => port_a
'port_b' => port_b
'distance_m' => distance
'slope_mean' => slope
'tri_mean' => tri
'road_fraction' => road
'passable_fraction' => passable
'risk_proxy' => slope + tri
'environment_proxy' => 1.0 - passable
```

```text
L265: files['port_pairs'] <- _file_record(build_dir, target_path)
L266: manifest['files'] <- files
L268: manifest['port_pairs_vehicle_hash'] <- vehicle_hash
L501: snapshot['vehicle'] <- vehicle
L502: result['vehicle_hash'] <- canonical_hash(vehicle)
L505: snapshot['factor_model'] <- factor
L506: result['factor_model_hash'] <- canonical_hash(factor)
L509: snapshot['static_planning'] <- static.to_dict()
L510: result['scenario_hash'] <- canonical_hash(list(static.environment.request_pressures))
L233: manifest['port_pairs_vehicle_hash'] <- port_pairs_vehicle_hash
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import cast
from uuid import uuid4
import h3
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import canonical_hash, load_factor_model, load_static_planning_config
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GridBuildError, H3Graph, PlanningInputError
from h3_offroad_planner.offline_pairs import OfflinePairs, load_offline_pairs

# RoutingIndex — L92
@dataclass(frozen=True)
class RoutingIndex:
    """Validated routing-index manifest and its immutable build directory."""

    @property
    def build_id(self) -> str:
        ...

    def load_cells(self, parent_h3: set[str]) -> pd.DataFrame:
        """Read only row groups matching the requested res11 parents."""
        ...

    def load_graph(self, parent_h3: set[str]) -> H3Graph:
        ...

    @property
    def has_port_pairs(self) -> bool:
        ...

    def load_port_pairs(self, active_parents: Collection[str], *, load_paths: bool=False) -> OfflinePairs:
        """Read only port-pair rows matching the requested res11 parents."""
        ...

# build_routing_index — L143
def build_routing_index(tile_manifest: Mapping[str, object], *, vehicle_path: str | None=None, factor_model_path: str | None=None, static_planning_path: str | None=None, port_pairs_path: str | Path | None=None, port_pairs_vehicle_hash: str | None=None) -> dict[str, object]:
    """Build, validate and atomically publish one immutable routing index."""
    ...

# register_port_pairs — L252
def register_port_pairs(build_dir: Path, port_pairs_path: Path, vehicle_hash: str | None=None) -> dict[str, object]:
    """Register or copy port_pairs.parquet into an existing routing index build."""
    ...

# open_routing_index — L274
def open_routing_index(path: str | Path) -> RoutingIndex:
    """Open a current pointer or a build manifest and validate all referenced files."""
    ...

# _write_cells — L297
def _write_cells(records: list[dict[str, object]], path: Path) -> tuple[dict[str, dict[str, float]], dict[str, list[str]], dict[int, tuple[str, float]], dict[int, tuple[str | None, str | None, str | None]]]:
    ...

# _cell_table — L329
def _cell_table(frame: pd.DataFrame) -> pa.Table:
    ...

# _collect_catalogs — L345
def _collect_catalogs(frame: pd.DataFrame, landcover: dict[int, tuple[str, float]], soil: dict[int, tuple[str | None, str | None, str | None]]) -> None:
    ...

# _parent_summary — L379
def _parent_summary(group: pd.DataFrame) -> dict[str, float]:
    ...

# _coarse_rows — L388
def _coarse_rows(summaries: Mapping[str, Mapping[str, float]], parent_cells: Mapping[str, list[str]]) -> list[dict[str, object]]:
    ...

# _boundary_ports — L431
def _boundary_ports(first: set[str], second: set[str]) -> list[tuple[str, str]]:
    ...

# _write_landcover_catalog — L442
def _write_landcover_catalog(path: Path, values: Mapping[int, tuple[str, float]]) -> None:
    ...

# _write_soil_catalog — L457
def _write_soil_catalog(path: Path, values: Mapping[int, tuple[str | None, str | None, str | None]]) -> None:
    ...

# _restore_catalog_columns — L476
def _restore_catalog_columns(frame: pd.DataFrame, build_dir: Path, manifest: Mapping[str, object]) -> pd.DataFrame:
    ...

# _project_identity — L492
def _project_identity(vehicle_path: str | None, factor_model_path: str | None, static_planning_path: str | None) -> dict[str, object]:
    ...

# _missing_evidence — L514
def _missing_evidence(tile_manifest: Mapping[str, object], project: Mapping[str, object]) -> list[str]:
    ...

# _usable_tile_records — L544
def _usable_tile_records(tile_manifest: Mapping[str, object]) -> list[dict[str, object]]:
    ...

# _source_crs — L565
def _source_crs(tile_manifest: Mapping[str, object]) -> str:
    ...

# _compressed_column_sizes — L570
def _compressed_column_sizes(path: Path) -> dict[str, int]:
    ...

# _file_record — L585
def _file_record(root: Path, path: Path) -> dict[str, object]:
    ...

# _file_sha256 — L593
def _file_sha256(path: Path) -> str:
    ...

# _validate_build — L601
def _validate_build(build_dir: Path, manifest: Mapping[str, object]) -> None:
    ...

# _manifest_path — L615
def _manifest_path(build_dir: Path, manifest: Mapping[str, object], key: str) -> Path:
    ...

# _manifest_mapping — L622
def _manifest_mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    ...

# _manifest_string — L629
def _manifest_string(payload: Mapping[str, object], key: str) -> str:
    ...

# _manifest_int — L636
def _manifest_int(payload: Mapping[str, object], key: str) -> int:
    ...

# _read_json — L643
def _read_json(path: Path) -> dict[str, object]:
    ...

# _write_json_strict — L653
def _write_json_strict(path: Path, payload: object) -> None:
    ...

# _publish_current — L663
def _publish_current(index_root: Path, build_id: str) -> None:
    ...

# _replace_directory_strict — L674
def _replace_directory_strict(source: Path, target: Path) -> None:
    """Retry a transient Windows handle race without changing the fixed target."""
    ...

# _remove_temporary — L686
def _remove_temporary(path: Path, builds_root: Path) -> None:
    ...
```
