# 当前实施状态

更新：2026-10-15。工作树：`D:/Workspace/demo_v4-manned-offroad`。分支：`codex/manned-offroad-map`。
历史基线：`986bd58eef846f6f8a34961a43b208c315471110`；M0 规范化与加固提交：`5f30c5c`，`a4c8642`；当前最新提交以 `git rev-parse HEAD` 为准。

## 已完成

### M0 数据与基线准备（已规范化闭环）

- **StaticScene 契约与接口落地**：按 `IMPLEMENTATION_PLAN.md` §5.1 和 §6.1 完整实现 `StaticScene` 数据结构与 `prepare_static_scene(inputs, weather_snapshot, build_config)` 函数。涵盖 `scene_id`、米制投影 CRS（`EPSG:4528`）、工区范围（WGS84 与米制投影双坐标边界）、源 DEM（`EPSG:4490`，原生分辨率约 2m，高程单位米）、地物矢量目录、道路矢量（124 条，含 Width 与 FuncClass 道路类型字段）、正射影像（`EPSG:4528`，0.5m 原生分辨率，采集时标 `2025-05-29T02:03:07Z`）、土壤栅格与分类表（27 类，标明适用范围说明）、CLDAS 静态含水率（3 层深度，观测日期 `2026-01-01`）、上游水文域 D 场（7 个栅格）、制图期冻结气象快照、字段映射与模型版本（`m0_static_scene_v1`）。实现严格的米制投影投影判定（拦截非投影经纬度 CRS）、研究区几何有效性与有限性校验（杜绝 NaN 边界）、栅格与研究区空间重叠检验、支持已有场景字典/JSON 反向重新准备及私有资产自动兜底。支持强类型 dataclass、字典与 JSON 的双向序列化/反序列化。
- **固定真实工区、OD 与车辆配置**：
  - 子工区范围：QDX `bound.shp`（CGCS2000 / `EPSG:4490`），WGS84 `[118.981333, 31.968832, 119.014808, 31.999863]`，米制投影 `EPSG:4528` `[40403708.17, 3538821.30, 40406902.65, 3542290.57]`。
  - 正式 OD：Start `[31.9905769003, 118.9960502257]`，Goal `[31.9931786713, 118.9894117713]`，走廊缓冲 0.005°。
  - 车辆配置：Iveco Daily 4x4 7t 单排 3480（宽度 2.056 m，轴距 3.48 m，后轴中心为参考点）。
  - 制图期气象：真实 Open-Meteo 冻结快照 `configs/scenes/baseline_986bd58_weather.json`（有效时刻 `2026-10-15T08:00:00Z`，表层含水率 0.25 m³/m³，24h 降水 0.3 mm，`degraded=false`）。
- **桌面正射影像预览与图层显示**：
  - 实现了 `orthophoto_preview.py`，根据工区 WGS84 范围将本地高分正射影像 `T.tif` 裁剪下采样为 RGB 预览图（`outputs/m0_qdx_baseline/orthophoto_preview.png`，最大边 2048 像素），并记录像素映射与严格 WGS84 边界，增加 WGS84 坐标合法范围校验。
  - 扩展桌面端 `DesktopMapView.set_orthophoto_overlay` 与 `DesktopProjectState`，以 base64 data URL 注入 Leaflet `L.imageOverlay`，支持 `map_display` 可视化配置与透明度调节。运行载荷自动剔除 `map_display`，明确正射影像仅用于桌面人工边界核对，不改变通行物理模型。
  - 桌面客户端支持 `--project` 参数直接加载 `configs/manned_offroad_m0.yaml`。
- **关键地物属性覆盖审计**：
  - 对工区相交地物要素进行逐层统计与抽样验证：
    - 森林 `forest.shp` 的 `rowspacing`：工区内有效要素 386 条，数值范围 [1.5, 8.0]，样本：`['4.9', '4.4', '2.1', '5.4', '6.3']`。
    - 水体 `water.shp` 的 `depth`：工区内有效要素 454 条，数值范围 [0.5, 2.5]，样本：`['0.7', '1.9', '2.2', '1.0', '0.7']`。
    - 道路 `road_fina.shp` 的 `Width`：工区内有效要素 124 条，数值范围 [30.0, 55.0]，样本：`['30', '30', '30', '30', '30']`；道路类型 `FuncClass` 样本 `['5', '5', '5', '5', '5']`。
  - 保留原始数据编码，明确物理解释与车辆通过规则由 M1 对齐。
