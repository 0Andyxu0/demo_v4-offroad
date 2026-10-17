# M1 第二轮整改审核报告（提交 `4559c74`）

- **审核日期**：2026-10-17
- **审核对象**：`D:/Workspace/demo_v4-manned-offroad`，分支 `codex/manned-offroad-map`，HEAD `4559c744e125fd450b1b272f427658d9c5815eff`
- **被审提交**：`92afa6a`（P0/P1 整改）、`4559c74`（并集统计与回归）
- **整改依据**：[M1_CONSOLIDATED_AUDIT_20261017.md](M1_CONSOLIDATED_AUDIT_20261017.md)；整改方自述：`.artifacts/20261017-talk/gemini1937.md`
- **前序提交**：`8c6fcb6`（上一轮不通过）

## 结论

**仍未达到签收门槛，不启动 M2；但本轮整改的工程质量显著高于前两轮，约 80% 的整改项真实闭环。**

必须区分两件事：

1. **代码是真的改了。** 私有评价器已删除、改走 `evaluate_factor_model` 与 `evaluate_path_metrics`；消融档位改成了 `FactorModelConfig` 显式开关；`is_water`、CI 阈值双源、沉陷降速短路、OD 静默跳点、走廊相加统计、硬编码叙述这六个老问题都已实质修复；新增回归 20 项、全量 547 passed / 4 skipped（我已独立复跑，数字吻合）。
2. **证据仍未达标。** 本轮新引入一个阻断级缺陷（栅格采样半像元偏移），并且 A1a、A2 两个档位在各自的目标 OD 上仍然是**严格零变化**——这正是上一轮判据第 1 条要解决的问题，换了实现方式但没换结果。

因此判定为**有条件迭代**：只需修 3 项（N-1 采样、N-2 档位可观测性、N-3 叙述纠偏），即可再次提请复核；不需要重做架构。

---

## 1. 审核方法与证据边界

| 项目 | 执行内容 | 结果 |
|---|---|---|
| 提交与工作树 | `git rev-parse` / `git log` / `git status -s` | HEAD `4559c74`，工作树干净 |
| 代码增量 | `git diff --stat 8c6fcb6..HEAD`（12 文件，+1850/−670）+ 逐段读 factor_model / scene / run_m1_ablation | 见 §2 |
| 专项回归 | `pytest tests/test_m1_consolidated_regression.py tests/test_m1_ablation.py -q` | **20 passed in 0.43s**（与自述一致） |
| 全量回归 | `pytest tests/ -q` | **547 passed, 4 skipped in 17.55s**（与自述一致） |
| 产物解析 | 解析 `outputs/m1_ablation/m1_ablation.json`（287,687 B）全部 level / OD / union 字段 | 见 §4、§6 |
| 栅格实测 | 用 rasterio 读 CLDAS/土壤/D 场元数据与像元值，并与代码采样算法逐点对比 | 见 §3 |
| 产物绑定 | JSON 的 `execution_commit` / `timestamp_utc` 与 mtime 比对 | 绑定 `4559c74`，写出于 2026-10-17 17:40（提交 17:37 之后） |

**未执行**：未重跑 `m1-ablation`（`outputs/` 被 .gitignore 忽略，重跑会覆盖送审产物）。所有数值均取自送审产物，可用 §8 的命令复现。

---

## 2. 整改达成度矩阵

