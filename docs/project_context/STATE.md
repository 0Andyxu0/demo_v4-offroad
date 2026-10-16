# 当前实施状态

更新：2026-10-16。工作树：`D:/Workspace/demo_v4-manned-offroad`。分支：`codex/manned-offroad-map`。
历史基线：`986bd58eef846f6f8a34961a43b208c315471110`；M0 规范化与加固提交：`5f30c5c`，`a4c8642`；当前最新提交以 `git rev-parse HEAD` 为准。

## 已完成

### 仓库审查、.gitignore 完备防护与远程仓库连接

- **.gitignore 规则加固与全面覆盖**：
  - 覆盖 Python 运行与构建缓存（`__pycache__/`, `*.so`, `*.pyd`, `*.egg-info/`, `build/`, `dist/`）；
  - 覆盖测试、覆盖率、Lint 与 Notebook 缓存（`.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`, `.ipynb_checkpoints/`, `audit_pytest_temp/`, `pytest_temp*/`, `.coverage*`, `coverage.xml`）；
  - 覆盖虚环境、操作系统与编辑器临时文件（`venv/`, `.venv/`, `.idea/`, `.vscode/`, `*.bak`, `*.lnk`, `Thumbs.db`, `.DS_Store`）；
  - 覆盖日志、产物与临时工作目录（`outputs/`, `.artifacts/`, `logs/`, `*.log`, `tmp/`, `temp/`）；
  - 覆盖敏感凭据、密钥与私有配置（`.env`, `*.env`, `.netrc`, `id_*`, `*.key`, `*.pem`, `*.der`, `*.p12`, `*.pfx`, `*.cer`, `*.crt`, `*.jks`, `*.keystore`, `*.token`, `token*.json`, `credentials.*`, `secrets.*`, `secret.*`, `*.private.yaml`, `*.local.yaml` 等），与 `scripts/audit_gitignore.py` 严格对齐；
  - 覆盖大体量 GIS 源数据、栅格、空间库及伴生文件（`*.tif`, `*.dem`, `*.nc`, `*.nc4`, `*.gpkg`, `*.parquet`, `*.feather`, `*.sqlite*`, `*.db`, `*.h5`, `*.hdf`, `*.mbtiles`, `*.shp`, `*.shx`, `*.dbf`, `*.prj`, `*.cpg`, `*.shp.xml`, `*.tfw`, `*.wld`, `*.jgw`, `*.pgw`, `*.lock`, `*.lck`, `*.sr.lock`, `*.gdb/`, `*.kml`, `*.kmz`）。
- **自动化测试保障**：新增 `tests/test_gitignore.py`（5 项测试全部通过），保证 `scripts/audit_gitignore.py` 顺利执行、现有版本追踪文件无一误拦截、敏感与私钥文件无遗漏拦截、GIS 二进制/伴生索引文件全量拦截、私有配置与产物目录隔离。
- **远程仓库连接与上游跟踪**：
  - 远程源配置：`origin` -> `https://github.com/0Andyxu0/demo_v4-offroad.git`（有人驾驶 H3 远程仓库）；
  - 跟踪分支：`codex/manned-offroad-map` -> `origin/codex/manned-offroad-map`。

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

### M1 静态通行属性修复与物理消融（已完成闭环）

- **消除 `strict_static_mode` 属性旁路 (A1a)**：
  - 移除了历史代码中 `strict_static_mode = environment is not None` 导致当传入气象快照时完全忽略林地株距与水深的逻辑；统一将 `strict_static_mode = False`；
  - 无论是否传入气象快照，`forest.shp` 的 `rowspacing`（株距 `< 2.056m` 安全车宽即以 `ROWSPACING_BLOCKED` 阻断）与 `water.shp` 的 `depth`（浅水 `<= 0.308m` 涉水放行并计算阻力降速，深水 `> 0.308m` 离地间隙即以 `WATER_DEPTH_LIMIT` 阻断）均严格作为车辆物理硬约束生效；标量与向量化模型保持一致。
