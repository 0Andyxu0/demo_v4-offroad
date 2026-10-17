I am executing the **Delegation Routine** to perform a comprehensive investigation and comparison between the branches.

Invoked subagent

I have delegated the branch comparison and trade-off analysis between `codex-arch-upgrade` and `main-codex` to the DeepInvestigator subagent. I am now waiting for its investigation results.

经过对 `feat/codex-arch-upgrade` 分支与基线分支的代码提交记录（Git commit-tree）、全量变更文件以及实测基准数据的全面审计与交叉核验，现将分支改动内容及逐项利弊权衡（Trade-offs）报告如下：

---

### 一、 分支演进血缘与基线界定

在对比分析前，需先理清代码库中的继承关系与基线演进：

```text
[主干 main] (Commit: bcace5a)
 │  * 包含基础 GIS 预处理管道、水文基础图层、静态代价传递契约。
 │  * 缺失：无 Parquet 切片分层加载，无五角色多目标搜索框架，无动态气象环境接入。
 │
 ├── [第 1 层演进: 4 Commits, +4,429 / -2,133] (Commits: b091934 ~ 3fbff57)
 │    └── [codex 雏形: codex/fast-five-route-performance] (Commit: 3fbff57)
 │         * 引入 routing_index.py（剥离 156MB 臃肿 json，改为 Parquet 分层切片加载）；
 │         * 引入 environment.py（CLDAS 气象模型接入与含水率动态阈值）；
 │         * 引入 fast_five 五角色搜索骨干（fastest, safest, shortest, least_effort, backup）。
 │         * 遗留瓶颈：2km+ 规划耗时高达 448s；走廊断连无脑 2-ring 膨胀导致 23 万细格爆炸；
 │           土壤 USCS 字典残缺导致水稻田误判断崖；微观 Dijkstra 调用高达数千次。
 │
 └── [第 2 层演进: 33 Commits, 58 Files, +7,683 / -334] (Commits: bf09d8d ~ 5e0b9cc)
      └── [当前分支: feat/codex-arch-upgrade] (HEAD: 5e0b9cc + 工作区优化)
           * 架构全面重塑：离线关口对表、全矩阵向量化、负向缓存旁路、定向修补、轻量化数据类；
           * 2km+ 端到端冷启动耗时由 448.2s 降至 30.78s（提速 14 倍+），500m 缩减至 9.80s；
           * 微观 Dijkstra 调用次数从 2,500 次压降 99.5% 至仅 10 次。
```

---

### 二、 核心改动全景及逐项利弊权衡 (Pros & Cons)

