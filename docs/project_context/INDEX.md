# 项目资料索引：按问题补充上下文

## 使用方式

本工作树接续入口：[当前状态](STATE.md)、[本地运行说明](WORKSPACE.md)、[实施决定](DECISIONS.md)。运行环境为本机默认 Python；命令通过 `scripts/run_local.py` 选择当前工作树源码。

**当前实施入口：[有人驾驶越野固定实施方案](IMPLEMENTATION_PLAN.md)，版本 1.0（2026-10-15），基于 Git `986bd58`。** 已整合 ARGON 1345 与本轮审核修正，明确 M0–M5 模块顺序、局部图/评分/预算/缓存接口及真实工区实验。新任务先读该方案，再按下表读取相关源码资料；历史 Gemini/ARGON 文稿只用于追溯。

若使用网页模型评审或接续实现，首轮上传 `docs/project_context/IMPLEMENTATION_PLAN.md`（当前实施依据）与 `STATE.md`（当前状态）。`PROJECT_HOLOGRAM.md` 仅是 `986bd58` 基线架构快照，**与方案冲突时以方案为准**，不要据它推断当前代码行为。

1. 首轮上传 `IMPLEMENTATION_PLAN.md` + `STATE.md`；需要目录概览时再补 `PROJECT_HOLOGRAM.md`，并明确它是历史快照。
2. 确定本轮问题，再提供下面“第一批”1–3 个模块附件。预算紧张时先传排名第一的模块。
3. 有明确缺口再补第二批。它们是文件导航，不是已启用的自动 RAG；网页模型不能凭本地链接读取未上传文件。不要一次把整个目录或两份长版都作为附件。
4. 若需要算法推导/正确性审查，AST 不够：按 `SYMBOL_INDEX.md` 定位所需函数，并另外提供实现。若需要性能/实地有效性结论，提供匹配配置与产物/实验，不从接口猜测。
5. 切换主题或开始新对话时，带上首读总览及少量已确认结论即可；是否分新对话由任务连贯性决定，不承诺附件不会占用模型上下文。

推荐补充请求格式：`主题=T4；问题=offline_pairs何时失效；已读=总览+portsmap；缺口=车辆/场景身份与回退；请求=routing_index.md、offline_pairs.md；若依赖实现请列具体符号。`

## 按问题定位

| ID | 主题 | 第一批 | 第二批 | 分析目标 |
|---|---|---|---|---|
| T1 | 规划闭环与请求 | [route_planning](modules/route_planning.md)、[models](modules/models.md)、[route_models](modules/route_models.md) | [cli](modules/cli.md)、[routing](modules/routing.md)、[route_persistence](modules/route_persistence.md) | 先明确输入/输出、分支条件和候选池边界；不要先更换规划器。 |
| T2 | GIS → 通行区域/网格 | [grid.h3_grid_builder](modules/grid.h3_grid_builder.md)、[preprocessing.gis_preprocessor](modules/preprocessing.gis_preprocessor.md)、[tiling](modules/tiling.md) | [preprocessing.hydrology](modules/preprocessing.hydrology.md)、[routing_index](modules/routing_index.md)、[models](modules/models.md) | 解释采样、分类映射、邻接和未知区域；验证表示的误连通/漏连通需要独立数据。 |
| T3 | 物理代价与环境 | [factor_model](modules/factor_model.md)、[environment](modules/environment.md) | [vectorized_factor](modules/vectorized_factor.md)、[vectorized_soil](modules/vectorized_soil.md)、[dynamics.bekker](modules/dynamics.bekker.md)、[weather_fallback](modules/weather_fallback.md) | 追踪静态来源、单位、缺失值、压力和物理假设；不是只阅读公式名字。 |
| T4 | 索引、走廊与性能 | [routing](modules/routing.md)、[portsmap](modules/portsmap.md)、[routing_index](modules/routing_index.md) | [offline_pairs](modules/offline_pairs.md)、[reachability](modules/reachability.md)、[route_planning](modules/route_planning.md) | 区分读盘、图构建、因子评价、细搜索、候选生成、导出；相同输入才能比较性能。 |
| T5 | 候选、角色与推荐 | [candidate_aggregation](modules/candidate_aggregation.md)、[planners.deterministic_pareto](modules/planners.deterministic_pareto.md)、[route_models](modules/route_models.md) | [portsmap](modules/portsmap.md)、[dynamics.trajectory_geometry](modules/dynamics.trajectory_geometry.md) | 区分搜索目标、角色标签和推荐策略；核对备份扰动存活证据。 |
| T6 | 车辆连续几何 | [dynamics.trajectory_geometry](modules/dynamics.trajectory_geometry.md)、[models](modules/models.md) | [factor_model](modules/factor_model.md)、[candidate_aggregation](modules/candidate_aggregation.md) | 需要实现时索取 _fillet_polyline/_validate_primitives 等源代码；区分离散采样与真实连续保证。 |
| T7 | 状态、持久化和重规划 | [route_persistence](modules/route_persistence.md)、[replanning](modules/replanning.md)、[route_models](modules/route_models.md) | [planners.dstar_lite](modules/planners.dstar_lite.md)、[cli](modules/cli.md) | 沿选择版本、输入身份、graph_storage、障碍生命周期追踪；全局回退范围是加载图。 |
| T8 | 适配层与用户交互 | [cli](modules/cli.md)、[web_console](modules/web_console.md) | [desktop_client](modules/desktop_client.md)、[desktop_project](modules/desktop_project.md)、[desktop_map](modules/desktop_map.md)、[map_config](modules/map_config.md) | 把 UI 操作与后端 handler/payload 对齐；private map 凭据值无需上传。 |

