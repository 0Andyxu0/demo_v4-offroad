# 有人驾驶越野通行地图与预算选线：固定实施方案

版本：1.0，2026-10-15。状态：**方案已固定，真实工区实现待开始**。

实施基线：`986bd58eef846f6f8a34961a43b208c315471110`。本文是后续实现的统一入口，整合 ARGON 1345 与对应审核修正。历史方案用于追溯，不与本文并列指导实现。本文中的新增类型、函数和配置均为待实现接口，不表示主干已经具备这些功能。

来源：[ARGON 1345](../../.artifacts/20261015-talk/argon1345.md)、[1345 审核](../../.artifacts/20261015-argon-1345-review/review.md)、[机制实验](../../.artifacts/20261015-argon-1345-review/probes.py)。本文已纳入必要结论，可脱离这些历史材料独立阅读。现有 [PROJECT_HOLOGRAM.md](../../PROJECT_HOLOGRAM.md) 作为基线架构快照使用。

## 1. 固定需求与交付目标

**使用 DEM、地物 TIF 或 SHP、遥感图像、土壤类型和土壤含水静态数据，辅以制作静态地图时真实气象修正，服务越野环境有人驾驶车辆的路线规划。允许路线出现格网离散导致的频繁小折线，由驾驶员局部修正。**

核心工作依次是：更好地构建越野通行地图、保留有用走廊、在合理绕行范围内选出整体更好的路线。输出包括路线引导线、可通行区域/走廊、沿程主要属性和整条路线的质量指标。轨迹平滑不作为有人驾驶模式选线的必要条件；真实障碍、车辆宽度、纵横坡、水深与软土通过能力仍进入通行评价。

天气只在制图/地图更新时修正通行条件，每个场景固定使用一份天气与含水率结果。查询期间不重新获取天气、不随搜索顺序改变边权。对照实验用同一场景快照。历史时段使用匹配时段的气象记录；合成干湿场景只能作为另列消融，不能代替真实气象修正。

误差分析、数据检查和状态检查是配套工作。首版不扩展成误差平差、不确定性传播、无人 UAV/UGV 控制、曲率连续轨迹或全局形式化完备性研究。

## 2. 冻结的技术主线与范围

**源地物边界驱动的选择性格内细化 → 介质侧入口与局部多通道图 → 绕行预算内累计质量选优 → 父格端口候选保留与按需补查。**

1. 开阔、同质区域沿用 H3 组织；在道路/自然土交界、窄通道、障碍边界，以及含水率/坡度变化会改变通道选择的区域细化。
2. 真实地物边界决定片段和通行开口。H3 边界、三角网分割线和父格边界只是组织边界，不充当障碍。
3. 片段内允许同一入口对存在多条曲线。先建立完整局部子图参考，再评价快速代表曲线的收益/损失。
4. 搜索固定为：非负静态可加 `(长度 L, 质量代价 Q)`，在统一长度预算内最小化累计 Q。
5. 先在有限真实工区建立未压缩细图 C00 与完整父格前沿 C0；确认地图与路线收益后再实施缓存补查和求解器优化。

论文贡献假设：选择性细化能够以受控图规模保留有用走廊和长度—质量折中，支撑有限绕行下更好的整体路线。具体收益由真实工区实验给出；不预先承诺所有指标同时下降。

## 3. 基线、目录与最小改造边界

2026-10-15 实查：`986bd58` 位于 `feat/codex-arch-upgrade`；名为 `main` 的分支仍为 `bcace5a`。实施从提交 `986bd58` 开始，不能因分支名称误用旧基线。建议开发分支 `codex/manned-offroad-map`，同仓库独立工作树 `D:/Workspace/demo_v4-manned-offroad`；本次固定方案不执行分支/工作树创建。

主干代码、CLI、桌面/WebGIS、车辆配置、原始数据读取和导出能力继续复用。沙盒 v2 只按模块选择性移植，经相同输入运行后接入，不整体替换主干。

实现代码进入 `src/h3_offroad_planner/`，持久测试进入 `tests/`，可重跑实验脚本进入 `scripts/`。本地数据路径使用忽略的私有配置；大数据与生成物继续在 Git 外管理。新工作树独立写入自己的输出目录，不覆盖 `demo_v4/outputs`。

