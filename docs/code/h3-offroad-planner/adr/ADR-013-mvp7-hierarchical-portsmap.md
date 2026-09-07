# ADR-013: MVP-7 Hierarchical PortsMap Corridor Planning

- **Status**: Superseded by ADR-022; weighted interim repair recorded by ADR-015
- **Date**: 2026-07-10
- **Scope**: Replace the H3AStar full-graph corridor placeholder with parent-H3 routing

## Context

> Historical record only. ADR-015 replaced constant macro weights, and ADR-022 later
> replaced the hierarchical corridor contract with exact request-scoped Port-pair
> expansion. The decision below is retained to explain the migration.

The existing public planner contract states a PortsMap -> macro A* -> corridor -> fine
A* sequence, but the implementation represented every fine cell as a Port and admitted
the whole passable graph into the corridor. That behavior cannot bound fine-search work
for tiled res13 graphs.

## Decision

- Use each passable cell `parent_h3` as the macro graph node. Empty synthetic parent ids
  fall back to the cell id for MVP-1 compatibility.
- Create a bidirectional parent adjacency only when a graph edge crosses two passable
  parent groups.
- Attach start and goal through their own parent group; macro routing returns a complete
  parent route or raises `PlanningFailedError`.
- Build the fine-search corridor from route parents plus a graph-derived parent-neighbor
  shell. Default dilation remains one parent ring.
- Do not introduce a new public API, persistent Port cache, true incremental D* Lite,
  or a multi-tile streaming search in this batch.

## Consequences

- Fine A* searches a smaller deterministic cell set when parent groups are present.
- Synthetic and legacy graphs with no parent ids remain correct but have no compression.
- Parent routing is topological and unweighted in MVP-7; fine A* remains responsible for
  physical cost optimality within the selected corridor.
