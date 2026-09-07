# 下一工程闭环计划书：静态因子、多角色路线、RoutePlan 与 D* Lite 状态流

> 历史证据（非活动规范）：本计划已经实施完毕，仅用于追溯；当前要求以活动架构文档和 ADR-022 为准。

## 文档信息

| 项目 | 内容 |
|---|---|
| 文档版本 | 1.0 |
| 基线日期 | 2026-07-16 |
| 状态 | 已锁定并完成实施 |
| 适用范围 | 单车、静态地形约束下的离线/在线辅助路线规划 |
| 主交互端 | PyQt 桌面 Client |
| 备份交互端 | Web |
| 自动化端 | CLI 与 HTTP API |

## 1. 背景与目标

现有 Demo 已具备 H3 图构建、基础通行性评估、A*、候选路线和 D* Lite 算法原型，但车辆参数、Tile 静态事实、路线指标、候选角色、用户选择和动态重规划之间缺少稳定的领域合同。本阶段将其重构为可重复、可审计、可持久化的单车业务闭环。

目标流程如下：

```text
车辆无关 Tile
→ 路由时车辆因子评估
→ 无权重物理瓶颈裕度
→ 有向边 ETA/风险/行驶代价缓存
→ 完整 PortsMap
→ DeterministicParetoPlanner 原始候选
→ 候选聚合与五角色分配
→ RoutePlan
→ 用户选择并持久化
→ D* Lite 动态重规划
→ GPKG/GeoJSON/JSON 交付
```

业务闭环必须满足：

1. 相同静态 Tile 可被不同车辆复用。
2. 每次规划均可追溯到车辆、因子模型、静态输入和图拓扑哈希。
3. 候选路线按明确业务角色分配，而不是统一描述为“帕累托前沿”。
4. 用户首次激活路线必须显式选择。
5. 动态阻塞必须通过持久化状态与 overlay 驱动，不修改基础图。
6. CLI 可在无 Qt、无浏览器、无在线底图条件下完成完整业务流程。

## 2. 已锁定的范围与决策

### 2.1 本期实现

- 车辆无关 Tile 与静态输入哈希。
- 显式车辆配置、因子模型配置和有效配置快照。
- 坡度、锥指、沉陷和方向推力的无权重物理瓶颈裕度。
- 路由时硬约束、节点速度、通行评分和有向边缓存。
- 完整内存 PortsMap 与精确细格路径展开。
- 确定性多目标候选搜索和 widest-path 通行裕度锚点。
- 候选聚合、五角色分配和独立备选存活验证。
- RoutePlan、RouteSelection、成果文件和用户显式选择。
- D* Lite 动态阻塞、状态生命周期、局部修复和全局回退。
- CLI、HTTP、PyQt Client 的同一业务合同。
- 天地图在线底图私密配置与离线成果叠加。

### 2.2 明确不实现

- 真正遗传式 NSGA-II 的种群、交叉、变异和代际迭代。
- PBS 或其他多车冲突消解与调度业务。
- 大范围并行 Tile、流式图搜索和跨请求磁盘 PortsMap 缓存。
- 实时交通、驾驶员行为、传感器融合和实车概率标定。
- `.lyrx` 自动生成。
- `index.html` 浏览器自动化门禁。
- 全市级生产调度能力。

### 2.3 命名和兼容策略

- 当前确定性候选算法统一命名为 `DeterministicParetoPlanner`。
- `global_planner: NSGAII` 仅作为旧配置输入别名，必须发出 `DeprecationWarning`。
- 新 RoutePlan、manifest 和 API 输出不得宣称使用真正 NSGA-II。
- PBS 仅保留 `FleetTask`、`FleetPlanningInput`、`FleetPlan` 和 `FleetCoordinator` Protocol，不保留同名空业务实现。

## 3. 核心领域合同

### 3.1 Tile 与配置边界

Tile 只保存车辆无关事实：

- H3 ID、父格、中心点、邻接、边长；
- 高程、方向坡度输入、TRI；
- 地类、土壤、含水率、USCS、道路覆盖；
- nodata、来源、采样方式、区域 q50/q90、缺失率；
- 静态输入哈希；
- 水体或损坏几何等可证明的静态禁行事实。

Tile 构建阶段不得引入默认车辆、车辆评估路径、评分权重或车辆相关权威 `is_passable/score/sinkage`。旧 `score/cost_score` 只允许兼容读取，并标记为不具备新路由权威性。

新路由请求必须显式提供：