首版建议只增加三个职责明确的源码文件：`local_passage.py`（类型与几何建图）、`route_quality.py`（微段评价与路线统计）、`planners/budget_quality.py`（预算搜索）。已有输入、因子、端口、缓存、持久化和显示模块按接口增量修改，不新增工厂/插件注册体系。文件过大时再按实际职责拆分。

## 4. 模块顺序与交付物

| 阶段 | 依赖 | 主要实现位置 | 输入 → 输出 | 阶段完成的具体表现 |
|---|---|---|---|---|
| M0 数据与基线准备 | 本方案 | `configs/`、数据预处理、桌面地图、实验脚本 | 原始数据/车辆/真实天气/OD → 固定工区配置与基线结果 | 同一工区可重跑 986bd58，正射影像和关键地物属性可读可显示，记录真实数据覆盖 |
| M1 静态通行属性 | M0 | `factor_model.py`、`vectorized_soil.py`、`dynamics/bekker.py`、`environment.py`、水文预处理 | 数据快照 → 静态地表属性、车辆通过规则与方向代价输入 | 株距/水深不被静态模式旁路，含水率进入土壤评价，纵横坡在有向曲线上判断 |
| M2 片段、入口和局部多通道 | M1 | `grid/h3_grid_builder.py`、新 `local_passage.py` | 固定地表场/H3/车辆 → `LocalPassageGraph` | 真实 GIS 自动生成片段与曲线；非凸片段曲线在可通行域内；偏心通道和同入口多曲线可保留 |
| M3 评分、预算搜索与输出贯通 | M2 | 新 `route_quality.py`、`planners/budget_quality.py`；`portsmap.py`、候选聚合、路线模型、持久化/显示 | 局部图/OD/预算 → 有身份的候选、推荐线与沿程统计 | C00 查询和图上回溯完成；同 H3 序列不同曲线不被误去重；有人驾驶路线不被自主平滑要求过滤 |
| M4 完整父格参考与真实工区比较 | M3 | `portsmap.py`、`offline_pairs.py`、`routing_index.py`、实验脚本 | C00 → C0 与 B 组对照结果 | C0 在完整入口条件下复现 C00 的预算可行性和最优 Q；输出通道、路线质量、建图规模表与地图 |
| M5 分层补查与效率优化 | M4 | `portsmap.py`、`offline_pairs.py`、预算搜索与对照脚本 | 同一图与完整参考 → C1–C4、D 组比较 | 测得缓存体积、在线补查次数/时间、路线质量损失；按结果选工程默认模式 |

前四步工程安排保持为：M0/M1 修通输入与物理属性；M2/M3 落地局部图和路线链；M4 建真实参考；M5 比较压缩和求解效率。M2 与 M3 共用微段类型定义，先定类型再填入几何与评分实现，避免模块反向依赖。

## 5. M0/M1：输入、地表与车辆评价接口

### 5.1 输入组织

`StaticScene` 至少包含 `scene_id`、米制投影 CRS、工区范围、源 DEM/地物/影像/土壤/含水率的引用、制图时间、冻结天气快照引用、水文域及 D 场引用、字段映射与模型版本。栅格按原生分辨率采样，矢量按实际几何解析，避免把 H3 分辨率当作观测分辨率。

| 输入 | 固定用途 | 必须贯通的属性 |
|---|---|---|
| DEM | 高程、地形梯度、粗糙度；支持有向纵横坡 | CRS、水平/高程单位、原生分辨率 |
| 地物 TIF/SHP | 地表分类、可通行片段、障碍与开口 | 类别、几何、株距、水深及来源字段 |
| 道路 | 道路片段与路外相邻区域分别评价 | 道路类型、有效宽度；线数据按有效宽度构建道路面 |
| 遥感/正射影像 | 保留底图显示，用于地物边界核对与可用矢量补充 | 范围、分辨率、时间；未经执行的影像解译不宣称已接入 |
| 土壤类型/含水率 | 静态承载力、沉陷与软土代价 | 土类映射、含水率单位/深度/时间、参数适用范围 |
| 制图期真实天气 | 在地图构建时修正湿润程度与地表通行条件 | 数据来源、有效时段、降雨/含水信息、实际使用的修正模型 |

