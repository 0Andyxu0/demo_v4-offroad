# 项目资料索引：按问题补充上下文

## 使用方式

本工作树接续入口：[当前状态](STATE.md)、[本地运行说明](WORKSPACE.md)、[实施决定](DECISIONS.md)。运行环境为本机默认 Python；命令通过 `scripts/run_local.py` 选择当前工作树源码。

**当前实施入口：[有人驾驶越野固定实施方案](IMPLEMENTATION_PLAN.md)，版本 1.0（2026-10-15），基于 Git `986bd58`。** 已整合 ARGON 1345 与本轮审核修正，明确 M0–M5 模块顺序、局部图/评分/预算/缓存接口及真实工区实验。新任务先读该方案，再按下表读取相关源码资料；历史 Gemini/ARGON 文稿只用于追溯。

若使用网页模型评审或接续实现，首轮上传 `docs/project_context/IMPLEMENTATION_PLAN.md`（当前实施依据）与 `STATE.md`（当前状态）。历史架构概览见 [`docs/history/PROJECT_HOLOGRAM_986bd58.md`](../history/PROJECT_HOLOGRAM_986bd58.md)（`986bd58` 冻结快照）；**与方案冲突时以方案与源码为准**，不要据它推断当前代码行为。

1. 首轮上传 `IMPLEMENTATION_PLAN.md` + `STATE.md`；需要历史目录概览时再补 `docs/history/PROJECT_HOLOGRAM_986bd58.md`，并明确它是冻结快照。
2. 确定本轮问题，再提供下面“第一批”1–3 个模块附件。预算紧张时先传排名第一的模块。
3. 有明确缺口再补第二批。它们是文件导航，不是已启用的自动 RAG；网页模型不能凭本地链接读取未上传文件。不要一次把整个目录或两份长版都作为附件。
4. 若需要算法推导/正确性审查，接口签名不够：直接提供 `src/h3_offroad_planner/` 中的实现文件。若需要性能/实地有效性结论，提供匹配配置与产物/实验，不从接口猜测。
5. 切换主题或开始新对话时，带上首读总览及少量已确认结论即可；是否分新对话由任务连贯性决定，不承诺附件不会占用模型上下文。

推荐补充请求格式：`主题=T4；问题=offline_pairs何时失效；已读=总览+portsmap；缺口=车辆/场景身份与回退；请求=routing_index.md、offline_pairs.md；若依赖实现请列具体符号。`

## 按问题定位

