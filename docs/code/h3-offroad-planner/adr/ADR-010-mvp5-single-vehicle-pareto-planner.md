# ADR-010: MVP-5 Single-Vehicle Pareto Candidate Planner

- **Date**: 2026-07-10
- **Status**: Superseded by ADR-021 and ADR-022
- **Scope**: MVP-5 single-vehicle multi-objective candidate path planning

## Context

> Historical record only. The current planner uses physical bottleneck margins and the
> deterministic closed-loop contract in ADR-021/ADR-022. The decision below is not an
> active API or algorithm specification.

Earlier MVP batches intentionally kept NSGA-II/Pareto planning out of scope until the
single-vehicle GIS, tile cache, and route-time loading loop was stable. MVP-3.1 already
persisted `score` and `cost_score` to prepare for later multi-objective search.

## Decision

MVP-5 activates `NSGAIIPlanner` for a bounded single-vehicle use case:

- `PlannerInput.objectives` accepts a whitelist of objectives:
  `distance`, `travel_cost`, `trafficability`, `slope`, and `roughness`.
- `Path` stores an `objectives` mapping with finite non-negative objective values.
- `NSGAIIPlanner` returns a bounded set of non-duplicate Pareto-style candidate paths.
- MVP-5 uses deterministic scalarized A* candidate generation plus non-dominated sorting
  and crowding selection. This preserves the `NSGAIIPlanner` public role while avoiding
  stochastic full-fleet genetic scheduling in the single-vehicle demo.
- PBS, time windows, multi-vehicle conflict resolution, and formal UI remain excluded.

## Consequences

- Existing `H3AStarPlanner` remains the default single-path planner.
- `PlannerFactory` can instantiate `NSGAIIPlanner` when `global_planner: NSGAII` is
  configured.
- Route and demo layers can inspect multiple candidate objective vectors, while current
  route exporters may still export the first candidate path.
