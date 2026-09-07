# 下一工程闭环实施成果报告

> 历史证据（非活动规范）：本报告保留实施时快照，不代表当前公共接口或门禁结果。

## 文档信息

| 项目 | 内容 |
|---|---|
| 报告版本 | 1.0 |
| 报告日期 | 2026-07-16 |
| 对应计划 | [下一工程闭环计划书](next-engine-closed-loop-plan.md) |
| 实施状态 | 完成 |
| 验收范围 | 单车静态因子、多角色候选、RoutePlan、显式选择、D* Lite 状态流 |

## 1. 执行摘要

“静态因子、多角色路线、RoutePlan 与 D* Lite 状态流”工程闭环已经完成。项目从算法 Demo 升级为具有显式输入、稳定领域对象、可复现配置哈希、精确路线指标、候选角色、用户选择、动态重规划和 GIS 成果交付的单车业务流程。

最终链路为：

```text
车辆无关 Tile
→ 路由时加载车辆和因子模型
→ 硬约束与物理瓶颈裕度
→ 冻结有向边指标缓存
→ 精确 PortsMap
→ DeterministicParetoPlanner + widest-path
→ CandidateAggregator 五角色聚合
→ RoutePlan
→ 显式 RouteSelection
→ D* Lite overlay 重规划
→ JSON / GeoJSON / GPKG
```

关键验收结论：

- 292 项自动化测试全部通过。
- 语句覆盖率 84.94%，分支覆盖率 70.85%。
- `ruff` 通过。
- `mypy --strict` 对 42 个源文件通过。
- 真实 CLI 闭环已生成完整成果目录。
- GeoPackage 六个要求图层均可枚举读取。
- wheel 构建成功并包含全部新增模块，不包含 PBS 业务实现。
- 旧 `NSGAII` 只保留产生弃用警告的兼容入口。

## 2. 批次完成情况

| 批次 | 状态 | 实施结果 | 主要证据 |
|---|---|---|---|
| 0 合同重置 | 完成 | 算法去歧义、兼容别名、PBS 收缩、角色重置、ADR 和合同更新 | `closed-loop-contract.md`、ADR-013、planner factory |
| 1 车辆无关 Tile | 完成 | 移除 Tile 构建期车辆评估，增加静态质量与哈希字段 | `tiling.py`、`h3_grid_builder.py` |
| 2 因子与边缓存 | 完成 | 物理硬约束、瓶颈裕度、ETA、风险和 travel cost | `factor_model.py` |
| 3 完整 PortsMap | 完成 | Port/Port-pair、精确内部路径、宏图展开、资源上限 | `portsmap.py` |
| 4 候选与角色 | 完成 | 四目标、widest、Pareto、聚类、五角色、独立性存活验证 | `deterministic_pareto.py`、`candidate_aggregation.py` |
| 5 RoutePlan 与选择 | 完成 | 稳定对象、原子持久化、CLI 五命令、完整 GIS/JSON 成果 | `route_models.py`、`route_persistence.py`、`cli.py` |
| 6 D* Lite 状态流 | 完成 | overlay、阻塞生命周期、角色代价、局部修复、全局回退 | `replanning.py`、`dstar_lite.py` |
| 7 Client/Web | 完成 | Qt 独立控制器、桌面主交互、HTTP 备份接口、在线地图私密配置 | `client_controller.py`、`desktop_client.py`、`web_console.py` |
| 8 工程验收 | 完成 | 全量测试、静态门禁、真实成果、GPKG 和 wheel 验证 | `outputs/closed_loop_acceptance`、覆盖率报告 |

## 3. 核心实施成果

### 3.1 车辆无关 Tile

Tile 构建请求已移除 `assessment_vehicle_path` 和 `assessment_weights`。新 Tile 以静态事实为权威，写入：

- H3 层级、邻接、边长；
- 高程、坡度输入、TRI；
- 地类、土壤、道路等采样事实；
- nodata、采样模式和静态输入哈希；
- 区域统计和来源元数据。

