# 模块参考：weather_fallback

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/weather_fallback.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`ee2dd988c6a0200fca081f258d3d23979137b54c83b92a5f07b7a874a2c90918`；类 0 个，函数/方法 2 个（含嵌套定义）。
- 项目内导入依赖：无。
- 直接导入本模块者：`environment`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

本模块没有单独提取的数据结构/映射片段；函数内部动态状态以源码为准。

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Mapping
from math import isfinite

# precipitation_pressure — L15
def precipitation_pressure(precipitation_24h_mm: float, api_reference_mm: float) -> float:
    """Map 24h precipitation to a bounded [0, 1] pressure proxy."""
    ...

# resolve_precipitation_fallback — L24
def resolve_precipitation_fallback(snapshot: Mapping[str, object], api_reference_mm: float | None) -> tuple[float | None, str | None, tuple[str, ...]]:
    """Resolve a provisional pressure from precipitation when moisture is absent.

    Returns ``(pressure, pressure_basis, warnings)``.
    """
    ...
```
