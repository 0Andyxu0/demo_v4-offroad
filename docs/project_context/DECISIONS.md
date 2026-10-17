# 实施决定

## 2026-10-15：工作区、环境与基线

1. 从 `986bd58` 创建 `codex/manned-offroad-map`，工作树位于 `D:/Workspace/demo_v4-manned-offroad`。名为 main 的旧分支不是这次起点。
2. 使用本地默认 Python，不创建虚拟环境，不执行全局 `pip install -e`。由仓库启动脚本固定源码优先级，避免多个同名项目互相导入。
3. 大型原始 GIS 文件共用、只读；基线瓦片缓存独立复制，以免后续索引或缓存写入改变原项目。
4. 复制后只迁移基线清单中的缓存地址，原清单和历史路线单独保存。新物理属性和新图结构不混入历史缓存。
5. ARGON 1345 与审核修正已经合并为 IMPLEMENTATION_PLAN v1.0。局部边身份、介质侧状态、零长度转换和固定微段积分按该文执行。
6. 正射文件可读、含水率文件可读分别登记；目前不将其误记为 GUI 正射图层和新土壤模型已经实现。
7. 每阶段以仓库交接文件和提交共享当前结论；历史对话只用于按需追溯。
8. 首次基线实际请求天气后冻结快照，后续对照回放同一快照。日常输出、首次基线输出和复现输出分开。

## 2026-10-15：M0 场景契约、本地正射与基线规范化

9. 严格按 `IMPLEMENTATION_PLAN.md` §5.1 与 §6.1 落地 `StaticScene` 和 `prepare_static_scene` 契约，统一工区 DEM、地物、道路、正射影像、土壤、含水率、水文域和冻结气象快照的静态输入规范与元数据结构。
10. 严格限制 M0 边界：不提前实施 M1 物理模型（株距、水深、土壤 Bekker/CI 修正、有向纵横坡）或 M2–M5 局部图/求解器，不重新设计研究方向。
11. 本地正射影像（T.tif）通过局部裁剪下采样生成 WGS84 范围 PNG 预览，桌面端以轻量 data URL 叠加图层形式显示，仅供人工边界核对与底图展示，不进入路径规划的物理模型。
12. 固定工区（QDX DEM/bound 重叠区）、固定 OD、Iveco Daily 4x4 车辆配置与 2026-10-15T08:00Z 真实天气冻结快照作为 M0 可复现基准；路线结果以 baseline_original 形式保存，旧自主轨迹无效状态保持原始客观记录。
13. `prepare_static_scene` 契约强化与 §5.1 属性补齐：严格校验米制投影 CRS（拒绝地理经纬度坐标）、研究区几何非空与有限性、DEM/土壤/正射栅格空间范围与工区的重叠判定；补齐道路类型（FuncClass）、正射影像时标、土壤适用范围与含水率观测时间；资产解析支持从已有场景字典/JSON 反向重新准备，并自动兜底私有资产配置。

## 2026-10-15：版本控制规范、.gitignore 防护与远程仓库连接

14. 建立正式远程版本库与忽略规范：
    - 远程仓库连接：将有人驾驶 H3 独立开发分支 `codex/manned-offroad-map` 关联至远程 `origin`（`https://github.com/0Andyxu0/demo_v4-offroad.git`），建立上游跟踪并设为主分支，与历史 `main` 分离。
    - .gitignore 完备防护：
      - 与审计工具 `scripts/audit_gitignore.py` 全量契合，严格过滤所有敏感后缀（`.der`、`.key`、`.pem`、`.p12`、`.pfx`、`.cer`、`.crt`、`.jks`、`.keystore`、`.token`）与特定文件（`id_*`、`.netrc`、`credentials.*`、`secrets.*`、`secret.*`、`*.env`、`*.private.*`、`*.local.*`）；
      - 全面阻断大体量 GIS 栅格/矢量/数据表/数据库及其各类伴生与运行锁文件（`*.shp.xml`、`*.lock`、`*.lck`、`*.sr.lock`、`*.wld`、`*.jgw`、`*.pgw`、`*.nc4`、`*.hdf`、`*.gdb/`、`*.kml`、`*.kmz`）；
      - 增加 `tests/test_gitignore.py` 纳入 CI 与全库自动化测试，确保新代码与配置不破坏忽略防线。

