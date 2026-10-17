# M1 阶段综合审核报告（提交 `8c6fcb6`）

- **审核日期**：2026-10-17
- **审核对象**：工作树 `D:/Workspace/demo_v4-manned-offroad`，分支 `codex/manned-offroad-map`，HEAD `8c6fcb658dd95857a14f0f35d1c3c39854d9695e`（提交时间 2026-10-16 21:10:39 +0800）
- **历史基线**：`986bd58`；上位依据 `docs/project_context/IMPLEMENTATION_PLAN.md` v1.0 §4 M1、§5.1、§5.2、§9.1、§9.2
- **合并的前序审核**：M1_ARGON1909_AUDIT_20261016.md（审核方 A / GPT）、`.artifacts/20261017-talk/argon1358.md`（审核方 B / Gemini 初版）、`.artifacts/20261017-talk/argon1509.md`（审核方 B / Gemini 融合版）
- **本报告性质**：第三方合并复核。对前两份报告的每条主张重新取证，采信者标注来源，改正者单列 §7，未被任何前序报告覆盖的发现标注「本次新增」。

## 结论

**M1 不通过签收，禁止启动 M2。**

R1 的道路宽度元数据解码、R2 的干密度换算与回归系数、R4 的正切代数式、以及回归测试，均有真实代码改动并可重复验证（538 passed / 4 skipped）。但 R2、R3、R4、R5、R6 五项的真图验收证据不成立，根因不在"脚本写得不够细"，而在三层：

1. **数据层**：真实瓦片缓存中土壤与水文的承载列**全部为空**，M1 声称的"物理通行属性"没有输入；
2. **代码层**：生产因子链存在两处会让物理量静默失效的缺陷（沉陷降速被静态查表短路、CI 阈值双源）；
3. **证据层**：消融脚本自造评价器、伪造输入常量、静默替换 OD 端点，并把 5 个重叠走廊相加冒充全工区统计。

因此当前产物最多支持「在真实 QDX 缓存图上做了一次**未接入真实土壤/气象输入**的敏感性原型」，不支持"CLDAS 已接入""真实天气已修正""Bekker/CI 已在真图验证""5 组指定 OD 完成端到端规划"，更不支持车辆可通过或现场有效性结论。

## 1. 审核方法与证据边界

### 1.1 本次实际执行的验证

| 项目 | 命令 / 方法 | 结果 |
|---|---|---|
| 工作树与分支 | `git rev-parse`、`git log`、`git status -s` | HEAD `8c6fcb6`，分支正确；唯一未跟踪文件为此前审核报告 |
| 源码核查 | 通读 `run_m1_ablation.py`（683 行）、`factor_model.py` 相关区段、`bekker.py`、`vectorized_soil.py`、`scene.py`、`grid/h3_grid_builder.py`、`route_planning.py` | 见 §5、§6 |
| 专项回归 | `python scripts/run_local.py pytest tests/test_m1_ablation.py tests/test_static_scene.py tests/test_vectorized_factor.py -q` | **43 passed in 1.90s** |
| 全量回归 | `python scripts/run_local.py pytest tests/ -q` | **538 passed, 4 skipped in 18.89s** |
| 锥指数复算 | 按 `bekker.py:66-75` 公式独立计算 | `CL` 在 θ=0.308 → **665.19 kPa**（m_g=22.158%） |
| 瓦片数据实测 | pyarrow 读取 `outputs/baseline_986bd58/qdx_tiles/routing_index/builds/1d6cd6e179cf10167c9e7355/cells/part-00000.parquet`（该 build 唯一 cells 分块，2,251,004 行） | 见 §5 P0-1、§8.2 |
| 引文核验 | 对前两份报告的 9 处「文件:行号」逐条定位 | 见 §7.2 |
| 产物绑定 | `m1_ablation.json` 内 `git_commit`/`timestamp` 与文件 mtime 三方比对 | 绑定当前 HEAD，写出于 2026-10-16 22:57:44（提交 21:10 之后） |

