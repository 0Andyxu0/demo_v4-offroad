# demo_v4 本地路由索引与十秒级规划改造方案

- 日期：2026-09-14
- 状态：修订实施基准；须先完成 I0 数据就绪与性能基线，不能把目标值表述为既有实测
- 目标：以 `D:\Workspace\demotest` 的“本地预存储、启动加载、粗图定界、走廊规划”为工程基准，保留 demo_v4 的 res11 + res14、物理硬约束、确定性多候选、连续车辆几何和重规划能力，使用户在底图就绪后只需输入起点和终点即可规划
- 性能目标：固定硬件、固定数据和固定起终点集上，预热后正常交互请求 `plan_ready_s` 的 P95 不超过 10 秒

## 0. 规范性用语

本文使用以下用语表达实施约束：

- **必须**：实现和验收不可缺少的要求；不满足即不得进入下一增量；
- **应**：默认实施要求；只有基准数据或兼容性证据证明不适用时才能偏离，并须记录原因；
- **可以**：不影响主目标的可选实现；不得为了“以后可能需要”提前建设；
- **不得**：明确禁止的行为或实现边界。

## 1. 结论与边界

demo_v4 当前已经预先生成静态 H3 瓦片，但正常规划仍会在请求期重复执行大量建库工作：

1. 从全区 6,767 个 res11 小 Parquet 瓦片中筛选并逐个读取与直线缓冲区相交的文件；当前固定基准请求读取 1,038 个文件、356,034 条原始记录；
2. 合并、去重和 ROI 过滤后，重新构造约 325,077 个 H3Cell 和 788,286 条无向边；
3. 对该请求图的全部节点和全部可用方向重新执行车辆物理因子模型；
4. 请求内新建 `PortsMapSearchContext`，执行多 profile、复用惩罚和 widest-path 搜索；
5. RoutePlan 返回前同步写出完整图 GeoPackage；当前 `outputs/qdx_route/routes.gpkg` 约 152 MB。

本方案只调整这些工作的执行时机和输入范围，不更换现有规划器，不降低分辨率，不删除物理约束，也不引入数据库、缓存服务或新的规划框架。

`demotest` 当前实物是 res13 + res10、321,725 格、约 6.75 MB 的 `cells.parquet`，并为五种车型预存关口图。它证明了“预建静态数据 + 启动加载 + 粗图走廊 + 走廊内计算”的方向可行，但其数据规模、字段丰富度和物理模型均不能作为 demo_v4 的等价性能证据。`demotest` 的 3.3 秒记录不得直接写成 demo_v4 的预期实测。

## 2. 当前事实与实施前提

### 2.1 已核实的数据规模

| 项目 | 当前实物 |
|---|---:|
| 全区细格 | 2,251,004 个 res14 格 |
| 全区父格瓦片 | 6,767 个 res11 瓦片 |
| 全区瓦片目录 | 约 369.5 MB |
| 固定基准请求读取 | 1,038 个瓦片、356,034 条原始记录 |
| 固定基准请求图 | 325,077 个格、788,286 条无向边 |
| 当前固定基准 GPKG | 约 152 MB |

上述是数据规模，不是分阶段耗时。当前源码没有完整的 `plan_ready_s` 分段计时，因此任何 I/O、物理评估、搜索或导出的秒数都必须由 I0 重新测量。

### 2.2 物理证据当前不完整

当前项目不能声称已经完成实车物理闭环：

- `configs/vehicle.yaml` 中 `width_m`、`wheelbase_m`、`front_overhang_m`、`rear_overhang_m` 仍为 `null`；
- `configs/static_gis_planning.yaml` 中 `mapping_t0`、`mapping_t1` 和 `default_theta_v` 仍为 `null`；
- 当前 QDX 路由输出的 tile manifest 中土壤和土壤目录来源为 `null`；
- 当前 RoutePlan 报告 `PHYSICAL_EVIDENCE_INCOMPLETE`、`NO_GEOMETRY_VALID_CANDIDATE`，且 `geometry_valid_count=0`。

