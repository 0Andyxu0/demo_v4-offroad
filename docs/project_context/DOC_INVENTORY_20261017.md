# 文档清点与清理审核（2026-10-17）

## 1. 判定口径

当前实施依据**唯一**收敛到：

1. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)（M0–M5 固定方案）
2. [STATE.md](STATE.md)（当前状态与实测结果）
3. [DECISIONS.md](DECISIONS.md)（已定案取舍）
4. `src/h3_offroad_planner/` 源码本身

## 2. 已执行

| 动作 | 对象 | 理由 |
|---|---|---|
| 删除 | 根目录 `PROJECT_HOLOGRAM_gemini.md`、`PROJECT_HOLOGRAM_gpt.md`、`demo_v4解决实际环境问题.md`、`gpt_plan_vs_requirement.md` | 项目负责人确认与当前任务无关 |
| 删除 | `docs/project_context/modules/`（49 篇 / 368 KB）、`SYMBOL_INDEX.md`（111 KB）、`MANIFEST.md`（9 KB） | 2026-10-14 于 `986bd58` 生成的 AST 索引；行号与签名随 M0/M1 改动失效，且全仓无生成脚本可重生成。保留会造成"看起来权威、实际过期"的误读 |
| 移入 history | `docs/code/h3-offroad-planner/`（58 篇 / 691 KB）→ `docs/history/code/` | 旧接口、已废弃 MVP 路线与旧架构方案，误读风险最高 |
| 移入 history | `docs/demo_v4路径规划性能优化方案.md` → `docs/history/` | 属原型 `demo_v4`，与本草图无关 |
| 移入 history | `PROJECT_HOLOGRAM.md` → `docs/history/PROJECT_HOLOGRAM_986bd58.md` | `986bd58` 冻结快照；原被 INDEX/提示词当作"首读"，是最大误读入口 |
| 新增 | `docs/history/README.md` | 声明历史属性 + 当前依据清单 |
| 改写 | [INDEX.md](INDEX.md) | 模块链接改为直接指向 `src/h3_offroad_planner/`；删除 49 行模块目录表；首读改为 PLAN + STATE |
| 改写 | [GEMINI_RESEARCH_PROMPT.md](GEMINI_RESEARCH_PROMPT.md) | 附件清单同步，明确 Hologram 仅为冻结快照 |
| 改写 | [../../AGENTS.md](../../AGENTS.md) | 指向 `docs/history/PROJECT_HOLOGRAM_986bd58.md`，并声明 `docs/history/` 下内容不作为当前依据 |

删除项仍可从 Git 历史取用（`git log -- docs/project_context/modules`）。

## 3. 保留

| 对象 | 处置 |
|---|---|
| [AGENTS.md](../../AGENTS.md)、[README.md](../../README.md)、[WORKSPACE.md](WORKSPACE.md) | 现行约定与运行说明 |
| [M1_ARGON1909_AUDIT_20261016.md](M1_ARGON1909_AUDIT_20261016.md)、[M1_CONSOLIDATED_AUDIT_20261017.md](M1_CONSOLIDATED_AUDIT_20261017.md)、[M1_AUDIT_ROUND2_20261017.md](M1_AUDIT_ROUND2_20261017.md)、[M1_REMEDIATION_20261017.md](M1_REMEDIATION_20261017.md) | 审核与整改证据链，签收时需引用 |
| `.artifacts/2026101x-talk/*.md`（已 gitignore） | 外部审核原稿，本地证据 |

## 4. 后续约定

- 新增文档若要成为实施依据，必须进入 `docs/project_context/` 并在 [INDEX.md](INDEX.md) 登记；否则视为草稿，不得作为实现依据。
- 不再在仓库内提交"全仓 AST 快照"类生成物；需要接口时直接读源码。
- 历史资料只进 `docs/history/`，并在其 `README.md` 登记来源与时间。
