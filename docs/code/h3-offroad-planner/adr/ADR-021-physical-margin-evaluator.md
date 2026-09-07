# ADR-021：以物理瓶颈裕度替换加权多指标评估内核

- 状态：Accepted
- 日期：2026-07-17
- 取代：ADR-022 中最初采用的加权多指标地形评估部分

## 背景

旧评估器把坡度、地类、土壤、TRI 和道路特征组合成一个相对评分。该评分依赖人为权重和
样本集合归一化，不能稳定表达车辆物理极限，也会把通行裕度、地形风险和行驶代价耦合。
本轮只修复该内核，不改变 Client、Web、CLI、请求 YAML、RoutePlan v1、GIS 输出、
PortsMap、五角色候选或 D* Lite 的外部合同。

## 决策

节点先检查静态阻塞、水体、车辆坡度上限、已知锥指和已知沉陷。缺失地类或土壤证据不
阻断规划，而是使用配置的保守速度区间、降低 `confidence`、记录原因码，并在成功计划中
写入 `PHYSICAL_EVIDENCE_INCOMPLETE`。

节点与有向边的兼容字段 `trafficability`、`score_lower`、`score_nominal`、`score_upper`
统一表示 `[0,1]` 的物理安全裕度，不表示效用评分。节点裕度是所有已知约束裕度的最小值；
有向边再加入方向坡度裕度和最小上坡推力裕度：

```text
grade_force = mass * g * max(sin(directed_slope), 0)
safety_margin = clamp(min(known_node_margins, slope_margin, thrust_margin), 0, 1)
```

风险固定为可加公式：

```text
terrain_risk = distance * -ln(max(safety_margin, epsilon))
```

ETA 继续使用既有地类、土壤、TRI、道路和方向坡度速度因子，完全不读取安全裕度。
`travel_cost` 保持抽象 cost unit，删除评分修正项：

```text
distance * lc_factor * (1 + slope_utilization^2 + k_tri * TRI)
+ k_g * elevation_gain
```

当前没有经过单位确认的滚阻系数或阻力，因此不新增机械功、燃油或电池能耗含义，
`sinkage_resistance` 不参与该公式。

配置快照沿用 `effective_factor_model.yaml` 文件名并升级为 schema v2。v2 仅允许速度、
缺失证据、硬约束、风险、代价和 PortsMap 参数，未知字段立即拒绝。schema v1 继续兼容
读取仍生效字段，其余字段只发出通用未使用警告；任何新快照都只写 v2。

## 保持不变的合同

- `factor_model_path`、`factor_model_hash` 和 RoutePlan schema v1 字段不变。
- `DeterministicParetoPlanner`、四目标搜索、Pareto 过滤、复用惩罚、widest 路线、独立走廊
  和五种 mission 映射不变。
- D* Lite 对最大裕度角色在内部读取有向边 `safety_margin_lower`；序列化时才映射为
  `score_lower`，其他角色继续读取各自同量纲边代价。
- 模型哈希变化继续使旧选择返回
  `ROUTE_SELECTION_HASH_MISMATCH_REPLAN_REQUIRED`，不静默迁移。
- JSON、GeoJSON、GPKG、Client、Web 和 CLI 的字段集合、文件名与目录组织不变。

## 后果

物理约束与 ETA 解耦，反向边可以因坡度和推力产生不同裕度、风险、时间与代价。缺失证据
仍允许规划，但调用方能从原因码、confidence 和计划 warning 看见不确定性。由于模型哈希
必然变化，旧 RouteSelection 需要重新全局规划后才能继续增量修复。
