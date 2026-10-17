# 当前实施状态

更新：2026-10-16。工作树：`D:/Workspace/demo_v4-manned-offroad`。分支：`codex/manned-offroad-map`。
历史基线：`986bd58eef846f6f8a34961a43b208c315471110`；M0 规范化与加固提交：`5f30c5c`，`88ddda0`；M1 静态通行属性修复与物理消融提交：`3b1a520`，`c715f08`；当前最新提交以 `git rev-parse HEAD` 为准。

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
  - 全套回归测试 550 passed, 4 skipped；
  - 包含 `tests/test_m1_consolidated_regression.py`、`tests/test_m1_ablation.py`、`tests/test_static_scene.py`、`tests/test_orthophoto_preview.py`、`tests/test_vectorized_factor.py` 等全量通过。

### M1 静态通行属性修复与综合审核整改闭环（整改完成，待复核）

- **R1 道路有效宽度米制换算 (`resolve_road_effective_width_m`)**：
  - 对照高分正射影像与图层编码，确认 `road_fina.shp` 的 `Width` 字段为分米（0.1m）编码（值域 30.0~55.0）；
  - 在 `src/h3_offroad_planner/scene.py` 与 `configs/scenes/m0_qdx_scene.json` 中增加 `width_unit_or_scale: "0.1m"` 与 `effective_width_m_range: [3.0, 5.5]`，提供统一辅助函数 `resolve_road_effective_width_m(raw_width, func_class, scale=0.1, default_m=3.5) -> float`；杜绝直接将原始 30.0~55.0 当作米使用而生成 30~55 米巨型虚假走廊；场景准备解析时安全过滤非字段配置项，支持从 `road_mapping` 动态解析配置。
- **R2 土壤 Bekker/CI 物理参数、干密度换算与超限阻断 (修复 A1b, P0-4)**：
  - 严格依据 Shahgholi et al. (2024) 农艺壤土/黏壤土实测数据修正 $k_c, k_\phi, n$ 回归系数（黏壤土：$k_c = -34.53 w_{\%} + 1475.7$，$k_\phi = -33.606 w_{\%} + 2560.6$；壤土：$k_c = -24.59 w_{\%} + 1065.9$，$k_\phi = -24.482 w_{\%} + 2087.4$）；
  - 建立体积含水率 $\theta_v$（$\text{m}^3/\text{m}^3$）与质量含水率 $w_{\%}$ 的干密度物理换算：$w_{\%} = (\theta_v \cdot \rho_{\text{water}} / \rho_d) \times 100\%$（取 $\rho_{\text{water}} = 1.0\text{ g/cm}^3, \rho_d = 1.4\text{ g/cm}^3$）；
  - 彻底消除 CI 阈值双源矛盾，单一收敛至 `min_cone_index_kpa: 185.73`；在 `_soil_speed_interval` 中建立沉陷速度衰减耦合 `sinkage_factor = max(config.speed_floor_ratio, 1.0 - sinkage / clearance_limit)`，使沉陷真实降低节点速度与 ETA；标量 `BekkerChecker` 与向量化 `evaluate_soil_bekker_vectorized` 保持完全一致。
- **R3 CLDAS 静态含水率与水文 D 场接入，规范降雨场景 (修复 A1c, P0-1, P0-2)**：
  - 实现真实栅格动态采样适配器 `enrich_graph_from_static_scene`，打通工区格元与真实土壤（`soil_nanjing.tif` + `.vat.dbf`，识别黄褐土 49 与水稻土 44 等）、CLDAS 静态含水率 NetCDF 0-5cm 栅格（按包含像元采样：均值 $0.3153\text{ m}^3/\text{m}^3$，范围 $[0.3080, 0.3301]$，2 个不同取值）及上游水文域 D 场（`drainage_sensitivity.tif`，值域 $[0, 1]$）的真实坐标采样；
  - 针对暴雨对照，使用 `configs/scenes/synthetic_rainy_weather.json`，在配置与元数据中显式标注为“合成降雨敏感性对照场景”（`synthetic_rainy_weather_sensitivity_contrast`，`derived_pressure = 0.8`），与真实历史 API 快照严格区分，杜绝冒充真实观测；降雨时由边级 `environment_distance_m / distance_m` 实测出最大地表阻抗倍率 $2.440\times$（数据驱动，非模板常量）。