**未执行**：未重跑 `m0-baseline` 与 `m1-ablation`。理由：`outputs/` 被 .gitignore:47 忽略，重跑会覆盖送审产物并破坏其时间戳证据；现有产物已由 `git_commit` 字段、`timestamp` 与 mtime 三方绑定当前 HEAD，且审核方 A 报告了同参数的独立复跑（`plan_ready_s=73.86276`，与 `outputs/m0_qdx_baseline/m0_baseline.json:88` 一致）。**本报告的全部数值结论均可在重跑后复核，重跑是重新签收的前置条件（§9）。**

### 1.2 一条必须记录的环境陷阱

在工作树内直接执行 `python -c "import h3_offroad_planner"`，解析到的是 **`D:\Workspace\demo_v4\src\h3_offroad_planner\__init__.py`（另一个工作树）**，不是本树 `src`。已实测确认。任何绕过 `scripts/run_local.py` 的临时校验、脚本或 CI 步骤，都可能测到另一份代码而得出虚假结论。本报告的全部测试均通过 `scripts/run_local.py` 执行——该入口优先导入本树 `src` 并把同一路径传给子进程。

## 2. 事实基线

| 事实 | 值 |
|---|---|
| 消融产物 | `outputs/m1_ablation/m1_ablation.json`（18,289 B）、`m1_ablation_summary.md`（4,782 B） |
| 产物 git_commit | `8c6fcb658dd95857a14f0f35d1c3c39854d9695e` |
| 产物 timestamp | `2026-10-16T14:57:44.417631+00:00`（= 本地 22:57:44） |
| 走廊格元（5 个 OD 相加） | 454,475 |
| 走廊有向边（5 个 OD 相加） | 2,133,478 |
| 车辆 | Iveco Daily 4x4：2,968 kg，宽 2.056 m，离地间隙 0.225 m，爬坡 31.0°，横倾 25.0° |
| CLDAS 母文件 | `m0_qdx_scene.json:163-165` 登记的 3 个 `.nc` 文件**存在**（约 2.6 MB/个） |
| D 场 | `D:/Workspace/demo_v4/outputs/qdx_hydrology_upstream_v1/drainage_sensitivity.tif`（脚本内硬编码绝对路径） |

## 3. R1–R6 判定矩阵

| 编号 | 判定 | 已核实的事实 | 不能据此宣称的结论 |
|---|---|---|---|
| **R1** 道路 Width | **部分通过** | `scene.py:132-163` 实现 `resolve_road_effective_width_m`：`>=15.0` 才乘 0.1，最终 `clip(2.0, 15.0)`；`30→3.0`、`55→5.5`；场景契约记录 `width_unit_or_scale="0.1m"` 与 `[3.0,5.5]` | 生产使用仅 `scene.py:694` 一处（场景审计），**未进入建图、缓冲或评价**。仅完成"元数据解码"，道路面/走廊未按 3–5.5 m 建成 |
| **R2** Bekker/CI | **公式通过，真图验收失败** | `vectorized_soil.py:28` 干密度换算、`:103`/`:106` 回归系数；`bekker.py:120-123` 已不再注入 `inf`。复算 `k_c`（黏壤土，10%→40%）= 1130.4→94.5，与方案引文吻合 | A1b 与 A1a 每一格、每一条边、每一组 OD 完全相同；脚本层未算沉陷；生产层沉陷被静态查表短路（§5 P0-4）；**且瓦片中无任何土类与含水率取值**（§5 P0-1）。真图 Bekker/CI 判别**从未发生** |
| **R3** CLDAS/D/天气 | **不通过** | D 场 TIFF 确实被逐格采样并写入 `drainage_sensitivity` | 未打开任何 CLDAS `.nc`；含水率写死 0.3080（`run_m1_ablation.py:83`、`:468`）；降雨压力写死 0.8（`:484`）；天气 JSON 只进元数据（`:573`），`DRY_WEATHER_PATH` 定义于 `:63` 后从未使用 |
| **R4** 纵横坡 | **部分通过** | `factor_model.py:1537-1546` 正切分解精确；标量/向量化一致；`:1451-1459` 的 `hard_codes` 已无 `STEEP_SLOPE` | `factor_model.py:1567` 传入的是 `max(source_cell.slope, target_cell.slope)`，不是同点位 DEM 梯度在切向/法向的投影。"零误差"只对代数式成立 |
| **R5** 真图消融 | **不通过** | 产物记录了当前 HEAD 与 5 个 OD 的输出 | 自造评价器与 Dijkstra（`138-384`），未调用 `evaluate_factor_model`；`c.uscs="CL"` 伪造（`:95-96`）；454,475 为 5 个重叠走廊相加（`:507`）；`od_04` 起点静默平移 290.56 m（`:386-435`） |
| **R6** 文档对齐 | **不通过** | OD ID 与合成天气文件名已更新 | `STATE.md:47`「已完成闭环」、`:57`「全面打通」、`DECISIONS.md:44`「真实栅格采样」均无证据；`STATE.md:55` `min_cone_index_kpa: 150` 与 `factor_model.py:613`/`:1730` 及 `configs/static_factor_model.yaml:31` 的 185.73 冲突 |