Tile schema 已升级，旧评分字段仅用于兼容读取，不再作为新路线计算依据。不同车辆可复用同一 Tile，车辆差异在路由评估阶段生效。

主要实现：

- [`tiling.py`](../../../../../src/h3_offroad_planner/tiling.py)
- [`h3_grid_builder.py`](../../../../../src/h3_offroad_planner/grid/h3_grid_builder.py)
- [`models.py`](../../../../../src/h3_offroad_planner/models.py)

### 3.2 物理瓶颈裕度与冻结边缓存

新增不可变因子对象和完整评估流程：

- `FactorInterval`
- `NodeFactorMetrics`
- `DirectedEdgeMetrics`
- `PathMetrics`
- `FactorModelConfig`
- `FactorEvaluation`

本报告初版交付的已退役加权多指标评估器，现已由 ADR-021 的物理瓶颈裕度取代。硬约束
先于边生成执行，已知坡度、锥指、沉陷和方向推力裕度直接取最小值，不做权重组合或
全局归一化。缺失地类或土壤不阻断路线，但降低 confidence、采用保守速度区间并生成诊断。

边缓存一次性计算：

- 节点速度区间；
- 方向坡度速度因子；
- ETA 上下界和是否有界；
- terrain risk；
- 综合行驶代价；
- 通行性与原因码。

搜索过程中只读缓存，不重复读取配置或运行 Bekker。

主要实现与配置：

- [`factor_model.py`](../../../../../src/h3_offroad_planner/factor_model.py)
- [`static_factor_model.yaml`](../../../../../configs/static_factor_model.yaml)
- [`vehicle.yaml`](../../../../../configs/vehicle.yaml)

### 3.3 完整内存 PortsMap

PortsMap 已从近似父格走廊升级为显式、精确、请求级内存结构：

- 跨父格边端点构成 Port。
- 起终点作为临时 Port。
- 每个父格内对所有 Port-pair 运行对应权重的精确细格最短路。
- 跨父格边保持方向和完整指标。
- 宏路径展开为连续 H3 细格序列。
- 请求内按权重、探索惩罚和阻塞哈希缓存。
- 超出资源上限返回 `PORTS_MAP_LIMIT_EXCEEDED`。

不同目标不复用错误的 travel-cost 内部路径。测试使用全图精确搜索作为 oracle，对路径成本和连续性进行对照。

主要实现：

- [`portsmap.py`](../../../../../src/h3_offroad_planner/portsmap.py)
- [`test_closed_loop_portsmap.py`](../../../../../tests/test_closed_loop_portsmap.py)

### 3.4 DeterministicParetoPlanner

原简化 NSGA-II 已正式改名为 `DeterministicParetoPlanner`。算法保留确定性权重轮廓、探索惩罚、非支配排序和拥挤度选择，但不再使用任何遗传算法表述。

规划器读取冻结边缓存，搜索：

```text
distance / eta / terrain_risk / travel_cost
```

并额外执行 widest-path，确保通行裕度锚点进入候选池。候选池上限为 24 条，标量搜索使用稳健尺度，最终输出保持原始单位。

兼容行为：

- `NSGAIIPlanner` 类仍可被旧代码导入。
- `global_planner: NSGAII` 仍可读取。
- 每次使用均产生 `DeprecationWarning`。
- 新输出统一写 `DeterministicParetoPlanner`。

主要实现：

- [`deterministic_pareto.py`](../../../../../src/h3_offroad_planner/planners/deterministic_pareto.py)
- [`factory.py`](../../../../../src/h3_offroad_planner/planners/factory.py)
- [`deterministic_pareto_planner.yaml`](../../../../../configs/deterministic_pareto_planner.yaml)

### 3.5 候选聚合与五角色

新增 `CandidateAggregator`，已实现：