因此：

- 性能改造可以在“不完整证据”状态下开发和测试；
- 但只有冻结可信土壤/水文映射和车辆外廓参数，并得到至少一条几何有效候选后，才能验收“实车物理保真”；
- 离线索引必须记录 `evidence_status` 和缺失项，不能把缺失值固化成已验证物理事实。

### 2.3 Git 边界

审查时当前分支为 `main`，工作树已有 13 个已跟踪修改、30 个已跟踪删除和 5 个未跟踪文件。本方案本身也是未跟踪文件。实施时必须保护这些既有改动，性能改造应使用独立提交边界，不能把不同来源的删除、UI 修改和索引实现混成一次提交。

### 2.4 当前 Parquet 与路线包结构审查

当前 `outputs/qdx_tiles/tiles` 中有 6,756 个非空 Parquet 分片、2,251,004 行和 24 个字段。实物检查发现 13 种 Arrow schema 变体，主要原因是空列被推断成 `null`，以及 `landcover_code`、`depth`、`rowspacing`、`edge_length_m` 在不同分片中被推断为不同类型。I1 必须使用显式 Arrow schema，不能继续依赖 pandas 按分片推断类型。

当前逐行字段的主要存储开销如下：

| 字段 | 当前压缩列块约占用 | 判定 |
|---|---:|---|
| `adjacency_json` | 156.4 MB，占目录 42.35% | 删除；现有建图链按 H3 邻接重新生成边，不读取该列 |
| `edge_length_m` | 18.6 MB，占目录 5.03% | 删除；现有建图链重新计算边距离 |
| `static_input_hash` | 1.73 MB | 从行级迁移到 `routing_index.json` 和分片清单 |
| `sampling_mode` | 0.53 MB | 从行级迁移到 `routing_index.json` |
| `nodata` | 0.38 MB | 删除；无效高程、坡度和 TRI 已在记录生成前过滤，当前规划链不读取该列 |

上述五列合计约 177.7 MB，相当于当前 Parquet 目录的 48.1%。该数值是现有压缩列块的静态统计，不等价于改造后的最终文件体积；I1 必须重新测量实际索引大小。

当前 `soil_code`、`soil_type`、`soil_texture`、`uscs`、`soil_moisture` 在全部现有非空分片中均为空。它们的主要问题不是磁盘占用，而是物理证据缺失和 schema 不稳定；不得把这些空列解释为已具备土壤事实。

当前 `outputs/qdx_route/routes.gpkg` 约 151.8 MB，其中 `route_candidates` 只有 5 行，而 `h3_static_facts` 有 325,077 行、`h3_edges` 有 788,286 行。当前恢复链仍依赖后两者重建请求图，所以它们不能在迁移恢复入口之前直接删除；I4 必须先让恢复和重规划从共享路由索引加载走廊，再停止把完整图复制进每个路线包。

## 3. 用户操作与在线请求契约

### 3.1 用户只输入起终点

首版只支持一个已冻结的正式项目配置。车辆、因子模型、静态场景、分辨率、候选策略和输出策略均由已加载的路由索引及项目配置确定，不再要求用户在每次规划时选择文件或重复输入参数。

用户可见请求只有：

```json
{
  "start": {"lat": 31.975, "lng": 118.988},
  "goal": {"lat": 31.992, "lng": 119.008}
}
```

内部仍保留 `vehicle_hash`、`factor_model_hash`、`scenario_hash`、分辨率和候选上限，但这些来自已加载项目身份，不属于用户本次路线请求。

如果以后确有第二种车辆或第二种场景，先把它定义为显式项目预设；在出现真实需求前不建设通用注册中心、插件层或任意配置组合缓存。

### 3.2 “加载底图”的含义

“底图已加载”必须表示路由索引已经校验并可规划，而不只是读取了 `tile_manifest.json` 或显示了地图影像。就绪状态至少包含：

