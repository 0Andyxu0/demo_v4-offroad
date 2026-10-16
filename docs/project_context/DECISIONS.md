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