## 4. 消融产物的实测数值（送审原文，未经改动）

| 档位 | 可通行格元 / 走廊格元 | 可通行有向边 / 走廊边 | 原因码统计 |
|---|---:|---:|---|
| A0 | 362,621 / 454,475 | 2,118,222 / 2,133,478 | `BUILDING:28696, STATIC_BLOCKED:91187, STEEP_SLOPE:1147` |
| A1a | 359,518 / 454,475 | 2,099,240 / 2,133,478 | 追加 `ROWSPACING_BLOCKED:3113, WATER:28696, WATER_DEPTH_LIMIT:62491` |
| A1b | 359,518 / 454,475 | 2,099,240 / 2,133,478 | 与 A1a 逐项相同 |
| A1c | 359,518 / 454,475 | 2,099,240 / 2,133,478 | 与 A1b 逐项相同 |
| A2 | 360,175 / 454,475 | 2,099,528 / 2,133,478 | 去掉 `STEEP_SLOPE`，其余同 A1c |

| OD | 吸附(起/终) | A0–A1b 距离(耗时/成本) | A1c 距离(耗时/成本) | A2 距离(耗时/成本) |
|---|---|---|---|---|
| `od_01_primary` | 0.00 / 0.00 m | 731.33 m (50.94 s / 742.19) | 873.52 m (57.69 s / 884.05) | 873.52 m (57.69 s / 884.11) |
| `od_02_forest_rowspacing` | 0.96 / 1.10 m | 576.70 m (42.16 s / 586.24) | 728.68 m (49.67 s / 757.06) | 728.68 m (49.67 s / 757.12) |
| `od_03_water_gully` | 1.14 / **40.63** m | 451.88 m (27.22 s / 457.66) | 451.88 m (27.66 s / 853.55) | 451.88 m (27.48 s / 853.69) |
| `od_04_narrow_road` | **290.56** / **34.01** m | 353.99 m (17.68 s / 358.09) | 353.99 m (18.44 s / 358.30) | 353.99 m (18.44 s / 358.33) |
| `od_05_slope_traverse` | 25.51 / 0.35 m | 919.23 m (51.66 s / 927.72) | 919.23 m (50.98 s / 1231.76) | 919.23 m (52.66 s / 1231.60) |

由此可直接读出三个结论：**A1b 相对 A1a 完全空转**；**A2 只把 657 个格元从不可通行改为可通行，但没有任何一条 OD 使用到它们**（五组距离全等，成本差仅 0.06–0.16，相对不超过 0.02%）；**od_04 的"路线"只有 353.99 m，而起点被挪了 290.56 m**——该结果已不回答 `m1_benchmark_ods.json` 提出的问题。

