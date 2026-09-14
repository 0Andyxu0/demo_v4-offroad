# 当前闭环测试规格与追踪矩阵

> 状态：当前活动基线，2026-07-27。CL-001～CL-040 均从
> [spec.md](spec.md) 和 [closed-loop-contract.md](closed-loop-contract.md) 派生。
> 下表中的 pytest 节点是唯一审计证据；旧 T-* 编号不构成当前验收合同。

## 1. 物理因子与静态 Tile

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-001 | 无权重物理瓶颈裕度和加和风险 | 人工计算坡度/推力最小裕度及 `distance * -ln(margin)` | `tests/test_closed_loop_factor.py::test_cl001_edge_margin_and_risk_are_hand_calculable` |
| CL-002 | 已知土壤硬约束 | 锥指、沉陷边界及越界原因码 | `tests/test_closed_loop_factor.py::test_cl002_known_soil_margins_and_boundaries_are_enforced` |
| CL-003 | 缺失证据不得伪造 | 缺地类/土壤时保持可通行、降低 confidence、给出原因码 | `tests/test_closed_loop_factor.py::test_cl003_missing_evidence_is_not_fabricated` |
| CL-004 | 水体硬阻断 | 水体节点不可通行且无入/出方向边 | `tests/test_closed_loop_factor.py::test_cl004_hard_water_constraint_removes_incident_edges` |
| CL-005 | 坡度和推力方向性 | 上坡受限、反向保留，ETA/风险/代价方向不同 | `tests/test_closed_loop_factor.py::test_cl005_grade_force_is_directional` |
| CL-006 | PathMetrics 精确加和 | 两条冻结方向边逐字段手算求和 | `tests/test_closed_loop_factor.py::test_cl006_eta_and_cost_are_exact_directed_edge_sums` |
| CL-007 | ETA 上界无界语义 | 速度下界为零时 `eta_upper_s=None` 且 bounded=false | `tests/test_closed_loop_factor.py::test_cl007_zero_speed_lower_produces_unbounded_eta` |
| CL-008 | 车辆请求改变路由指标 | 两车辆共享静态/拓扑哈希但车辆哈希和 ETA 不同 | `tests/test_closed_loop_factor.py::test_cl008_two_vehicles_reuse_static_graph_but_change_eta` |

## 2. 配置与 PortsMap

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-009 | schema v1 兼容迁移 | 旧字段只迁移仍生效参数并规范为 v2 | `tests/test_closed_loop_contract_validation.py::test_cl009_schema_v1_ignores_unused_fields_and_normalizes_to_v2` |
| CL-010 | schema v2 严格校验 | 未知章节/字段、隐式类型和非法范围均拒绝 | `tests/test_closed_loop_contract_validation.py::test_cl010_schema_v2_rejects_unknown_sections_and_fields` |
| CL-011 | 有效快照和哈希 | 快照只含 v2 生效字段且重复加载稳定 | `tests/test_closed_loop_contract_validation.py::test_cl011_effective_snapshot_contains_only_schema_v2_active_sections` |
| CL-012 | 精确方向代价与连续展开 | 每个目标与完整有向图 Dijkstra 相等，所有展开边存在 | `tests/test_closed_loop_portsmap.py::test_cl012_portsmap_matches_full_graph_dijkstra` |
| CL-013 | 请求内相同上下文复用 | 相同端点/权重/阻塞重复搜索增加 cache hit 且路径相同 | `tests/test_closed_loop_portsmap.py::test_cl013_portsmap_reuses_identical_parent_pair_context` |
| CL-014 | 资源上限显式失败 | 超过 Port/Port-pair 上限返回固定错误码，无近似路径 | `tests/test_closed_loop_portsmap.py::test_cl014_portsmap_limit_is_explicit` |
| CL-015 | 缓存上下文有界 | 权重上下文变化替换同父格旧项，显式清空后为空 | `tests/test_closed_loop_portsmap.py::test_cl015_portsmap_cache_keeps_only_latest_context_per_parent` |