- **R4 零近似误差的正切纵横坡解耦 (完善 A2, P1-1)**：
  - 统一采用精确正切分解：$\tan\theta_{\text{roll}} = \sqrt{\max\left(0, \, \tan^2\theta_{\text{terrain}} - \tan^2\theta_{\text{pitch}}\right)}, \theta_{\text{roll}} = \arctan(\tan\theta_{\text{roll}})$，标量与 NumPy 向量化逐元素一致；明确记录输入坡度为离散格元坡度代理量 `max(source.slope, target.slope)`，连续全地形曲面梯度投影归属 M2；
  - 在 Iveco 爬坡 $31.0^\circ$ 与横倾 $25.0^\circ$ 双约束下，精确放行安全对角通行边。
- **R5 真实 QDX 瓦片图与 5 组基准 OD 端到端消融验证 (P0-3, P0-5, P0-6)**：
  - 废除消融脚本私有评价器，在 `FactorModelConfig` 中引入显式开关，统一调用 `evaluate_factor_model` 与 `evaluate_path_metrics`；
  - 依据正射影像与矢量边界修正 `m1_benchmark_ods.json` 为 `m1_benchmark_ods_v2`，消除原端点落在深水塘与建筑物的失误，将 5 组 OD 初始吸附距离控制在 $\le 1.14\text{ m}$（远低于 $30.0\text{ m}$ 门限）；
  - 严格执行 `A0 → A1a → A1b → A1c → A2` 5 档消融，产出 `outputs/m1_ablation/m1_ablation.json` 与 `m1_ablation_summary.md`，每档在目标 OD 上均呈现自洽非零差异。
- **R6 文档事实记录全面核对与对齐 (P1-2, P1-5, P1-6)**：
  - 修正 `is_water` 仅对 `landcover_code == 5` 生效，防止建筑（code 6）误打水体标签；删除遗留冗余文件 `configs/scenes/rainy_weather.json`；全部对比文字由实测数据动态生成，杜绝模板空话。

## 基线与消融运行结果

### M0 可复现基线结果

在固定工区与冻结气象下运行 `scripts/run_local.py m0-baseline`，退出码 0：
- 图规模：加载 41,503 个细格元和 120,647 条边；
- 道路有效宽度审计：124 条要素原始值域 30.0~55.0 分米，换算为有效米制宽度 3.0~5.5m；
- 候选路线：生成 5 条候选（推荐 candidate ID：`route-6b6c07b10e2d5803`）；
- 产物哈希与配置校验一致记录于 `outputs/m0_qdx_baseline/m0_baseline.json` 与 `static_scene.json`。

### M1 物理通行属性消融真实评测结果 (A0 → A1a → A1b → A1c → A2)

运行 `scripts/run_local.py m1-ablation` 针对 QDX 真实工区瓦片图（176,645 去重独立格元）和 5 组基准 OD（`m1_benchmark_ods_v3`）开展全量消融实验：

1. **去重走廊并集 (Corridor Union) 节点与边通行统计**：
   - **A0 基线**：去重总格元 176,645，可通行格元 139,650，阻断格元 36,995；可通行边 815,342。
   - **A1a 恢复株距与水深**：可通行格元 137,105，阻断格元 39,540；可通行边 799,872（净减 15,470 条）；新增阻断：`ROWSPACING_BLOCKED`、`WATER_DEPTH_LIMIT`。
   - **A1b 土壤力学与 Bekker/CI**：可通行格元/边与 A1a 完全相同（该档只影响速度、ETA、安全裕度，不影响连通性）；铺装路面已豁免土壤沉陷（见 DECISIONS #37），沉陷只作用于越野格元，`od_03` ETA +0.78 s、`od_05` +0.21 s。
   - **A1c 气象与水文域地表阻抗**：边级实测最大地表阻抗倍率 2.440×；`od_01_primary` +160.40 m、成本 +39.28。
   - **A2 正切纵横坡解耦**：可通行格元恢复至 137,523 (+418)，可通行边 800,192 (+320)；移除 `STEEP_SLOPE` 标量坡度硬阻断。**注意**：A2 在目标 OD 上仍未产生 ≥1% 的路线变化（仅最小裕度变化，如 `od_05` −0.0058）。

