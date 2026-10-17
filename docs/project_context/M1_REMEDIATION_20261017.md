# M1 第二轮整改执行记录（2026-10-17）

- **执行日期**：2026-10-17
- **依据**：[M1_AUDIT_ROUND2_20261017.md](M1_AUDIT_ROUND2_20261017.md) 的 N-1 / N-2 / N-3 与 N-4
- **范围**：只修审核报告列出的三项阻断 + 清扫本轮新增代码中的缺陷；未改动 M2–M5，未改动物理模型取值。

## 1. 修复清单

| 编号 | 问题 | 修复 | 位置 |
|---|---|---|---|
| **N-1** | 栅格采样用 `round()` 取像元，角点基准坐标偏移半像元；CLDAS 6.9 km 像元上偏移 3.45 km，55% 格元读到邻像元值，并集含水率退化为单值 0.3301 | 新增 `_pixel_index()` 统一按 `floor()` 取**包含**像元；三处采样（土壤 / CLDAS / D 场）全部改用；CLDAS 补投影坐标系分支；元数据新增 `distinct_pixels` / `distinct_values` | `scene.py:1074`、`:1182`、`:1230`、`:1265` |
| **N-2** | 三个档位跃迁在目标 OD 上零变化，但摘要仍写"彻底摆脱空转""主动绕行" | 新增 `comparison` 段：逐档逐 OD 记录 ΔL/ΔETA/ΔCost、相对变化、是否 ≥1%、目标 OD 是否可观测；摘要 §5 输出可观测性判定表与结论，零变化档位如实标注 | `run_m1_ablation.py` 的 `comparison` 与 `_generate_markdown_summary` |
| **N-3** | 文档/叙述与产物不符 | 修正 `DECISIONS.md:46` 的 454,475 / 2,133,478 → 380,044 / 1,738,210；把"2.44×/1.864×"改为由边级 `environment_distance_m / distance_m` 实测（现值 2.440×）；`STATE.md` 全部 OD 数值按新产物重写并标注可观测性局限 | DECISIONS #25、#33–#35；STATE §M1 |
| **N-4** | 死代码与陈旧项 | 删除 `factor_model.py` 中已失效的 `CI_THRESHOLD_KPA` 导入；删除摘要生成器里不再使用的 `eta_diffs_1b` / `cost_diffs_1c` | `factor_model.py:18`、`run_m1_ablation.py` |

## 2. 修复前后证据

### 2.1 CLDAS 采样（关键证据）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 并集含水率取值数 | 1（0.3301） | **2**（0.3080 / 0.3301） |
| min / max | 0.3301 / 0.3301 | 0.3080 / 0.3301 |
| 均值 | 0.3301 | 0.3153 |
| 与 `ds.index()` 不一致的抽样点 | 165 / 300（55%） | 0 / 300 |

修复后工区确实跨 119.0° 经线像元边界，两个取值分别落在经线两侧，此前"工区位于单一像元"的印象是取整 bug 造成的假象。

### 2.2 可观测性（`m1_ablation.json.comparison`）

| 档位跃迁 | 目标 OD | 目标 OD ≥1% 变化 | 实测最大相对变化 |
|---|---|---|---|
| A0 → A1a | od_01 / od_02 / od_03 | 否 | 0 |
| A1a → A1b | od_01 / od_04 | 否 | 4.1e-4（od_04 ETA +0.02 s） |
| A1b → A1c | od_01 / od_03 | **是** | 0.285（od_01 +210.05 m / +19.67 s / +74.38） |
| A1c → A2 | od_01 / od_05 | 否 | 0（仅最小裕度 −0.0058） |

## 3. 新增回归

- `test_raster_sampling_uses_containing_pixel_not_rounded_neighbour`：2×2 合成栅格，取像元后半格的点，断言读到**包含**像元的值（旧 `round` 实现会把 0.10 读成 0.20，必失败）；并断言 `distinct_pixels == 3`、`distinct_values == 3`。
- `test_pixel_index_matches_rasterio_index`：对 20 个坐标断言 `_pixel_index()` 与 rasterio `ds.index()` 完全一致。

## 4. 验证