## 5. 阻断项（必须全部关闭后方可重新提请签收）

### P0-1（本次新增，前置）真实瓦片没有土壤与水文输入

- **现象**：`cells/part-00000.parquet`（2,251,004 行，该 build 唯一分块）中：

  | 列 | 非空行数 |
  |---|---:|
  | `soil_moisture` | 0 |
  | `soil_code` | 0 |
  | `soil_source` | 0 |
  | `drainage_sensitivity` | 0 |
  | `surface_response` | 0 |

  且**不存在** `uscs` / `soil_type` 列。
- **机制**：列存在但从未被赋值，说明土壤栅格（`soil_nanjing.tif` + `.vat.dbf`）与 CLDAS 从未进入建图。于是 `run_m1_ablation.py:92-98` 的两个伪造动作成了整条链路唯一的"输入来源"：`c.soil_moisture = 0.3080`、`c.uscs = "CL"`。
- **影响**：A1b 的"物理判别"不可能成立——不是没算，是没有可算的输入。若按前序报告"保留 `None`、报 `MISSING_SOIL`"整改，结果只会从"全图 CL"变成"全图 MISSING_SOIL"，判别力仍为 0。**R2 的真图验收在数据接入完成前不可达。**
- **整改**：先完成 `soil_nanjing.tif`(+VAT) → USCS/Bekker 土类 → 瓦片 `soil_code`/`uscs` 的建图接入，并把 CLDAS 采样值写入 `soil_moisture`；然后在消融中如实统计"已知/未知土类格元数"。禁止以 `CL` 兜底。
- **验收**：产物中出现非零的土类分布直方图与 `MISSING_SOIL` 计数；对同一 OD 改变土类或含水率能改变节点/边指标。

### P0-2 消融脚本以常量伪造真实输入

- **证据**：`:83` 形参默认 `cldas_moisture=0.3080`；`:468` 固定传入 0.3080；`:92` 整图赋值；`:484` `rainy_pressure = 0.8`；`:95-96` `c.uscs = "CL"`；`:60` 硬编码旧工作树绝对路径 `D:/Workspace/demo_v4/...`。
- **影响**：M1 无法区分格元间含水率差异、天气时相与无数据区；`datasets` 段（`:570-574`）把常量包装成"CLDAS 静态含水率"写进产物，构成对证据的失真陈述。
- **整改**：以 `StaticScene` 登记项为唯一来源驱动一个采样适配器；记录每个栅格的路径、band、CRS、分辨率、时间、nodata、SHA-256、有效采样率与逐格值；天气快照必须被解析为压力/含水率修正并真实改变结果；合成场景在代码与报告中标 `synthetic_sensitivity_scenario`。D 场路径从场景配置读取，禁止硬编码。
- **验收**：修改天气 JSON 参数或 CLDAS 采样值，正式评价链输出必须改变；产物含全部输入哈希。

### P0-3 消融绕过正式评价链，导致 A1b 空转

- **证据**：脚本自写 `evaluate_level_nodes`（`:138-209`）、`evaluate_level_edges`（`:212-294`）、`dijkstra_shortest_path`（`:297-384`）；导入清单（`:38-47`）无 `evaluate_factor_model`。A1b 分支只调 `compute_cone_index_kpa`（`:198-201`），从不计算沉陷。边速度（`:260-263`）只含坡度惩罚与地物系数，**不含土壤、株距、涉水任何降速因子**。
- **为什么 A1b 恒等于 A1a**：全图 `CL` + θ=0.308 → CI = **665.19 kPa** 远大于 185.73，`CONE_INDEX_INSUFFICIENT` 永不触发；而边速度本就不含土壤项。两个条件叠加使 A1b 在数学上不可能产生任何差异。
- **整改**：删除私有评价器；把 A0/A1a/A1b/A1c/A2 设计为 `FactorModelConfig` 的显式开关，每档统一调用 `evaluate_factor_model`（并校验标量与 `vectorized_factor` 逐元素一致）与 `evaluate_path_metrics`（`factor_model.py:1017`，已存在）。
- **验收**：每一档至少在目标 OD 上产生非零的距离/ETA/成本或原因码变化，且变化可由该档唯一变量解释。

