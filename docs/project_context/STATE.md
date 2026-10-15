# 当前实施状态

更新：2026-10-15。工作树：`D:/Workspace/demo_v4-manned-offroad`。分支：`codex/manned-offroad-map`。
历史基线：`986bd58eef846f6f8a34961a43b208c315471110`；当前提交以 `git rev-parse HEAD` 为准。

## 已完成

- 从指定基线创建同仓库工作树，原 `demo_v4` 保持原分支和文件。
- 迁入固定实施方案、基线架构说明、模块资料索引与必要审核探针。
- 使用本机默认 Python 3.12.10：`C:/Users/31287/AppData/Local/Programs/Python/Python312/python.exe`。GIS、PyQt5、QtWebEngine、pytest 依赖可用；没有安装或替换全局包。
- `scripts/run_local.py` 提供 CLI、desktop、pytest、verify 入口，确保导入本工作树源码。
- 独立复制基线瓦片与路由索引共 6,766 文件、595,784,161 字节，复制时逐文件 SHA-256 一致；只改写副本 `tile_manifest.json` 的缓存地址。原清单另存 `original_metadata`。
- 验证 6,756 个瓦片路径存在且全部位于本工作树输出目录；读取 DEM、正射影像、土壤栅格、9 个矢量图层、3 份 CLDAS 静态含水率文件和 7 个水文栅格。
- 森林 `rowspacing` 有值 557 条，水体 `depth` 有值 599 条，道路 `Width` 有值 124 条；原值保留，字段编码的物理解释由 M1 对齐。
- 本地在线底图私有配置已复制，凭据仍留在 Git 忽略文件。
- CLI 帮助正常；桌面项目和底图配置回归测试 15 passed。

## 基线运行结果

在新工作树实际运行原始 QDX OD，退出码 0，加载 41,503 个格元和 120,647 条边，返回 5 条候选并导出 GeoJSON/GPKG。`plan_ready_s=76.381761`，候选搜索 68.456878 s；这是本机一次启动验证，未作为新旧算法性能对比。

5 条候选的旧自主轨迹检查状态均为 `invalid`，保留该原始结果；有人驾驶模式的评分/交付适配尚未实施。历史输出单独位于 `historical_route`。

真实 Open-Meteo 请求成功（`degraded=false`），有效时刻 `2026-10-15T08:00:00+00:00`，表层含水率 0.25 m³/m³、前 24 h 降水 0.3 mm。已冻结到 `configs/scenes/baseline_986bd58_weather.json`。本地配置默认回放该快照，不把后续查询日天气混入同一基线。

## 运行方式

在工作树根目录执行：

```powershell
python scripts/run_local.py verify
python scripts/run_local.py cli plan --request configs/manned_offroad.local.private.yaml
python scripts/run_local.py cli plan --request configs/manned_offroad.baseline.private.yaml
python scripts/run_local.py desktop
python scripts/run_local.py pytest tests/test_desktop_project_validation.py tests/test_map_config.py -q
```

桌面启动器指定本工作树 QDX 配置，避免使用基线源码中指向 demo_v1 的默认示例。`plan` 使用迁移的缓存；`run` 会重建并规划，准备阶段不要用它替代 `plan`。

## 本地配置与证据

- `configs/manned_offroad.local.private.yaml`：日常开发配置，源 GIS 外部引用，新路线写 `outputs/manned_offroad_route`。
- `configs/manned_offroad.baseline.private.yaml`：冻结天气的基线复现配置，路线写 `outputs/baseline_986bd58/replay_route`，不覆盖首次 fresh_route。
- `configs/manned_offroad.example.yaml`：可提交的相对工作树路径示例；本地私有配置保留实际绝对路径。
- `configs/manned_assets.private.yaml`：正射影像、原始地物、CLDAS 和上游水文数据入口。
- `.artifacts/workspace-preparation/migration.json`：复制与地址迁移摘要。
- `.artifacts/workspace-preparation/cache_copy_hashes.json`：基线副本校验记录。
- `.artifacts/workspace-preparation/data_check.json`：实际读取元数据、字段和值样本。
- `.artifacts/workspace-preparation/baseline_stdout.json`、`baseline_stderr.log`：本轮运行日志。
- `.artifacts/workspace-preparation/baseline_result.json`：本轮实际运行摘要。
- `outputs/baseline_986bd58/`：独立缓存、原清单备份、历史结果与 fresh_route。

## 下一步与未完成项

当前完成的是工作树、数据入口和基线迁移，不是 M1–M5 实现。

1. M0 固定首个真实子工区和正式 OD/车辆/气象组合，保留本轮基线运行作为启动验证。
2. `986bd58` 桌面底图目前是在线瓦片与本地通行图，未提供本地正射 GeoTIFF 图层接口。T.tif 已可读并登记；本地正射图层显示与物理建图用途在 M0/M1 接入，不能称已在现有界面展示。
3. CLDAS 含水率和上游水文数据已接通文件入口，尚未替换基线物理链。旧静态模式的株距/水深旁路和土壤评价修复仍按 M1 实施。
4. 基线缓存与旧路线不因迁移自动获得新方案能力。后续建图使用 `outputs/qdx_tiles` 等新目录，保留基线副本作对照。
