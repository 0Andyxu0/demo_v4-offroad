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
  - 全套回归测试 520 passed, 4 skipped；
  - 专门增加 `tests/test_static_scene.py`（StaticScene 强类型序列化、合成矢量/栅格 fixtures 场景准备、降级气象拦截、缺失输入拦截、已有场景文件/字典解析、实际 QDX 数据准备回归、地理 metric_crs 拦截、退化几何拦截、非重叠栅格拦截、气象数值合法性拦截、缺失含水率文件拦截）与 `tests/test_orthophoto_preview.py`（裁剪下采样、坐标越界拦截、项目配置解析、Leaflet 地图叠加），全部通过。

### M1 静态通行属性修复与物理消融（已完成闭环）

- **R1 道路有效宽度米制换算 (`resolve_road_effective_width_m`)**：
  - 对照高分正射影像与图层编码，确认 `road_fina.shp` 的 `Width` 字段为分米（0.1m）编码（值域 30.0~55.0）；
  - 在 `src/h3_offroad_planner/scene.py` 与 `configs/scenes/m0_qdx_scene.json` 中增加 `width_unit_or_scale: "0.1m"` 与 `effective_width_m_range: [3.0, 5.5]`，提供统一辅助函数 `resolve_road_effective_width_m(raw_width, func_class, scale=0.1, default_m=3.5) -> float`；杜绝直接将原始 30.0~55.0 当作米使用而生成 30~55 米巨型虚假走廊；场景准备解析时安全过滤非字段配置项，支持从 `road_mapping` 动态解析配置。
- **R2 土壤 Bekker/CI 物理参数、干密度换算与超限阻断 (修复 A1b)**：
  - 严格依据 Shahgholi et al. (2024) 农艺壤土/黏壤土实测数据修正 $k_c, k_\phi, n$ 回归系数（黏壤土：$k_c = -34.53 w_{\%} + 1475.7$，$k_\phi = -33.606 w_{\%} + 2560.6$；壤土：$k_c = -24.59 w_{\%} + 1065.9$，$k_\phi = -24.482 w_{\%} + 2087.4$）；
  - 建立体积含水率 $\theta_v$（$\text{m}^3/\text{m}^3$）与质量含水率 $w_{\%}$ 的干密度物理换算：$w_{\%} = (\theta_v \cdot \rho_{\text{water}} / \rho_d) \times 100\%$（取 $\rho_{\text{water}} = 1.0\text{ g/cm}^3, \rho_d = 1.4\text{ g/cm}^3$）；在实测 $10\%\sim 40\%$ 范围内 $k_c$ 始终为确定正物理值；
  - 超出文献适用土类或参数失效时规范回退至声明的土类与圆锥指数（CI）评价规则，不再将缺值直接赋为无穷大沉陷或零沉陷；针对极端饱和（$\theta_v \ge 0.65$）走标准圆锥指数规则，CI 低于门限（`min_cone_index_kpa: 150`）时以 `CONE_INDEX_INSUFFICIENT` 明确阻断；当沉陷超过离地间隙时以 `SINKAGE_CLEARANCE_EXCEEDED` 阻断；标量 `BekkerChecker` 与向量化 `evaluate_soil_bekker_vectorized` 保持完全一致。
- **R3 CLDAS 静态含水率与水文 D 场接入，规范降雨场景 (修复 A1c)**：
  - 将工区格元与 CLDAS 静态含水率栅格采样（基底 $0.3080\text{ m}^3/\text{m}^3$）及固定上游水文域 D 场（`qdx_hydrology_upstream_v1/drainage_sensitivity.tif`，值域 $[0, 1]$）全面打通；
  - 针对暴雨对照，新增 `configs/scenes/synthetic_rainy_weather.json`，在配置与元数据中显式标注为“合成降雨敏感性对照场景”（`synthetic_rainy_weather_sensitivity_contrast`，`derived_pressure = 0.8`），与真实历史 API 快照严格区分，杜绝冒充真实观测；降雨时在低洼汇水冲沟区产生最高 $2.44\times$ 地表阻抗倍率（基准倍率 $1.864\times$），主动引导路径规避湿软冲沟。
- **R4 零近似误差的正切纵横坡解耦 (完善 A2)**：
  - 废除原角度直接平方相减的近似公式，在标量 `_directed_edge_metrics`、`compute_directed_roll_deg` 与向量化 `evaluate_directed_edges_vectorized` 中统一采用无近似误差的精确正切分解：
    $$\tan\theta_{\text{roll}} = \sqrt{\max\left(0, \, \tan^2\theta_{\text{terrain}} - \tan^2\theta_{\text{pitch}}\right)}, \quad \theta_{\text{roll}} = \arctan(\tan\theta_{\text{roll}})$$
  - 标量与 NumPy 向量化逐元素误差 $< 10^{-12}$；彻底移除单一 DEM 标量坡度超限即一票否决删除节点的粗暴逻辑，在 Iveco 爬坡 $31.0^\circ$ 与横倾 $25.0^\circ$ 双约束下，精确放行安全对角通行边。
