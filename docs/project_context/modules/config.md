# 模块参考：config

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/config.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`d6ba6271daeb160b51407b8db756e84adbaa56c16271308dbc7f188922a0efd8`；类 0 个，函数/方法 4 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`cli`, `h3_offroad_planner`, `offline_pairs`, `replanning`, `route_planning`, `routing`, `routing_index`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

本模块没有单独提取的数据结构/映射片段；函数内部动态状态以源码为准。

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from pathlib import Path
from typing import cast
import yaml
from h3_offroad_planner.models import ConfigError, VehicleProfile

# _load_yaml_mapping — L30
def _load_yaml_mapping(path: str) -> dict[str, object]:
    ...

# load_config — L41
def load_config(path: str) -> dict[str, object]:
    """Load and validate planner configuration from a YAML file.

    Args:
        path: YAML file path. Unit: filesystem path. Must exist and contain a mapping
            with `global_planner`, `local_replanner`, and `cost`.

    Returns:
        Validated configuration dictionary.

    Raises:
        ConfigError: If the file is missing, malformed, or lacks required keys.
    """
    ...

# load_vehicle — L63
def load_vehicle(path: str) -> VehicleProfile:
    """Load and validate a vehicle profile from a YAML file.

    Args:
        path: YAML file path. Unit: filesystem path. Must contain all
            `VehicleProfile` fields.

    Returns:
        Validated vehicle profile.

    Raises:
        ConfigError: If the file is missing, malformed, or lacks vehicle fields.
        ValueError: If vehicle physical ranges are invalid.
    """
    ...

# _optional_float — L99
def _optional_float(data: dict[str, object], key: str) -> float | None:
    ...
```
