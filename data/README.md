# data/inputs —— 本工作树的只读输入数据

本目录存放当前 M0/M1 链路真正读取的输入文件，用于摆脱对 `D:/Workspace/qdx数据`、`D:/Workspace/demo_v1`、`D:/Workspace/demo_v4` 的外部依赖。
除本 README 外，整目录被 `.gitignore` 的 `/data/**` 规则忽略（数据不入库，代码与配置入库）。

## 目录与来源

| 子目录 | 内容 | 原始位置 | 大小 |
|---|---|---|---|
| `dem/` | `DEM_CGCS2000.tif`（+tfw/aux/ovr）、`DEM.tif`、`DSM.tif` | `D:/Workspace/qdx数据/DEM-DSM/` | 38.8 MB |
| `landcover/` | 地物矢量（`bound` / `forest` / `water` / `building` 等 shp 组） | `D:/Workspace/qdx数据/矢量数据/` | 1.9 MB |
| `road/` | `road_fina.shp`（Width / FuncClass 字段源） | `D:/Workspace/qdx数据/road/` | 0.1 MB |
| `orthophoto/` | `T.tif` + `.ovr` / `.tfw` / `.aux.xml` | `D:/Workspace/qdx数据/正射影像/` | 1378.1 MB |
| `soil/` | `soil_nanjing.tif` + `soil_nanjing.tif.vat.dbf` | `D:/Workspace/demo_v1/data/` | 14.9 MB |
| `cldas/` | CLDAS 三层静态含水率 `.nc`（**2026-01-01**，现仅作敏感度输入） | `D:/Workspace/demo_v4/data/` | 7.6 MB |
| `hydrology/` | 上游水文 6 层（`twi` 已从场景去注册，文件保留）+ `hydrology_manifest.json` + `twi_threshold_analysis.json` | `D:/Workspace/demo_v4/outputs/qdx_hydrology_upstream_v1/` | 23.2 MB |

合计约 **1.46 GB**，2026-10-18 复制。复制为字节级拷贝，源文件哈希不变。

## 引用方式

配置改为**相对路径**（相对工作树根目录）：
- `configs/scenes/m0_qdx_scene.json`：17 处来源路径
- `configs/manned_offroad_m0.yaml`：`tile_build` 的 dem / landcover / road / roi / soil
- `configs/static_gis_planning.yaml`：soil 栅格与分类表

`scripts/run_local.py` 会把工作目录切到工作树根，因此相对路径可直接解析；脱离 `run_local.py` 运行脚本时需保证 cwd 为工作树根。

## 需要记录的事实

1. **CLDAS 是 2026-01-01 的冬季数据**，而制图期是 2026-10；静态含水率已改用冻结的制图期快照（DECISIONS 44），CLDAS 仅保留作敏感度输入。
2. **水文层是既有产物**，本次只搬迁不重算；重算会改变 D 场数值并作废既有证据。
3. **正射影像 1.38 GB** 是目录里最大的单项；它只用于预览与边界核对，不参与通行评价。
4. 原始 QDX 数据目录保持只读，未被修改。