```powershell
python scripts/run_local.py m1-ablation
python scripts/run_local.py pytest tests/test_m1_consolidated_regression.py tests/test_m1_ablation.py -q
python scripts/run_local.py pytest tests/ -q
git status -s
```

结果：专项 `11 passed`、`20 passed`；全量 **549 passed, 4 skipped**（原 547，新增 2 项）。

## 5. 本轮仍未处理（需决策，不在整改范围内）

1. **铺装路面仍套用土壤沉陷**：`_soil_speed_interval` 对所有格元生效，`has_road=True` 的格元同时拿到 `road_speed_factor=1.0` 与土壤沉陷降速；而 `surface_response=0.0` 已把道路视为不透水面。二者语义冲突，是否给道路豁免 Bekker 属**建模决策**，需在 DECISIONS 中定案后再改，本轮未动。
2. **基准 OD 不重选**：5 组端点均落在可通行 res14 格，按负责人判定保留 v2 坐标；A1b / A2 的零变化如实记录为可观测性局限。
3. **寻路权重仍是自定义复合式**（`travel_cost + 2·eta + 0.1·risk + env_cost`），非正式候选规划入口的代价函数。评价对象是正式的，规划器不是。
4. `MISSING_LANDCOVER: 11,510` 格元的地物证据缺失成因尚未追查。

## 6. 第三批整改（审核要求 1–3）

| 要求 | 落地 | 证据 |
|---|---|---|
| **1a 端点不可通行即报错** | `_resolve_endpoint` 改为 `h3.latlng_to_cell(lat, lng, 14)` 求**含格元**，取消走廊图上的最近格元搜索；含格元缺失/不可通行分别返回 `OD_ENDPOINT_OUTSIDE_CORRIDOR` / `OD_ENDPOINT_IMPASSABLE` | 回归 `test_endpoint_resolves_containing_cell_and_never_crosses_cells`：邻格不可通行时断言不会跳回可通行格 |
| **1b 吸附限制在 res14 格内** | `MAX_SNAP_DISTANCE_M` 30.0 m → **2.0 m**（res14 边长 1.35 m），只吸收落在格边的坐标 | 产物 `metadata.max_snap_distance_m = 2.0`；实测 5 组 OD 吸附 0.00–1.14 m |
| **1c 只在端点不可通行时重选** | 复核 5 组 OD：端点所在 res14 格元全部可通行 ⇒ **不重选**，保留 `m1_benchmark_ods_v2`。曾一度升级的 v3（把 od_02 移到密林两侧）已按负责人判定撤回 | DECISIONS #38；`configs/scenes/m1_benchmark_ods.json` 与 8871d9b 版本一致 |
| **2 铺装路面豁免 Bekker** | `_soil_speed_interval` 对 `has_road` 格元直接返回土壤系数 1.0，且不计算 CI/沉陷、不产生土壤原因码与土壤裕度 | 回归 `test_road_cells_are_exempt_from_soil_sinkage`；`od_04` ETA 49.33→26.66 s、`od_05` 169.02→116.84 s |
| **3 文档清理** | 删除根目录 4 份残留、`modules/`（49 篇）、`SYMBOL_INDEX.md`、`MANIFEST.md`；`docs/code/`（58 篇）、`demo_v4` 性能方案、`PROJECT_HOLOGRAM.md` 移入 `docs/history/` | DECISIONS #39；详见 [DOC_INVENTORY_20261017.md](DOC_INVENTORY_20261017.md) |

**撤回 v3 之后的结果**：修复路面豁免后重新测得的 A0→A1a 变化并未消失——`od_02` 由 639.31 m / 85.78 s 变为 593.04 m / 136.90 s（相对变化 59.6%），说明此前观察到的"A1a 零变化"主要是 **A1b 之前的路面沉陷把两条路线压成同一条**造成的，不是基准点选得不对。这直接支持"先修物理模型、不移动基准点"的处理原则。

第三批后的并集口径：380,044 格元，可通行 300,755 / 297,706 / 297,706 / 297,706 / 298,253（A0→A2），可通行有向边 1,756,868 / 1,738,210 / 1,738,210 / 1,738,210 / 1,738,452。