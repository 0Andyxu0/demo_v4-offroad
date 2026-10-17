# M2 前后整改事项表（2026-10-17）

- **依据**：本轮审核（M1_CONSOLIDATED / ROUND2）、第三批整改记录、以及最近几轮关于数据层与端点判定的讨论
- **当前基线**：`513e5a7`；消融产物绑定 `513e5a7` 之前的 `b646190`（数据未变，仅注释修正）
- **判定口径**：**阻断** = 不修则 M2 会在失真的代价面或无审计依据的数据上开工；**必要** = 影响 M2 的输入质量或产物可信度，但可在 M2 首个提交内消化；**优化** = 不阻断开工

## A. 进入 M2 之前必须完成（阻断）

| 编号 | 事项 | 现状与证据 | 目标动作 | 验收标准 |
|---|---|---|---|---|
| **A1** | 地表场接入生产加载链 | `enrich_graph_from_static_scene` 仅被 `run_m1_ablation.py` 与测试调用；生产 `_load_route_graph` / `_load_index_route_graph` 不调用。routing-index 构建 `f84ef3b` 的 `soil_code / soil_moisture / soil_source / drainage_sensitivity / surface_response / twi` 均为 **0 / 2,251,004** | 在图加载入口统一调用 enrich，或把字段写进 routing index | 任一生产入口产出的图四列非空率 ≥99%，或产物显式打印缺失率；`routing_index.json` 的 `evidence_status` 不再是 `INCOMPLETE` |
| **A2** | 非空率 / 有效率进产物 | 现有产物只有土壤/含水率/D 场的均值；`drainage_valid` 非空 100% 但取值**全为 False**（非空 ≠ 有效） | 产物新增 `data_coverage: {field: {non_null_rate, valid_rate}}`，低于阈值标 `evidence_status: incomplete` | 消融与 M2 产物均打印；回归断言该字段存在 |
| **A3** | USCS 映射外置可审计 | [gis_preprocessor.py:38](../src/h3_offroad_planner/preprocessing/gis_preprocessor.py#L38) 的 `SOIL_USCS_OVERRIDES` 为 27 条硬编码 provisional 映射，未进入 `static_input_hash` | 移到 `configs/soil_uscs_map.yaml`（含来源、日期、依据），加载后并入哈希 | 改任一映射值必然改变 `static_input_hash`；配置内注明出处 |
| **A4** | 基准 OD 集登记 | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) 全文无 OD 定义，只有"M0 选若干 OD，覆盖窄道/路土邻接/湿软/坡度，并在比较前固定"；实际 5 组在 [m1_benchmark_ods.json](../../configs/scenes/m1_benchmark_ods.json)，ID 写死在测试 | 在 STATE / DECISIONS 登记：v2 五组、覆盖类别、冻结提交、文件 SHA-256，并引用计划选点要求 | 文档可独立回答"为什么是这 5 组、依据什么、何时冻结" |


> **状态（2026-10-17 晚）：A1–A4 已完成。** 地表场已接入 `_load_route_graph`（`RouteRequest.static_scene_path`），生产 plan 与消融产物均输出 `data_coverage`（五类字段 `valid_rate = 1.000`）；USCS 映射外置为 `configs/soil_uscs_map.yaml` 并记录哈希；OD 集登记见 DECISIONS #42 与 STATE。详见 [STATE.md](STATE.md) 的「A 组」小节。
## B. M2 第一个提交内完成（输入前置）

