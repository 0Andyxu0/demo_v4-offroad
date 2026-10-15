# 模块参考：map_config

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/map_config.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`ede20d6df802652170f91af662d34cda67511e1ae524699ce50848411d8058d3`；类 1 个，函数/方法 3 个（含嵌套定义）。
- 项目内导入依赖：无。
- 直接导入本模块者：`desktop_map`, `web_console`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# MapProviderConfig — src/h3_offroad_planner/map_config.py:31
@dataclass(frozen=True)
class MapProviderConfig:
    'Runtime-only basemap settings that are never written to route artifacts.'
    provider: str = 'tianditu'
    layer_type: str = 'imagery'
    token: str = ''
    token_source: str = 'unset'
    ...
```

校验 `MapProviderConfig.__post_init__`：

- `L40 if self.provider != 'tianditu'` → `raise ValueError("map provider must be 'tianditu'.")`
- `L42 if self.layer_type not in SUPPORTED_LAYERS` → `raise ValueError(f'map layer_type must be one of {sorted(SUPPORTED_LAYERS)}.')`
- `L44 if not isinstance(self.token, str)` → `raise TypeError('map token must be a string.')`
- `L46 if self.token_source not in {'unset', 'environment', 'local_config'}` → `raise ValueError('map token_source is invalid.')`

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast
import yaml

# MapProviderConfig — L31
@dataclass(frozen=True)
class MapProviderConfig:
    """Runtime-only basemap settings that are never written to route artifacts."""

    def __post_init__(self) -> None:
        ...

# load_map_provider_config — L54
def load_map_provider_config(path: str | None=None) -> MapProviderConfig:
    """Load optional private YAML, then allow a non-empty environment token to override it."""
    ...

# _resolve_config_path — L96
def _resolve_config_path(path: str | None) -> Path | None:
    ...
```