若某字段只有区域统计意义，如林地平均株距，按区域车辆约束使用，不生成不存在的逐株树木坐标。道路邻近缓冲不能把附近自然土全部改成硬化路。没有桥梁/涵洞证据时，道路线与水体相交本身不证明可跨越。

QDX 配置中现有 `D:/Workspace/demo_v1/data` 和外部数据引用可继续读取；配置中的 `D:/Workspace/demo_v4/outputs`、旧配置引用需改为新工作树的独立输出/配置。优先复用大数据，不复制整套历史输出。

### 5.2 静态属性修复

- 修复 `strict_static_mode = environment is not None` 所关联的株距、水深旁路；“静态”不表示忽略静态地物属性。同步标量与向量化因子实现。
- 保留主干车辆质量、接地参数、宽度、涉水/坡度等配置。现有 Iveco 配置宽度 2.056 m 仅为该配置实例，不成为算法硬编码常数。
- Bekker/CI 先复现文献适用土类、单位与含水范围，修正标量/向量化一致性；体积含水率和质量含水率按干密度明确换算。`theta=0.44` 是历史缺值放行的回归样例，不是全土类统一阻断阈值。参数不适用时走已声明的土类/CI 评价规则，不能将缺值直接当作沉陷为零或无限通过能力。
- 复用固定上游水文域计算的 D 场，裁剪工区时不重新按小 ROI 归一化。静态含水率经天气修正后冻结；若使用地表阻抗倍率而非物理含水率更新，字段明确区分，不把倍率冒充体积含水率。M1 将实际公式与参数写入工区配置，避免在两个环节重复施加同一降雨影响。
- 取消仅因节点标量坡度超过某角度而删除所有方向的做法。沿候选曲线切向/侧向分解 DEM 梯度，获得纵坡/横坡近似，分别使用车辆限制。源 DEM 无法支持的微地形不通过增加采样点伪造出来。

### 5.3 通行宽度与困难程度分开

车辆宽度作用于有物理含义的障碍/可用空间。连续几何方法可用于真实障碍边界；**不将可通行 H3 格元并集的锯齿边界统一负缓冲，作为唯一车宽删边依据**。片段分界线和 H3 公共边不作物理障碍。

局部曲线每个微段沿法向量测左右可用空间，量测范围跨越纯组织边界，但在真实障碍或不允许的地表处截止。记录 `left_clearance_m`、`right_clearance_m` 与有效总宽度。总宽足够但当前引导线偏心时，优先在局部子图中寻找可用位置，不能直接用中心点净空否定整个通道。明确宽度不足、水深超限、纵横坡超限和承载不满足等车辆限制仍可阻断；其余狭窄/困难程度进入软代价。

## 6. M2/M3：冻结的图、微段与路线数据接口

以下是接口契约，采用简单 dataclass/字典实现即可。对象引用的几何统一为同一米制投影；稳定 ID 在相同建图输入下可复现。

| 对象 | 必需字段 | 约定 |
|---|---|---|
| `InCellPatch` | `patch_id, fine_h3, coarse_parent_h3, geometry_xy, surface_type, source_feature_ids` | 不连通几何拆成不同片段；同介质内的湿度/坡度仍可沿程变化 |
| `AnchorState` | `state_id, physical_anchor_id, patch_id, xy` | 状态身份等价于 `(physical_anchor_id, patch_id)`；同坐标不同片段侧是不同状态 |
| `CurveMicroSegment` | `ds_m, left_clearance_m, right_clearance_m, width_m, pitch_deg, roll_deg, sinkage_m, roughness, dq_cost` | 存冻结的方向属性与代价；方向相关时正反边分别评价；无法量测的属性显式空值，由 M1 的既定规则处理 |
| `LocalCurveEdge` | `local_edge_id, src_state_id, dst_state_id, is_transition, polyline_xy, segments, length_m, quality_cost, min_width_m` | 内部边另带 `patch_id`；两端 H3/父格从状态所属片段获得；不同曲线拥有不同边 ID |
| `LocalPassageGraph` | `patches, states, edges_by_id, outgoing, incoming, scene_id, model_id` | 邻接表存边 ID，不以 `(u,v)` 唯一键覆盖平行边；同一图固定车辆/场景/质量参数 |
| `LocalRoute` | `route_id, local_edge_path, h3_path, polyline_xy, metrics, scene_id, model_id` | `local_edge_path` 是评价与身份依据；`h3_path` 仅为空间索引及兼容表示 |
| `QualityMetrics` | `length_m, quality_cost, narrow_length_m, high_roll_length_m, soft_length_m, lcds_m, min_width_m` | 保留 Q 分量和实际暴露量，避免只展示一个加权分数 |