| 编号 | 上一轮要求 | 本轮实现 | 判定 |
|---|---|---|---|
| **P0-1** 真实栅格接入 | 删除 0.3080/0.8/`CL` 常量；从 `StaticScene` 采样并记录哈希 | 新增 `scene.py:1073` `enrich_graph_from_static_scene`；土壤走 `.vat.dbf` 目录映射 USCS，CLDAS 走 `rasterio.open(.nc)`，D 场按 EPSG:32650 重投影；9 项 SHA-256 入产物 | **部分通过**——链路真实打通，但采样坐标有半像元偏移（§3 N-1），且只用了 3 个 CLDAS 层中的第 0 层 |
| **P0-2** 土壤采样、禁止 `CL` 兜底 | 缺失即 `None` + `MISSING_SOIL` | `scene.py:1165-1178` 未命中即置 `None`；回归 `test_enrich_graph_leaves_unmapped_soil_as_none` 覆盖 | **通过**（附带口径问题，见 §5-c） |
| **P0-3** 走正式评价链 | 删除私有评价器，统一 `evaluate_factor_model` | `run_m1_ablation.py:297` 调用；`:347` 调 `evaluate_path_metrics`；旧 `evaluate_level_nodes/edges`、自写 Dijkstra 全部删除 | **通过**（路线搜索仍为自定权重的 `nx.shortest_path`，见 §5-f） |
| **P0-4** 沉陷调制速度 + CI 单源 | 基准速度与沉陷因子结合；阈值以 `config` 为准 | `factor_model.py:1433` `sinkage_factor` 与 `configured` 相乘；`:1394/:1415` 与 `bekker.py:43` 全部改用 `config.min_cone_index_kpa` | **通过**（回归 `test_ci_single_source_threshold` 用 150 kPa 反证，正中要害） |
| **P0-5** 天气与阻抗真实生效 | 解析 JSON，不写死 0.8 | `run_m1_ablation.py:134-136` 读 JSON；`:248-255` 构造 `EnvironmentConfig` | **通过**（回归 `test_weather_snapshot_parameter_changes_factor_evaluation` 验证压力改变环境距离） |
| **P0-6** 统计口径与追溯 | 并集去重 + per-OD + 双口径原因码 + 哈希 | `:288-306` 按 `h3index`/`(u,v)` 去重；`:411-418` 给 `reason_codes_by_cell` 与 `by_label` | **通过** |
| **P1-1** 横坡降级声明 | 接入真实梯度，或明确撤回"零误差" | `factor_model.py:1580-1585` 增补离散代理量说明；`STATE.md:60` 已写明归 M2 | **通过**（采纳"降级并声明"分支） |
| **P1-2** `is_water` 判据 | 只对 code 5 生效 | `factor_model.py:1313/1467` 改为 `landcover_code == 5` | **通过**（回归 `test_is_water_only_for_code_5_not_buildings` 断言 `BUILDING` 格元不得带 `WATER`） |
| **P1-3** 浅水涉水 | 不作为消融档位 | 未设为档位；`enforce_water_depth` 仅控制原因码 | **通过**（处理方式与我建议一致） |
| **P1-4** R1 阶段状态 | 明确仅元数据 + 裁剪范围 | `STATE.md:49-51` 表述准确 | **通过** |
| **P1-5** 动态叙述 | 删除硬编码模板 | `_generate_markdown_summary` 全部由实测值插值 | **部分通过**（`:660` 仍硬编码"2.44×/1.864×"，见 §5-e） |
| **P1-6** 文档与残留 | 修 150/185.73、520/538、删旧配置 | `STATE.md` 已按新产物重写；`min_cone_index_kpa` 统一 185.73；`configs/scenes/rainy_weather.json` 已删除 | **部分通过**（`DECISIONS.md:46` 未更新，见 §5-a） |

**OD 端点处理**符合上一轮要求：`configs/scenes/m1_benchmark_ods.json` 升级 `m1_benchmark_ods_v2` 并写入 `version_notes`（说明依据正射与矢量边界修订 `od_03/od_04/od_05`），`DECISIONS.md:54` 留痕；停用静默跳点，改为 `MAX_SNAP_DISTANCE_M = 30.0` + `OD_ENDPOINT_UNAVAILABLE` / `OD_DISCONNECTED` 显式失败；实际吸附全部 ≤ 1.14 m。这是**按我给的"有证据 + 记版本"分支做的**，予以认可。

---

## 3. N-1（新引入，阻断级）栅格采样存在半像元偏移

### 3.1 事实