## 3. 确定性候选与角色

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-016 | 唯一路线和固定角色 | 输出 1～5 条唯一路线，各指标角色等于真实极值 | `tests/test_closed_loop_candidates.py::test_cl016_planner_and_aggregator_return_unique_fixed_roles` |
| CL-017 | 独立备选必须经扰动存活 | 屏蔽参考走廊后仍可达才分配独立角色 | `tests/test_closed_loop_candidates.py::test_cl017_resilient_route_survives_reference_corridor_failure` |
| CL-018 | 不伪造独立备选 | 无可屏蔽核心时不创建角色并返回固定警告 | `tests/test_closed_loop_candidates.py::test_cl018_no_core_corridor_does_not_fabricate_backup` |
| CL-019 | 候选生成确定性 | 相同图和配置两次产生相同路径、角色与顺序 | `tests/test_closed_loop_candidates.py::test_cl019_candidate_generation_is_deterministic` |
| CL-020 | Pareto、拥挤和 widest 保留 | 支配关系、前沿、拥挤排序和截断均符合构造 Oracle | `tests/test_closed_loop_candidates.py::test_cl020_pareto_front_crowding_and_widest_preservation` |
| CL-021 | 聚合边界和缓存完整性 | 非法上限/任务/空候选拒绝，篡改指标不得进入结果 | `tests/test_closed_loop_candidates.py::test_cl021_candidate_aggregator_boundary_and_metric_validation` |

## 4. RoutePlan、选择与 GIS 成果

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-022 | 计划/GPKG 往返且不隐式选择 | 固定图层存在、旧重复成果移除、首次无 selection | `tests/test_closed_loop_persistence.py::test_cl022_plan_round_trip_gpkg_layers_and_explicit_selection` |
| CL-023 | 选择幂等和版本冲突 | 相同角色重复选择相等，陈旧 expected version 拒绝 | `tests/test_closed_loop_persistence.py::test_cl023_selection_is_idempotent_and_version_conflicts_are_rejected` |
| CL-024 | 损坏状态隔离 | 非法 JSON 移为 `.corrupt` 并返回明确错误 | `tests/test_closed_loop_persistence.py::test_cl024_corrupt_selection_is_isolated` |
| CL-025 | 规范 JSON 确定性 | 相同输入的 plan ID 和 JSON 字节完全一致 | `tests/test_closed_loop_persistence.py::test_cl025_plan_json_is_canonical_and_deterministic` |
| CL-026 | 原子替换失败保留旧状态 | 模拟 `Path.replace` 失败，已提交 JSON 内容不变 | `tests/test_closed_loop_persistence.py::test_cl026_atomic_write_failure_preserves_previous_file` |
| CL-027 | GIS 指标与 RoutePlan 一致 | GPKG 候选 ETA、距离、裕度兼容列、风险和代价逐条相等 | `tests/test_closed_loop_persistence.py::test_cl027_gpkg_candidate_metrics_match_route_plan` |

## 5. 阻塞生命周期与重规划

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-028 | confirmed 阻塞只作用于 overlay | 活动路线避开阻塞而基础图保持可通行 | `tests/test_closed_loop_replanning.py::test_cl028_confirmed_blockage_repairs_overlay_without_mutating_base` |
| CL-029 | cleared/expired 恢复 | TTL 过期后从未修改基础图恢复原路径 | `tests/test_closed_loop_replanning.py::test_cl029_cleared_and_expired_blockages_restore_edges` |
| CL-030 | tentative 去抖 | 未确认观测持久化但不增加路径版本 | `tests/test_closed_loop_replanning.py::test_cl030_tentative_observation_is_debounced_without_path_version` |
| CL-031 | 重启恢复和哈希防护 | GPKG 重建可重规划；车辆/因子哈希变化拒绝局部修复 | `tests/test_closed_loop_replanning.py::test_cl031_restart_snapshot_and_hash_mismatch_guard` |
| CL-032 | 确认次数状态转移 | 重复不可信观测达到阈值后才确认并修复 | `tests/test_closed_loop_replanning.py::test_cl032_confirmation_count_promotes_tentative_record` |
| CL-033 | 显式当前位置 | 缺失、未知或超出吸附距离的位置拒绝 | `tests/test_closed_loop_contract_validation.py::test_cl033_replan_request_requires_explicit_valid_position` |
| CL-034 | 回退使用冻结角色代价 | 各角色只读取对应冻结边字段和裕度阈值 | `tests/test_closed_loop_replanning.py::test_cl034_role_cost_reads_only_frozen_edge_metrics` |
| CL-035 | 有界回退终态 | 超出频率进入 safe_hold；证明无路进入 invalidated | `tests/test_closed_loop_replanning.py::test_cl035_global_fallback_rate_limit_and_no_route_states` |

