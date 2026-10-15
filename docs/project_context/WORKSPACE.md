# 本地工作树使用说明

工作目录：`D:/Workspace/demo_v4-manned-offroad`；开发分支：`codex/manned-offroad-map`。

使用 PowerShell 的默认 `python`，所有命令从本目录启动：

```powershell
Set-Location D:/Workspace/demo_v4-manned-offroad
python scripts/run_local.py verify
python scripts/run_local.py desktop
```

CLI 基线运行：

```powershell
python scripts/run_local.py cli plan --request configs/manned_offroad.baseline.private.yaml
```

启动脚本只在当前进程及其子进程选择本工作树源码；不修改默认 Python 的其他项目安装。桌面入口选择本地 QDX 配置，不打开旧示例配置。

日常桌面和 `manned_offroad.local.private.yaml` 写入 `outputs/manned_offroad_route`。基线复现配置写入 `outputs/baseline_986bd58/replay_route`，首次基线结果保存在 `fresh_route`。两种配置目前均回放已保存的真实天气快照，更新场景时再显式更换。

私有配置和大型数据不进入 Git。`manned_offroad.local.private.yaml` 是实际可运行配置；`manned_assets.private.yaml` 记录原始资源。数据位于原有 `D:/Workspace/qdx数据`、`D:/Workspace/demo_v1/data` 和 `D:/Workspace/demo_v4/data` 等位置，移动这些来源前需更新资源引用。

新任务在本工作树中开始，先读 AGENTS、STATE 与 IMPLEMENTATION_PLAN。已有 Codex 任务若仍显示旧目录，应在应用中打开本目录后启动后续实施任务，不靠聊天文字假定工作目录已经改变。

数据验证报告位于 `.artifacts/workspace-preparation/data_check.json`。验证检查文件读取、属性保留和缓存地址，不代表新图算法或实车通行验证。具体阶段状态见 [STATE](STATE.md)。