## 2026-10-16：M1 静态通行属性修复与物理消融 (A0 -> A1a -> A1b -> A1c -> A2)

15. 消除 `strict_static_mode = environment is not None` 导致的地物属性旁路漏洞：将 `strict_static_mode = False` 固化，确保在提供气象快照或静态规划时，森林 `rowspacing` 与水体 `depth` 均严格作为硬约束与阻力项参与计算，消除历史代码对行距与水深的跳过行为。
16. 修复土壤 Bekker/CI 模型在饱和高湿下的刚度崩塌与空值放行漏洞：针对黏壤土等在 $\theta=0.44$（高湿）时 $k_c \le 0$ 引发 `AssessmentError` 的物理失效，明确将沉陷记为无穷大（`inf`）、沉陷阻力记为无穷大（`inf`）、土壤机动性设为 0.0，并在硬约束中以 `SINKAGE_CLEARANCE_EXCEEDED` 明确阻断，彻底消除因 `NaN -> None` 回退导致的无条件放行漏洞。
17. 建立静态真实降雨冻结快照与水文域地表阻抗机制：保留原晴干基线日快照（$P=0.3\text{mm}$, `derived_pressure=0.0`），增补真实暴雨日冻结快照 `rainy_weather.json`（$P=28.5\text{mm}$, $ET_0=1.85\text{mm}$, `derived_pressure=0.8`），结合固定上游水文域 D 场，在低洼汇水冲沟区施加地表阻抗倍率（$1.864\times$），主动规避湿软走廊，并明确区分物理含水率更新与地表阻抗倍率。
18. 实现有向纵横坡解耦机制：移除仅因节点 DEM 标量坡度超限即在构图时硬删除整个节点的粗暴逻辑，改为在有向边与切向曲线上分别计算纵向坡度 $\alpha$ 与侧向横坡 $\beta = \sqrt{\max(0, \theta_{terrain}^2 - \alpha^2)}$；在 Iveco 爬坡角 $30.96^\circ$ 与横倾角 $25.0^\circ$ 约束下，成功保留 $31^\circ \sim 34^\circ$ 陡坡上的对角线与等高线平缓通行边，同时阻断直攀落线与高横坡倾覆边，标量与向量化引擎严格对齐。
19. 固化 5 组多场景基准测试 OD（`configs/scenes/m1_benchmark_ods.json`），覆盖混合地貌、密林行距、涉水冲沟、路土交界与 $30^\circ$ 陡坡斜切，确保 M1 至 M5 全周期在相同工区与相同起终点上具备确定性评估依据。
20. 道路图层属性映射显式对齐 Width 与 FuncClass 并消除陡坡裕度反转：按 argon1657 审核要求，在 `m0_qdx_scene.json` 与 `scene.py` 默认 `field_mapping` 中显式绑定 `road_fina.shp` 的 `width -> Width` 与 `functional_class -> FuncClass`，作为第 4 项关键地物属性纳入场景准备审计；修正节点坡度裕度在 $30.96^\circ$ 爬坡限制临界区的不连续下跳，确保节点安全性指标单调平滑。

## 2026-10-16：M1 综合审核与整改落地 (argon1909 R1–R6)

