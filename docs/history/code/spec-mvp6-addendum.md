# MVP-6 Requirements Addendum

- **Status**: Superseded by ADR-022; historical requirements only
- **Scope**: Minimal multi-vehicle conflict coordination over one H3 graph
- **Decision ADR**: `ADR-011-mvp6-pbs-compatible-fleet-coordination.md`

MVP-6 promotes the deferred PBS/fleet item into a bounded demo scope. It does not
implement full PBS tree branching, task allocation, time windows, or formal UI.

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-018 | Define fleet planning tasks | A `FleetTask` validates unique vehicle id, graph-contained start/goal, priority, vehicle profile, and objective whitelist through `FleetPlanningInput`. |
| FR-019 | Detect discrete path conflicts | `detect_conflicts()` reports same-cell same-time vertex conflicts and opposite-direction same-time edge-swap conflicts. |
| FR-020 | Coordinate fixed-priority fleet paths | `PBSFleetCoordinator.coordinate()` returns one `Path` per task, with no detected conflicts, or raises `PlanningFailedError`. |
| FR-021 | Represent waits explicitly | Repeated cells in a returned `Path.cells` sequence represent a one-step wait at that cell. |
| FR-022 | Keep MVP-6 bounded | Coordination refuses impossible or oversized searches using `max_time_steps` and `max_expansions_per_task`. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-008 | Deterministic fleet output | Equal inputs produce stable task order, tie-breaking, paths, and manifests. |
| NFR-009 | Acyclic dependency | `coordination` depends on `models` and `dynamics`, not on routing, tiling, preprocessing, exporting, or demo code. |