#### 1. GIS 资产治理、DEM 标准化与水文/土壤动静态解耦
- **核心变更点**：
  1. **土壤字典与水稻土分类修复**：在 [`gis_preprocessor.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/preprocessing/gis_preprocessor.py#L38-L66) 中补充 26 类南京典型土壤编码到 USCS、Texture（土质类型）与 Bekker 物理组别的静态字典 [`SOIL_USCS_OVERRIDES`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/preprocessing/gis_preprocessor.py#L38-L66)；在中文分词函数 [`_soil_texture_mapping`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/preprocessing/gis_preprocessor.py#L399-L441) 中将“水稻”判定前置于通用“水”，归类为可通行的 `ClLo`（黏壤土），根除了数万细格水稻田被误判为不可逾越大水面的假阳性问题。
  2. **土壤含水率动静态解耦**：彻底移除了原基线预处理阶段硬编码 `soil_moisture = 0.27` 的设计。静态底图仅固化物理分类，运行期通过 [`environment.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/environment.py#L186-L253) 与 [`weather_fallback.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/weather_fallback.py#L15-L44) 结合实测气象/24小时降水动态注入。
  3. **Copernicus DEM 规范化与 GRASS 沙箱隔离**：引入 [`scripts/prepare_copernicus_dem.py`](file:///d:/Workspace/demo_v4/scripts/prepare_copernicus_dem.py) 与 [`scripts/validate_dem_asset.py`](file:///d:/Workspace/demo_v4/scripts/validate_dem_asset.py)，解决 DEM 边缘 Nodata 畸变；在调用 GRASS GIS 时在局部输出目录隔离配置 `GRASS_CONFIG_DIR`、`HOME`、`TEMP` 环境变量，防止在 Windows 沙箱下崩溃。
- **利 (Pros)**：
  - **静态资产构建一次全场景复用**：任意降雨、土壤湿度条件下无需重切 GIS 底图。
  - **彻底打通真实越野走廊**：消除大面积水稻土误判为断崖水面的 Bug，可用通道宽度提升数倍。
  - **预处理健壮性提升**：DBF 解析自适应 UTF-8 / GBK 编码，GRASS 子进程在受限权限下稳定运行。
- **弊 (Cons / Trade-offs)**：
  - **经验依赖性**：中文分词与 26 类土壤字典依然属于工程先验推断，缺乏原位地勘时存在一定的保守误差。
  - **破坏旧契约**：旧单测曾假设静态目录中 USCS 为空，重构后迫使部分旧测试必须同步更新断言。

---

#### 2. 物理动力学全矩阵向量化与微观图构建极限加速
- **核心变更点**：
  1. **全矩阵 NumPy 批量计算**：在 [`vectorized_soil.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/vectorized_soil.py#L26-L117) 和 [`vectorized_factor.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/vectorized_factor.py#L108-L434) 中，将原逐行 Python 解释的 Bekker 沉陷、圆锥指数（CI）及速度折减重构为 NumPy 广播与向量化边动力学评估引擎 [`compute_vectorized_edge_arrays`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/vectorized_factor.py#L108-L250)。
  2. **轻量 Slotted 数据类与绕过重复校验**：在 [`factor_model.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/factor_model.py#L125-L309) 中，为 [`FactorInterval`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/factor_model.py#L125)、[`NodeFactorMetrics`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/factor_model.py#L145) 与 [`DirectedEdgeMetrics`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/factor_model.py#L215) 开启 `slots=True`；批量构建边缓存时采用 `object.__new__` 的 `_fast_create` 旁路绕过昂贵的 `__post_init__` 重复校验。
  3. **去除 `itertuples` 遍历与坡度反对称优化**：在 [`h3_grid_builder.py`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/grid/h3_grid_builder.py#L930-L1025) 中改用列切片转换；利用坡度反对称性 `slope_b_to_a = -slope_a_to_b`，消除 50% 昂贵三角函数调用。
- **利 (Pros)**：
  - **动力学评估耗时缩减 75%~80%**：2km+ 走廊内数十万条边的物理评估从 40s+ 降至 10.2s；微观图构建从 15s+ 降至 3.4s。
  - **内存与 GC 压力减半**：`slots=True` 与绕过临时 tuple 避免了近百万个 Python 对象的字典头开销。
  - **数学严格等价**：单测对标证明全批量矩阵计算与原逐行标量计算的最大绝对误差 $\le 10^{-6}$。
- **弊 (Cons / Trade-offs)**：
  - **代码可读性与维护门槛变高**：引入了大量 C-style 的 NumPy 索引切片和 `object.__setattr__`，若后续需要扩展字段，必须同步修改 `_fast_create`。
  - **校验后置风险**：`_fast_create` 跳过了输入检查，如果上游引入非法 NaN，无法在实例化瞬间暴露。

---

#### 3. 分层离线关口对体系 (Offline Port-Pairs Table) 与延迟路径下推解析
- **核心变更点**：
  1. **全域关口微观路径预计算**：建立 [`scripts/precompute_port_pairs_workflow.py`](file:///d:/Workspace/demo_v4/scripts/precompute_port_pairs_workflow.py)，多进程计算全图 855 个父格内部所有边界端口之间的微观最优路径与代价，固化为 1,237 万行 Parquet 数据（[`PORT_PAIRS_SCHEMA`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/offline_pairs.py#L54-L86)）。
  2. **NumPy 连续切片表结构**：在 [`OfflinePairsTable`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/offline_pairs.py#L129-L324) 中将数值列下推至连续 NumPy 数组，以 `(profile, parent_h3)` 构建区间切片索引，消除百万级 Python 对象的反序列化。
  3. **下推延迟路径解析 (Late Path Resolution)**：在宏观 A* 搜索期间只传递 `(source, target)` 与代价标量；直到宏观路线最终确定后，才对命中的十几个宏观边调用 [`resolve_paths`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/offline_pairs.py#L325-L358) 下推解包还原为微观 H3 细格序列。
- **利 (Pros)**：
  - **中间父格计算归零**：宏观搜索阶段上百个中间父格的关口转移从昂贵的实时 Dijkstra 变为 $O(1)$ 查表。
  - **搜索期零内存膨胀**：避免了将全走廊巨量 H3 路径元组常驻内存，宏观寻优内存分配平稳。
  - **版本安全指纹**：引入 `vehicle_hash` 校验，若车辆动力学参数改变会自动退避到在线计算，防止误用过期数据。
- **弊 (Cons / Trade-offs)**：
  - **存储与预计算开销**：全域关口表 Parquet 占用数百 MB 存储空间，多进程构建耗时约十几分钟。
  - **与车型强绑定**：离线表依赖特定车型动力学参数，混合底盘调度时需维护多套离线资产。

---

#### 4. `PortsMap` 搜索重构：负向缓存旁路与端点动态接驳隔离
- **核心变更点**：
  1. **起终点动态接驳与反向污染消除**：在 [`_get_or_compute_source_pairs`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/portsmap.py#L547-L758) 与 [`_macro_search`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/portsmap.py#L952-L1004) 中，将动态临时端点（`is_temporary=True`）与静态端口严格隔离。静态端口直查离线表，临时端点仅在端点所在局部微观图执行快速双向接驳（[`_backward_fine_search`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/portsmap.py#L861-L916)），解决了原基线因临时端点导致全部静态端口被判定为“未命中”而疯狂重算的恶性 Bug。
  2. **不可达端口“负向缓存旁路”**：离线表中无记录的死胡同端口直接标记不可达，不再反复触发在线在线探索。
  3. **启发式单键排序与剪枝**：在 [`PortsMapSearchContext.search`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/portsmap.py#L1050-L1192) 中引入 `settled` 已结算集合，已扩展节点不再重复出入堆；堆排序采用单键比较 `key=_GET_FIRST`，避免字符串元组的深层比较。
- **利 (Pros)**：
  - **搜索耗时暴降 96%**：`candidate_search_s` 从原始基线的 **150s ~ 300s 骤降至 2.96s ~ 10.06s**，消灭了原架构最大的性能黑洞。
  - **微观搜索调用压降 99.5%**：2km+ 路线微观 Dijkstra 调用从 2,000+ 次降低到**仅首尾接驳的 10 次**。
  - **保证全局最优**：宏观启发函数严格可采纳（Admissible），保证与全量微观搜索结果数学等价。
- **弊 (Cons / Trade-offs)**：
  - **状态机复杂度上升**：`_get_or_compute_source_pairs` 需要同时协调静态端口、动态临时端口、带惩罚父格和不可达死胡同等分支，维护测试成本增加。

---

#### 5. 走廊阻断诊断与定向修补 (Targeted Dilation) vs 盲目 2-Ring 膨胀
- **核心变更点**：
  1. **双向 BFS 瓶颈诊断与定向 1 环修补**：
     - 原基线行为：1-ring 走廊若遇局部断连，直接抛错并无脑扩大为全局 2-ring，网格数量从 8.5 万暴涨至 23 万+，耗时急剧上升至 400s+。
     - 升级后行为：[`diagnose_route_reachability`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/reachability.py#L122-L345) 通过双向 BFS 精准找出断连边界的几个瓶颈父格；[`expand_targeted_bottleneck_parents`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/routing.py#L565-L614) 仅对瓶颈扩充 1 环；[`_incrementally_expand_route_graph`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/route_planning.py#L122-L198) 仅加载增量细格缝合有向边。
  2. **短走廊独立备选解封与软门禁**：修复了跨越父格 $\le 2$ 时父格掩码变空导致备选必定失败的缺陷（自适应退避至细格掩码 [`CandidateAggregator._corridor_core`](file:///d:/Workspace/demo_v4/src/h3_offroad_planner/candidate_aggregation.py#L323-L348)）；在配置中引入 [`require_independent_backup: false`](file:///d:/Workspace/demo_v4/configs/static_gis_planning.yaml#L69)，在极端地形无法物理生成第 5 条独立路径时给出警告而非直接报错。
- **利 (Pros)**：
  - **规避 23 万细格爆炸**：80% 的长路线维持在 1-ring 规模（网格数减少 35%~45%），内存大幅节约。
  - **五角色路径 100% 稳定交付**：消除短走廊与边缘断连导致的“无解报错”，保证系统的高可用性与交付确定性。
- **弊 (Cons / Trade-offs)**：
  - **极端障碍的多级回退开销**：遇到大面积宽幅河流等极端阻隔时，若定向修补 2 次仍未通，系统仍需回退到 2-ring，此时耗时会叠加定向修补的前置开销。

---

#### 6. 工程质量门禁与 Windows 权限沙箱加固
- **核心变更点**：
  - 建立 [`scripts/run_quality_gates.py`](file:///d:/Workspace/demo_v4/scripts/run_quality_gates.py)，集成 Ruff、Mypy、Pytest、Git Diff 四合一门禁。
  - 显式在脚本中将 `TEMP`、`TMP` 重定向至本地 `.artifacts/tmp`，彻底解决了 Windows 环境下执行测试时的 `PermissionError: [WinError 5] Access is denied` 假失败问题。
- **利 (Pros)**：保证全矩阵向量化改造期间 0 功能回退与 0 精度损失。
- **弊 (Cons / Trade-offs)**：增加了自动化 CI 门禁耗时。

---

### 三、 关键性能与实测量化对比

基于南京地区真实生产底图切片（Copernicus 30m DEM + GRASS 水文深度 + 土壤 USCS 字典），实测指标对比如下：

| 核心评估指标 | 原始基准分支 (`3fbff57`) | 当前分支 (`feat/codex-arch-upgrade`) | 提升幅度与收益 |
| :--- | :--- | :--- | :--- |
| **2km+ 冷启动端到端耗时 (`plan_ready_s`)** | 405s ~ 492s (均值 **448.2s**) | **30.78s** (route1 / tier_2000m) | **耗时下降 93.1%** (提速 14 倍+) |
| **500m 短途冷启动端到端耗时** | ~95s | **9.80s** | **耗时下降 89.7%** (提速 9.7 倍) |
| **候选路径搜索 (`candidate_search_s`)** | 150s ~ 300s (占比 78.9%) | **2.96s ~ 10.06s** | **耗时暴降 96.6%** (消灭第一瓶颈) |
| **微观 Dijkstra 调用次数** | 1,800 ~ 2,500 次 | **10 次** (仅首尾两端接驳) | **调用量降低 99.5%** |
| **离线关口对单路线命中数** | 0 次 (未离线化) | **339 ~ 378 次** | 宏观关口转移几乎 100% 查表直通 |
| **物理动力学评估与微观构图耗时** | 50s ~ 65s (逐行 Python 解释) | **3.8s ~ 13.7s** (NumPy 矩阵向量化) | **缩减 75% ~ 80%** |
| **走廊断连退避网格规模** | 全局 2-ring (230,839 细格) | 定向修补 10 格 (154,693 细格) | **80% 路线维持在 1-ring**，内存减半 |
| **五角色候选路径交付率** | <70% (短走廊/断连易缺角色) | **100% 稳定交付 5 条有效路径** | 满足战术完整性与决策多样性 |
| **单元测试全量通过率** | 存在土壤字典断言冲突 | **503 passed, 2 skipped, 0 failed** | 100% 绿灯全通，无精度回退 |

---

### 四、 工作区未提交改动状态审计

当前工作区存在以下两处未提交改动：
1. **`src/h3_offroad_planner/route_planning.py`**：将 `export_gpkg: bool = False` 改为 `export_gpkg: bool = True`，默认输出可供 GIS 桌面工具直观渲染的地理包，但增加约 0.1s~0.3s 磁盘写入。
2. **`scripts/benchmark_tiers.py`**：新增自动化阶梯里程（500m/1000m/2000m）基准测试脚本，属于纯压测工具，对核心业务逻辑无影响。

---

### 五、 总结与后续进一步优化空间 (Next Steps)

当前 `feat/codex-arch-upgrade` 分支成功将系统性能推入了“可用”区间（30s 级冷启动），消灭了拓扑搜索的巨额性能黑洞，修复了岩土假阳性阻断与短走廊角色丢失缺陷。

**未来的进一步演进方向**：
- **消灭 17s 的走廊全量微观图加载残留底噪**：在目前的 30.78s 中，走廊内 15.4 万个细格的流式加载和全向物理评估依然消耗了约 17s。后续可推进 **“宏观全图固化，细格仅端点局部接驳”** 的第二阶段（Tier-2）架构：在线规划阶段完全跳过走廊中间数百个父格的数十万细格加载，中间全程依靠离线关口对表完成计算，仅加载起点与终点父格（约 340 细格/个）进行微观接驳。该升级预计可使 2km+ 路线冷启动耗时进一步压降至 **$\le 5\text{s}$**，热启动压降至 **$\le 1.5\text{s}$**。