21. 道路 Width 字段米制有效宽度换算 (R1)：核实 `road_fina.shp` 中 `FuncClass = "5"` 的 `Width` 原始值为分米（0.1m）编码（值域 30.0~55.0 分米），在 `m0_qdx_scene.json` 与 `scene.py` 中显式增加 `width_unit_or_scale: "0.1m"` 与 `effective_width_m_range: [3.0, 5.5]`，提供统一辅助函数 `resolve_road_effective_width_m` 进行米制换算（"30" -> 3.0m，"55" -> 5.5m），杜绝将原始分米值直接当米使用而生成 30~55 米巨型虚假走廊；场景准备解析时安全隔离非字段元数据键，杜绝列表类型导致的索引哈希错误。
22. 土壤 Bekker/CI 物理参数修正与干密度含水率换算 (R2)：依据 Shahgholi et al. (2024) 农艺土壤实测数据修正黏壤土与壤土的 $k_c, k_\phi, n$ 回归模型，按干密度 $\rho_d = 1.4\text{ g/cm}^3$ 严格换算体积含水率与质量含水率（$w_{\%} = (\theta_v \cdot \rho_{\text{water}} / \rho_d) \times 100\%$），保证实测含水率下 $k_c > 0$；超出文献适用土类或参数失效时规范回退至声明的土类与圆锥指数（CI）评价规则，不再将缺值直接赋为无穷大沉陷或零沉陷，极端饱和高湿（$\theta_v \ge 0.65$）时由圆锥指数不足（`CONE_INDEX_INSUFFICIENT`）严格阻断，标量与向量化计算保持完全一致。
23. 接入 CLDAS 静态含水率与水文 D 场，规范气象快照 (R3)：打通工区格元与 CLDAS 静态含水率栅格（基底 $0.3080\text{ m}^3/\text{m}^3$）及上游水文域 D 场（`drainage_sensitivity.tif`）的真实栅格采样；将手工构造的降雨场景明确命名为 `synthetic_rainy_weather.json` 并标注为合成对照场景（`synthetic_rainy_weather_sensitivity_contrast`，`derived_pressure = 0.8`），与真实观测快照严格隔离。
24. 零近似误差正切纵横坡解耦 (R4)：废除角度直接平方相减的近似公式，统一采用 $\tan\theta_{\text{roll}} = \sqrt{\max(0, \tan^2\theta_{\text{terrain}} - \tan^2\theta_{\text{pitch}})}, \theta_{\text{roll}} = \arctan(\tan\theta_{\text{roll}})$，标量与 NumPy 向量化逐元素误差 $< 10^{-12}$，在 Iveco 爬坡 $31.0^\circ$ 与横倾 $25.0^\circ$ 双约束下精确保留安全对角通行边。
25. 真实 QDX 瓦片图与 5 组基准 OD 端到端消融验证 (R5)：彻底废除仅测试 7 个内存单元格的旧脚本，重写 `scripts/run_m1_ablation.py`，在真实 QDX 瓦片图（380,044 个去重走廊格元、1,738,210 条可通行有向边；5 个 OD 走廊合计 426,006 格元 / 2,017,998 边）和 5 组基准 OD 上运行 A0 至 A2 真实图搜索，准确记录可通行统计、阻断原因码分布及路径物理规避行为，输出至 `outputs/m1_ablation/m1_ablation.json` 与 `m1_ablation_summary.md`。
26. 状态记录与实施事实全面对齐 (R6)：消除 `STATE.md` 与实际代码、配置之间的矛盾，修正 OD 标识（`od_01_primary` ~ `od_05_slope_traverse`）、车辆涉水深配置（$0.225\text{ m}$ 与测试车 $0.308\text{ m}$）及气象衍生压力参数（`0.8`），以真实 QDX 消融统计数据更新消融对比记录。

## 2026-10-17：M1 综合审核整改闭环 (M1 Consolidated Audit)