```yaml
vehicle_path: configs/vehicle.yaml
factor_model_path: configs/static_factor_model.yaml
mission_profile: fastest | shortest | passability | economy | resilient
max_candidate_paths: 1..5
candidate_limit: 1..24
```

每次规划必须输出：

```text
effective_vehicle.yaml
effective_factor_model.yaml
vehicle_hash
factor_model_hash
static_input_hash
graph_topology_hash
```

所有默认值先进入规范化有效配置，再计算 SHA-256，禁止只存在于代码中的隐式车辆或因子参数。

### 3.2 物理裕度因子模型

公共不可变对象：

- `FactorInterval`
- `NodeFactorMetrics`
- `DirectedEdgeMetrics`
- `FactorEvaluation`
- `FactorModelConfig`

该计划初版采用的加权多指标评估器已经退役。当前合同不保留矩阵、权重、一致性检验、
理想解归一化或 benefit 分数；兼容字段 `trafficability/score_*` 统一表示物理裕度。

```text
slope_margin = 1 - abs(directed_slope) / max_climb_angle
cone_margin = 1 - min_cone_index / actual_cone_index       # 已知时
sinkage_margin = 1 - sinkage / clearance_limit             # 已知时
grade_force = mass * g * max(sin(directed_slope), 0)
thrust_margin = 1 - grade_force / max_thrust
safety_margin = clamp(min(known_margins), 0, 1)
```

硬约束包括静态阻塞、水体、超过车辆爬坡极限、已知沉陷超限、已知锥指不足和方向推力
不足。缺失地类或土壤证据不阻断规划，只采用保守速度区间、降低 confidence、记录原因码，
且不向裕度中加入虚构值。

### 3.3 ETA、风险与综合行驶代价

路由评估必须一次性产生冻结的有向边缓存。搜索过程不得重复读取 YAML、调用 Bekker 或重新计算因子。

有向边速度和 ETA：

```text
edge_speed_b =
    min(node_u_speed_b, node_v_speed_b)
    × directed_slope_speed_factor_b

eta_lower = distance / speed_upper
eta       = distance / speed_nominal
eta_upper = distance / speed_lower
```

速度下界不足以形成有限 ETA 上界时：

```text
eta_upper_s = null
eta_upper_bounded = false
```

路线 ETA 逐边累加，展示层不得再用“距离 ÷ 平均评分速度”估算。

可加地形风险：

```text
terrain_risk = distance × -ln(max(safety_margin, epsilon))
```

综合行驶代价：

```text
travel_cost(e) =
    distance
    × lc_factor
    × (1 + slope_utilization² + tri_coefficient × TRI)
    + gravity_coefficient × max(delta_elevation, 0)
```

该指标单位为抽象 cost unit，不宣称为能耗或时间。

### 3.4 完整内存 PortsMap

领域对象：

- `Port`
- `PortPairPath`
- `PortsMapTopology`
- `PortsMapSearchContext`

实现规则：

1. 每个跨父格可通行边端点都是 Port。
2. 起终点是请求级临时 Port。
3. 父格内部对所有 Port-pair 运行精确细格最短路。
4. 跨父格边保留方向与完整边指标。
5. 宏图结果展开为连续细格 H3 序列。
6. 展开后重新计算的指标必须与搜索结果一致。
7. 请求内按父格、权重轮廓、探索惩罚和阻塞哈希复用结果。
8. 不落磁盘，不做跨请求缓存。
9. 超过资源上限返回 `PORTS_MAP_LIMIT_EXCEEDED`，不得截断或近似回退。

不同标量权重轮廓必须使用对应边权。单路径 A*、确定性多目标搜索和全局回退共用 PortsMap 搜索内核；D* Lite 局部修复仍在当前细格图上运行。

### 3.5 候选生成与 Pareto 判断

`DeterministicParetoPlanner` 保留：固定权重轮廓、单目标锚点、混合权重、重用惩罚、非支配排序、拥挤度和确定性并列规则。

四个可加目标：

```text
distance
eta
terrain_risk
travel_cost
```

搜索使用当前可通行边的稳健尺度归一化；最终输出和 Pareto 判断使用原始单位。额外执行 widest-path：

```text
maximize score_lower_min
tie-break: terrain_risk, eta, distance, H3 sequence
```

原始候选池最多 24 条。五维非支配判断使用：

```text
distance
eta
terrain_risk
travel_cost
1 - score_lower_min
```

独立备选属于拓扑价值，经扰动存活验证后即使在普通指标空间被支配也可保留。

### 3.6 候选聚合和五角色

`CandidateAggregator` 固定流程：