- **R5 真实 QDX 瓦片图与 5 组基准 OD 端到端消融验证**：
  - 废除仅测试 7 个内存单元格的旧测试脚本，重写 `scripts/run_m1_ablation.py`，加载真实的 5 组 OD 走廊瓦片图（覆盖 454,475 个格元与 2,133,478 条有向边）；
  - 严格执行 `A0 → A1a → A1b → A1c → A2` 5 个单变量递进消融，全部 5 组基准 OD（`od_01_primary`, `od_02_forest_rowspacing`, `od_03_water_gully`, `od_04_narrow_road`, `od_05_slope_traverse`）完成真实图搜索，产出真实消融证据 `outputs/m1_ablation/m1_ablation.json` 与 `m1_ablation_summary.md`。
- **R6 文档事实记录全面核对与对齐**：
  - 修正 OD 标识、车辆实际涉水间隙（$0.225\text{ m}$ 与测试车 $0.308\text{ m}$）、气象衍生压力参数（`0.8`），以真实统计数据更新消融运行结果。

## 基线与消融运行结果

### M0 可复现基线结果

在固定工区与冻结气象下运行 `scripts/run_m0_baseline.py`，退出码 0：
- 图规模：加载 41,503 个细格元和 120,647 条边；
- 道路有效宽度审计：124 条要素原始值域 30.0~55.0 分米，换算为有效米制宽度 3.0~5.5m；
- 候选路线：生成 5 条候选（推荐 candidate ID：`route-6b6c07b10e2d5803`）；
- 产物哈希与配置校验一致记录于 `outputs/m0_qdx_baseline/m0_baseline.json` 与 `static_scene.json`。

### M1 物理通行属性消融真实评测结果 (A0 → A1a → A1b → A1c → A2)

运行 `scripts/run_local.py m1-ablation` 针对 QDX 真实工区瓦片图（454,475 格元，2,133,478 有向边）和 5 组基准 OD 开展全量消融实验：

1. **工区走廊级节点与边通行统计**：
   - **A0 基线**：可通行格元 362,621 (79.79%)，可通行边 2,118,222 (99.28%)；阻断原因：`BUILDING:28696, STATIC_BLOCKED:91187, STEEP_SLOPE:1147`（存在行距/水深跳过、软土无阻断与节点坡度误删）。
   - **A1a 恢复株距与水深**：可通行格元 359,518 (79.11%)，可通行边 2,099,240 (98.40%)；新增阻断：`ROWSPACING_BLOCKED:3113, WATER:28696, WATER_DEPTH_LIMIT:62491`，严格拦截密林与深水。
   - **A1b 土壤力学与 Bekker/CI**：可通行格元 359,518 (79.11%)，可通行边 2,099,240 (98.40%)；CLDAS 静态含水率 0.308 下黄棕壤具备合理承载力，极端饱和时规范阻断。
   - **A1c 气象与水文域地表阻抗**：低洼汇水冲沟区地表阻抗提升至最高 2.44 倍，路径主动撤离低洼汇水区。
   - **A2 正切纵横坡解耦**：可通行格元恢复至 360,175 (79.25%，+657格元)，可通行边 2,099,528 (98.41%)；彻底消除 `STEEP_SLOPE` 节点删除，放行对角平缓爬坡微段。

2. **5 组基准 OD 真实规划结果**：
   - `od_01_primary`（吸附: 0.0m / 0.0m）：A0~A1b 距离 731.3m (50.9s, 成本 742.2) → A1c/A2 距离 873.5m (57.7s, 成本 884.1)；暴雨下冲沟高阻抗引导路径主动走高燥铺装路；A2 消除周边陡坡误阻。
   - `od_02_forest_rowspacing`（吸附: 1.0m / 1.1m）：A0~A1b 距离 576.7m (42.2s, 成本 586.2) → A1c/A2 距离 728.7m (49.7s, 成本 757.1)；A1a 拦截行距 < 2.056m 密林，A1c 避开低洼湿软林缘。
   - `od_03_water_gully`（吸附: 1.1m / 40.6m）：终点精准吸附至水体边界通行格；距离 451.9m；A1c 暴雨下路径旅行成本自 457.7 激增至 853.6 (+86.5%)，有效反映湿软危险。
   - `od_04_narrow_road`（吸附: 290.6m / 34.0m）：道路与自然土交界走廊（354.0m）；准确反映路基与土路机动性差异，A2 消除道路周边边坡的标量误删。
   - `od_05_slope_traverse`（吸附: 25.5m / 0.3m）：起终点吸附至山地主连通区（919.2m）；A1c 暴雨下山脚汇水冲沟阻抗增加（成本 927.7 -> 1231.8）；A2 消除 STEEP_SLOPE 粗暴阻断，正切横坡分解精确保留斜切登山边。

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
- `configs/scenes/synthetic_rainy_weather.json`：合成降雨敏感性对照场景快照（`derived_pressure = 0.8`，耦合 CLDAS 0.3080 m³/m³ 静态含水率与水文 D 场）。
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
