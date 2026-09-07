# 当前 RoutePlan 闭环 API 强合同

> 状态：当前活动基线，2026-07-27。本文记录生产闭环的公共边界、范围、单位、异常和恢复；
> 旧 MVP API 仅由相应历史 ADR 保留。

## 1. 配置与物理评估

| API | 输入与范围 | 输出与单位 | 异常 | 恢复 |
|---|---|---|---|---|
| `load_factor_model(path)` | 存在的 YAML 路径；schema v1 或 v2 | 规范化 `FactorModelConfig` | 路径缺失、YAML 非映射、未知 v2 字段、布尔伪数值或越界参数抛 `ConfigError` | v1 仅迁移仍有效字段并产生未使用配置警告；v2 不猜测 |
| `evaluate_factor_model(graph, vehicle, config)` | 非空图；有效车辆；坡度 degree、锥指 kPa、沉陷 m、推力 N、速度 m/s | 新 `FactorEvaluation`，含节点物理裕度和冻结有向边 | 空图、非法车辆/配置或拓扑字段抛输入错误 | 缺失地类/土壤使用保守区间并降低 confidence；不修改输入图 |
| `evaluate_path_metrics(path, evaluation)` | 至少一个节点；相邻节点必须存在对应方向边 | 距离 m、ETA s、terrain risk、travel cost、裕度最小值/均值 | 路径不连续或方向边缺失抛 `PlanningInputError` | 不执行展示层估算 |
| `load_map_provider_config(path=None)` | 显式路径可选；YAML token/图层必须是非空原生字符串或空 token | `MapProviderConfig`，来源为 unset/environment/local_config | 配置非映射、未知字段、错误类型或非法图层抛 `ConfigError` | 空白 token 环境变量回退到选中的 YAML；无配置返回 unset |

地图配置文件选择顺序为：显式路径、`H3_OFFROAD_MAP_CONFIG`、项目
`configs/map.private.yaml`、无配置。Token 顺序为：非空
`H3_OFFROAD_TIANDITU_TOKEN`、所选 YAML、unset。

## 2. 搜索与候选

| API | 输入与范围 | 输出与单位 | 异常 | 恢复 |
|---|---|---|---|---|
| `PortsMapSearchContext.search(start, goal, profile, blocked)` | 端点必须在图中；标量权重有限非负；阻塞为 `set[str]` | 连续细格路径和原始单位标量代价 | 无路抛规划失败；端点/权重非法抛输入错误；资源超限返回 `PORTS_MAP_LIMIT_EXCEEDED` | 不执行近似走廊或磁盘缓存回退 |
| `DeterministicParetoPlanner.plan(start, goal)` | `max_paths` 1..5；`candidate_limit` 1..24 且不小于 `max_paths`；`penalty_factor` 有限非负 | 唯一确定的 `GeneratedPath` 列表；距离 m、ETA s、其余为冻结边指标和 | 无可通行边、无路或参数非法时显式失败 | widest 锚点独立保留；不回退到随机或遗传搜索 |
| `CandidateAggregator.aggregate(raw, mission, max_candidates)` | 输入 1..24 条；任务为 fastest/shortest/passability/economy/resilient；输出上限 1..5 | `CandidateAggregationResult`，角色固定且同一路线可合并多角色 | 空候选、非法任务、指标与冻结缓存不一致时失败 | 无存活独立备选时回退最快并写 `INDEPENDENT_BACKUP_UNAVAILABLE` |

内部搜索目标固定为 distance、eta、terrain risk、travel cost，加 widest-path 锚点。
候选角色固定为 fastest ETA、shortest distance、maximum passability margin、minimum travel
cost 和 independent backup。

## 3. 计划、选择与持久化

