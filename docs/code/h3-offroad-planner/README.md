# H3 Off-road Planner 技术基线索引

本目录的技术基线只取自当前本地资源树，不引用或比较任何远程仓库。

## 1. 权威顺序

发生冲突时按以下顺序解释：

1. [closed-loop-contract.md](closed-loop-contract.md)：冻结的闭环算法、状态和兼容边界。
2. [architecture.md](architecture.md)、[api-design.md](api-design.md)、
   [spec.md](spec.md)：当前架构、API 与需求。
3. [test-specs.md](test-specs.md) 和 [gate1-design-score.md](gate1-design-score.md)：
   可执行 Oracle、追踪和量化门禁。
4. 状态为 Accepted/Amended 的当前 ADR。

`spec-mvp*.md`、旧 Gate 附录、被 Superseded 的 ADR 和历史评审只解释决策演进，不得覆盖
上述活动合同。未被 Git 跟踪的分析报告和临时目录不属于交付基线；本次修复不修改、删除或
提交这些用户材料。

## 2. 当前基线

- 单车规划：物理瓶颈裕度、精确请求内 PortsMap、确定性 Pareto 标签搜索和五角色聚合。
- 分辨率基线：默认父格网 `res11` + 子格网 `res14`（亚米级离散格网），单瓦片管理 ~343 个子格。
- 数据集接入：QDX 真实 GIS 数据集（CGCS2000/EPSG:4490 自动无损投影、多矢量图层自动融合、林木间距提取）。
- 状态闭环：RoutePlan 不隐式激活；显式 RouteSelection；阻塞生命周期与 D* Lite 状态修复。
- UI：DesktopProjectState 为唯一项目状态；普通后台线程经 SimpleQueue 向 QTimer/UI 回传。
- 协调：只保留 Protocol 与基础模型，不包含多车求解业务。
- 地图：实际 token 仅来自运行时环境或被忽略的 `configs/map.private.yaml`。
- 质量：CL-001～CL-040 一对一测试、语句覆盖率 80%、分支覆盖率 70%、ruff、mypy 和 Git
  差异门禁。

<!-- BASELINE-HISTORY-START -->
## 3. 技术迁移表

| 领域 | 历史设计 | 当前基线 | 兼容/归档策略 |
|---|---|---|---|
| 地形评价 | AHP/TOPSIS 或加权通行评分 | 无权重物理瓶颈 `safety_margin` | 旧评分名仅允许作为序列化兼容别名 |
| 全局规划 | H3 A* 单路径、误命名的 `NSGAIIPlanner` | `DeterministicParetoPlanner` 四目标加 widest 锚点 | 新生产链是唯一候选规划入口；旧名称明确失败 |
| 候选目标 | 多单位直接相加及高阶风险目标 | distance、ETA、terrain risk、travel cost | 角色由独立聚合器分配 |
| 格网分辨率 | 历史默认 coarse=7/fine=9 | 当前基线 coarse=11/fine=14 (ADR-023) | 单瓦片 ~343 个亚米级子格网，支持大尺度分块缓存 |
| GIS 数据源 | 南京合成单图层栅格 | QDX 多图层矢量+DEM (EPSG:4490 转 EPSG:4326) | 自动投影转换并提取 depth/rowspacing 微地形属性 |
| PortsMap | 父格拓扑近似或常量宏边 | 请求内精确 Port-pair 与连续细格展开 | 旧 ADR-013 作为迁移历史 |
| 重规划 | 重新运行全局 A* 的占位实现 | 保留 `g/rhs/km` 的反向 D* Lite | 控制层管理 BlockageRecord |
| 多车 | `PBSFleetCoordinator` 固定优先级实现 | 只有 FleetCoordinator Protocol | 多车业务移出当前范围 |
| 桌面后台 | `DesktopOperationWorker`/QThread 生产调度 | Thread → SimpleQueue → QTimer → UI | Worker 仅为 compatibility shim |
| 地图凭据 | Python 常量或静态默认 Key | 私有 YAML/环境变量注入 | 完整 Key 不进入 Git |
<!-- BASELINE-HISTORY-END -->

## 4. 验收入口

```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts\verify_baseline.py
```

普通 `pytest` 行为保持不变；完整基线门禁由上述脚本显式执行。
