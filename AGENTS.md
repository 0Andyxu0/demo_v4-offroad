# 本工作树的实施约定

- 工作目录：`D:/Workspace/demo_v4-manned-offroad`。开发分支：`codex/manned-offroad-map`；历史基线：`986bd58`。开始时检查实际 cwd、分支和源码导入位置。
- 先读 `docs/project_context/STATE.md`、`IMPLEMENTATION_PLAN.md` 和 `DECISIONS.md`，再按任务读取相关源码。历史架构概览在 `docs/history/PROJECT_HOLOGRAM_986bd58.md`（`986bd58` 冻结快照），不是实时实现状态；`docs/history/` 下的一切均不作为当前依据。
- 需求是 DEM、地物 TIF/SHP、遥感影像、土壤类型与静态含水率，加制图期真实气象修正，服务有人驾驶越野。允许格网小折线；重点是通行地图、走廊保留和整体路线质量。
- 按固定方案 M0–M5 顺序推进。沙盒 v2 仅选择性参考。误差分析与数据检查为配套，不另立防御性研究方向。可实验验证的问题直接验证。
- 使用本机默认 `python`，不建虚拟环境、不修改全局 editable 安装。执行入口为 `python scripts/run_local.py`；它优先导入本工作树 `src`，并将同一路径传给子进程。
- 原始 GIS 数据只读引用，新增产物写本工作树 `outputs/` 或 `.artifacts/`。`outputs/baseline_986bd58/qdx_tiles` 是迁移的基线缓存，不用新建图覆盖它。
- 私有配置位于 `configs/*.private.yaml`，不提交凭据或令牌，不把在线底图配置内容写入日志。正式方案、交接记录、脚本和测试进入 Git。
- 阶段结束更新 STATE：已完成、接口变化、运行命令、产物位置、未完成项与下一步。重要取舍记入 DECISIONS；不要求新任务重读所有历史对话。
- 只有实际实施和验证后才标记完成。数据可读不等于已进入物理模型；生成路线不等于实车通过；累计 Q 改善不等于所有困难分量同时下降。
