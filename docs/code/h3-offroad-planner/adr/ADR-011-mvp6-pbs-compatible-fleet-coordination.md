# ADR-011: MVP-6 PBS-Compatible Fleet Coordination（已撤销）

> 状态：Superseded。当前单车工程闭环已删除 `PBSFleetCoordinator`、冲突检测、
> 固定优先级预约算法、Demo 和专项测试。仅保留 `FleetTask`、`FleetPlanningInput`、
> `FleetPlan` 以及没有具体实现的 `FleetCoordinator` Protocol。多车协调未实现，
> 不属于当前验收范围；下文仅为历史记录，不代表现有能力。

- **Status**: Superseded by ADR-022
- **Date**: 2026-07-10
- **Scope**: MVP-6 minimal multi-vehicle cell-time coordination

## Context

MVP-5 produces bounded single-vehicle Pareto candidate paths, but the remaining
algorithmic risk is multi-vehicle conflict handling. A full PBS implementation with
task allocation, time windows, stochastic global optimization, and UI control would be
too large for the next batch.

The project already has stable graph, cost, A*, route, tile, and candidate-path
contracts. MVP-6 should therefore prove the smallest useful fleet loop: given known
vehicle tasks on the same H3 graph, produce conflict-free discrete cell-time paths or
fail explicitly.

## Decision

MVP-6 adds a `coordination` module with a `PBSFleetCoordinator` public boundary:

- `FleetTask` defines one vehicle id, start, goal, vehicle profile, objectives, and
  integer priority.
- `FleetPlanningInput` carries the shared `H3Graph`, tasks, and bounded time-search
  controls.
- `PBSFleetCoordinator.coordinate()` plans tasks in priority order using a
  time-expanded A* search constrained by higher-priority reservations.
- `detect_conflicts()` reports vertex conflicts and opposite-direction edge swaps.
- `FleetPlan` returns per-vehicle `Path` objects with repeated cells representing
  waits.

MVP-6 is PBS-compatible rather than full PBS: it uses fixed priority ordering and
reservation constraints, but it does not branch over a PBS constraint tree.

## Consequences

- Multi-vehicle correctness becomes testable without adding UI or task assignment.
- Existing single-vehicle planners remain unchanged.
- The dependency path stays acyclic: `models -> dynamics -> coordination -> demo/tests`.
- Narrow passages may fail when fixed priorities cannot find a bounded conflict-free
  solution; this is acceptable and explicit through `PlanningFailedError`.

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Full PBS constraint tree | Too much scope before basic cell-time conflict contracts exist |
| Fleet NSGA-II scheduling | Mixes two algorithm families and hides conflict semantics |
| UI-first fleet controls | Does not reduce algorithmic risk |
| Ignore edge-swap conflicts | Unsafe for vehicles moving through the same edge in opposite directions |