物理片段的 `fine_h3` 与粗分组 `coarse_parent_h3` 必须分别命名。跨父格转换边依据两端状态连接，不能把一个“所属细格”塞入主干 `parent_h3` 后作为粗父格分组。

### 6.1 固定的函数边界

```python
prepare_static_scene(inputs, weather_snapshot, build_config) -> StaticScene
build_local_passage_graph(scene, vehicle, map_config, quality_config) -> LocalPassageGraph
evaluate_curve(polyline_xy, scene, vehicle, quality_config) -> tuple[CurveMicroSegment, ...]
attach_query(graph, origin_xy, destination_xy) -> QueryGraph
solve_budget_quality(query_graph, length_budget_m) -> LocalRoute | NoRoute
evaluate_local_route(graph, local_edge_path) -> QualityMetrics
build_parent_frontiers(graph, mode) -> ParentFrontierIndex
refill_parent_intervals(index, graph, parent_id, source_state, target_state,
                        local_budget_m, active_interval_ids) -> tuple[LocalRoute, ...]
```

`QueryGraph` 为固定底图加起终点连接的轻量叠加，不在查询时重建天气/土壤场。`NoRoute` 说明工区、候选模式和预算范围，不扩展成真实世界全区域不可通行结论。

### 6.2 自动生成局部图

1. 在米制 CRS 下，将源地物/障碍/道路边界与 H3 相交得到连通片段。真实障碍优先保留，道路和自然土保持各自属性；内部湿度变化通过属性采样和局部细分表达。
2. 从相邻片段的实际公共开口建立物理锚点。采用确定性的沿边采样，宽开口保留多个锚点，步长写入配置；B4a 专门只取中点作对照。只有点接触且不具备车辆通过空间的几何不凭拓扑相接建立通道。
3. 细化区域使用边界约束的局部三角细分图，纳入入口锚点、源边界和必要内部采样点；图边必须位于允许通行域。非凸片段不得直接用穿出区域的入口直连代替内部路径。开阔区域保留简化连接，边界接口与细化区域一致。
4. `subgraph_pareto`：在上述固定局部子图上生成非支配 `(L,Q)` 入口间路径，作为参考。所谓完整只相对于该离散子图，不声称恢复连续空间全部最优曲线。
5. `heuristic_triad`：在同一局部图上生成最短可行线、偏好最大瓶颈净空的候选、局部长度上限内累计 Q 最小的候选；去重/支配筛选后最多三条。净空候选可由图上 widest-path 取得，不把近似图脊线声称为精确连续中轴。
6. 低阻候选最小化 `sum(dq_cost)`，不最小化 `Q/L`。局部长度上限作为快速模式参数，不施加给完整局部前沿；测量快速模式相对参考丢失的折中路线。
7. 候选几何来自真实输入自动构建。手工给定 `(100,100)` 与 `(104,2)` 的曲线只保留为机制测试。

### 6.3 转换边、曲线积分与等价标签

内部曲线连接同一片段的入口状态；其 L/Q 均来自冻结微段。跨片段转换连接同一物理锚点两侧的状态：`L=0, Q=kappa(surface_from, surface_to)`。同介质切换代价为零；跨介质 kappa 使用非负参数，单位与累计 Q 一致，只在实际切换时计一次。

转换边使用 `segments=()`、`min_width_m=None`，不调用空数组 `min()`，不把空值替换成无限物理净宽。公共开口是否可通过在建边时确定。转换边走 LocalPassageGraph，不塞进要求正长度的旧 `H3Edge`，也不通过添加 epsilon 伪造距离。

同状态下按 `(L,Q)` 支配；相同 `(L,Q)` 保留确定性代表，可避免零代价环无限扩展。不要添加“上一条为转换边就禁止下一条转换”的历史规则，合法的多片段交汇转换仍保留。首版单一最优 Q 不要求枚举所有等价几何路径；备选路线的身份与展示另行处理。

