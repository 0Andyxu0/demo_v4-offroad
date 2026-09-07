# ADR-022：车辆无关 Tile、五角色 RoutePlan 与 D* Lite 状态闭环

- 状态：Accepted（当前闭环决策）
- 日期：2026-07-16
- 取代：ADR-010 中误用 NSGA-II 名称的输出合同、ADR-011 的 PBS 业务实现，以及旧
  Tile 构建期车辆评分合同

## 决策

Tile 只持久化车辆无关事实；本 ADR 最初规定车辆与已退役的加权多指标评估器在每次路由
请求中显式输入并规范化快照。其评估内核现由 ADR-021 的物理瓶颈裕度取代，RoutePlan、
PortsMap、五角色和 D* Lite 合同保持不变。路由搜索只读取一次性冻结的有向边 ETA、
terrain risk 与综合行驶代价。

所有全局搜索使用请求内精确 PortsMap 内核。现有确定性多权重搜索命名为
`DeterministicParetoPlanner`。旧输入别名和 Legacy/NSGA-II 适配器已经删除；
`PlannerFactory` 对旧名称明确抛出 `ConfigError`。新生产链是唯一候选规划入口。
候选聚合器分配最快 ETA、最短距离、最大通行裕度、最小综合行驶代价和经走廊失效验证的
独立备选；数据可靠性不构成路线角色。

规划产生 `RoutePlan` 但不激活路线。用户通过 `select` 显式生成 `RouteSelection`。动态变化
通过基础图只读 overlay 进入 D* Lite；阻塞具有 tentative/confirmed/cleared/expired 生命周期，
局部失败可按同一任务偏好进行有界全局回退。

PBS 业务代码、Demo 和专项测试删除，只保留 `FleetCoordinator` 抽象接口和基础模型。本期不
实现真正 NSGA-II、大规模 Tile、磁盘 PortsMap、实时交通、`.lyrx` 或多车协调。

## 后果

- 两辆车可复用同一 Tile，但因子、ETA 和路线允许不同。
- 每个成果可由车辆/因子/静态事实/图拓扑哈希追溯。
- 候选为 1–5 条唯一几何；一条路线可承担多个角色，不复制凑数。
- CLI 完整交付业务数据，Client 为主交互端，Web 为备份端。
- 配置或静态图哈希改变会使旧选择失效，不能作为 D* Lite 局部边变化处理。