1. 验证路径和指标。
2. 按完整 H3 序列精确去重。
3. 五维非支配筛选。
4. 计算核心父格走廊签名。
5. 按指标区间和走廊聚类。
6. 每簇选代表。
7. 分配四个指标角色。
8. 对推荐基准执行主走廊失效仿真。
9. 必要时在扰动图补充搜索独立备选。
10. 合并多角色并截断为最多五条唯一路线。

角色合同：

| 角色 | 规则 |
|---|---|
| `fastest_eta` | 最小 `eta_s` |
| `shortest_distance` | 最小 `distance_m` |
| `max_passability_margin` | 最大 `score_lower_min`，再最小 `terrain_risk` |
| `minimum_travel_cost` | 最小 `travel_cost` |
| `independent_backup` | 通过基准走廊失效仿真后核心走廊差异最大 |

独立备选必须在屏蔽基准核心父格及扰动半径后仍连续、可通行且起终点连通。不得用固定 Jaccard 阈值代替存活验证；无合格路径时不创建该角色。

任务偏好映射：

```text
fastest     → fastest_eta
shortest    → shortest_distance
passability → max_passability_margin
economy     → minimum_travel_cost
resilient   → independent_backup
```

`resilient` 以最快路线为独立性参照。无独立备选时推荐最快路线并产生 `INDEPENDENT_BACKUP_UNAVAILABLE`。

### 3.7 RoutePlan、选择与成果

公共对象：

- `PathMetrics`
- `RouteCandidate`
- `RoutePlan`
- `RouteSelection`
- `BlockageRecord`
- `ReplanRequest`
- `ReplanResult`

`RouteCandidate` 至少包含候选 ID、H3 路径、角色、推荐标记、目标、指标、走廊签名、独立性证据、GeoJSON、生成轮廓和重规划轮廓。

`RoutePlan` 包含稳定 `plan_id`、任务偏好、推荐候选、独立性参照、配置及图哈希、候选列表、聚合统计和输出文件。

CLI 合同：

```text
build-tiles   构建车辆无关 Demo Tile
plan          从现有 Tile 生成 RoutePlan
run           build-tiles + plan，不自动激活
select        按 candidate_id 或角色激活候选
replan        从 RouteSelection 执行 D* Lite 重规划
```

一次完整交付目录：

```text
effective_vehicle.yaml
effective_factor_model.yaml
tile_manifest.json
route_manifest.json
route_plan.json
route_candidates.geojson
route_recommended.geojson
routes.gpkg
route_selection.json
selected_route.geojson
active_route.geojson
replan_history.jsonl
style_manifest.json
```

GeoPackage 至少包含：

```text
h3_static_facts
route_candidates
route_recommended
route_selected
route_active
confirmed_blockages
```

所有状态 JSON 使用规范字段顺序和同目录临时文件原子替换。

### 3.8 D* Lite 状态流程

重规划必须显式提供选择文件、当前位置和阻塞观测。当前位置使用 `current_h3`，或经 `snap_distance` 限制的经纬度吸附；禁止从旧路线首格或未持久化游标猜测。

阻塞生命周期：

```text
tentative → confirmed → cleared/expired
```

状态流支持确认次数、可信来源直接确认、TTL、mission 生命周期、防抖、冷却、失败走廊 TTL、滑动窗口回退上限，以及：

```text
active / safe_hold / superseded / invalidated
```

D* Lite 不持久化内部堆和 `g/rhs`。服务重启后从选择、基础图、因子哈希和阻塞记录恢复。

角色对应重规划代价：

- 最快路线：最小 ETA。
- 最短路线：最小距离。
- 行驶代价路线：最小 travel cost。
- 通行裕度路线：保持已选瓶颈阈值后最小 terrain risk；无法保持则全局 widest-path。
- resilient 路线：在确认阻塞和失败走廊约束下最小 ETA。

局部成功时 `plan_id` 不变、`replan_version += 1`，重新计算全部指标、原子替换活动成果并追加历史。局部失败后按相同任务偏好执行完整全局流程；超过回退窗口进入 `safe_hold`，全局无路进入 `invalidated`。车辆、因子模型或静态图哈希变化必须使旧选择失效并重新规划。

## 4. Client、Web 与在线底图

天地图 provider、图层类型和 token 来源必须显式配置。token 只从环境变量或本地私密配置读取，不进入 RoutePlan、公开成果或项目文件。

桌面 Client 负责：

