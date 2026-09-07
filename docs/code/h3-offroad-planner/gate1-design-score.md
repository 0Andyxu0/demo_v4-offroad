# Gate 1 当前设计完整性评分

- **状态**：PASS
- **基线日期**：2026-07-27
- **范围**：当前本地单车 RoutePlan 闭环
- **评分依据**：[spec.md](spec.md)、[api-design.md](api-design.md)、
  [architecture.md](architecture.md)、[test-specs.md](test-specs.md)

## 1. 证据表

`C_func` 的分母固定为 `spec.md` 中 FR-001～FR-012 共 12 项。每一行必须同时存在活动
设计、源码入口和测试证据，才计为覆盖。

| 需求/模块 | 活动设计 | 源码入口 | 测试证据 | 范围 | 单位 | 异常 | 恢复 | 细节分 |
|---|---|---|---|---:|---:|---:|---:|---:|
| FR-001 静态 Tile | architecture §2 | `tiling.py`, `grid/` | CL-008, CL-039 | 1 | 1 | 1 | 1 | 1.00 |
| FR-002 配置与哈希 | API §1 | `factor_model.py`, `config.py` | CL-009..011 | 1 | 1 | 1 | 1 | 1.00 |
| FR-003 物理裕度 | API §1 | `factor_model.py` | CL-001..005 | 1 | 1 | 1 | 1 | 1.00 |
| FR-004 冻结方向边 | API §1 | `factor_model.py` | CL-005..008 | 1 | 1 | 1 | 1 | 1.00 |
| FR-005 精确 PortsMap | API §2 | `portsmap.py` | CL-012..015 | 1 | 1 | 1 | 1 | 1.00 |
| FR-006 确定性候选 | API §2 | `planners/deterministic_pareto.py` | CL-019..020 | 1 | 1 | 1 | 1 | 1.00 |
| FR-007 候选聚合 | API §2 | `candidate_aggregation.py` | CL-016..018, CL-021 | 1 | 1 | 1 | 1 | 1.00 |
| FR-008 计划与选择 | API §3 | `route_models.py`, `route_persistence.py` | CL-022..027 | 1 | 1 | 1 | 1 | 1.00 |
| FR-009 阻塞生命周期 | API §4 | `route_models.py`, `replanning.py` | CL-028..033 | 1 | 1 | 1 | 1 | 1.00 |
| FR-010 状态化重规划 | API §4 | `planners/dstar_lite.py`, `replanning.py` | CL-028, CL-034..035 | 1 | 1 | 1 | 1 | 1.00 |
| FR-011 | CLI/HTTP/Desktop | API §5 | `cli.py`, `web_console.py`, `desktop_client.py` | CL-036..038 | 1 | 1 | 1 | 1 | 1.00 |
| FR-012 | 私有地图配置 | API §1 | `map_config.py` | `tests/test_map_config.py` | 1 | 1 | 1 | 1 | 1.00 |
| FR-013 | 多矢量地物与物理属性 | ADR-023 | `gis_preprocessor.py`, `h3_grid_builder.py` | `test_qdx_data_ingestion.py` | 1 | 1 | 1 | 1 | 1.00 |
| FR-014 | res11+res14高精度基线 | ADR-023 | `models.py`, `h3_grid_builder.py` | `test_qdx_data_ingestion.py` | 1 | 1 | 1 | 1 | 1.00 |

## 2. 明确计算

```text
C_func   = 14 / 14 = 1.00
C_detail = (14 × 1.00) / 14 = 1.00
C_decouple = 1.00

S_design = 0.4 × C_func + 0.3 × C_detail + 0.3 × C_decouple
         = 0.4 × 1.00 + 0.3 × 1.00 + 0.3 × 1.00
         = 1.00
```

`S_design=1.00 ≥ 0.95`，通过 Gate 1。若任一 FR 缺少设计、源码入口或测试证据，
`C_func` 分子必须立即减少，不得继续沿用本页分数。

## 3. 解耦证据

核心路径为：

```text
Tile -> FactorEvaluation -> PortsMap -> DeterministicParetoPlanner
     -> CandidateAggregator -> RoutePlan -> RouteSelection
     -> D* Lite controller -> adapters
```

- Tile 不依赖车辆、候选或 UI。
- 搜索读取冻结边，不回调 GIS 配置或持久化层。
- RoutePlan/Selection 值对象不依赖适配器。
- CLI、HTTP、Desktop 只调用业务入口，不被核心模块反向导入。
- 协调模块不进入单车闭环。

因此核心与辅助组件均无已知循环，`C_decouple=1.00`。

## 4. 反方复核

- [x] 隐含需求已显式化：凭据、原子写、确定性、资源上限和状态恢复均进入规格。
- [x] 恢复路径可执行：保守证据、损坏隔离、D* 修复、有界全局回退和无 token 本地运行。
- [x] 所有物理量均有真实单位或明确说明为无量纲/成本单位。
- [x] PortsMap、物理裕度、候选角色和状态转移均有独立 Oracle，不用覆盖率代替正确性。
- [x] CL-001～CL-040 与 pytest 节点一对一，由 `scripts/verify_baseline.py` 自动检查。
- [x] 旧算法和调度实现不参与当前 Gate-1 计分。

## 5. 熔断条件

以下任一情况使 Gate-1 立即失效：

- 活动需求新增但证据表分母未更新；
- 当前 API 缺少范围、单位、异常或可执行恢复；
- CL 编号缺失、重复或对应测试被删除；
- 核心依赖出现循环；
- 活动文档重新把历史算法或兼容 shim 描述为生产链；
- 验收脚本的覆盖率、静态检查、ADR 或敏感信息门禁失败。