曲线建边时一次性冻结微段和前缀和。拼接只求和；在原顶点切分直接切片。如果查询连接必须在某个微段内部拆分，则沿用该微段冻结密度按弧长分配代价，不对两边独立重新采样。正反曲线若代价不同，各自建立固定微段序列。

## 7. 路线目标、整体评价与旧接口贯通

内部边的质量代价固定为：

\[
Q_e=\sum_m \Delta s_m\,[w_w c_{narrow}(W_m)+w_r c_{roll}(\theta_m)+w_s c_{soft}(z_m)+w_g c_{rough}(r_m)].
\]

各惩罚密度和权重非负，阈值/归一化尺度来自车辆和工区配置；同一组对照固定使用。窄宽度只影响其所在微段，不能拿全边最小宽度乘整条边长。`min_width_m` 用于瓶颈统计及有证据的通行判定，与累计狭窄代价分开。

查询先在同一车辆、场景和完整当前参考图上计算 `L_min`，再求：

\[
\min Q(P),\quad L(P)\le B=(1+\delta)L_{min},\qquad \delta_{default}=0.15.
\]

原型默认 δ=15%，从既有 `decision.detour_ratio` 读取，不写死；敏感性实验另用 5%/25%。实验 B 统一使用共同细图 `L_min_ref` 设预算，不能各方法用各自更长的最短路换取更宽松预算。工程快速图若本来丢掉了更短曲线，明确其参考图身份；不能用候选池最短长度替代完整参考图最短路。分层搜索的长度下界也不能只来自删边后的四代表元缓存。

沿程评价固定记录：长度/绕行比、Q 及分量、狭窄/高横坡/软土暴露米数、最长连续困难段 LCDS、瓶颈宽度和可用走廊。困难段按固定微段阈值定义，跨局部边/片段/父格继续累计；零长度转换不重置连续段。LCDS 是独立评价指标，首版不升为第三搜索维度，也不承诺随 Q 同步下降。总体推荐可按已固定的 Q 策略选择，展示各分量取舍。

主干接入具体任务：

- `FactorModelConfig` 与路线指标接入 `quality_cost`；`portsmap.py` 的 `OBJECTIVE_NAMES`、`ScalarProfile` 默认尺度、校验、缓存权重及边代价读取一并扩展。旧四目标配置可由解析器补齐新目标默认尺度，旧目标结果不因新增字段被改义；新模式不得用未计算的 Q=0 冒充质量评价。
- 新搜索首版使用易核对的标签算法，前驱为 `(prev_label_id, local_edge_id)`；反向 Dijkstra 在完整允许图上分别求长度与质量下界。可达但尚无可行完整路线时，质量上界为无穷，不能提前做错误的质量截断。
- `GeneratedPath`/新 `LocalRoute` 通过明确适配进入候选聚合；评价、去重、聚类与导出均保留局部边序列。旧 H3 路线继续走原评价函数，新局部路线走 `evaluate_local_route`，不能混用。
- 新增明确的有人驾驶静态模式配置，例如 `planning_mode: manned_static`。聚合、持久化、CLI/Web/桌面接受该模式的引导线与通行结果，不以自主轨迹 `trajectory.status == valid` 作为交付前置条件。旧模式继续保留，不伪造其轨迹有效状态。
- 默认展示最短参考与预算内质量推荐，有用备选按真实结果保留，不强制凑满五条。已有 fastest/cost 等角色保持其目标含义；`recommended` 是选择策略，不冒充独立优化目标；没有经扰动检验的路线不标为独立备份。

## 8. M4/M5：父格前沿、存储与多区间补查

### 8.1 先建立完整参考

父格入口是跨粗父格连接涉及的侧状态，保留方向和局部边身份。C0 的父格内 shortcut 只由该父格诱导子图路径生成，跨父格转换单独连接；起终点所在父格的连接同样保留。允许路线经不同入口重访父格，不能以“父格已访问”直接裁剪所有折中路径。

C0 保存每个有向入口对的完整非支配局部前沿，展开后能恢复原始 `local_edge_path`。在同图、完整跨区入口、完整局部前沿和起终点连接条件下，C0/C00 比较预算可行性和最优 Q，应一致；存在等价解时不要求几何路径相同。若另行裁剪入口，该版本单列为近似入口实验。

