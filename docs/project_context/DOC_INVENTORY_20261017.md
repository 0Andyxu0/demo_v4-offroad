# 文档清点与清理审核（2026-10-17）

## 1. 判定口径

当前实施依据**唯一**收敛到：

1. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)（M0–M5 固定方案）
2. [STATE.md](STATE.md)（当前状态与实测结果）
3. [DECISIONS.md](DECISIONS.md)（已定案的取舍）
4. 源码本身

其余文档分四类：**现行**（保留）、**审计记录**（保留，作为证据链）、**历史资料**（建议归档并声明）、**生成物**（需重生成或标注过期）。

## 2. 本轮已执行

| 动作 | 对象 | 依据 |
|---|---|---|
| 删除 | 根目录 `PROJECT_HOLOGRAM_gemini.md`、`PROJECT_HOLOGRAM_gpt.md`、`demo_v4解决实际环境问题.md`、`gpt_plan_vs_requirement.md` | 项目负责人确认为与当前任务无关的历史残留 |
| 修正引用 | [INDEX.md](INDEX.md) 第 9/11/38 行：删除对已删文件的两处提及，把"首轮上传"从 HOLOGRAM 改为 PLAN + STATE | 避免 AI 查找不存在的文件，或据旧快照推断当前行为 |
| 加冻结标记 | [PROJECT_HOLOGRAM.md](../../PROJECT_HOLOGRAM.md) 顶部横幅：Git `986bd58` 冻结快照，不反映 M0/M1 之后实现 | 该文件 19 KB，被 INDEX 与提示词列为"首读"，是最大的误读入口 |
| 同步提示词 | [GEMINI_RESEARCH_PROMPT.md](GEMINI_RESEARCH_PROMPT.md) 第 3、11 行 | 外部网页模型据此选附件 |

## 3. 待批准清单

### 3.1 高误读风险：历史工程文档（建议整体归档）

| 组 | 规模 | 内容 | 风险 | 建议 |
|---|---|---|---|---|
| `docs/code/h3-offroad-planner/` | **58 篇 / 691 KB** | 2026-09-16 至 2026-10-13 的 MVP 规格、Phase 报告、codex 分支架构升级方案、性能优化、研究综述 | **高**：大量描述旧接口、旧模块划分与已废弃的 MVP 路线（例如 `static-gis-factor-multipath-design.md` 92 KB、`ponytail-simplification-plan.md` 38 KB、`research-direction-a-literature-review` 53 KB），AI 极易当成当前设计 | 移到 `docs/history/code/`，目录加 `README.md` 声明"历史，不代表当前实现"；不删除（设计过程仍是证据） |
| `docs/demo_v4路径规划性能优化方案.md` | 29 KB | 针对原型 `demo_v4` 的性能方案 | 中：属另一工作树的产物 | 移入 `docs/history/` |

### 3.2 中风险：生成型索引（行号已失效）

| 组 | 规模 | 现状 | 建议 |
|---|---|---|---|
| [modules/](modules/) | **49 篇 / 368 KB** | 2026-10-14 于 `986bd58` 生成的 AST 索引，每篇头部写着"扫描日期 2026-10-14；HEAD 986bd58"。此后 `factor_model.py`、`scene.py`、`vectorized_factor.py`、`bekker.py` 均改动 100+ 行，**文档内的行号和部分签名已经过期** | 仓库内**没有生成脚本**（全仓 py 检索 0 命中），无法就地重生成。建议二选一：①删除 `modules/` + `SYMBOL_INDEX.md` + `MANIFEST.md`，需要接口时直接读源码；②保留但在每篇头部加"行号基于 986bd58，不可作为当前实现依据" |
| [SYMBOL_INDEX.md](SYMBOL_INDEX.md) | 111 KB | 同上，行号索引 | 同上 |
| [MANIFEST.md](MANIFEST.md) | 9 KB | 源文件 SHA-256 清单，同样基于 `986bd58` | 同上；它的价值是"检查是否过期"，现在恰好证明**已过期** |

### 3.3 低风险：保留

| 对象 | 处置 |
|---|---|
| [AGENTS.md](../../AGENTS.md)、[README.md](../../README.md)、[WORKSPACE.md](WORKSPACE.md) | 保留（现行约定与运行说明） |
| [M1_ARGON1909_AUDIT_20261016.md](M1_ARGON1909_AUDIT_20261016.md)、[M1_CONSOLIDATED_AUDIT_20261017.md](M1_CONSOLIDATED_AUDIT_20261017.md)、[M1_AUDIT_ROUND2_20261017.md](M1_AUDIT_ROUND2_20261017.md)、[M1_REMEDIATION_20261017.md](M1_REMEDIATION_20261017.md) | 保留（审核与整改证据链，M1 签收时需引用） |
| [PROJECT_HOLOGRAM.md](../../PROJECT_HOLOGRAM.md) | 已加冻结横幅，可保留；若要彻底消除误读，也可移入 `docs/history/` |
| `.artifacts/2026101x-talk/*.md`（已 gitignore） | 保留（外部审核原稿，本地证据） |
| `.pytest_cache/README.md` | 生成物，忽略 |

## 4. 建议的处理顺序

1. 先归档 `docs/code/h3-offroad-planner/`（收益最大、风险最高）；
2. 再决定 `modules/` + `SYMBOL_INDEX.md` + `MANIFEST.md` 是删是留——**保留但不重生成，比删除更危险**，因为读者会默认它准确；
3. `PROJECT_HOLOGRAM.md` 已可接受；是否移归档取决于是否还要用它做外部评审的目录导览。

## 5. 需要负责人确认

1. `docs/code/h3-offroad-planner/` 是否同意整体移到 `docs/history/code/`（不删除，仅改变位置与门面）？
2. `modules/` 49 篇 + `SYMBOL_INDEX.md` + `MANIFEST.md` 选择"删除"还是"加过期声明保留"？
3. `PROJECT_HOLOGRAM.md` 保留在根目录（已标记冻结）还是同样移入 `docs/history/`？