- **土壤 Bekker/CI 模型高湿崩塌与空值放行修复 (A1b)**：
  - 针对黏壤土等在含水率 $\theta=0.44$ 时因 $k_c \le 0$ 引发 `AssessmentError` 的物理失效，在 `dynamics/bekker.py` 的 `enrich_cell` 与 `_sinkage_passes` 中捕获该失效并显式赋予沉陷无穷大（`inf`）、沉陷阻力无穷大（`inf`）、土壤机动性 0.0；
  - 在 `factor_model.py` 的 `_hard_constraints` 中拦截无限沉陷并以 `SINKAGE_CLEARANCE_EXCEEDED` 明确阻断；消除历史代码因 `NaN -> None` 回退导致高湿软土无条件放行的重大安全漏洞。
- **静态真实天气修正与水文域地表阻抗 (A1c)**：
  - 在 `configs/scenes/` 增补真实暴雨日冻结快照 `rainy_weather.json`（24h 降水 28.5 mm，潜在蒸散发 1.85 mm，`derived_pressure = 0.8`）；
  - 与基线干旱日 `baseline_986bd58_weather.json`（`derived_pressure = 0.0`）形成对照，结合固定上游水文域 D 场（`drainage_sensitivity`），在降雨条件下对低洼冲沟区域施加 $1.864\times$ 地表阻抗惩罚，主动引导路线规避湿软冲沟走廊，明确区分物理含水率与地表阻抗倍率。
- **有向纵横坡解耦 (A2)**：
  - 在 `VehicleProfile` 与 `configs/vehicle.yaml` 中新增横倾角限制 `max_roll_angle_deg: 25.0` 与动态属性 `effective_max_roll_angle_deg`；
  - 彻底移除了因子模型硬约束中单一 DEM 标量坡度超过爬坡限制即删除整个格元节点的粗暴逻辑；
  - 在标量 `_directed_edge_metrics` 与向量化 `evaluate_directed_edges_vectorized` 中，沿有向边将 DEM 地形梯度分解为纵向爬坡角 $\alpha$ 与侧向横坡角 $\beta = \sqrt{\max(0, \theta_{terrain}^2 - \alpha^2)}$；在 Iveco $30.96^\circ$ 爬坡角与 $25.0^\circ$ 横倾角限制下，成功保留 $31^\circ \sim 34^\circ$ 陡坡上的对角线与等高线平缓通行边，同时阻断直攀落线与侧向倾覆边；横坡裕度同步纳入边安全性指标。
- **5 组多场景基准测试 OD 固化**：
  - 在 `configs/scenes/m1_benchmark_ods.json` 中固化了 5 组专项测试起终点，分别覆盖综合农田/路网全场景（`od_01_primary`）、密林行距安全宽度约束（`od_02_forest_rowspacing`）、水深涉水与低洼冲沟湿软规避（`od_03_water_gully`）、道路与自然土界面（`od_04_narrow_road`）以及 $30^\circ$ 陡坡斜切纵横坡解耦（`od_05_slope_traverse`），为 M1–M5 提供一致的基准测试基底。
- **道路图层双字段对齐与审计贯通 (argon1657 审计项 3)**：
  - 在 `configs/scenes/m0_qdx_scene.json` 与 `src/h3_offroad_planner/scene.py` 的默认 `field_mapping` 中，将 `road_fina.shp` 的 `width` 映射到 `Width`，`functional_class` 映射到 `FuncClass`；
  - `prepare_static_scene` 与 `scripts/run_m0_baseline.py` 的关键地物属性审计扩展为 4 项（林地 `rowspacing` 386 条、水深 `depth` 454 条、路宽 `Width` 124 条、道路等级 `FuncClass` 124 条），避免在后续 M2 道路多边形构建时硬编码字段。