- 当前索引 build ID 和 schema 已验证；
- res11 粗图和父格定位结构已在内存；
- 细格 Parquet metadata 已打开，可按父格裁剪；
- 固定车辆、因子和场景身份与索引一致；
- 物理证据完整性状态已显示。

索引未就绪时禁用“开始规划”，并提供明确的重建或重新加载提示。

## 4. 离线、启动期和请求期的职责划分

| 阶段 | 负责内容 | 明确不做 |
|---|---|---|
| 离线建库 | 原始 GIS 处理、res14 静态格属性、父格映射、车辆无关邻接原语、res11 粗拓扑、边界口候选、输入哈希 | 不生成起终点相关路线，不固化临时阻塞和复用惩罚 |
| 应用启动/加载项目 | 校验 manifest，加载粗图和父格定位，打开细格列存 metadata，建立小型进程内切片缓存 | 不重跑 GIS，不重建全区 Python 对象图 |
| 正常路线请求 | 起终点吸附、多目标粗走廊、细格切片、走廊内物理评估、现有 Pareto/聚合/连续几何、轻量结果持久化 | 不扫描原始 GIS，不逐个读取 1,038 个瓦片，不同步写完整 GPKG |
| 可选性能层 | 对实测仍超预算的单一最大阶段增加最小缓存 | 不在 I0 前预建全区 Factor Cache 或跨请求 Port-pair 框架 |

## 5. 本地路由索引设计

### 5.1 产物布局

复用当前 `build_h3_tile_cache()` 的数据处理结果，在瓦片建库全部成功后执行一次索引发布：

```text
outputs/qdx_tiles/
  tile_manifest.json
  tiles/...
  routing_index/
    current.json
    builds/
      <build_id>/
        routing_index.json
        cells/
          part-*.parquet
        landcover_catalog.parquet
        soil_catalog.parquet        # 仅在存在可信土壤来源时生成
        coarse_graph.parquet
```

使用版本目录是为了保证多文件索引的一致性：先完整写入并校验 `<build_id>`，最后原子替换很小的 `current.json` 指针。旧索引在新索引完全可用前不得被覆盖。

首版不创建空的 `factor_cache/` 脚手架；只有 I5 被实测触发时才增加该产物。`current.json` 固定文件名替换失败必须让发布失败，不能用时间戳旁路文件冒充发布成功。

### 5.2 `cells` 细格列存

- 首版固定核心字段必须为 `h3index`、`parent_h3`、`lat`、`lng`、`elevation`、`slope`、`tri`、`landcover_code`、`lc_factor`、`has_road`、`is_passable`、`depth`、`rowspacing`；除下述有可信来源的可选空间物理事实外，不得增加其他逐格字段；
- `parent_h3` 必须保留用于分区和谓词裁剪；`lat`、`lng` 首版应保留，只有基准证明按需从 H3 推导更快且不增加请求尾延迟时才能删除；
- `lc_factor`、`is_passable` 首版应保留以兼容现有规划链；只有土地覆盖映射、静态限制规则及其版本均被冻结，并通过 A/B 验证后，才可以改为加载时派生；
- `depth`、`rowspacing` 属于已存在的空间物理事实，不能仅因部分记录为空而删除；
- `soil_code` 应使用显式可空整数类型；`soil_type`、`soil_texture`、`uscs` 等代码说明不得逐格重复保存，应放入版本化 `soil_catalog` 小表，并在 manifest 中记录目录哈希；没有可信土壤来源时不得生成空目录文件；
- `soil_moisture`、TWI、排水敏感度和边界影响等随空间变化的物理事实，只有存在可信输入时才写入单元表；schema 要求其存在但当前无证据时，必须写成显式类型的可空列并把缺失状态写入 manifest，不能写成 Arrow `null` 类型；
- `landcover_type` 应由 `landcover_code` 和版本化 `landcover_catalog` 解析；若自定义矢量来源包含不能由代码恢复的业务名称，必须先冻结映射表后才能删除逐格文本；
- `adjacency_json`、`edge_length_m`、`nodata`、逐行 `sampling_mode` 和逐行 `static_input_hash` 不得进入新 `cells`；
- 所有字段必须使用一个显式 Arrow schema，并按 `(parent_h3, h3index)` 排序；
- Row Group 或少量分片必须支持按 `parent_h3` 谓词裁剪；
- 不预设“一定是单文件”或固定分片数，由 I1 的读取、文件大小和 metadata 开销实测选择最简单的合格布局；
- 正常规划只能从该列存快路径读取，不再逐个打开原瓦片；
- 原瓦片暂时保留用于增量建库和故障定位。