1. 路径和指标校验。
2. 完整 H3 序列去重。
3. 五维非支配筛选。
4. 核心父格走廊签名。
5. 指标与走廊聚类。
6. 聚类代表选择。
7. 四个指标角色分配。
8. 基准走廊失效仿真。
9. 扰动图补充搜索独立备选。
10. 多角色合并和最多五条截断。

最终角色：

| 角色 | 已实施规则 |
|---|---|
| `fastest_eta` | 最小逐边累计 ETA |
| `shortest_distance` | 最小距离 |
| `max_passability_margin` | 最大最低通行评分，再最小风险 |
| `minimum_travel_cost` | 最小综合行驶代价 |
| `independent_backup` | 屏蔽基准核心走廊后仍存活且差异最大的路线 |

同一条路线可具有多个角色，不复制路线凑数。无独立走廊时不伪造备选；`resilient` 任务回退到最快路线并生成警告。

主要实现：

- [`candidate_aggregation.py`](../../../../../src/h3_offroad_planner/candidate_aggregation.py)
- [`test_closed_loop_candidates.py`](../../../../../tests/test_closed_loop_candidates.py)

### 3.6 RoutePlan、显式选择与成果持久化

新增公共领域对象：

- `RouteCandidate`
- `RoutePlan`
- `RouteSelection`
- `BlockageRecord`
- `ReplanRequest`
- `ReplanResult`

RoutePlan 保存稳定 ID、任务偏好、推荐者、独立性参照、配置哈希、图哈希、候选、聚合统计和成果位置。RouteSelection 由用户通过候选 ID 或角色显式创建。

持久化实现包括：

- JSON 规范字段顺序；
- 同目录临时文件和原子替换；
- 幂等选择；
- 版本冲突检查；
- 损坏状态文件隔离；
- 活动路线原子更新；
- 重规划历史追加。

CLI 已实现：

```text
build-tiles
plan
run
select
replan
```

`plan/run` 不自动激活路线；首次选择必须调用 `select`。

主要实现：

- [`route_models.py`](../../../../../src/h3_offroad_planner/route_models.py)
- [`route_persistence.py`](../../../../../src/h3_offroad_planner/route_persistence.py)
- [`route_planning.py`](../../../../../src/h3_offroad_planner/route_planning.py)
- [`cli.py`](../../../../../src/h3_offroad_planner/cli.py)

### 3.7 D* Lite 完整状态流

产品级重规划控制器已在算法核心外实现。请求必须显式提供当前位置和阻塞观测，不再从路线首格猜测。

已支持：

- `tentative → confirmed → cleared/expired` 生命周期；
- 确认次数和可信来源直接确认；
- TTL 与 mission 阻塞；
- 防抖和重规划冷却；
- 最近失败走廊 TTL；
- 滑动窗口全局回退上限；
- `active/safe_hold/superseded/invalidated` 状态；
- 按选中角色选择重规划代价；
- D* 局部失败后的全局 PortsMap/候选流程回退；
- 服务重启后从业务持久化状态重建。

局部成功保持 `plan_id`，递增 `replan_version`，重新计算全部 PathMetrics，原子替换活动 GeoJSON/GPKG，并记录路径哈希、阻塞和指标变化。

此外修复了原 D* Lite 启发式纬度项的笔误：

```python
sqrt((cell_a.lat - cell_b.lat) ** 2 + (cell_a.lng - cell_b.lng) ** 2)
```

主要实现：

- [`replanning.py`](../../../../../src/h3_offroad_planner/replanning.py)
- [`dstar_lite.py`](../../../../../src/h3_offroad_planner/planners/dstar_lite.py)
- [`test_closed_loop_replanning.py`](../../../../../tests/test_closed_loop_replanning.py)

### 3.8 PBS 收缩

已删除：

- `PBSFleetCoordinator`；
- 固定优先级预约算法；
- 冲突检测业务函数；
- PBS Demo；
- PBS 专项测试；
- PlannerFactory 的 PBS 入口。

仅保留基础模型和 `FleetCoordinator` Protocol，用于未来边界兼容。当前系统不宣称支持多车协调。