### P0-4 生产因子链两处使物理量静默失效（审核方 B 首先发现，本次复核成立）

1. **沉陷降速被静态查表短路**：`factor_model.py:1399-1401` 中 `configured = config.soil_speed_by_uscs.get(cell.uscs)` 非空即 `value = configured` 直接返回，其后的 `soil_mobility`（`:1402`）与 `sinkage`（`:1404`）分支永不执行。消融配置恰好配了 `{"CL":0.5,"SM":0.7}`，于是**沉陷增加不改变节点速度**。注：沉陷仍影响 `SINKAGE_CLEARANCE_EXCEEDED` 硬阻断（`:1449`）与安全裕度（`:1481-1483`），故准确表述是"对节点速度失效"，不是"完全丢弃"。
2. **CI 阈值双源**：`:1367` 与 `:1388` 使用硬编码 `CI_THRESHOLD_KPA`（`bekker.py:17` = 185.73）把 `soil_mobility` 置 0，而 `:1446` 用 `config.min_cone_index_kpa` 判 `CONE_INDEX_INSUFFICIENT`。若按文档把配置改为 150，CI 落在 [150, 185.73) 的格元将**速度归零却不产生任何阻断原因码**——静默不可通行。这正是 `STATE.md:55` 与代码不一致的真实危害。

- **整改**：(a) 基准土类速度与沉陷退化因子 `max(floor, 1 - z0/z_limit)` 结合（取乘或取小），使沉陷真实改变 `eta_s`/`travel_cost`/`safety_margin`；(b) 全部阈值单一来源为 `config.min_cone_index_kpa`；(c) 统一配置值并在产物中回显实际生效值。
- **验收**：新增回归——同一格元在 θ 从 0.10 变到 0.40 时，沉陷增加必须带来速度下降或阻断，且阻断码与配置阈值一致；标量与向量化结果逐元素一致。

### P0-5 OD 端点被静默替换，至少一条结果无效

- **证据**：`find_best_od_endpoints`（`:386-435`）在前 5 大连通分量中重选起终点，无距离上限、无拒绝分支，且在**档次评价之前**执行，不按各档 `nodes` 重新校验。产物只留偏移标量（`:518-530`），不留替换后的 H3 ID、坐标或拒绝原因。
- **实测偏移**：`od_04` 起点 **290.56 m** / 终点 34.01 m（路线全长 353.99 m）；`od_03` 终点 40.63 m；`od_05` 起点 25.51 m。
- **整改**：声明固定上限（如 `max_snap_distance_m`），在当前档位的 `node_metrics` 上校验；超限输出 `OD_ENDPOINT_UNAVAILABLE` / `OD_DISCONNECTED`，禁止跨分量换点。若某组坐标确系选点失误（`od_04` 起点落在水深 > 0.5 m 的水塘），应**在有正射/矢量证据的前提下修正基准配置文件并记录版本**，而不是运行时静默跳点。
- **验收**：产物为每组 OD 输出原始坐标、实际 `start_h3`/`goal_h3` 及经纬度、`snap_m`、端点状态、`h3_path` 全序列；所有 OD 满足声明上限或如实失败。

### P0-6 统计口径与可追溯性不足

