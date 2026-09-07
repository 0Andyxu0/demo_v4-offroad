# ADR-015: LOS, Incremental D* Lite, and Weighted Macro Repairs

- **Status**: Accepted
- **Date**: 2026-07-10
- **Scope**: Correct algorithm defects identified by external assessment

## Context

The assessment correctly found that LOS shortcutting rejected non-integer geographic
coordinates, the local replanner fell back to fresh global A*, and parent macro edges
used constant weights. The first is a real-data correctness defect. The latter two were
previously deferred MVP limitations, but are promoted by this corrective decision.

## Decision

- LOS uses `h3.grid_path_cells` for valid H3 indexes and verifies every sampled cell is
  present and passable. The integer-coordinate helper remains only for synthetic tests.
- `DStarLiteReplanner` maintains reverse `g`, `rhs`, lazy priority queue keys, and `km`;
  changed obstacle cells update their local predecessors before path extraction.
- Parent PortsMap edges store the minimum finite directional `CostFunction` boundary
  crossing cost, replacing the constant macro weight.

## Consequences

- Real H3 paths can be shortened safely without coordinate-integer assumptions.
- Replanning repairs the retained reverse-search state instead of invoking H3AStar.
- Macro routing distinguishes expensive boundary crossings, while full Port-pair cache
  construction remains a later performance refinement.