| ID | 主题 | 第一批 | 第二批 | 分析目标 |
|---|---|---|---|---|
| T1 | 规划闭环与请求 | [route_planning](../../src/h3_offroad_planner/route_planning.py)、[models](../../src/h3_offroad_planner/models.py)、[route_models](../../src/h3_offroad_planner/route_models.py) | [cli](../../src/h3_offroad_planner/cli.py)、[routing](../../src/h3_offroad_planner/routing.py)、[route_persistence](../../src/h3_offroad_planner/route_persistence.py) | 先明确输入/输出、分支条件和候选池边界；不要先更换规划器。 |
| T2 | GIS → 通行区域/网格 | [grid.h3_grid_builder](../../src/h3_offroad_planner/grid/h3_grid_builder.py)、[preprocessing.gis_preprocessor](../../src/h3_offroad_planner/preprocessing/gis_preprocessor.py)、[tiling](../../src/h3_offroad_planner/tiling.py) | [preprocessing.hydrology](../../src/h3_offroad_planner/preprocessing/hydrology.py)、[routing_index](../../src/h3_offroad_planner/routing_index.py)、[models](../../src/h3_offroad_planner/models.py) | 解释采样、分类映射、邻接和未知区域；验证表示的误连通/漏连通需要独立数据。 |
| T3 | 物理代价与环境 | [factor_model](../../src/h3_offroad_planner/factor_model.py)、[environment](../../src/h3_offroad_planner/environment.py) | [vectorized_factor](../../src/h3_offroad_planner/vectorized_factor.py)、[vectorized_soil](../../src/h3_offroad_planner/vectorized_soil.py)、[dynamics.bekker](../../src/h3_offroad_planner/dynamics/bekker.py)、[weather_fallback](../../src/h3_offroad_planner/weather_fallback.py) | 追踪静态来源、单位、缺失值、压力和物理假设；不是只阅读公式名字。 |
| T4 | 索引、走廊与性能 | [routing](../../src/h3_offroad_planner/routing.py)、[portsmap](../../src/h3_offroad_planner/portsmap.py)、[routing_index](../../src/h3_offroad_planner/routing_index.py) | [offline_pairs](../../src/h3_offroad_planner/offline_pairs.py)、[reachability](../../src/h3_offroad_planner/reachability.py)、[route_planning](../../src/h3_offroad_planner/route_planning.py) | 区分读盘、图构建、因子评价、细搜索、候选生成、导出；相同输入才能比较性能。 |
| T5 | 候选、角色与推荐 | [candidate_aggregation](../../src/h3_offroad_planner/candidate_aggregation.py)、[planners.deterministic_pareto](../../src/h3_offroad_planner/planners/deterministic_pareto.py)、[route_models](../../src/h3_offroad_planner/route_models.py) | [portsmap](../../src/h3_offroad_planner/portsmap.py)、[dynamics.trajectory_geometry](../../src/h3_offroad_planner/dynamics/trajectory_geometry.py) | 区分搜索目标、角色标签和推荐策略；核对备份扰动存活证据。 |
| T6 | 车辆连续几何 | [dynamics.trajectory_geometry](../../src/h3_offroad_planner/dynamics/trajectory_geometry.py)、[models](../../src/h3_offroad_planner/models.py) | [factor_model](../../src/h3_offroad_planner/factor_model.py)、[candidate_aggregation](../../src/h3_offroad_planner/candidate_aggregation.py) | 需要实现时索取 _fillet_polyline/_validate_primitives 等源代码；区分离散采样与真实连续保证。 |
| T7 | 状态、持久化和重规划 | [route_persistence](../../src/h3_offroad_planner/route_persistence.py)、[replanning](../../src/h3_offroad_planner/replanning.py)、[route_models](../../src/h3_offroad_planner/route_models.py) | [planners.dstar_lite](../../src/h3_offroad_planner/planners/dstar_lite.py)、[cli](../../src/h3_offroad_planner/cli.py) | 沿选择版本、输入身份、graph_storage、障碍生命周期追踪；全局回退范围是加载图。 |
| T8 | 适配层与用户交互 | [cli](../../src/h3_offroad_planner/cli.py)、[web_console](../../src/h3_offroad_planner/web_console.py) | [desktop_client](../../src/h3_offroad_planner/desktop_client.py)、[desktop_project](../../src/h3_offroad_planner/desktop_project.py)、[desktop_map](../../src/h3_offroad_planner/desktop_map.py)、[map_config](../../src/h3_offroad_planner/map_config.py) | 把 UI 操作与后端 handler/payload 对齐；private map 凭据值无需上传。 |

## 参考材料是什么、不能证明什么

- 接口与实现一律以 `src/h3_offroad_planner/` 源码为准；上表的模块链接直接指向源文件。
- 旧版按模块生成的 AST 附件与符号索引（`modules/*.md`、`SYMBOL_INDEX.md`、`MANIFEST.md`）已于 2026-10-17 删除：它们生成于 `986bd58`，行号与签名已随 M0/M1 改动失效，保留会造成误读；需要时从 Git 历史取用。
- 历史设计、Phase 报告与研究综述集中在 [`docs/history/`](../history/)，**不代表当前实现**。
- `docs/history/PROJECT_HOLOGRAM_986bd58.md` 是 `986bd58` 基线的**冻结架构快照**，只用于理解目录结构，不反映 M0/M1 之后的实现；`PROJECT_HOLOGRAM_gpt.md` / `PROJECT_HOLOGRAM_gemini.md` 已删除。
- **当前实施依据唯一收敛到 `IMPLEMENTATION_PLAN.md`**；与快照冲突时以方案与源码为准。
- 阶段记录：[M2_READINESS_CHECKLIST_20261017.md](M2_READINESS_CHECKLIST_20261017.md)（M2 前后整改事项表）、[M1_REMEDIATION_20261017.md](M1_REMEDIATION_20261017.md)（整改执行记录）、[M1_CONSOLIDATED_AUDIT_20261017.md](M1_CONSOLIDATED_AUDIT_20261017.md) / [M1_AUDIT_ROUND2_20261017.md](M1_AUDIT_ROUND2_20261017.md)（审核报告）。

## 从理解到进一步探索

每轮输出尽量包含：①当前链路的解释；②可引用证据；③假设与未知；④一个需要验证的关键机制；⑤最小验证方案或补充资料请求。不要把重新命名现有 H3/Pareto/PortsMap 模块当成创新。

例如研究地图表示：先用 T2/T3 确认输入、采样和物理可通行判定，再决定是否需要新的区域/拓扑表示；验证时固定输入与车辆条件，对比错误连通、窄通道保留和独立路线有效性。其价值需要实验确认，本文不预先宣告成立。

本索引是按需提供资料的工作流，没有调用 Gemini、没有创建检索服务，也没有自动上传任何文件。