- **证据**：`:507` 的 `total_cells_all += total_cells` 把 5 个重叠 2-ring 走廊相加（454,475 约等于 5 × 90,895），产物字段却名为 `total_corridor_cells` 并在文档中被表述为"全工区"；原因码在 `:512-514` 按"每格每条原因"累加，多原因格元被重复计数；产物无 tile manifest 哈希、场景哈希、OD 配置哈希、CLDAS/D 场哈希与有效像元覆盖率。
- **整改**：统计口径拆成「5 个 OD 走廊的**去重并集**」与「**各 OD 独立**」两套；原因码另给"触发格元数（去重）"与"原因标签数"两个口径；补齐全部输入哈希与覆盖率。
- **验收**：并集格元数不超过单走廊之和且可独立复算；产物中的 git_commit、哈希、时间戳与运行环境一致。

## 6. 重要非阻断项

| 编号 | 问题 | 证据 | 整改 |
|---|---|---|---|
| **P1-1** | 横坡仍是"格元坡度代理量"分解 | `factor_model.py:1567` | 接入同点位 `(dz/dx, dz/dy)` 按边方位投影；若留待 M2，必须在代码注释、`STATE.md` 与报告中撤回"对真实地形横坡零误差"的表述 |
| **P1-2** | `is_water` 判据污染原因码（**本次新增**） | `factor_model.py:1428-1432`、`run_m1_ablation.py:171-175` 用 `lc_factor == inf` 判水体，而 `h3_grid_builder.py:66-73` 中 0/5/6（未分类/水体/建筑）**同为 inf** | 改按 `landcover_code == 5` 判水体。实测：code 6 建筑 273,163 格，`depth` 全空、`lc_factor` 全 inf、`is_passable` 全 False，被打 `WATER`；这正好解释 `WATER:28696 == BUILDING:28696` 且加 `WATER_DEPTH_LIMIT:62491` 等于 `STATIC_BLOCKED:91187`。**A1a 中 28,696 个"水体"其实是建筑** |
| **P1-3** | "浅水涉水放行"在本工区无实例 | 实测水体 385,189 格，`depth` 取值 **0.5–2.5 m**，`<= 0.225 m` 的数量为 **0** | 涉水放行属代码卫生（水体在建图时即 `is_passable=False`，见 `route_planning.py:892`；且 `_hard_constraints` 首行即按 `is_passable` 记 `STATIC_BLOCKED`，在该层改不出效果）。**不得把它设为一个消融档位**，也不得据它解释 A1a 的变化 |
| **P1-4** | R1 阶段状态与裁剪范围需明示 | `scene.py:160-163`：`>=15.0` 才缩放，`clip(2.0,15.0)` | 文档明确"完成的是元数据解码与场景契约注入"，道路面缓冲与格内片段属 M2；区分通用合法范围 [2,15] 与 QDX 观测范围 [3.0,5.5] |
| **P1-5** | 摘要文字硬编码 | `run_m1_ablation.py:629-641` 写死"A0 穿林漏阻""A1b/A1c 准确反映含水率 0.308 下的土壤机动性"等与表格矛盾的句子 | 删除该模板，全部对比文字由各档实测差值生成 |
| **P1-6** | 文档超前与残留 | `STATE.md:47`「已完成闭环」、`:57`「全面打通」、`:44`「520 passed」（实测 538）；`STATE.md:55` 的 150 与代码 185.73；`configs/scenes/rainy_weather.json`（798 B）与 `synthetic_rainy_weather.json`（798 B）并存，"正名"实为新增未删 | 以复跑产物重写；统一阈值来源；删除遗留旧配置 |

## 7. 与前序三份审核的差异与纠错

### 7.1 采信与更正

