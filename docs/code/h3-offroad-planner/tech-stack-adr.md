# ADR-001: Use Python H3/GIS Stack for the Single-Vehicle Demo

- **Status**: Accepted
- **Date**: 2026-07-07
- **Author(s)**: Codex coordinator
- **Triggered by**: Phase 0 tech stack selection
- **Supersedes**: None

## Context

项目需要在复杂越野地形上处理 DEM、地表覆盖、土壤、路网和 H3 网格拓扑，并验证 A*、D* Lite、通行度评估和 LOS 平滑闭环。当前目标是单车 Demo，重点是可验证、可调试和快速迭代。

约束：

- GIS 栅格和矢量处理需要成熟 Python 生态。
- H3 批量映射需要性能较好的绑定。
- 首版不做正式 UI，不做多车协同完整版。
- 代码必须支持本地 pytest、ruff、mypy 质量门。

## Decision

选择 Python 3.11+ 作为首版实现语言，核心技术栈如下：

| 层次 | 选择 |
|---|---|
| 语言 | Python 3.11+ |
| GIS 栅格 | `rasterio`, `numpy` |
| GIS 矢量 | `geopandas`, `shapely`, `STRtree` |
| H3 | `h3`, `h3ronpy` |
| 数据表 | `pandas`, `pyarrow`/Parquet |
| 配置 | YAML |
| 测试 | `pytest`, `pytest-cov` |
| 静态质量 | `ruff`, `mypy` |
| 桌面主界面 | `PyQt5`, `PyQtWebEngine`（可选 `desktop` 依赖） |

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| C++ full implementation | GIS/H3 glue cost higher; slower to produce validated MVP |
| Java/Kotlin GIS stack | Python GIS ecosystem is stronger for raster/vector/H3 experimentation |
| Full GUI first | UI does not reduce algorithm risk; initially deferred until GIS/route delivery loop stabilized |
| Full NSGA-II/PBS first | Violates MVP minimalism; single-car loop must be proven first |

## Consequences

Positive:

- Python GIS/H3 ecosystem reduces prototype risk.
- Tests and data inspection are straightforward.
- Later performance hot spots can be isolated.

Negative:

- Large Res 13 areas may exceed Python memory/runtime budget.
- Some GIS libraries can be difficult to install on constrained machines.
- PyQt5/PyQtWebEngine desktop deployment must comply with their licensing and runtime packaging requirements.

Required follow-up:

- [ ] Pin concrete dependency versions in `pyproject.toml`.
- [ ] Load `conventions/python_style_guide.md` before Phase 3 coding.
- [ ] Run ruff, mypy, pytest-cov in Phase 4.
