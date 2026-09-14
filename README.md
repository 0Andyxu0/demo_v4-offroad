# H3 Off-road Planner (越野多目标路径规划系统)

基于 Uber H3 离散六边形分层格网的高精度越野通行力建模与多目标路径规划系统。系统解耦传统 AHP/TOPSIS 主观权重，建立基于车辆物理力学裕度的通行代价评估体系，构建请求内精确 PortsMap 拓扑，支持确定性多候选路径规划、动态走廊聚类、D* Lite 局部重规划以及工业级 GIS 交付产物导出（JSON / GeoPackage / GeoJSON / Tile Parquet）。

---

## 🌟 核心特性与架构

- **双层高精格网基线**：默认采用父格网 **res11**（瓦片管理层）+ 子格网 **res14**（亚米级精确物理评估层），单瓦片包含约 343 个高精子六边形格网。
- **物理裕度代价模型**：无主观权重的物理瓶颈评估（`safety_margin`），逐边精确计算通行时间（ETA）、行驶能耗代价与地形几何风险。
- **确定性 Pareto 规划**：多目标（时间、距离、风险、代价）Pareto 最优前沿求解与角色偏好（Fastest、Safest、Energy-efficient、Balanced）路径分配。
- **静态 GIS 土壤—机动迁移链**：分类土壤只保留来源事实；离线 GRASS 水文输出 TWI、排水敏感度 D 和有效性；路径阶段以独立环境等效距离 J、后轴参考车体连续扫掠、15% 绕行预算及 5% 切换滞后完成稳健选路。
- **QDX 真实 GIS 深度适配**：
  - 支持 **CGCS2000 (EPSG:4490)** 坐标系自动识别与 WGS84 (EPSG:4326) 无损投影；
  - 自动遍历与融合 QDX 矢量用地数据（林地、草地、耕地、水体、灌木、建筑、荒地、道路网），智能过滤 `bound.shp`；
  - 自动提取并挂载树木深/冠径（`depth`）与行株距（`rowspacing`）等越野微地形参数；
  - 具备边缘瓦片容错与不规则边界连续覆盖能力。
- **断点续算与分块瓦片缓存**：支持大型战区/作业区瓦片化离线构建（Parquet 格式），规划时动态空间相交加载。
- **工业级工程标准**：遵循 Gate 1 架构与测试设计准则，通过严格的 400+ 自动化测试套件、独立语句/分支覆盖率门槛和 Mypy Strict 检查。

---

## 📁 目录结构

```text
demo_v4/
├── configs/                     # 系统核心配置文件
│   ├── mvp81_qdx_delivery.yaml  # QDX 真实数据集全流程交付配置（res11+res14）
│   ├── static_factor_model.yaml # 地表覆被与速度因子配置
│   ├── vehicle.yaml             # 车辆物理参数配置
│   ├── static_gis_planning.yaml # 静态环境、车辆几何与稳健决策策略
│   ├── hydrology.example.yaml   # 离线 GRASS 水文处理示例
│   └── deterministic_pareto_planner.yaml # 规划器多目标参数
├── data/                        # 示例与处理后数据
│   └── qdx/                     # QDX 融合后矢量及测试数据
├── docs/code/h3-offroad-planner/ # 技术基线与规范文档
│   ├── README.md                # 技术基线与演进索引
│   ├── adr/                     # 架构决策记录（ADR-001 ~ ADR-023）
│   ├── spec.md                  # 系统工程需求规范
│   ├── architecture.md          # 全局架构设计
│   └── gate1-design-score.md    # Gate 1 量化评分（1.00 / 1.00）
├── src/h3_offroad_planner/      # 核心算法源码
│   ├── grid/                    # H3 网格构建与矢量/栅格属性挂载
│   ├── preprocessing/           # GIS 栅格与矢量预处理（CGCS2000/EPSG:4490 转换）
│   ├── tiling.py                # 分层瓦片缓存构建与管理
│   ├── routing.py               # Pareto 路径搜索与拓扑图构建
│   ├── route_planning.py        # 闭环全局规划入口
│   ├── dynamic_replanning.py    # D* Lite 动态重规划
│   └── exporting.py             # GPKG / JSON / GeoJSON 导出
├── scripts/                     # 运维与验证脚本
│   ├── verify_baseline.py       # 基线完整门禁自动化验证
│   └── prepare_qdx_dataset.py   # QDX 原始数据校验与预处理工具
└── tests/                       # 自动化测试集（含 QDX 双盲测试）
```

---

## 🚀 快速开始

### 1. 环境准备

确保 Python 环境版本 $\ge 3.10$，并在项目根目录以可编辑模式安装：

```powershell
pip install -e . --no-deps
```

### 2. QDX 原始数据预处理（可选）

对 `D:\Workspace\qdx数据` 下的多图层矢量与 DEM 进行字段扫描与合规合并：

```powershell
python scripts/prepare_qdx_dataset.py --qdx-dir "D:/Workspace/qdx数据" --output-dir "data/qdx"
```

### 3. 执行端到端交付与路径规划

使用 QDX 交付配置一键运行瓦片缓存构建与最优候选路径规划：

```powershell
python -m h3_offroad_planner run --request configs/mvp81_qdx_delivery.yaml
```

如需生成静态水文缓存，先复制并填写 `configs/hydrology.example.yaml` 中的米制投影 DEM、
分析分辨率和已冻结 TWI 阈值，再运行：

```powershell
python -m h3_offroad_planner preprocess-hydrology --request configs/hydrology.example.yaml
```

`mapping_t0/mapping_t1` 未填写时只生成诊断 TWI，不把 `null` 当作中性 D。车辆宽度、轴距、
前后悬缺失时仍保留 H3 候选，但连续轨迹明确标为 `not_evaluated`，不会伪造整车可通行结论。

产物将输出至：
- 瓦片缓存：`outputs/qdx_tiles/tile_manifest.json` 及 `outputs/qdx_tiles/tiles/`
- 规划结果：`outputs/qdx_route/route_plan.json`、`route_candidates.gpkg` 等。

---

## 🧪 基线门禁与质量验收

执行项目全量基线验证脚本（包含测试覆盖率、类型检查、代码规范与架构合规性）：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts/verify_baseline.py
```

- **测试用例**：401 项通过、2 项按环境条件跳过。
- **代码覆盖率**：语句覆盖率 84.08%，分支覆盖率 70.09%。
- **静态类型**：`mypy --strict` 零报错（48 个源文件）。
- **代码规范**：`ruff` 零警告。

---

## 📖 详细技术文档

更多详细技术规格与架构决策请参考：
- [技术基线索引](docs/code/h3-offroad-planner/README.md)
- [ADR-023: QDX 真实数据集与 res11/res14 亚米级基线](docs/code/h3-offroad-planner/adr/ADR-023-qdx-dataset-and-res11-res14-baseline.md)
- [需求与设计规范 Spec](docs/code/h3-offroad-planner/spec.md)
- [Gate 1 量化设计门禁评分表](docs/code/h3-offroad-planner/gate1-design-score.md)
- [静态 GIS 土壤—机动迁移实施方案](docs/code/h3-offroad-planner/static-gis-soil-motion-transfer-technical-plan.md)