| 主张 | 出处 | 本报告判定 |
|---|---|---|
| "M1 不通过签收，禁止进入 M2" | A / B-1509 | **采信**。B-1358 的"有条件通过核心算子"不予采纳：其自列的缺陷 1/4/5 任一成立，R5 验收条件即不成立 |
| "有条件通过核心算子" | B-1358 | **驳回**。措辞与自身证据不自洽 |
| R4 达标 | B-1358 | **改为部分通过**。代数式精确，但输入是 `max(slope_a, slope_b)` 代理量（`factor_model.py:1567`） |
| `min_cone_index_kpa: 150` 在 `DECISIONS.md` | A | **更正**。`DECISIONS.md` 无此字段；实际在 `STATE.md:55` |
| `min_cone_index_kpa: 150` 在 `STATE_2.md:86` | B-1358 | **更正**。该文件不存在；实际 `STATE.md:55` |
| 产物写出于 `2026-10-16T22:57:44+00:00` | A | **更正**。JSON 内为 `14:57:44+00:00`（本地 22:57:44），UTC/本地混用 |
| `CL` 在 θ=0.308 的 CI 约 266.8 kPa | B-1358 | **更正**。实算 **665.19 kPa**；266.8 kPa 对应 θ 约 0.399 |
| "WATER:28696 + WATER_DEPTH_LIMIT:62491 恰等于 STATIC_BLOCKED:91187，说明水深被预锁死" | B-1358 | **半采信**。结论（水深规则零增量）正确；机制归因不完整——`WATER:28696` 实为**建筑**误标（见 P1-2） |
| "应删除 `c.uscs='CL'`，保留 `None` 并报 `MISSING_SOIL`" | A / B-1509 | **采信但不足**。瓦片中土壤列**全空**（P0-1），仅改兜底会得到"全图 MISSING_SOIL"。必须先补数据接入 |
| "允许浅水涉水放行（改 `_hard_constraints`）" | B-1358 / B-1509 | **降级为 P1-3**。本工区无 `depth <= 0.225 m` 的水体；且修复层级错误 |
| "把 5 组 OD 吸附压到 15 m 内并确保 A0 穿林、A2 恢复斜切" | B-1358 | **驳回"确保"**。改坐标可以，但须有正射/矢量证据并记录版本，不得以"出现预期差异"为修订依据；上限取值应有依据而非 15 m |

### 7.2 引文可靠性（这是选择采信哪份报告的关键依据）

对 B 的两版报告共取样 9 处「文件:行号」，逐条定位，**全部落空**：

| 引用 | 实际该行内容 | 应指向 |
|---|---|---|
| `run_m1_ablation.py:56` | 空行 | `DRAINAGE_PATH` 在 60 |
| `:344` | `path_cells.append(p)`（Dijkstra 内） | — |
| `:360` | `try:`（grid_disk 内） | — |
| `:274` | 阻抗注释 | `find_best_od_endpoints` 在 386 |
| `:472` | `find_best_od_endpoints` 调用 | `generate_markdown_summary` 在 581 |
| `factor_model.py:730` | `FactorEvaluation` 邻接缓存 | `_soil_speed_interval` 在 1335 |
| `:768` | `decision` 配置键 | 沉陷短路在 1399-1401 |
| `:787` | `request_pressures` | `_hard_constraints` 在 1417 |
| `:863` | hydrology backend 报错 | `max(source,target)` 在 1567 |

A 报告的行号则**逐条精确**（1537-1546、1563-1569、613、1730、80-98、297-384、386-435 全部命中）。故本报告的结论框架采信 A，代码细节采信 B 的**内容**、一律不采信其**位置**。B-1509 已吸收 A 的结论与 P0 结构，判定已更正为"不通过"，但引文未重算，且新增 `:344/:360` 两处无效引用——它修正的是"观点"，不是"证据"。

## 8. 复算与实测附录

### 8.1 锥指数

按 `bekker.py:66-75`：`CI = exp(a + b*ln(m_g)) * 6.89476`，`m_g = θ * ρ_water / ρ_d * 100`。

| 土类 | ρ_d | θ=0.308 时 m_g | CI (kPa) |
|---|---:|---:|---:|
| CL | 1.390 | 22.158% | **665.19** |
| ML | 1.180 | 26.102% | 409.58 |
| SM | 1.474 | 20.896% | 242.48 |
| CH | 1.370 | 22.482% | 1335.28 |

全部远高于 185.73，故全图 `CL` 不可能触发 `CONE_INDEX_INSUFFICIENT`。