| API | 输入与范围 | 输出 | 异常 | 恢复 |
|---|---|---|---|---|
| `write_route_plan_outputs(plan, graph, output_dir, tile_manifest=None)` | 合法 RoutePlan、匹配图和可写目录 | 规范 JSON、routes.gpkg、manifest 和静态/候选图层 | 序列化、GIS 或替换失败向上传播 | 所有最终文件通过同目录临时成果替换；旧成果在替换失败时保留 |
| `load_route_plan(path)` | 存在且满足 schema 的 JSON | `RoutePlan` | 缺失、损坏、未知字段或不变量失败抛输入错误 | 不修补或猜测计划 |
| `select_route(plan_path, candidate_id=None, role=None, expected_selection_version=None)` | candidate ID 与 role 二选一；版本为非负整数 | 版本化 `RouteSelection` 和活动路线成果 | 候选不存在、选择歧义或版本冲突时失败 | 相同选择幂等；首次规划不隐式调用 |
| `load_route_selection(path)` | 存在的有效选择 JSON | `RouteSelection` | 损坏状态抛明确错误 | 损坏文件移动为 `.corrupt`，不覆盖 |
| `load_route_graph_snapshot(manifest_path)` | manifest 指向受支持的 GPKG 图层/边表 | 重建的静态 `H3Graph` | 路径、格式、列、类型或拓扑无效时失败 | 不回退到隐藏 JSON 图快照 |

序列化器可以输出 RoutePlan v1 的兼容字段；这些字段不得被重新读回为内部规划权威值。

## 4. 重规划状态流

| API | 输入与范围 | 输出 | 异常 | 恢复 |
|---|---|---|---|---|
| `replan_route(request, graph, evaluation, policy=...)` | 必须有 selection、显式 `current_h3` 或可吸附经纬度、观测时间；策略计数和时间均有限有界 | `ReplanResult`、新选择版本、活动路线和历史 | 位置缺失/过远、哈希不匹配、非法生命周期或状态文件损坏时失败 | 本地 D* Lite 修复；失败后按同一角色有界全局回退；频率超限安全保持 |
| `DStarLiteReplanner.replan(graph, current, goal, blocked_cells)` | 静态图、有效端点和已解析阻塞集合 | 连续局部路径 | 端点无效或无路时失败 | 保留并修复反向 `g/rhs/km` 状态，不重新读取阻塞记录 |

`BlockageRecord` 仅允许 `tentative -> confirmed -> cleared|expired`；路线仅允许
`active -> safe_hold|superseded|invalidated`。TTL、确认次数、解除和过期均在
`replanning` 控制层解析。

## 5. 适配器和桌面接口

| API | 输入与范围 | 输出 | 异常 | 恢复 |
|---|---|---|---|---|
| CLI `build-tiles/plan/run/select/replan` | 严格 YAML/命令参数 | JSON 结果、进度事件和文件成果 | 配置或业务错误映射为非零退出 | 不复制业务逻辑 |
| HTTP `/api/run`、`/api/select`、`/api/replan` | 有界 JSON 请求 | JSON 状态及活动路线几何 | 非法 JSON/字段返回 4xx；执行失败返回明确错误 | 保留最后有效 UI/活动成果 |
| `DesktopProjectState.build_run_payload` | 唯一项目状态、有效文件和地图选择 | 统一业务 payload | 非法项目状态或后端不支持字段时失败 | 保留用户输入但阻止执行 |
| `run_desktop_client()` | 可用 PyQt5；在线底图 token 可缺省 | 主窗口和本地交互 | Qt/文件/业务错误显示到 UI | 后台线程只向队列发消息；QTimer 在 UI 线程恢复状态 |

## 6. 非生产公共边界

- `TrafficabilityAssessor`：standalone evaluator；不进入 Tile、RoutePlan 或重规划链。
- `PlannerFactory` 仅保留 H3 A* 旧图入口；Legacy/NSGA-II 全局规划器名称均明确抛出
  `ConfigError`，不得静默映射到新规划器。
- `DesktopOperationWorker`：Qt 兼容 shim；生产后台调度不依赖该类。
- `FleetCoordinator`：只有 Protocol 和基础数据模型，无多车求解器实现。