2. **5 组基准 OD 真实规划结果**（端点按 res14 含格元解析，不允许跨格吸附）：
   - `od_01_primary`（吸附 0.00/0.00 m）：A0~A1b 785.50 m (ETA 85.39 s, 成本 1220.29) → A1c/A2 945.90 m (ETA 81.24 s, 成本 1259.57)；降雨阻抗带来 +160.40 m 绕行。
   - `od_02_forest_rowspacing`（吸附 0.01/0.01 m，**v3 重选**）：A0 139.54 m (13.11 s, 208.86) → A1a/A1b 382.91 m (48.28 s, 519.46) —— 行距硬约束使路径必须绕过 1,930 格的密林图斑，**+243.37 m / +35.17 s / +175%**，是本轮新增的可观测单变量证据；A1c/A2 距离不变。
   - `od_03_water_gully`（吸附 1.14/0.05 m）：451.88 m；A1a 103.60 s → A1b 104.38 s（+0.78 s，沉陷降速）→ A1c/A2 104.42 s。
   - `od_04_narrow_road`（吸附 0.02/0.05 m）：353.99 m；A0~A1b 26.66 s（路面豁免土壤后不再受沉陷降速）→ A1c/A2 27.86 s（降雨阻抗）。
   - `od_05_slope_traverse`（吸附 0.04/0.35 m）：921.49 m；A1a 116.84 s → A1b 117.05 s → A1c/A2 117.19 s；A2 仅把最小安全裕度由 0.1215 校正为 0.1157。

3. **本工区实测口径与可观测性边界（第三批整改后）**：
   - 并集 176,645 格元中 USCS **全部为 `CL`**（土壤栅格出现代码 49 黄褐土 164,187 格与代码 44 水稻土 12,458 格，二者映射 USCS 均为 CL，Bekker 组分别为 loam / clayloam）；土壤差异只体现在 Bekker 组，不体现在 CI。
   - CLDAS 0-5cm 采样实测 2 个取值（0.3080 / 0.3301，均值 0.3107），跨 119.0° 经线像元边界。
   - 单变量档位可观测性（目标 OD 上 L/ETA/Cost 相对变化 ≥1%）：A0→A1a **是**（`od_02` +175%）；A1a→A1b 否；A1b→A1c **是**（`od_01` +20.4%）；A1c→A2 否。结论由 `m1_ablation.json.comparison` 给出。A1b 与 A2 的剩余零变化属**本工区地貌与选点共同决定的可观测性局限**，不等于模型空转；如继续要求其选线差异，须再按证据修订基准 OD。

## 运行方式

在工作树根目录执行：

```powershell
# 1. 验证工作区数据引用与基线瓦片
python scripts/run_local.py verify

# 2. 执行忽略文件安全审计
python scripts/audit_gitignore.py

# 3. 一键执行 M0 规范化基准管线（场景契约、正射预览、属性审计及重跑基线）
python scripts/run_local.py m0-baseline

# 4. 一键执行 M1 物理通行属性消融实验管线
python scripts/run_local.py m1-ablation

# 5. 运行 M1 物理消融单元测试
python scripts/run_local.py pytest tests/test_m1_ablation.py -v

# 6. 运行全仓库完整回归测试
python scripts/run_local.py pytest tests/ -q

# 7. 启动桌面端并加载 M0 项目（包含本地正射影像底图叠加）
python scripts/run_local.py desktop --project configs/manned_offroad_m0.yaml
```

## 本地配置与证据产物

- `configs/manned_offroad_m0.yaml`：M0 固定工区、OD、车辆、冻结气象与正射底图配置。
- `configs/scenes/m0_qdx_scene.json`：符合 `StaticScene` 规范的固定场景元数据。
- `configs/scenes/baseline_986bd58_weather.json`：2026-10-15T08:00Z 真实 Open-Meteo 冻结干旱/微雨气象快照。
- `configs/scenes/synthetic_rainy_weather.json`：合成降雨敏感性对照场景快照（`derived_pressure = 0.8`，耦合 CLDAS 0.3301 m³/m³ 静态含水率与水文 D 场）。
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