### 5.3 `coarse_graph.parquet`

粗图保存车辆无关的父格拓扑和可用于粗搜索的摘要，不冒充最终物理判定：

- res11 父格邻接；
- 跨父格边界口候选；
- 距离、地形、道路、静态风险和环境代理量的可审计摘要；
- 静态缺失或明显不可用区域标记；
- 与 `cells` 一致的 build ID、schema 和输入哈希。

车辆硬约束、场景压力、临时阻塞和连续车辆外廓仍在走廊细格层判定。粗图只负责缩小搜索范围，不能直接证明路线可通行。

### 5.4 身份和校验

`routing_index.json` 至少记录：

- `schema_version`、`build_id`、创建时间；
- CRS、res_fine=14、res_coarse=11；
- `static_input_hash`、`topology_hash`；
- 构建索引时使用的项目配置快照及其 `vehicle_hash`、`factor_model_hash`、`scenario_hash`，但这些不参与静态 build ID；
- cells/父格/边界口数量、分片清单和文件大小；
- `evidence_status`、缺失物理输入和适用边界。

静态 build ID 只由静态输入、拓扑和 schema 决定；更换车辆或场景不要求重建相同静态索引，但会形成新的加载项目身份，并使可选物理派生缓存失效。全区强哈希在离线阶段计算。正常请求只校验 manifest 身份和将要读取的分片，不允许为了“验证缓存”再次扫描全区数据。

## 6. 多目标粗走廊与细格加载

### 6.1 不能只取一条粗路径

demo_v4 的现有候选池同时包含 distance、eta、terrain_risk、travel_cost、环境压力和 widest-path 方向。若只围绕单一粗路径加载细格，最快、最短、高通过性、经济性或独立备选可能在进入 `DeterministicParetoPlanner` 前就被裁掉。

粗层必须生成与现有目标族对齐的有界骨干集合：

1. 距离优先；
2. ETA/道路优先；
3. 地形风险或 travel cost 优先；
4. 环境压力优先；
5. widest/passability 代理；
6. 屏蔽主骨干父格后生成一条拓扑独立备选。

相同骨干去重后取父格并集，再向外扩张 1-ring。具体激活父格数只能由实测记录，不能预先承诺 30～60 个或“缩小 95%”。

### 6.2 有界扩张与失败语义

正常流程：

1. 在粗图吸附起终点父格；
2. 生成并合并多目标骨干；
3. 读取 1-ring 走廊的细格；
4. 执行细格物理评估、连通性和候选搜索；
5. 若硬约束、连续性或角色覆盖不足，扩大到 2-ring 重试一次；
6. 再失败则返回明确的连通性、物理证据或候选不足诊断。

正常交互入口不得静默回退到旧的 1,038 文件直线大缓冲慢路径。旧路径只作为开发期正确性参考入口保留，不作为生产快路径兜底。

## 7. 走廊内物理计算

### 7.1 首版策略

首版只离线保存车辆无关静态事实和边原语。每次正常路线请求在选中的细格走廊内复用现有 `evaluate_factor_model()` 语义计算：

- 节点可通行性和安全裕度；
- 有向坡度、推力平衡、ETA、地形风险和 travel cost；
- 环境压力距离；
- 请求期临时阻塞和复用惩罚；
- 候选级 `evaluate_path_metrics()` 精确累计；
- 连续轨迹、最小转弯半径和车辆外廓扫掠。

这保留了“用户只输入起终点，系统自动计算物理量”的业务语义，同时把计算范围从完整直线 ROI 缩到多目标走廊。