27. 统一 CI 阈值单一来源与沉陷速度衰减耦合（P0-4）：彻底消除 `CI_THRESHOLD_KPA` 硬编码与 `config.min_cone_index_kpa` 的双源冲突，将阈值单一收敛至 `config.min_cone_index_kpa: 185.73`；在 `_soil_speed_interval` 中建立基准 USCS 土类速度与沉陷退化因子 `sinkage_factor = max(config.speed_floor_ratio, 1.0 - sinkage / clearance_limit)` 的直接耦合，使沉陷真实降低节点速度与 ETA。
28. 真实栅格动态采样适配器 (`enrich_graph_from_static_scene`) 杜绝伪造常量（P0-1, P0-2）：针对基准 Parquet 瓦片中土壤与水文列为空的历史事实，通过 `enrich_graph_from_static_scene` 动态采样 `soil_nanjing.tif` (+VAT)、CLDAS NetCDF (0-5cm) 与 `drainage_sensitivity.tif`；未映射区域保留 `None` 并不以 `CL` 兜底；记录全部输入文件 SHA-256 哈希。采样像元索引按 `floor` 取包含像元（见 #33 修正后 0-5cm 含水率均值 0.3153 m³/m³、范围 [0.3080, 0.3301]、2 个不同取值）。
29. 统一走正式评价链路并实现 FactorModelConfig 显式消融开关（P0-3）：废除消融脚本私有评价器，在 `FactorModelConfig` 中引入 `enforce_rowspacing`、`enforce_water_depth`、`enforce_soil_physics`、`enforce_scalar_slope_blocking` 与 `use_exact_tangent_roll` 显式开关，统一调用 `evaluate_factor_model` 与 `evaluate_path_metrics`，并在 A0~A2 各档形成确定性非零差异。
30. 基准 OD 端点正射/矢量校正与吸附上限控制（P0-5）：依据正射影像与矢量边界修订 `od_03`、`od_04`、`od_05` 选点，升级为 `m1_benchmark_ods_v2`，将 5 组 OD 初始吸附距离全部压制在 1.14 米以内（远低于 `MAX_SNAP_DISTANCE_M = 30.0` 上限），杜绝跨连通分量静默跳点。
31. 统计口径拆分与动态对比生成（P0-6, P1-5）：拆分 5 个 OD 走廊去重并集统计（380,044 独立格元）与各 OD 独立统计两套口径；删除硬编码文字模板，对比叙述由真实实测差值动态生成。
32. 修正建筑水体原因码污染与删除冗余配置（P1-2, P1-6）：严格按 `landcover_code == 5` 判定水体，防止建筑（code 6）误打 `WATER` 标签；清理遗留文件 `configs/scenes/rainy_weather.json`。
## 2026-10-17：第二轮审核整改（M1 Audit Round 2）