现有 `OfflinePairs` 按父格/入口对/profile 保存单路径，不足以承载新前沿。新增版本化路径表至少包含：`scene_id, model_id, coarse_parent_h3, source_state, target_state, path_id, length_m, quality_cost, local_edge_path`。旧表保持兼容读取，新版不能把多路径压回旧单路径键。跨父格连接另列；表中所有引用能展开到同版本底图。

### 8.2 固定规模缓存与补查接口

C2/C4 的启动缓存最多四个代表元，至少保留最短与最低 Q 极端点，其余按确定性长度分布选取。区间描述覆盖被丢弃前沿的全部长度区间，包括必要的两端尾区间；不能只检查预算落入的最后一个区间。

区间记录：`interval_id, length_lo, length_hi, may_have_dropped, dropped_length_lb, dropped_quality_lb`。在完整前沿参考阶段可精确求得；工程按需构建阶段只能使用有效下界与可靠“无遗漏”结论，尚未枚举不等于无遗漏。没有更强界时可用保守零质量下界，不能把代表元质量当作所有遗漏路径的下界。

对入口 u 的当前标签 `(L_acc,Q_acc)`、候选出口 v：

\[
B_{local}=B-L_{acc}-h_L(v).
\]

扫描全部可能遗漏区间：

1. 若 `dropped_length_lb > B_local`，该标签下无需补查。
2. 若 `Q_acc + dropped_quality_lb + h_Q(v)` 不可能改善现有可行解，可跳过；相等时只需最优 Q 而非全部等价路线。
3. 若同一出口侧状态 v 已有标签支配乐观组合 `(L_acc+dropped_length_lb, Q_acc+dropped_quality_lb)`，可跳过。
4. 其余区间在父格原始局部图内做受预算约束的搜索，恢复所有仍可能需要的非支配候选，不能只恢复一个局部最低 Q 点。恢复路径带完整边 ID，随后参与全局标签扩展。

上述跳过只针对当前标签/预算，不把区间永久标记为空。查询获得的更大预算可触发进一步补查；已有可行候选可以缓存。反向 hL/hQ 是完整允许图的下界，不来自已经丢路径的压缩图。

研究比较中区分两种成本：完整前沿已知后压缩的实验上限；从底层图按需恢复的实际工程开销。若磁盘仍保存完整前沿，其存储必须计入总索引体积。原有 800 例使用已知前沿恢复描述符，不能据此宣称真实地图补查成本已测得。

## 9. 真实工区实验安排

### 9.1 最小首轮实验

M0 从实际覆盖充分的 QDX 区域确定工区，不预设数据一定包含全部困难地形。选若干不同 OD，覆盖可辨认窄道、道路/自然土邻接、湿软区域或方向坡度差异；缺一种场景可另选子区域。工区、OD、车辆、真实天气、Q 参数和预算在比较前固定。

先完成 B0、B4a/b/c/d、C00/C0；输出可通行片段/开口、局部曲线、两条主要路线和沿程剖面。真实地图是否保住走廊由源几何/影像人工核对样本评价，不以被测方法自己的连通图当真值；实际车辆通过结论另以现场记录支持。

### 9.2 完整消融与对照

| 分组 | 固定条件 | 对照序列 | 主要结果 |
|---|---|---|---|
| A 物理属性 | 相同几何候选超图和求解器，允许通行掩码随物理规则变化 | A0 基线因子；A1a 恢复株距/水深；A1b 土壤/CI修复；A1c 静态真实天气修正；A2 有向纵横坡 | 哪些通行边恢复/阻断、湿软暴露、方向坡度路线变化 |
| B 地图表示 | A2 物理层、共同微段评分、共同预算 `L_min_ref` | B0 基线 H3 表示；B1 显式中心净空；B2 Wu 同质六边形；B3 Zhou 凸导航网格；B4a 单中点单最短；B4b 多锚点单最短；B4c 快速多通道；B4d 完整局部前沿 | 走廊召回/错误连接、同格介质分离、路线分量、图规模、建图耗时 |
| C 分层候选 | 相同 B4c 或 B4d 底图、相同求解器；两种底图分别成组 | C00 无父格抽象；C0 完整前沿；C1 单标量；C2 四代表元；C3 Regret k=4；C4 四代表元+全区间补查 | 预算可行性、最优 Q 保留、绝对/相对 Q 差、索引总大小、补查时间/次数 |
| D 求解器 | 相同 C0 图、代价、预算和机器 | D1 局部贪心解释性对照；D2 标签法；D3 BiPulse；D4 WC-A* | D2–D4 最优值一致性、查询时间、扩展量和内存；不预设某算法胜出 |