- **M0 可复现基线管线与运行闭环**：
  - 提供 `scripts/run_m0_baseline.py` 与 `python scripts/run_local.py m0-baseline`，自动执行：请求校验 → 正射预览生成 → 关键属性审计 → `prepare_static_scene` 契约生成与保存（正射预览路径贯通注入） → `cli plan` 基线运行 → 产物摘要与哈希归档。
  - 产物写入独立目录 `outputs/m0_qdx_baseline/`，包含 `m0_baseline.json`、`static_scene.json`、`orthophoto_preview.png`、`orthophoto_preview.json`、`landcover_attribute_audit.json` 及路线结果。
- **自动化测试**：
  - 全套回归测试 520 passed, 4 skipped；
  - 专门增加 `tests/test_static_scene.py`（StaticScene 强类型序列化、合成矢量/栅格 fixtures 场景准备、降级气象拦截、缺失输入拦截、已有场景文件/字典解析、实际 QDX 数据准备回归、地理 metric_crs 拦截、退化几何拦截、非重叠栅格拦截、气象数值合法性拦截、缺失含水率文件拦截）与 `tests/test_orthophoto_preview.py`（裁剪下采样、坐标越界拦截、项目配置解析、Leaflet 地图叠加），全部通过。

## 基线运行结果（M0 可复现基准）

在固定工区与冻结气象下运行 `scripts/run_m0_baseline.py`，退出码 0：
- 图规模：加载 41,503 个细格元和 120,647 条边；
- 耗时：`plan_ready_s=81.616593`，候选搜索 76.416995 s；
- 候选路线：生成 5 条候选（推荐 candidate ID：`route-6b6c07b10e2d5803`）；
- 轨迹状态：5 条候选的旧自主平滑轨迹状态均为 `invalid`，保留该原始客观结果，未伪造通过性结论；
- 产物哈希与配置校验一致记录于 `outputs/m0_qdx_baseline/m0_baseline.json`。

## 运行方式

在工作树根目录执行：

```powershell
# 1. 验证工作区数据引用与基线瓦片
python scripts/run_local.py verify

# 2. 一键执行 M0 规范化基准管线（生成场景契约、正射预览、属性审计及重跑基线）
python scripts/run_local.py m0-baseline

# 3. 运行 M0 场景契约、正射预览与桌面配置单元测试
python scripts/run_local.py pytest tests/test_static_scene.py tests/test_orthophoto_preview.py tests/test_desktop_project_validation.py tests/test_map_config.py -v

# 4. 运行全仓库测试
python scripts/run_local.py pytest tests/ -q

# 5. 启动桌面端并加载 M0 项目（包含本地正射影像底图叠加）
python scripts/run_local.py desktop --project configs/manned_offroad_m0.yaml

# 6. 使用固定私有配置运行规划
python scripts/run_local.py cli plan --request configs/manned_offroad.local.private.yaml
```

## 本地配置与证据产物

- `configs/manned_offroad_m0.yaml`：M0 固定工区、OD、车辆、冻结气象与正射底图配置。
- `configs/scenes/m0_qdx_scene.json`：符合 `StaticScene` 规范的固定场景元数据。
- `configs/scenes/baseline_986bd58_weather.json`：2026-10-15T08:00Z 真实 Open-Meteo 冻结气象快照。
- `outputs/m0_qdx_baseline/m0_baseline.json`：M0 运行摘要、输入哈希、性能与解释边界记录。
- `outputs/m0_qdx_baseline/static_scene.json`：`prepare_static_scene` 运行时生成的正式静态场景元数据。
- `outputs/m0_qdx_baseline/orthophoto_preview.png`、`orthophoto_preview.json`：本地正射影像裁剪预览图与几何元数据。
- `outputs/m0_qdx_baseline/landcover_attribute_audit.json`：工区内关键属性覆盖与值域审计。
- `outputs/m0_qdx_baseline/baseline_route/`：基线 5 条候选路线导出的 GeoJSON/GPKG 与性能记录。

## 下一步与未完成项

M0 规范化与基线准备已全部完成闭环，下一步严格按计划进入 **M1 静态通行属性**：

1. **静态地物属性旁路修复**：消除 `strict_static_mode = environment is not None` 对森林 `rowspacing` 和水体 `depth` 的旁路，统一标量与向量化因子模型。
2. **土壤与含水率模型修复**：将 CLDAS 静态含水率与天气修正结合，复现文献适用土类与 Bekker/CI 评价规则，取代 `theta=0.44` 硬编码阻断阈值。
3. **水文域与 D 场集成**：复用上游水文域 D 场与含水率修正，建立物理含水率与通行阻抗之间的显式映射。
4. **有向纵横坡计算**：沿候选曲线切向/侧向分解 DEM 梯度，取代单一节点标量坡度阻断机制。
