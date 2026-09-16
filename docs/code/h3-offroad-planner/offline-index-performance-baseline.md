# 本地路由索引 I0 性能与正确性基线

- 冻结日期：2026-09-14
- 分支：`main`
- Python：3.12.10，`C:\Users\31287\AppData\Local\Programs\Python\Python312\python.exe`
- 平台：Windows 11 10.0.26200，16 个逻辑处理器
- 关键依赖：GeoPandas 1.1.3、H3 4.4.2、NumPy 2.3.1、pandas 3.0.2、PyArrow 24.0.0、Rasterio 1.5.0、Shapely 2.1.2
- 数据身份：`outputs/qdx_tiles/tile_manifest.json`，`static_input_hash=2d4fd5b81e8f10646d90b3c2bd90b51d1c54d97597ac57f74adcd9b90a9034f7`
- 质量门禁：`402 passed, 2 skipped`；Ruff 全部通过

## 请求基线

所有成功样本使用相同的 res14/res11、车辆、因子、静态场景、候选上限和 `0.005°` 旧直线缓冲区。原方案坐标 `(31.975,118.988) -> (31.992,119.008)` 在当前数据和配置下复现为 `Endpoints disconnected`，保留为失败诊断，不作为成功 A/B 样本。

| 样本 | 起点 -> 终点 | 文件/原始行 | 格/边 | plan_ready_s | candidate_search_s | heavy_export_s |
|---|---|---:|---:|---:|---:|---:|
| legacy_case_1 | `(31.9905769003,118.9960502257)` -> `(31.9931786713,118.9894117713)` | 1040 / 356720 | 325205 / 788720 | 574.422757 | 520.749411 | 8.739076 |
| legacy_case_2 | `(31.9905769003,118.9960502257)` -> `(31.9909032912,118.9922684898)` | 819 / 280917 | 252791 / 586675 | 221.098747 | 180.017564 | 6.777325 |
| legacy_case_3 | `(31.9909032912,118.9922684898)` -> `(31.9931786713,118.9894117713)` | 805 / 276115 | 249656 / 662071 | 264.366449 | 221.590201 | 7.475266 |

原始 RoutePlan、日志计时和完整旧 GPKG 位于 `outputs/performance_baseline/legacy_case_1..3`。冷索引打开、读取、建图、物理评估、候选搜索、连续几何、计划就绪和重型导出均由 `time.perf_counter()` 独立计时。

## 格式基线

- 原瓦片：6756 个非空 Parquet，2251004 行，13 种 Arrow schema；schema 变体计数为 1652、1157、1123、665、651、586、453、405、37、23、2、1、1。
- 旧 `adjacency_json`、`edge_length_m`、`static_input_hash`、`sampling_mode`、`nodata` 压缩列块分别为 156447859、18601491、1729098、533436、379462 字节。
- `legacy_case_1/routes.gpkg` 包含 325205 行 `h3_static_facts`、788720 行 `h3_edges`、5 行 `route_candidates`、1 行重复推荐图层和 4 个空/重复状态图层。
- 物理证据状态：车辆宽度、轴距和前后悬为空；可信水文映射为空；瓦片 manifest 的土壤及土壤目录来源为空。不得宣称实车物理闭环完成。

## 冻结 A/B 阈值

- 每个基线已存在的候选角色必须仍可用；若粗走廊无法提供，必须返回原因，不得静默替换语义。
- 同角色的 `distance_m`、`eta_s`、`terrain_risk`、`travel_cost` 和各环境压力距离相对差异不得超过 5%。
- 同角色 `score_lower_min` 绝对差异不得超过 0.02。
- 硬约束零容差、H3 路径连续、相同输入确定；连续车辆几何和证据缺失状态必须如实保留。

## 复现命令

```powershell
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests demo
python -m h3_offroad_planner plan --request <固定请求 YAML>
```

请求 YAML 必须固定上述端点、`configs/mvp81_qdx_delivery.yaml` 中的路线参数和独立输出目录；每次读取对应 `performance.json`、`route_plan.json` 与 `routes.gpkg`。