B0 指“986bd58 地图表示 + 共同 A2 物理层”，不是未经修改的原始系统；原始 986bd58 端到端结果另列 `baseline_original`。不同表示若生成违反共同物理规则的路线，作为无效路线记录，不能只比较其低分数。B2/B3 有适配时记录适配项，不把启发式近似称为完整复现。

C3 的 Regret 与严格预算质量差分别报告；已有 Regret 理论允许一定约束放宽的情形不能算作本项目严格预算成功。相对 Q 差仅在参考 Q>0 时计算；参考 Q=0 时报告绝对差，不除以零。

工程首轮不要求先完成所有论文基线和全部求解器。首轮地图收益成立后再补齐 B2/B3、C、D；若收益主要来自属性修复而非表示改进，就据结果调整论文贡献强度，不追加无关理论包装。

### 9.3 已有实验的继承方式

| 已有材料 | 实际支持的结论 | 接入阶段 |
|---|---|---|
| 1239 审核：平行曲线、介质切换、微段积分、多锚点例 | 旧设计失效原因及修正机制；多锚点从 12.806 降到 10.198，并非恢复到 10 | M2/M3 回归测试 |
| 2300 审核：9 个构造例 + 800 个预算算例 | 已知完整前沿、分层非负图上的补查结果与穷举一致 | M5 回归，并增加真实父格补查测试 |
| 1345 审核：组合图 + 150 图/450 预算例 | 平行边、介质侧状态和零代价环的标签搜索与穷举一致 | M3 回归 |
| 1345 审核：Q/L 与累计 Q、LCDS 反例 | 避免目标替换；较低 Q 不保证较短 LCDS | 评分和评价脚本 |

已有探针不是 QDX 自动提取曲线、实车通过或生产性能结果。实施时将必要回归用例迁入 `tests/`，不要依赖被忽略的历史 `.artifacts` 目录运行正式功能。

## 10. 文献依据与 SCI 定位

以下文献于 2026-10-15 联网核对。Wu 以出版摘要为依据；Zhou 以出版元数据/可检索正文为依据；HAA* 使用作者 PDF；其余采用出版页、开放正文或作者/机构版本。摘要级证据不写成已逐页复现方法。

