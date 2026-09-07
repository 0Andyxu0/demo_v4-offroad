# pm-project-initiation 当前状态

- **状态日期**：2026-07-27
- **事实范围**：当前本地工作树；不比较远程仓库
- **工作区判定**：可使用；此前“已污染”定义已于 2026-07-27 经当前工作树复验后解除
- **当前阶段**：Phase 5 基线验收
- **设计 Gate**：1.00，详见 [gate1-design-score.md](gate1-design-score.md)

> “可使用”表示当前本地工作树通过活动合同、测试、覆盖率、静态检查、敏感信息和桌面
> 启动门禁；不表示 Git 工作树没有未提交变更，也不表示已与远程仓库同步。

## 1. 阶段状态

| 阶段 | 状态 | 当前证据 |
|---|---|---|
| Phase 0 需求与约束 | Complete | [spec.md](spec.md) |
| Phase 1 API/测试合同 | Complete | [api-design.md](api-design.md)、[test-specs.md](test-specs.md) |
| Gate 1 设计完整性 | PASS | 12/12 需求覆盖、12/12 完整细节、核心 DAG 无循环 |
| Phase 2 依赖架构 | Complete | [architecture.md](architecture.md) |
| Phase 3 当前实现 | Complete | 本地 `src/h3_offroad_planner/` |
| Phase 4 双盲测试 | Complete | CL-001～CL-040 唯一 pytest 节点；326 项测试通过 |
| Phase 5 交付门禁 | PASS | `scripts/verify_baseline.py` 于 2026-07-27 完整通过 |

## 2. 当前能力

- 车辆无关 Tile 和路由时物理瓶颈裕度评估。
- 冻结有向边指标、精确请求内 PortsMap 和确定性候选搜索。
- 五角色候选聚合、RoutePlan/GPKG/manifest 持久化及显式 RouteSelection。
- BlockageRecord 生命周期、保留状态的 D* Lite、同任务偏好全局回退和安全保持。
- CLI、HTTP 与 PyQt 桌面入口共享同一业务适配器。
- 私有地图配置自动发现、环境覆盖和无 token 本地降级。
- Legacy standalone evaluator、旧图适配器和 Qt compatibility shim 仅用于兼容。

## 3. 范围锁

当前不包含遗传式多目标优化、多车冲突求解、实时交通、大规模并行 Tile、磁盘 PortsMap、
在线服务部署、`.lyrx` 或自动化浏览器 UI。协调模块只保留 Protocol 和基础值对象。

## 4. 最新验收

本节只记录最近一次本地门禁快照，不作为永久固定测试数量。重新执行
`scripts/verify_baseline.py` 后，应以命令输出为准。

| 门禁 | 最近结果 |
|---|---|
| CL 追踪 | CL-001～CL-040 各有唯一 pytest 函数 |
| pytest | 326 passed |
| 语句覆盖率 | 85.46%（阈值 ≥80%） |
| 分支覆盖率 | 71.66%（阈值 ≥70%） |
| ruff | PASS：`src tests demo scripts` |
| mypy | PASS：`src scripts`，42 个源文件 |
| ADR/活动文档/Git 差异 | PASS；私有 token 保持未跟踪 |
| Phase 5 独立审计 | PASS：TODO/FIXME、未声明依赖、暂存区敏感文件检查 |
| PyQt/QWebEngine 桌面烟雾 | PASS：真实窗口和事件循环运行 2.5 秒后正常退出，返回码 0 |

历史 MVP 状态和实施批次由 Git 历史及对应 superseded ADR 保存，不再复制到本活动状态页。