| 编号 | 事项 | 现状与证据 | 目标动作 | 验收标准 |
|---|---|---|---|---|
| **B1** | 道路有效宽度进入建面 | `resolve_road_effective_width_m` 的生产使用仅 [scene.py:694](../src/h3_offroad_planner/scene.py#L694) 的场景审计；M2 要建道路面/片段，必须消费 3.0–5.5 m | 在片段/局部图构建中调用该函数，并把 `effective_width_m` 连同来源写入 | 片段产物携带有效宽度，且落在 [3.0, 5.5] 或显式标注越界 |
| **B2** | 坡度方向分量 `dz/dx, dz/dy` | 瓦片只有 `elevation / slope / tri` 标量，所以 R4 只能用 `max(slope_u, slope_v)` 代理量（已在 STATE 声明降级） | 建图写入梯度分量，或 M2 保留 DEM 引用按边方位重采样 | 有向边 pitch/roll 由同点位梯度投影得出；与代理量结果并列对比并记录差异 |

## C. M2 期间完成（不阻断开工）

| 编号 | 事项 | 现状与证据 | 目标动作 | 验收标准 |
|---|---|---|---|---|
| **C1** | 画图三态分离 | 现图无法区分"不可通行（水/建筑，内窗实测 29.9%）"与"无数据（覆盖外）"，观感上像"节点缺失" | 导出与前端分三态着色；核查图用全库或 bbox 查询，不复用搜索子图 | 图上可区分三态；任意区域可查询覆盖率 |
| **C2** | 走廊裁剪边界 | [routing.py:282](../src/h3_offroad_planner/routing.py#L282) 硬限制 `corridor_ring ∈ {1,2}`；细搜索只能看到粗骨架周围 1–2 环父格 | 改为可配置缓冲距离（如 300–800 m），或由 M2 局部图取代走廊裁剪 | 同一 OD 扩大范围后可选到更短/更优路径，且耗时可控 |
| **C3** | 采样性能与重复哈希 | 380k 格元 × 3 栅格的 Python 循环；每个 OD 重复计算大文件 SHA-256（5 次） | 向量化批量索引 + 哈希缓存 | 单次消融准备时间下降可测；结果与逐格实现一致 |
| **C4** | 路面口径统一 | 瓦片中存在 `landcover=5`（水）却 `has_road=True` 的格元（跨水桥/堤）；"路面豁免土壤"与"水深阻断"是两条独立判据 | 明确优先级并写入文档；路面格跳过土壤采样 | 跨水路面格行为可预测且有测试覆盖 |
| **C5** | `MISSING_LANDCOVER` 11,510 格元 | 并集内 11,510 格元 `landcover_code` 为空（不阻断通行，但证据缺口） | 追查成因（矢量覆盖空洞/边界裁剪），标注为无数据或补采样 | 该计数归零或进入"无数据"统计口径 |
| **C6** | CLDAS 表述与降尺度 | 0.0625° ≈ 6.9 km，整片工区实测只有 2 个取值；`twi` 列存在但全空 | 文档改为"区域标量输入"，或引入 TWI/质地做降尺度 | 报告不再出现"逐格采样"表述；或降尺度方法有验证 |
| **C7** | USCS 全为 CL 的说明 | 380,044 格元 USCS 全 `CL`（代码 49 / 44 均映射 CL）；差异只在 Bekker 组 loam / clayloam | 在 STATE 与产物中写明"CI 无分化、仅 Bekker 组有分化" | 读者不会把"5.1% 不同土类"误读为 CI 分化 |
| **C8** | A1b / A2 可观测性 | 两档在目标 OD 上仍 <1%（A1b 最大 4e-4，A2 仅裕度变化），已按裁定记录为局限，**不移动基准点** | 补足地物样本：连续软土段、大坡斜切段（新增 OD，不改现有 5 组） | 新增 OD 上出现可归因的非零变化，或其不可观测性再次被证据化 |

## D. M3 之前完成

| 编号 | 事项 | 现状与证据 | 目标动作 | 验收标准 |
|---|---|---|---|---|
| **D1** | 寻路权重换正式入口 | 消融用 `travel_cost + 2·eta + 0.1·risk + env_cost` 的自定义复合权重（[run_m1_ablation.py:342](../scripts/run_m1_ablation.py#L342)），不是正式候选规划器的代价 | 改用正式候选规划入口，或将该权重登记为 M1 专用"证据口径" | 同图同 OD 下两种口径的路径与成本差异报告 |

## E. 已闭环（本轮不再重复）

| 编号 | 事项 | 提交 |
|---|---|---|
| E1 | 栅格采样半像元偏移 → 含水率恢复 2 个取值（0.3080 / 0.3301） | `8871d9b` |
| E2 | 端点按 res14 含格元解析 + 吸附上限 2.0 m + 不可通行即报错 | `292d953` |
| E3 | 铺装路面豁免 Bekker / CI / 土壤沉陷 | `292d953` |
| E4 | 单变量可观测性 `comparison` 段与摘要判定表 | `8871d9b` |
| E5 | 文档清理（history 归档、删除过期索引、INDEX 改指源码） | `b646190` |
| E6 | `MAX_SNAP_DISTANCE_M` 几何注释修正（res14 边长 1.55 m） | `513e5a7` |

## 开工判定

**A1–A4 全部完成即可开工 M2**；B1/B2 必须落在 M2 的第一个提交里；C 组按 M2 节奏推进；D1 前置于 M3。