主要实现：

- [`coordination/interfaces.py`](../../../../../src/h3_offroad_planner/coordination/interfaces.py)
- [`coordination/__init__.py`](../../../../../src/h3_offroad_planner/coordination/__init__.py)

### 3.9 Client、Web 与天地图

桌面 Client 已增加车辆、因子模型、任务偏好和候选数量设置，并支持规划、候选展示、显式选择、当前位置、阻塞输入和重规划状态展示。

新增 Qt 独立业务控制器，覆盖：

- plan/select/replan 状态转换；
- 事务性失败恢复；
- 取消；
- 活动候选和版本更新。

Web 已接入 `/api/select` 和 `/api/replan`，路线指标直接读取 PathMetrics，不再自行估算 ETA。

天地图配置已移除硬编码 token。provider、layer 和 token_source 显式配置，token 只从环境变量或本地私密 YAML 读取。离线时仍可加载本地路线成果。

主要实现：

- `src/h3_offroad_planner/client_controller.py`（历史文件，当前已删除）
- [`desktop_client.py`](../../../../../src/h3_offroad_planner/desktop_client.py)
- [`web_console.py`](../../../../../src/h3_offroad_planner/web_console.py)
- [`map_config.py`](../../../../../src/h3_offroad_planner/map_config.py)
- [`map.private.example.yaml`](../../../../../configs/map.private.example.yaml)

## 4. 交付成果验证

真实闭环验收目录：

- [`outputs/closed_loop_acceptance`](../../../../../outputs/closed_loop_acceptance)

已生成文件：

```text
active_route.geojson
effective_factor_model.yaml
effective_vehicle.yaml
replan_history.jsonl
route_candidates.geojson
route_manifest.json
route_plan.json
route_recommended.geojson
route_selection.json
routes.gpkg
selected_route.geojson
style_manifest.json
tile_manifest.json
```

关键成果链接：

- [`route_plan.json`](../../../../../outputs/closed_loop_acceptance/route_plan.json)
- [`route_selection.json`](../../../../../outputs/closed_loop_acceptance/route_selection.json)
- [`active_route.geojson`](../../../../../outputs/closed_loop_acceptance/active_route.geojson)
- [`routes.gpkg`](../../../../../outputs/closed_loop_acceptance/routes.gpkg)
- [`replan_history.jsonl`](../../../../../outputs/closed_loop_acceptance/replan_history.jsonl)

GeoPackage 已验证包含：

```text
h3_static_facts
route_candidates
route_recommended
route_selected
route_active
confirmed_blockages
```

验收流程执行了：

```text
plan
→ 确认未自动生成 RouteSelection
→ select
→ replan
→ 读取活动路线、历史和 GeoPackage 图层
```

## 5. 自动化测试与质量门禁

### 5.1 最终结果

| 门禁 | 要求 | 结果 | 状态 |
|---|---:|---:|---|
| 全部测试 | 通过 | 292 passed | 通过 |
| 语句覆盖率 | ≥ 80% | 84.94% | 通过 |
| 分支覆盖率 | ≥ 70% | 70.85% | 通过 |
| Ruff | 无错误 | All checks passed | 通过 |
| mypy strict | 无错误 | 42 source files | 通过 |
| TODO/FIXME 审计 | 无未完成实现 | 通过 | 通过 |
| 依赖声明审计 | 导入均有声明 | 通过 | 通过 |

覆盖率证据：

- `outputs/coverage_release_final.json`（历史门禁证据，当前可再生成）

5 条测试警告均来自刻意保留的 `NSGAIIPlanner` 兼容入口，属于预期弃用警告。

### 5.2 新增重点测试