| 文献 | 已有研究覆盖 | 本方案采用方式/贡献边界 |
|---|---|---|
| Wu et al. (2024), *A hierarchical model with hexagon grids for multi-objective route planning in large-scale off-road environments*, IJGIS 38(7):1388–1413。[出版页](https://www.tandfonline.com/doi/abs/10.1080/13658816.2024.2347319) | 六边形同类合并、分层多目标越野选线 | B2 对照；H3/分层/Pareto 本身不单列创新 |
| Zhou et al. (2025 online/2026), *An unstructured roadless environment navigation map construction method based on remote sensing*, Geo-Spatial Information Science 29(3):1897–1918。[出版页](https://doi.org/10.1080/10095020.2025.2570025) | 遥感到通行域与不规则导航网格，展望含水率/土类/承载力 | B3 对照；比较选择性细化的走廊和规模收益 |
| Harabor & Botea (2008), *Hierarchical Path Planning for Multi-Size Agents in Heterogeneous Environments*, IEEE CIG。[作者 PDF](https://www.harabor.net/data/papers/harabor-botea-cig08.pdf) | HAA*，地形能力、净空、多尺寸与分层 | 收紧相关工作定位，不另加大规模复现任务 |
| Botea, Müller & Schaeffer (2004), *Near Optimal Hierarchical Path-Finding*。[机构 PDF](https://webdocs.cs.ualberta.ca/~mmueller/ps/2004/hpastar.pdf) | 分层入口与局部路径抽象 | 多入口和 C00/C0 的已有方法基础 |
| Truschel & Storandt (2025), *Multi-Criteria Route Planning with Little Regret*, ATMOS。[全文](https://drops.dagstuhl.de/storage/01oasics/oasics-vol137-atmos2025/html/OASIcs.ATMOS.2025.13/OASIcs.ATMOS.2025.13.html) | 固定规模 Pareto 代表集及分层应用；约束查询可能需要预算放宽 | C3 对照；C4 评价严格预算恢复收益，不冒称代表集首创 |
| Ahmadi et al. (2024), *Enhanced methods for the weight constrained shortest path problem*, Networks 84(1):3–30。[机构页](https://research.monash.edu/en/publications/enhanced-methods-for-the-weight-constrained-shortest-path-problem/) | WCSPP 的 A* 系列方法 | D4 强基线，求解器调用不是地图创新 |
| Cabrera et al. (2020), *An exact bidirectional pulse algorithm for the constrained shortest path*, Networks 76(2):128–146。[出版页](https://onlinelibrary.wiley.com/doi/10.1002/net.21960) | 双向 Pulse 约束搜索 | D3 对照，不预设效率优势 |
| Seegmiller, Shirabe & Tomlin (2021), *A method for finding least-cost corridors with reduced distortion in raster space*, IJGIS 35(8):1570–1591。[出版页](https://www.tandfonline.com/doi/abs/10.1080/13658816.2020.1850734) | 栅格宽走廊与方向离散畸变 | 说明走廊表示已有基础；固定微段可加性由本方案定义验证，不归功于未核实的论文命题 |
| Schönauer et al. (2024), *Soil moisture modeling with ERA5-Land retrievals, topographic indices, and in situ measurements and its use for predicting ruts*, HESS 28:2617–2633。[全文](https://hess.copernicus.org/articles/28/2617/2024/) | 气象再分析、地形、含水率与车辙预测 | 支持静态天气—湿度通行评价动机；不直接证明项目 D 场公式 |
| Shahgholi et al. (2024), *Evaluation of the changes in Bekker's parameters and their use in determining the rolling resistance*, International Agrophysics 38(3):257–266。[出版页](https://www.international-agrophysics.org/Evaluation-of-the-changes-in-Bekker-s-parameters-and-their-use-in-determining-nthe,187017,0,2.html) | 壤土/黏壤土、含水条件和加载速度影响 Bekker 参数与阻力 | M1 参数复现来源；不能外推为所有土类和含水范围的通用标定 |

**SCI 判断**：当前具备可实施、值得研究的方向，尚未形成足以认定达到发表要求的真实地图结果。投稿贡献应由同输入对照证明“边界驱动局部细化如何保住有用走廊和折中路线，以及代价是多少”。多重图、状态扩展、冻结积分、现成约束搜索都是支撑手段。更好的图规模—路线质量折中及机制解释可构成方法论文的核心证据；若主要收益只有既有属性旁路修复，应按工程改进报告，不夸大方法创新。

## 11. 实施交接与方案变更

本方案作为当前唯一实施入口。后续每阶段交接简要记录：代码提交、已完成接口、运行命令、结果位置、未完成项和下一阶段入口。实现启动时再建立 `STATE.md`/`DECISIONS.md` 和根目录 `AGENTS.md` 读取约定；本次不代建工作树、不改业务代码、不自动提交 Git。

参数、局部算法实现细节可根据实际工区调整，但修改需说明影响的接口和对照。若发现可实验验证的问题，直接补小图/真实子区实验，并把结果写入阶段状态；不重新扩展研究主题。主线、三个核心图契约和阶段顺序保持稳定。

### 已合并的审核修正清单

- [x] 独立局部多重图、边 ID 回溯、全链路身份与 Q 注册。
- [x] 介质侧状态和静态转换代价；零长度与空微段的专用处理。
- [x] 相同标签合并，不普遍禁止连续转换。
- [x] 固定微段积分和切分/拼接规则。
- [x] `fine_h3`/`coarse_parent_h3` 分开，跨父格边按两端连接。
- [x] 低阻曲线最小化累计 Q，不最小化 Q/L。
- [x] LCDS 独立评价，收窄所有分量同步改善的承诺。
- [x] B0 名称、完整 C0/C00 对照与共同预算明确。
- [x] 快速三曲线和完整局部前沿区分；先真实建图收益，后补查效率。
- [x] 保留主干正射影像、地物属性、土壤/天气、显示和导出链；v2 选择性移植。