### 7.2 可选 Factor Cache

只有 I3 之后的计时证明 `factor_eval_s` 仍是最大瓶颈且导致 P95 超过 10 秒，才实施固定身份的派生缓存：

```text
identity = static_input_hash
         + topology_hash
         + vehicle_hash
         + factor_model_hash
         + scenario_hash
```

缓存只能保存该固定身份下的基础节点和有向边派生量。临时阻塞、复用惩罚、D* Lite 状态和用户本次起终点不得写入缓存。任何身份变化必须拒绝旧缓存并提示重建。

即使缓存命中，最终候选仍必须用权威有向边指标精确复算，并执行连续车辆几何验证。不得用缓存成功等价替代物理正确性。

## 8. 轻量结果、选择、重规划与 GPKG 解耦

### 8.1 `plan_ready` 同步产物

正常交互请求只同步生成：

- `route_plan.json`；
- `route_manifest.json`；
- 包含全部候选路线的单一轻量 GeoJSON，以 `is_recommended`、`is_selected`、`is_active` 字段表达状态，不再复制推荐、选中和活动路线图层；
- `routing_index_build_id`、激活父格集合、车辆/因子/场景哈希和诊断状态。

`route_manifest.json` 不再把 `routes.gpkg` 作为恢复路线图的唯一来源。重启后选择或重规划时，依据 build ID 和激活父格集合从不可变路由索引重新加载走廊，并校验相同身份。

### 8.2 选择和重规划

- 选择候选只原子更新 `route_selection.json`；若公开候选 GeoJSON 需要携带选中或活动状态，只重写该小型候选文件，不再生成 `selected_route.geojson` 或 `active_route.geojson` 路线副本；
- 选择操作不得复制或改写整个 `routes.gpkg`；
- 阻塞重规划从路由索引恢复走廊或使用当前内存上下文；
- 索引 build ID 或物理身份不匹配时明确拒绝恢复，不静默读取旧图；
- GPKG 尚未生成时，候选切换和阻塞重规划仍必须可用。

### 8.3 路线 GPKG 交付契约

面向用户和 QGIS 的默认 `routes.gpkg` 必须只包含 `main.route_candidates`。该图层至少保留：

- 路线几何；
- `candidate_id`、`roles`、`is_recommended`；
- `distance_m`、`eta_s` 及实际可用的 ETA 区间；
- `score_lower_min`、`terrain_risk`、`travel_cost`；
- `trajectory_status` 和实际启用时的 `environment_distance_m`。

`generation_profile`、`replan_profile` 和没有外部引用关系的 `trajectory_id` 应保留在 `route_plan.json` 诊断信息中，不应默认进入公开 GPKG。若后续存在明确的 QGIS 审计需求，可以按交付配置增加，不能提前固化为默认字段。

以下图层或表不得进入新的默认路线包：

- `h3_static_facts`、`h3_edges`：属于共享路由索引，不属于单次路线结果；
- `route_recommended`：与 `route_candidates.is_recommended` 重复；
- `route_selected`、`route_active`：与候选状态字段重复；
- 空的 `confirmed_blockages`：只有存在已确认阻断且用户要求空间交付时才创建。

路线目录不得复制完整 `tile_manifest.json`。`route_manifest.json` 只保存 `routing_index_build_id`、必要哈希、激活父格集合和恢复所需的最小身份信息。时间戳备份和 recovered GPKG 不属于默认交付契约；如需保留，必须由独立的数量或期限策略管理。

### 8.4 重型导出

- Web/桌面端在 `plan_ready` 后按需或后台生成符合 8.3 契约的路线 GPKG；
- UI 显示“路线已就绪 / 工程包生成中 / 工程包可下载”；
- CLI 正式交付命令可以继续等待全部文件，以保持批处理语义；
- `heavy_export_s` 单独报告，禁止计入路线搜索，也不得用排除导出来掩盖其他阶段耗时。

## 9. 实施增量

### I0：冻结证据、请求和性能基线