- [`test_closed_loop_factor.py`](../../../../../tests/test_closed_loop_factor.py)：物理裕度、硬约束、方向推力、ETA、风险和行驶代价。
- [`test_closed_loop_portsmap.py`](../../../../../tests/test_closed_loop_portsmap.py)：精确 Port-pair、路径展开与 oracle。
- [`test_closed_loop_candidates.py`](../../../../../tests/test_closed_loop_candidates.py)：Pareto、角色、多角色合并和独立走廊。
- [`test_closed_loop_persistence.py`](../../../../../tests/test_closed_loop_persistence.py)：RoutePlan、选择、原子写和 GPKG。
- [`test_closed_loop_replanning.py`](../../../../../tests/test_closed_loop_replanning.py)：阻塞状态、D*、回退和 `safe_hold`。
- `tests/test_closed_loop_client_controller.py`（历史文件，当前已删除）：Qt 独立业务状态控制。
- [`test_closed_loop_contract_validation.py`](../../../../../tests/test_closed_loop_contract_validation.py)：配置、兼容别名和合同错误。
- [`test_map_config.py`](../../../../../tests/test_map_config.py)：天地图环境变量和私密配置。

### 5.3 构建验证

wheel 已成功构建：

- `outputs/wheel_acceptance/h3_offroad_planner-0.1.0-py3-none-any.whl`（历史可再生成交付证据）

包内容检查结果：

- 新增闭环模块全部存在。
- Web 静态资源存在。
- `coordination/pbs.py` 不存在。

## 6. 配置和使用入口

示例配置：

- [`closed_loop_plan.example.yaml`](../../../../../configs/closed_loop_plan.example.yaml)
- [`closed_loop_select.example.yaml`](../../../../../configs/closed_loop_select.example.yaml)
- [`closed_loop_replan.example.yaml`](../../../../../configs/closed_loop_replan.example.yaml)
- [`vehicle.yaml`](../../../../../configs/vehicle.yaml)
- [`static_factor_model.yaml`](../../../../../configs/static_factor_model.yaml)

典型 CLI 流程：

```powershell
h3-offroad-planner build-tiles --config <build-config.yaml>
h3-offroad-planner plan --config configs/closed_loop_plan.example.yaml
h3-offroad-planner select --config configs/closed_loop_select.example.yaml
h3-offroad-planner replan --config configs/closed_loop_replan.example.yaml
```

`run` 可组合构建和规划，但仍不会自动选择或激活路线。

## 7. 与原计划的边界一致性

以下能力按计划明确保持未实现：

- 真正遗传式 NSGA-II；
- PBS 和多车行为；
- 大范围并行 Tile；
- 跨请求磁盘 PortsMap；
- `.lyrx`；
- 实时交通、驾驶行为和传感器融合；
- `index.html` 自动化 UI 门禁。

当前 ETA 是静态地形和车辆约束下的规划 ETA，不包含交通、未建模加减速或驾驶员行为。综合行驶代价是抽象 cost unit，不代表能耗。

独立备选只有在基准走廊扰动后实际存活时才出现，因此 RoutePlan 合法返回 1–5 条唯一路线，而不是固定五条。

## 8. 工程与仓库说明

- `.gitignore` 已覆盖本地 GIS 原始数据、GPKG、Parquet、GeoTIFF、NetCDF、Shapefile、构建产物和输出目录。
- 当前没有已被 Git 跟踪的 1 MB 以上大文件。
- 两张约 1.1–1.2 MB 的流程图 PNG 被保留为文档资产。
- 天地图明文 token 不进入版本库、RoutePlan 或公开成果。

## 9. 结论

本阶段计划所定义的单车工程闭环已完成。核心算法不再以不准确的 NSGA-II 名称对外表达，Tile 与车辆边界已经分离，路线指标具有稳定计算合同，候选具备明确角色和独立性证据，RoutePlan 与用户选择可持久恢复，D* Lite 已接入完整业务状态流，CLI、Web 和 Client 共享同一成果模型。

后续工程应在保持这些合同稳定的前提下开展性能剖析、真实车辆参数标定和更大区域的数据工程优化，而不应重新把车辆结论写回静态 Tile 或恢复未经存活验证的“独立备选”。