## 参考材料是什么、不能证明什么

- `modules/*.md`：当前生产包按模块拆分的类属性、类型别名、常量、显式 Schema/序列化片段、完整 AST 接口及 Docstring；不是人为重设计后的理想接口。
- 字典映射没有统一强类型 schema，生成文档也不会替源码创造必填性；静态分析不能穷尽动态 setattr、鸭子类型和回调调用关系。
- `SYMBOL_INDEX.md`：类/函数/方法的模块、词法名称、源码行号。无需首轮上传。
- `MANIFEST.md`：源文件与参考文档 SHA-256、覆盖统计和版本信息；用于检查是否过期，无需首轮上传。
- `PROJECT_HOLOGRAM.md` 是 `986bd58` 基线的**冻结架构快照**，只用于理解目录结构，不反映 M0/M1 之后的实现（见 DECISIONS、STATE）。`PROJECT_HOLOGRAM_gpt.md` / `PROJECT_HOLOGRAM_gemini.md` 已按项目负责人确认删除，不再保留。
- **当前实施依据唯一收敛到 `IMPLEMENTATION_PLAN.md`**；与快照冲突时以方案与源码为准。

## 单模块文件目录

大小为 UTF-8 字节数，不是 token 数，也不代表模型实际注意力开销。建议先阅读问题相关模块，大小仅辅助选择。