交付：

- 记录固定硬件、解释器、依赖版本、数据 build ID 和运行命令；
- 使用 `time.perf_counter()` 记录 `index_open_s`、`corridor_load_s`、`graph_build_s`、`factor_eval_s`、`coarse_search_s`、`candidate_search_s`、`geometry_s`、`plan_ready_s`、`heavy_export_s`；
- 记录加载文件数、原始行数、格数、边数、访问节点数、候选池数和输出字节数；
- 固化当前 Parquet 字段、显式类型、空值比例、压缩列块大小和 GPKG 图层/行数，作为字段裁剪前基线；
- 保存至少三组起终点的旧完整 ROI 结果，作为优化正确性参考；
- 冻结当前缺失物理输入清单和 `evidence_status`；
- 在 I0 结果中确定每个候选角色允许的指标差异阈值，实施中不得临时放宽。

准出：计时可复现；冷启动、热请求和重型导出已经分开；参考 RoutePlan 和原始日志可追溯。

### I1：生成并加载本地路由索引

交付：

- 新增最小 `routing_index.py`，负责 build ID、manifest、列存和粗图读写；
- 在完整瓦片建库末尾生成版本化索引并原子发布 `current.json`；
- 使用 5.2 的显式字段契约和 Arrow schema，删除行级邻接、边长及重复元数据，生成版本化土地覆盖映射表，并仅在存在可信土壤来源时生成土壤映射表；
- Web/桌面加载项目时验证索引并常驻粗图；
- 细格只按父格读取，正常规划不再逐个读取原瓦片。

准出：同一输入两次生成身份一致；失败不覆盖旧索引；所有分片 schema 完全一致；固定父格集合的规划事实与原瓦片逐字段一致；被删除字段没有运行时消费者；报告索引总体积和字段级压缩大小。

### I2：只输入起终点并生成多目标走廊

交付：

- 在线公开请求收敛为起点和终点；
- 其他配置由已加载项目身份提供；
- 实现与现有 objective/profile 对齐的粗骨干并集；
- 实现 1-ring 正常路径和一次 2-ring 有界扩张；
- 保留旧完整 ROI 入口仅供开发期 A/B 对照。

准出：三组起终点均不调用旧逐瓦片路径；走廊父格、细格数量和粗路径原因可审计；没有因单粗路径导致的固定角色回归。

### I3：把物理评估限制在走廊

交付：

- 在细格切片后调用现有物理评估链；
- 保留请求期环境压力、阻塞、复用惩罚和精确指标复算；
- 保留 `DeterministicParetoPlanner -> CandidateAggregator -> trajectory_geometry` 主链；
- 记录物理证据不完整和几何未评估状态。

准出：硬约束零容差；路径 H3 连续；相同输入确定；与 I0 参考结果的角色和指标差异不超过 I0 冻结阈值。

### I4：拆分轻量结果与重型交付

交付：

- RoutePlan 和轻量 GeoJSON 完成即报告 `plan_ready`；
- 选择与重规划不再依赖或改写完整 GPKG；
- route manifest 通过索引 build ID 和激活父格恢复走廊；
- GPKG 转为后台/按需导出，并严格执行 8.3 的单一默认路线图层契约；CLI 保留等待模式。

准出：GPKG 尚未生成时可以选择候选、重启恢复和执行阻塞重规划；默认 GPKG 只含 `main.route_candidates`；非空阻断数据仅在明确要求时附加；路线包不再包含静态格、全图边或完整 tile manifest。

### I5：只优化实测仍超预算的最大阶段

若 I1～I4 后 P95 已不超过 10 秒，停止实施，不增加 Factor Cache 或跨请求 Port-pair 缓存。

若仍超预算：

- `factor_eval_s` 最大：增加单一固定 identity 的 Factor Cache；
- `candidate_search_s` 最大：只缓存无阻塞、无复用惩罚且带完整 build/vehicle/factor/scenario/父格端口哈希的基础 pair；
- `corridor_load_s` 最大：调整 Row Group/分片布局和小型 LRU；
- 其他阶段最大：只处理该阶段，不同时引入多套优化。

