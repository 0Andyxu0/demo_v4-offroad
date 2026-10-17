# docs/history —— 历史资料（不代表当前实现）

本目录收纳 2026-09 至 2026-10 期间产生的设计、审查、报告与生成索引。**它们不是当前实施依据**，只用于追溯设计过程。

## 当前依据（与本目录冲突时以此为准）

1. [../project_context/IMPLEMENTATION_PLAN.md](../project_context/IMPLEMENTATION_PLAN.md) —— M0–M5 固定实施方案
2. [../project_context/STATE.md](../project_context/STATE.md) —— 当前状态与实测结果
3. [../project_context/DECISIONS.md](../project_context/DECISIONS.md) —— 已定案取舍
4. `src/h3_offroad_planner/` 源码本身

## 目录内容

| 路径 | 来源与时间 | 注意 |
|---|---|---|
| `code/`（58 篇） | 2026-09-16 ~ 2026-10-13，codex 分支的 MVP 规格、Phase 报告、架构升级与性能方案、研究综述 | 描述旧接口与已废弃的 MVP 路线，**不可据此推断当前代码行为** |
| `PROJECT_HOLOGRAM_986bd58.md` | 2026-10-14 生成的基线架构快照 | 冻结于 `986bd58`，不含 M0/M1 之后的实现 |
| `demo_v4路径规划性能优化方案.md` | 针对原型 `demo_v4` 的性能方案 | 属另一工作树，不适用于本树 |

## 已删除（保留在 Git 历史中）

- `docs/project_context/modules/*.md`（49 篇）、`SYMBOL_INDEX.md`、`MANIFEST.md`：2026-10-14 生成的 AST 索引，行号与签名随 M0/M1 改动失效，且仓库内没有生成脚本可重生成。
- 仓库根目录的 `PROJECT_HOLOGRAM_gpt.md`、`PROJECT_HOLOGRAM_gemini.md`、`demo_v4解决实际环境问题.md`、`gpt_plan_vs_requirement.md`：项目负责人确认为与当前任务无关。
