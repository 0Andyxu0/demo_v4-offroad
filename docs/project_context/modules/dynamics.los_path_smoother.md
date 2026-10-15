# 模块参考：dynamics.los_path_smoother

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/dynamics/los_path_smoother.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`de0de734386b1e81f54fc51679c297b586709c950212fe9c53ba4e8f0a9a311d`；类 1 个，函数/方法 10 个（含嵌套定义）。
- 项目内导入依赖：`models`。
- 直接导入本模块者：`dynamics`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# LOSPathSmoother — src/h3_offroad_planner/dynamics/los_path_smoother.py:14
class LOSPathSmoother:
    'Smooth a path by greedily shortcutting across visible graph segments.'
    # self.graph: 未注解; L23; initial=graph
    ...
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
from __future__ import annotations
from collections.abc import Iterable
import h3
from h3_offroad_planner.models import H3Graph

# LOSPathSmoother — L14
class LOSPathSmoother:
    """Smooth a path by greedily shortcutting across visible graph segments."""

    def __init__(self, graph: H3Graph) -> None:
        """Initialize the smoother.

        Args:
            graph: In-memory planning graph. Must contain all path cells.
        """
        ...

    def smooth(self, raw_path: list[str]) -> list[str]:
        """Return a path with redundant visible intermediate cells removed.

        Args:
            raw_path: Non-empty ordered cell id path.

        Returns:
            Smoothed path. The first and last cells are unchanged, and the length is
            never greater than `raw_path`.

        Raises:
            ValueError: If `raw_path` is empty.
        """
        ...

    def to_latlng(self, smoothed_path: list[str]) -> list[tuple[float, float]]:
        """Convert a cell-id path to latitude/longitude coordinates in degrees."""
        ...

    def _farthest_visible_index(self, raw_path: list[str], anchor_index: int) -> int:
        ...

    def _line_of_sight(self, cell_a: str, cell_b: str) -> bool:
        ...

    def _h3_line_cells(self, cell_a: str, cell_b: str) -> list[str] | None:
        """Return an H3 grid path for real H3 indexes without coordinate rounding."""
        ...

    def _axis_aligned_cells(self, cell_a: str, cell_b: str) -> list[str] | None:
        ...

    def _horizontal_cells(self, lat: int, start_lng: int, end_lng: int) -> list[str] | None:
        ...

    def _vertical_cells(self, lng: int, start_lat: int, end_lat: int) -> list[str] | None:
        ...

    def _cells_from_coordinates(self, coordinates: Iterable[tuple[int, int]]) -> list[str] | None:
        ...
```