## 10. 文件改动边界

预计新增：

- `src/h3_offroad_planner/routing_index.py`
- `tests/test_routing_index.py`

预计修改：

- `tiling.py`：在完整建库结束后发布路由索引；
- `routing.py`：索引读取、多目标粗走廊和有界扩张；
- `route_planning.py`：计时、已加载项目身份和快路径编排；
- `models.py`、`cli.py`、`desktop_client.py`、`web_console.py`：区分内部项目配置与用户可见起终点请求；
- `factor_model.py`：支持走廊范围评估；只有 I5 触发时才增加派生缓存读写；
- `route_persistence.py`、`replanning.py`：选择/恢复/重规划脱离 GPKG；
- 相关现有测试：增加索引往返、身份失效、A/B 正确性和无 GPKG 重规划覆盖。

不新增索引服务、仓库层、工厂、注册中心、Redis、SQLite 路由库、PostGIS、Neo4j、消息队列、进程池或 GPU 方案。使用项目已有 Python、PyArrow/Parquet 和现有调用链。

## 11. 验收矩阵

| 场景 | 必须满足 |
|---|---|
| 数据就绪 | manifest 明确列出 evidence_status；缺失车身或水文/土壤参数时不宣称实车物理完备 |
| 索引确定性 | 同一输入生成相同身份；新索引失败不覆盖旧可用索引 |
| 加载底图 | 加载完成代表路由索引可用，不只是地图显示或 manifest 被读取 |
| 用户输入 | 正常 UI 规划只要求起点和终点；固定车辆/因子/场景来自项目身份 |
| 冷启动 | 单独报告索引打开和粗图加载，不与热请求混算 |
| 热请求 | 三组起终点各预热一次、连续运行五次，汇总 `plan_ready_s` P95 ≤ 10 秒 |
| I/O 快路径 | 不逐个打开旧 ROI 的 1,038 个瓦片，不扫描全区哈希，不运行原始 GIS 处理 |
| Parquet schema | 所有分片字段和类型一致；不存在 Arrow `null` 物理类型；行级不含邻接 JSON、边长或索引级重复元数据 |
| 多候选 | 粗层覆盖现有目标族；角色可用性不低于 I0 固定参考，缺失时输出原因 |
| 物理正确性 | 全部硬约束零容差；路径连续；最终指标精确复算；连续车辆几何状态真实报告 |
| 动态覆盖 | 临时阻塞、环境压力和复用惩罚保持请求期生效，不污染静态索引 |
| 恢复与重规划 | GPKG 不存在或仍在生成时，选择、重启恢复和阻塞重规划可用 |
| 重型导出 | `heavy_export_s` 独立；默认 GPKG 只含 `main.route_candidates`，可选图层必须非空且由明确交付需求触发 |
| 资源 | 记录冷/热峰值内存、索引磁盘体积和缓存命中；不得以全区 Python 对象图常驻换速度 |
| 质量 | 当前收集到的 pytest 行为测试和 Ruff 全部通过，并增加本方案最小必要测试 |

## 12. 停止条件与明确不做

达标即止：I1～I4 后若性能和正确性矩阵通过，不实施 I5。

明确不做：

- 不降低 res14/res11；res14 约为米级细格，不称为亚米级；
- 不用单一路径或单一粗走廊冒充多候选；
- 不删除推力、坡度、土壤、环境压力、连续几何或独立备选语义；
- 不把缺失物理数据缓存成已验证事实；
- 不照搬 demotest 的全图内存对象或 pickle 车型关口图；
- 不让旧静态索引静默兼容新数据或新 schema，也不让旧物理派生缓存兼容新车辆、因子或场景；
- 不让正常请求回退到分钟级逐瓦片全图流程；
- 不把 GPKG 导出移出计时后宣称搜索本身已经提速；
- 不恢复已删除的复杂门禁，也不新增仅为未来可能需求服务的抽象层。
