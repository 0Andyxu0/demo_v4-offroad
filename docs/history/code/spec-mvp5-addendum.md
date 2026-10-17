# MVP-5 Requirements Addendum

- **Date**: 2026-07-10
- **Status**: Superseded by ADR-021 and the current RoutePlan/PortsMap contract
- **Scope**: Single-vehicle multi-objective candidate path planning
- **Decision ADR**: `ADR-010-mvp5-single-vehicle-pareto-planner.md`

The original planner name and objective-vector interface are retired. The retained
requirement is deterministic, bounded, single-vehicle alternative generation without
genetic populations, crossover, mutation, or generations.

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-015 | Generate bounded multi-objective candidate paths | Given a frozen PortsMap context, start and goal, `DeterministicParetoPlanner.plan` produces bounded unique raw candidates for exact aggregation. |
| FR-016 | Record exact metrics per path | Each RoutePlan candidate records finite distance, ETA, terrain risk, travel cost and physical safety-margin aggregates, including explicit unbounded ETA representation. |
| FR-017 | Keep single-vehicle scope | MVP-5 does not implement PBS, time-window scheduling, deadlock handling, or formal UI. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-006 | Deterministic bounded runtime | MVP-5 uses fixed candidate limits and deterministic tie-breaking for reproducible tests and demos. |
| NFR-007 | Backward compatibility | Existing A* route, tile route, and export flows continue to pass unchanged. |