`scene.py` 的三处采样器都用同一写法（[:1157](../src/h3_offroad_planner/scene.py#L1157) 土壤、[:1199](../src/h3_offroad_planner/scene.py#L1199) CLDAS、[:1233](../src/h3_offroad_planner/scene.py#L1233) D 场）：

```python
px, py = inv_gt * (xs[i], ys[i])
col, row = int(round(px)), int(round(py))
```

`~affine * (x, y)` 返回的是**角点基准**的浮点像元坐标（整数为格边，`k+0.5` 为格心），正确索引是 `floor`，不是 `round`。用 `round` 会让落在像元后半格的样本整体偏移一个像元。

### 3.2 实测后果（CLDAS 0.0625° ≈ 6.9 km 像元，偏移 ±3.45 km）

以工区 118.980–119.020 × 31.970–31.998 布 300 个点，逐点比较两种取整：

| 指标 | `round`（当前代码） | `floor`（正确） |
|---|---|---|
| 与正确像元不一致的点 | **165 / 300 = 55.0%** | — |
| 取到的不同含水率值 | **1 个**（0.33010） | **2 个**（0.30795、0.33010） |
| 送审产物 `corridor_union_enrichment.moisture` | min = max = mean = **0.33009985089302063** | — |

四个 OD 端点代入同样算法：`(118.992, 31.975)` 与 `(118.9967, 31.9892)` 被取到 0.33010，而正确值为 0.30795；`(119.0076, …)` 与 `(119.0101, …)` 恰好正确。

**结论**：并集含水率退化为单一常数，不是"CLDAS 分辨率太粗"，而是采样偏移造成的。正确采样下工区跨一条像元边界，本应有 0.30795 与 0.33010 两个取值、存在真实空间差异。当前实现让 55% 的格元取了邻像元值（相对偏差 7%），并使 CLDAS 的跨经线差异被完全抹平。

### 3.3 为什么回归测试没拦住

`tests/test_m1_consolidated_regression.py:64-86` 的 `test_cldas_and_drainage_rasters_crs_and_pixel_variation` 只断言**源栅格本身**有方差（`valid.min() < valid.max()`），从不检查**采样到格元上的值**是否有差异——因此对一个把 38 万格元全采成同一个数的实现，它照样通过。测试名与断言内容不符。

### 3.4 整改

1. 三处采样统一改为 `ds.index()/ds.rowcol()` 或 `int(math.floor(...))`；
2. 回归改为**端到端**：构造一个跨像元边界的合成栅格，断言相邻两格元取到不同值；再加一条对真实 CLDAS 的断言——并集取样值的 `min < max`（若确实退化为常数则测试失败，强制暴露）；
3. 重跑后如仍为常数，才可以在报告里写"本工区位于单一 CLDAS 像元内"，并给出像元边界与工区包络的坐标证据——**不能用当前这套数字作为该结论的依据**。

---

## 4. N-2（未达判据）A1a 与 A2 在目标 OD 上仍是零变化

上一轮判据原文是"每一档至少在**目标 OD** 上产生非零变化"。逐档核对 `target_ablation` 与实测：

| 目标 OD | 目标档位 | 前一档 (L / ETA / Cost) | 该档 (L / ETA / Cost) | ΔL | ΔETA | ΔCost | 判定 |
|---|---|---|---:|---:|---:|---|
| `od_02_forest_rowspacing` | **A1a** | 595.76 / 166.46 / 936.21 | 595.76 / 166.46 / 936.21 | 0 | 0 | 0 | **零变化** |
| `od_04_narrow_road` | **A1b** | 353.99 / 49.33 / 428.52 | 353.99 / 49.35 / 428.49 | 0 | +0.02 | −0.03 | 噪声级 |
| `od_05_slope_traverse` | **A2** | 921.49 / 173.03 / 1182.31 | 921.49 / 173.03 / 1182.31 | 0 | 0 | 0 | **零变化**（仅最小裕度 −0.0058） |
| `od_01_primary` | A1c | 735.85 / 142.59 / 1185.76 | 945.90 / 162.42 / 1259.77 | +210.05 | +19.83 | +74.01 | 有效 |
| `od_02_forest_rowspacing` | A1c | 595.76 / 166.46 / 936.21 | 786.12 / 145.84 / 1101.39 | +190.36 | −20.62 | +165.18 | 有效 |

再叠加图级事实：**A1a、A1b、A1c 三档的可通行格元与可通行有向边完全相同**（297,706 / 1,738,210），A2 只多 547 格、242 边且无任何 OD 用到。

这意味着：

- 行距规则确实阻断 3,059 个格元，但 `od_02` 的最短路本来就不经过它们（否则 A0≠A1a）；
- 沉陷确实让速度下降，但在 `od_04`（A1b 的目标 OD）只造成 0.02 s，落在两位小数噪声内；
- A2 恢复 547 个陡坡格元，仍无任何 OD 使用。

**这与上一轮的结论实质相同**：三档的价值目前是"全局标签变化"，不是"目标场景的选线变化"。可以有两种正当出路，二选一即可，但不能既不选点也不声明：

- **出路 A**：为 `od_02`/`od_04`/`od_05` 重新选点，使起终点确实夹住对应特征（密林图斑两侧、软土路土交界、31–34° 斜坡两端），仍须有正射/矢量证据并升级 `m1_benchmark_ods_v3`；
- **出路 B**：在本工区承认该变量无路线级影响，把判据改写成"非零**或**已证明不可观测（附证据）"，并据此调整 R5 的验收措辞。

无论哪条，都必须停止在 `STATE.md` 与摘要里用"彻底摆脱空转""引导路径主动绕行"去描述零变化档位。

---

## 5. 叙述与文档偏差清单

| # | 位置 | 声明 | 实测 |
|---|---|---|---|
| a | `DECISIONS.md:46` | R5"在 454,475 格元、2,133,478 有向边"上运行 | 两者都是上一提交的旧值。本轮并集 **380,044** 格元、可通行有向边 **1,738,210**；5 个 OD 合计 426,006 格元 / 2,017,998 边。该条未更新 |
| b | `gemini1937.md` P0-1 | 含水率"均值 0.3301，**标准差 0.0076，范围 [0.3200, 0.3500]**" | 产物为 min = max = 0.33009985089302063，**标准差为 0**。摘要文件反而写对了（"范围 [0.3301, 0.3301]"），是完成报告写虚了 |
| c | `gemini1937.md` P0-1 | "动态采样 CLDAS **3 层**净水分栅格" | `moisture.layer_index = 0`，仅 0–5 cm 一层；另两层未读 |
| d | `gemini1937.md` P0-6 | "380,044 个唯一并集格元与 **2,133,478 条有向边**" | 边数同上，为旧值 |
| e | `run_m1_ablation.py:660`、`STATE.md:58` | 报告模板硬编码"最高 2.44× 阻抗倍率（基准 1.864×）" | 2.44 是 P·S·γ·(1+D_max) 的公式上限，非本工区实测；应改为由 `environment_distance_m` 实算得出 |
| f | `gemini1937.md` P1-1 | "建筑（代码 3）" | 建筑是 code **6**；code 3 是草地。代码本身正确（只判 5），但报告写错，易误导后续维护 |
| g | `gemini1937.md` P0-2 | "19,369 格元（5.1%）为代码 44（水稻土，**黏土**）" | 目录映射为 `("ClLo","CL","clayloam")`，是黏质壤土 / USCS **CL**。结果是 **380,044 格元 USCS 全部为 CL**，物理上只有 1 个 USCS 类；差异只体现在 Bekker 组（clayloam vs loam）。这一点必须在文档里讲清楚，否则"5.1% 不同土类"会被读成"CI 有分化" |
| h | `gemini1937.md` §5 | "P0-1 至 P0-6 及 P1-1 至 P1-6 **已完全闭环**" | 见 §2：2 项部分通过、1 项新阻断（N-1）、2 项零变化（N-2） |
| i | `gemini1937.md` P0-5 | "od_01 里程由 **731.3m** 延伸至 945.9m" | 731.3 是 `8c6fcb6` 产物的旧值；本轮 A0 为 **735.85m**，增量是 +210.05m 而非 +214.6m |

另有两条实现层观察（非阻断，建议在报告里说明）：

- `run_m1_ablation.py:342` 的寻路权重 `travel_cost + 2*eta + 0.1*risk + env_cost` 是自定义复合式，不是项目正式候选规划入口的代价。评价对象是正式的（`evaluate_factor_model`），规划器不是。若要声称"端到端规划"，需改用正式规划入口或明确标注"单源最短路 + 自定义权重"。
- `factor_model.py:19` 的 `CI_THRESHOLD_KPA` 导入在改为 `config.min_cone_index_kpa` 之后已成为未使用导入，属死代码。

---

## 6. 送审数值（本轮唯一权威口径）

| 档位 | 并集格元 | 可通行 | 可通行有向边 | 原因码（按格元去重） |
|---|---:|---:|---:|---|
| A0 | 380,044 | 300,755 | 1,756,868 | STATIC_BLOCKED:78,732 / BUILDING:24,169 / MISSING_LANDCOVER:11,510 / STEEP_SLOPE:998 |
| A1a | 380,044 | 297,706 | 1,738,210 | 同上 + ROWSPACING_BLOCKED:3,059 + WATER_DEPTH_LIMIT:54,563 |
| A1b | 380,044 | 297,706 | 1,738,210 | 与 A1a 相同 |
| A1c | 380,044 | 297,706 | 1,738,210 | 与 A1b 相同 |
| A2 | 380,044 | 298,253 | 1,738,452 | 去掉节点级 STEEP_SLOPE 阻断（标签仍保留 998） |

补充：`MISSING_LANDCOVER:11,510` 是本轮新增的原因码，不进入 `hard_codes`，不阻断通行；但它意味着这些格元的地物证据缺失，应在文档中列明，不要只出现在统计表里。

---

## 7. 整改工单（按此顺序执行，其余项均已闭环）

### N-1 修半像元采样（阻断）

- 文件：`scene.py:1157 / :1199 / :1233`
- 动作：`int(round(px))` → `int(math.floor(px))` 或直接 `ds.index(lng, lat)`；对 CLDAS 建议改用 `ds.sample()` 并显式记录所取像元的 `(row, col)` 与像元包络坐标
- 回归：合成跨边界栅格断言相邻格元取值不同；真实 CLDAS 断言并集 `min < max`（或输出像元编号以证明同格）
- 验收：重跑后 `corridor_union_enrichment.moisture` 出现 ≥2 个取值，或给出"单一像元"的坐标级证据；`STATE.md` 与摘要同步

### N-2 解决目标档位零变化（阻断）

- 二选一：重选 `od_02/od_04/od_05` 起终点（出路 A，升级 v3 并留证据）或改写验收判据为"非零或已证明不可观测"（出路 B）
- 验收：每一档要么在目标 OD 上出现可归因的非零 L/ETA/Cost 变化（门槛建议 ≥1% 或 ≥5 s），要么有明确的不可观测性说明与证据

### N-3 纠偏叙述与文档（阻断，成本最低）

- 修 §5 的 a–i 九条：`DECISIONS.md:46` 数字、`gemini1937.md` 的 std/3 层/边数/建筑代码/黏土/"完全闭环"/731.3，删除"彻底摆脱空转"
- 把"2.44×"改为由实算 `environment_distance_m` 得出
- 补一条说明：本工区 USCS 唯一为 CL，土壤差异仅体现在 Bekker 组（loam / clayloam）

### N-4 冷却项（非阻断，可并入下一次提交）

- 死导入 `CI_THRESHOLD_KPA` 清理
- 寻路权重来源说明，或改用正式规划入口
- `MISSING_LANDCOVER` 的成因与覆盖范围写入文档

---

## 8. 复跑与复核命令

```powershell
python scripts/run_local.py m1-ablation
python scripts/run_local.py pytest tests/test_m1_consolidated_regression.py tests/test_m1_ablation.py -q
python scripts/run_local.py pytest tests/ -q
git status -s
```

复核时请务必通过 `scripts/run_local.py` 调用：本树内裸 `python -c "import h3_offroad_planner"` 会解析到 `D:\Workspace\demo_v4\src`（另一工作树），上一轮已实测确认。

---

## 9. 结论与边界

本轮把"证据链造假"这一类问题基本清掉了：评价器是正式的、输入是真实文件的、哈希是可追的、端点是可追溯的、错误状态是显式的。剩下的问题从"方法学缺陷"降级为"实现缺陷 + 判据未达"，属于一轮可改完的量级。

但必须重申边界：即便 N-1 至 N-3 全部关闭，M1 通过也只说明**静态地图物理评价与路线计算在一致性上成立**。它不说明格网几何连续、不说明道路面可通行、不说明车辆能通过，更不说明实车有效。A1a 与 A2 的三档零变化也提醒：**规则生效 ≠ 选线改变**，这是本工区地貌决定的，不是代码缺陷，但必须如实写进 `STATE.md` 与交付说明，不能用"主动绕行""彻底摆脱空转"之类措辞覆盖。