| 模块附件 | 类 | 函数/方法 | 字节 |
|---|---:|---:|---:|
| [__init__](modules/__init__.md) | 0 | 0 | 2,440 |
| [__main__](modules/__main__.md) | 0 | 0 | 1,459 |
| [assessment.__init__](modules/assessment.__init__.md) | 0 | 0 | 1,508 |
| [assessment.trafficability](modules/assessment.trafficability.md) | 1 | 5 | 2,801 |
| [candidate_aggregation](modules/candidate_aggregation.md) | 2 | 32 | 10,280 |
| [cli](modules/cli.md) | 0 | 32 | 10,128 |
| [config](modules/config.md) | 0 | 4 | 2,792 |
| [coordination.__init__](modules/coordination.__init__.md) | 0 | 0 | 1,513 |
| [coordination.interfaces](modules/coordination.interfaces.md) | 1 | 1 | 1,972 |
| [desktop_client](modules/desktop_client.md) | 3 | 71 | 13,176 |
| [desktop_map](modules/desktop_map.md) | 1 | 19 | 4,679 |
| [desktop_project](modules/desktop_project.md) | 1 | 22 | 6,489 |
| [dynamics.__init__](modules/dynamics.__init__.md) | 0 | 0 | 1,592 |
| [dynamics.bekker](modules/dynamics.bekker.md) | 1 | 14 | 3,940 |
| [dynamics.cost_function](modules/dynamics.cost_function.md) | 1 | 5 | 3,627 |
| [dynamics.los_path_smoother](modules/dynamics.los_path_smoother.md) | 1 | 10 | 3,407 |
| [dynamics.trajectory_geometry](modules/dynamics.trajectory_geometry.md) | 3 | 31 | 9,570 |
| [environment](modules/environment.md) | 3 | 16 | 7,034 |
| [exporting.__init__](modules/exporting.__init__.md) | 0 | 0 | 1,521 |
| [exporting.gis_exporter](modules/exporting.gis_exporter.md) | 1 | 22 | 7,671 |
| [factor_model](modules/factor_model.md) | 12 | 77 | 35,229 |
| [grid.__init__](modules/grid.__init__.md) | 0 | 0 | 1,521 |
| [grid.h3_grid_builder](modules/grid.h3_grid_builder.md) | 2 | 68 | 17,253 |
| [map_config](modules/map_config.md) | 1 | 3 | 2,804 |
| [models](modules/models.md) | 20 | 21 | 37,496 |
| [offline_pairs](modules/offline_pairs.md) | 1 | 19 | 9,571 |
| [planners.__init__](modules/planners.__init__.md) | 0 | 0 | 1,965 |
| [planners.deterministic_pareto](modules/planners.deterministic_pareto.md) | 2 | 12 | 5,507 |
| [planners.dstar_lite](modules/planners.dstar_lite.md) | 2 | 18 | 5,909 |
| [planners.facade](modules/planners.facade.md) | 1 | 4 | 2,678 |
| [planners.factory](modules/planners.factory.md) | 1 | 6 | 3,070 |
| [planners.h3_astar](modules/planners.h3_astar.md) | 1 | 17 | 5,047 |
| [planners.interfaces](modules/planners.interfaces.md) | 2 | 2 | 2,376 |
| [portsmap](modules/portsmap.md) | 7 | 36 | 16,305 |
| [preprocessing.__init__](modules/preprocessing.__init__.md) | 0 | 0 | 1,729 |
| [preprocessing.gis_preprocessor](modules/preprocessing.gis_preprocessor.md) | 3 | 22 | 9,488 |
| [preprocessing.hydrology](modules/preprocessing.hydrology.md) | 2 | 11 | 6,717 |
| [reachability](modules/reachability.md) | 2 | 6 | 4,182 |
| [replanning](modules/replanning.md) | 2 | 30 | 9,088 |
| [route_models](modules/route_models.md) | 6 | 12 | 15,010 |
| [route_persistence](modules/route_persistence.md) | 0 | 59 | 16,475 |
| [route_planning](modules/route_planning.md) | 0 | 13 | 9,698 |
| [routing](modules/routing.md) | 0 | 50 | 10,758 |
| [routing_index](modules/routing_index.md) | 1 | 34 | 14,318 |
| [tiling](modules/tiling.md) | 0 | 24 | 9,239 |
| [vectorized_factor](modules/vectorized_factor.md) | 1 | 6 | 4,297 |
| [vectorized_soil](modules/vectorized_soil.md) | 0 | 2 | 2,581 |
| [weather_fallback](modules/weather_fallback.md) | 0 | 2 | 2,047 |
| [web_console](modules/web_console.md) | 1 | 65 | 16,685 |

## 从理解到进一步探索

每轮输出尽量包含：①当前链路的解释；②可引用证据；③假设与未知；④一个需要验证的关键机制；⑤最小验证方案或补充资料请求。不要把重新命名现有 H3/Pareto/PortsMap 模块当成创新。

例如研究地图表示：先用 T2/T3 确认输入、采样和物理可通行判定，再决定是否需要新的区域/拓扑表示；验证时固定输入与车辆条件，对比错误连通、窄通道保留和独立路线有效性。其价值需要实验确认，本文不预先宣告成立。

本索引是按需提供资料的工作流，没有调用 Gemini、没有创建检索服务，也没有自动上传任何文件。