### 8.2 瓦片土层与水体实测（该 build 唯一 cells 分块，2,251,004 行）

| landcover_code | 格元数 | `is_passable=True` | `depth` 为空 | `lc_factor=inf` |
|---|---:|---:|---:|---:|
| 1 农田 | 503,982 | 503,982 | 503,982 | 0 |
| 2 林地 | 640,927 | 640,927 | 640,927 | 0 |
| 3 草地 | 51,484 | 51,484 | 51,484 | 0 |
| 4 灌木 | 80,405 | 80,405 | 80,405 | 0 |
| 5 水体 | 385,189 | **0** | 0 | 385,189 |
| 6 建筑 | 273,163 | **0** | **273,163** | 273,163 |
| 7 裸地 | 241,878 | 241,878 | 241,878 | 0 |

读法：水体与建筑在建图时即全部不可通行；建筑无水深字段，被 `lc_factor==inf` 判为水体，记 `WATER`。水体水深刻度 0.5–2.5 m，无浅水格元。

### 8.3 测试

- 专项：`test_m1_ablation.py` + `test_static_scene.py` + `test_vectorized_factor.py` 共 43 passed。
- 全量：538 passed, 4 skipped。
- `tests/test_m1_ablation.py` **不调用** `run_ablation` / `enrich_graph_with_cldas_and_hydrology`，故对上述 6 个阻断项无覆盖能力。

## 9. 整改顺序与重新签收门槛

**顺序不可调换**（P0-1 是其余项能否被观测的前提）：

1. **P0-1** 土壤/水文入图（数据接入）——否则后续任何消融都无判别力；
2. **P0-2、P0-3** 去除伪造常量、删除私有评价器，统一走 `evaluate_factor_model` + `evaluate_path_metrics`；
3. **P0-4** 修生产因子链（沉陷调制、阈值单源），否则 A1b 在正式链上仍为空转；
4. **P0-5** 端点上限与显式失败；
5. **P0-6** 统计口径与输入哈希；
6. **P1-1 至 P1-6** 边界声明与文档清理。

**必须新增的回归**（建议新建集成测试文件，不要塞进现有单元测试）：

- CLDAS/D 场栅格的 CRS、nodata、逐格差异（拒绝常数覆盖）；
- 修改天气快照参数必须改变正式评价链输出；
- `uscs=None` 保持未知并计 `MISSING_SOIL`，不被伪造为 `CL`；
- θ 变化 → 沉陷变化 → 速度/阻断变化（标量与向量化一致）；
- 端点超限返回不可用状态，不跨分量跳点；
- 产物含哈希、去重并集统计、端点偏移与 `h3_path`；
- `is_water` 仅对 `landcover_code==5` 生效，建筑不得记 `WATER`。

**签收命令**（按序全部通过）：

```powershell
python scripts/run_local.py verify
python scripts/run_local.py m0-baseline
python scripts/run_local.py m1-ablation
python scripts/run_local.py pytest tests/test_m1_ablation.py -v
python scripts/run_local.py pytest tests/ -q
git status -s   # 必须为空（本报告与复跑产物除外）
```

**硬性判据**：A0 至 A2 每一档至少在目标 OD 上产生可由该档唯一变量解释的非零变化；5 组 OD 端点均在声明上限内或如实失败；产物中每个数值都能追到输入哈希；文档只陈述这些可验证事实。

## 10. 声明边界

即便上述全部关闭，M1 通过也**只说明静态地图物理评价与路线计算在一致性上成立**。它不等于格网几何连续、不等于道路面可通行、不等于车辆能通过，更不等于实车验证。M1 不覆盖片段与局部多通道（M2）、路线质量与预算（M3–M5）。任何"已消除陡坡误阻""已规避湿软冲沟""真实气象已修正"的表述，在对应档位没有真实非零差异前，均不得写入 `STATE.md`、`DECISIONS.md` 或交付报告。