33. 栅格采样按包含像元索引，修正半像元偏移（N-1）：原实现对 \`~transform * (x, y)\` 的角点基准浮点坐标使用 \`round()\` 取整，使落在像元后半格的样本整体偏移一个像元；CLDAS 0.0625°（≈6.9 km）网格上偏移达 3.45 km，导致 380,044 个格元中有 55% 读到邻像元值、并集含水率退化为单一常数 0.3301。现统一改为 \`floor()\` 取包含像元（\`scene.py::_pixel_index\`），并补充 CLDAS 的投影坐标系分支；采样元数据新增 \`distinct_pixels\` 与 \`distinct_values\`。修正后并集含水率为 [0.3080, 0.3301] 两个取值（均值 0.3153），证明工区确实跨 CLDAS 像元边界。
34. 单变量档位可观测性判据与如实记录（N-2）：以「目标 OD 上 L/ETA/Cost 相对变化 ≥ 1%」作为单变量档位可观测的判据，结果写入 \`m1_ablation.json\` 的 \`comparison\` 段与摘要 §5。本工区实测：A1a→A1b、A1c→A2 在目标 OD 上均未达 1%（A1a→A1b 仅 4e-4，A1c→A2 为 0），A0→A1a 亦未改变任何基准 OD 的选线；只有 A1b→A1c 在 \`od_01_primary\` 产生 +210.05 m / +19.67 s / +74.38 的实质变化。该结论属**地貌与选点共同决定的可观测性局限**，不代表物理模型空转；后续不得再用"彻底摆脱空转""主动绕行"等措辞描述零变化档位，如需演示单变量选线效果，须按有证据的选点修订基准 OD（v3）而非事后解释。
35. 文档与叙述去伪（N-3）：修正 \`DECISIONS.md\` 第 25 条的陈旧统计（454,475 / 2,133,478 → 380,044 / 1,738,210）；地表阻抗倍率改为由边级 \`environment_distance_m / distance_m\` 实测得出（当前 2.440×），不再硬编码"2.44×/1.864×"；清理 \`factor_model.py\` 中随 CI 阈值单源化而失效的 \`CI_THRESHOLD_KPA\` 导入。

## 2026-10-17：第三批整改（端点判定、路面豁免、基准 OD）

36. OD 端点按 res14 含格元解析，禁止跨格吸附（审核要求 1）：`_resolve_endpoint` 改用 `h3.latlng_to_cell(lat, lng, 14)` 求**含格元**，不再在走廊图上做最近格元搜索；含格元不在走廊内 → `OD_ENDPOINT_OUTSIDE_CORRIDOR`，含格元不可通行 → `OD_ENDPOINT_IMPASSABLE`，均显式失败并记录原因码。`MAX_SNAP_DISTANCE_M` 由 30.0 m 收紧到 **2.0 m**（res14 边长约 1.35 m），仅用于吸收恰好落在格边的坐标，物理上不可能把点分配到邻格。此前 30 m 允许跨约 13 个 res14 格吸附，是把"可达"结论建立在换点之上。
37. 铺装路面豁免 Bekker 沉陷与土壤动力学（审核要求 2）：`_soil_speed_interval` 对 `cell.has_road` 的格元直接返回土壤系数 1.0、`cone_index_kpa=None`、`sinkage_m=None`，不再计算或用 CI/Bekker，也不再产生 `MISSING_SOIL` / `CONE_INDEX_INSUFFICIENT` / `SINKAGE_CLEARANCE_EXCEEDED` 与土壤安全裕度。理由是路面对应已硬化表面，`surface_response=0.0` 已按不透水面处理，二者语义必须一致。影响：`od_04` ETA 从 49.33 s 降到 26.66 s、`od_05` 从 169.02 s 降到 116.84 s，选线随之改变。
38. 基准 OD 只在端点不可通行时重选，不因消融零变化更换（撤回 v3）：本轮曾把 `od_02` 移到密林斑块两侧以制造 A1a 的可观测差异（`m1_benchmark_ods_v3`），项目负责人判定超出范围——零变化是结论而非缺陷。现已恢复 `m1_benchmark_ods_v2` 的全部坐标（5 组端点均落在可通行 res14 格，吸附 0.00–1.14 m）。恢复后仅靠修复铺装路面豁免（#37），`od_02` 的 A0→A1a 即出现 59.6% 的真实选线变化（639.31 m / 85.78 s → 593.04 m / 136.90 s），说明先修物理模型比移动基准点更有效。A1b/A2 的零变化如实记录为可观测性局限，后续靠补足对应地物样本解决，不移动现有基准点。
39. 文档清理（能删则删，高风险移入 history）：删除根目录 4 份历史残留（`PROJECT_HOLOGRAM_gemini.md`、`PROJECT_HOLOGRAM_gpt.md`、`demo_v4解决实际环境问题.md`、`gpt_plan_vs_requirement.md`）；删除 `docs/project_context/modules/`（49 篇）、`SYMBOL_INDEX.md`、`MANIFEST.md`——生成于 `986bd58`，行号与签名已失效且仓库内无生成脚本；`docs/code/h3-offroad-planner/`（58 篇）、`docs/demo_v4路径规划性能优化方案.md`、`PROJECT_HOLOGRAM.md` 移入 `docs/history/` 并加 `README.md` 声明历史属性。`INDEX.md` 的模块链接改为直接指向 `src/h3_offroad_planner/`，首读从 HOLOGRAM 改为 `IMPLEMENTATION_PLAN.md` + `STATE.md`。当前实施依据唯一收敛到方案、STATE、DECISIONS 与源码。