- 车辆、因子模型、任务偏好和候选数量配置；
- Tile、规划、选择、重规划任务；
- 1–5 条候选叠加、高亮和角色筛选；
- ETA 区间、距离、通行裕度、行驶代价和风险展示；
- 显式用户确认与选择；
- 当前车辆位置和阻塞输入；
- D* 状态、版本、`safe_hold` 和错误码展示；
- 后台线程、取消和失败恢复；
- 不保存明文天地图 token。

Web 作为备份端，共用 `/api/run`、`/api/select`、`/api/replan` 业务接口并支持基本候选切换。在线底图不可用时，两端仍必须加载本地 H3、候选和活动路线。

## 5. 实施批次

| 批次 | 主题 | 核心成果 | 门禁 |
|---|---|---|---|
| 0 | 合同重置与去歧义 | 文档、ADR、算法改名、PBS 收缩、五角色固定 | 旧单车链路可用；输出不再宣称真正 NSGA-II/PBS |
| 1 | 车辆无关 Tile | 静态事实、质量字段、区域统计、哈希、旧 Tile 兼容读取 | 两辆车辆复用同一 Tile，Tile 哈希不变 |
| 2 | 因子模型与边缓存 | 物理裕度、硬约束、ETA、风险、travel cost | 物理量边界和手算 ETA 通过 |
| 3 | 完整 PortsMap | 显式 Port、全部 Port-pair、精确展开、资源上限 | 与同权重全图 Dijkstra 成本一致 |
| 4 | 候选与角色 | 四目标、widest、Pareto、聚类、独立备选 | 1–5 条唯一路线；角色满足定义 |
| 5 | RoutePlan 与选择 | 稳定 ID、成果文件、CLI、原子选择与恢复 | `plan → select → restart → recover` 通过 |
| 6 | D* Lite 状态控制器 | overlay、生命周期、角色代价、回退、safe_hold | 阻塞、解除、TTL、重启和循环保护通过 |
| 7 | Client 与 Web | Client 主交互、HTTP 备份、在线/离线地图 | PyQt 离屏业务交互通过 |
| 8 | 工程验收 | 全量测试、南京 Demo、确定性回归、GIS 兼容 | 覆盖率、静态检查和算法 oracle 全部达标 |

## 6. 测试与验收矩阵

重点测试：

- 坡度、锥指、沉陷和方向推力的正常值、边界值与超限值。
- 缺失地类或土壤的保守速度、confidence、原因码和无虚构裕度。
- 硬约束不可被高评分抵消。
- ETA 逐边手算、方向坡度和无界上界。
- travel cost 公式回归。
- PortsMap 与全图精确搜索 oracle 一致。
- 四目标候选、widest-path、重复路线和多角色合并。
- 独立走廊扰动存活和无备选场景。
- RoutePlan 哈希、原子选择、幂等和损坏恢复。
- D* Lite 显式当前位置、阻塞/解除、重启、`safe_hold`。
- CLI 全流程与 GPKG/GeoJSON/JSON。
- Client 离屏业务交互。

工程门槛：

```text
全部测试通过
语句覆盖率 ≥ 80%
分支覆盖率 ≥ 70%
ruff 通过
mypy strict 通过
```

算法验收不得仅依赖覆盖率；物理裕度、PortsMap、ETA、角色聚合和 D* 状态流必须具备手算或全图 oracle 对照。

## 7. 风险和约束

| 风险 | 控制措施 |
|---|---|
| Tile 混入车辆结论 | 静态事实 schema、权威标志和双车辆复用测试 |
| 物理证据缺失 | 保守速度、confidence 和明确 warning；不伪造裕度 |
| 配置历史字段污染 | v1 通用未使用警告，v2 未知字段严格拒绝 |
| ETA 展示漂移 | 逐边缓存并禁止 UI 自行估算 |
| PortsMap 近似导致非最优 | 与全图 Dijkstra oracle 对照；超限显式失败 |
| 多角色重复路线 | H3 全序列去重并合并 roles |
| 伪造独立备选 | 扰动屏蔽后的实际存活验证 |
| D* 状态不可恢复 | 只持久化业务状态，启动时重建内部状态 |
| 在线地图泄漏 token | 环境变量/私密配置，成果中禁止写入 |
| 二进制大文件进入 Git | `.gitignore` 忽略本地 GIS 数据和生成成果 |

## 8. 相关文档

- [闭环合同](closed-loop-contract.md)
- [当前架构](architecture.md)
- [API 设计](api-design.md)
- [测试规格](test-specs.md)
- [ADR-013：单车静态因子 RoutePlan 闭环](adr/ADR-013-static-factor-routeplan-dstar-closed-loop.md)
- [实施成果报告](next-engine-closed-loop-implementation-report.md)