- **自动化消融实验脚本与全量测试验证**：
  - 新增 `scripts/run_m1_ablation.py` 与 `scripts/run_local.py m1-ablation` 命令行接口，产出标准化消融报告 `outputs/m1_ablation/m1_ablation.json` 与 `m1_ablation_summary.md`；
  - 新增专项测试 `tests/test_m1_ablation.py`（8 项单变量消融与边界测试全部通过，覆盖 A1a、A1b、A1c、A2、陡坡裕度单调性、$\theta_{terrain} < \alpha$ 精度边界及道路字段对齐）；
  - 全仓库测试集 533 passed, 4 skipped，零回归。

## 运行方式

在工作树根目录执行：

```powershell
# 1. 验证工作区数据引用与基线瓦片
python scripts/run_local.py verify

# 2. 一键执行 M0 规范化基准管线
python scripts/run_local.py m0-baseline

# 3. 一键执行 M1 物理通行属性消融实验管线
python scripts/run_local.py m1-ablation

# 4. 运行 M1 消融测试
python scripts/run_local.py pytest tests/test_m1_ablation.py -v

# 5. 运行全仓库测试
python scripts/run_local.py pytest tests/ -q

# 6. 启动桌面端并加载 M0 项目（包含本地正射影像底图叠加）
python scripts/run_local.py desktop --project configs/manned_offroad_m0.yaml
```

## 本地配置与证据产物

- `configs/manned_offroad_m0.yaml`：M0 固定工区、OD、车辆、冻结气象与正射底图配置。
- `configs/scenes/m0_qdx_scene.json`：符合 `StaticScene` 规范的固定场景元数据。
- `configs/scenes/baseline_986bd58_weather.json`：2026-10-15T08:00Z 真实 Open-Meteo 冻结干旱/微雨气象快照。
- `configs/scenes/rainy_weather.json`：2026-06-25T08:00Z 真实 Open-Meteo 冻结降雨日气象快照（$28.5\text{mm}$）。
- `configs/scenes/m1_benchmark_ods.json`：M1–M5 固化的 5 组基准多场景测试起终点列表。
- `outputs/m1_ablation/m1_ablation.json`：M1 物理通行属性消融实验原始数据。
- `outputs/m1_ablation/m1_ablation_summary.md`：M1 物理消融对比报告（A0 -> A1a -> A1b -> A1c -> A2）。
- `outputs/m0_qdx_baseline/m0_baseline.json`：M0 运行摘要、输入哈希、性能与解释边界记录。
- `outputs/m0_qdx_baseline/static_scene.json`：`prepare_static_scene` 运行时生成的正式静态场景元数据。
- `outputs/m0_qdx_baseline/orthophoto_preview.png`、`orthophoto_preview.json`：本地正射影像裁剪预览图与几何元数据。
- `outputs/m0_qdx_baseline/landcover_attribute_audit.json`：工区内关键属性覆盖与值域审计。
- `outputs/m0_qdx_baseline/baseline_route/`：基线 5 条候选路线导出的 GeoJSON/GPKG 与性能记录。

## 下一步与未完成项

M0 与 M1 阶段已全部完成代码级实现与测试验证。下一步严格按 `IMPLEMENTATION_PLAN.md` §4 & §6.2 启动 **M2：片段、入口和局部多通道**：

1. **物理片段拆分 (`InCellPatch`)**：在米制 CRS 下将源地物/障碍/道路边界与 H3 相交得到连通片段，道路和自然土保持各自属性。
2. **公共开口与物理锚点 (`AnchorState`)**：从相邻片段实际公共开口建立物理锚点，宽开口保留多个锚点，拒绝无宽度空间纯拓扑相接。
3. **局部约束三角细分与通道曲线 (`LocalCurveEdge`, `LocalPassageGraph`)**：边界约束三角细分，生成非支配多曲线（最短线、最大瓶颈净空线、最小累计 Q 线），保住真实走廊。