## 6. 适配器、桌面和端到端

| ID | 需求 | 输入/Oracle | Pytest 节点 |
|---|---|---|---|
| CL-036 | CLI 统一 RoutePlan 流 | CLI payload 调用同一业务入口并传递进度/参数 | `tests/test_cli_validation_coverage.py::test_cl036_cli_progress_and_route_plan_dispatch` |
| CL-037 | HTTP 选择与重规划状态 | `/api/select` 和 `/api/replan` 返回真实活动几何 | `tests/test_mvp8.py::test_cl037_web_state_endpoints_select_and_return_replanned_active_geometry` |
| CL-038 | 桌面生产后台链 | 普通 Thread 和 SimpleQueue 存在，生产启动不实例化 Legacy Worker | `tests/test_desktop_ui.py::test_cl038_plain_background_thread_contract_uses_queue_not_qthread` |
| CL-039 | 双车辆复用静态 Tile | 连续两次车辆评估后输入 cell/edge 对象值完全不变 | `tests/test_closed_loop_factor.py::test_cl039_route_time_evaluation_does_not_mutate_reusable_tile` |
| CL-040 | 完整计划身份确定性 | 相同闭环输入重建的计划、候选、角色和哈希完全一致 | `tests/test_closed_loop_persistence.py::test_cl040_complete_route_plan_identity_is_deterministic` |

## 7. 静态 GIS 土壤—机动迁移验收

| ID | 行为 | Pytest 节点 |
|---|---|---|
| T01 | 分类土壤不伪造水分/工程类别 | `tests/test_static_gis_transfer.py::test_t01_soil_catalog_stays_categorical_without_default_moisture` |
| T02 | TWI→D 截断且无效值保持未知 | `tests/test_static_gis_transfer.py::test_t02_twi_mapping_preserves_invalid_cells_and_clips` |
| T03 | 水文阈值成对冻结、上游状态显式 | `tests/test_static_gis_transfer.py::test_t03_hydrology_policy_requires_frozen_threshold_pair` |
| T04 | 100/110 m 双路线随请求压力切换 | `tests/test_static_gis_transfer.py::test_t04_wet_and_dry_requests_choose_different_budgeted_routes` |
| T05 | 后轴参考矩形覆盖完整车辆尺寸 | `tests/test_static_gis_transfer.py::test_t05_rear_axle_reference_footprint_uses_all_vehicle_dimensions` |
| T06 | 直线段执行连续整车扫掠 | `tests/test_static_gis_transfer.py::test_t06_straight_sweep_is_continuous_between_endpoint_poses` |
| T07 | 圆弧满足最小半径或明确失败 | `tests/test_static_gis_transfer.py::test_t07_fillet_obeys_radius_or_reports_insufficient_space` |
| T08 | 新模式水体硬阻断且行距不是净空 | `tests/test_static_gis_transfer.py::test_t08_strict_static_mode_blocks_water_and_does_not_use_rowspacing` |
| T09 | 环境倍率独立于 travel_cost | `tests/test_static_gis_transfer.py::test_t09_environment_multiplier_uses_surface_and_drainage_not_travel_cost` |
| T10 | 超过 15% 绕行预算的候选排除 | `tests/test_static_gis_transfer.py::test_t10_detour_budget_excludes_overlong_candidate` |
| T11 | 小收益保留旧路、旧路失效立即切换 | `tests/test_static_gis_transfer.py::test_t11_hysteresis_retains_small_gain_but_invalid_old_route_switches` |
| T12 | 投影静态栅格按 WGS84 H3 中心正确采样 | `tests/test_static_gis_transfer.py::test_t12_projected_static_raster_is_sampled_from_wgs84_centers` |

## 8. 门禁

唯一基线验收入口：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts\verify_baseline.py
```

验收必须同时满足：

- CL-001～CL-040 每个编号在测试函数中恰好出现一次；
- 全部 pytest 通过；
- 语句覆盖率 ≥80%，分支覆盖率 ≥70%；
- `ruff check src tests demo scripts` 零错误；
- `mypy src scripts` 零错误；
- 活动文档禁用符号、ADR 编号唯一、Git 差异格式和私有文件检查通过。
