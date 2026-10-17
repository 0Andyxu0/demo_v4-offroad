# MVP-7.2 Requirements Addendum

- **Status**: Historical; current requirements are defined in `spec.md`
- **Scope**: Algorithm correctness repairs
- **Decision ADR**: `ADR-015-algorithm-correctness-repairs.md`

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-035 | Real-H3 LOS | Non-integer real H3 indexes use `grid_path_cells`; a shortcut succeeds only when every sampled cell exists and is passable. |
| FR-036 | Incremental D* Lite | Replanning retains and repairs `g/rhs`, queue, and key-shift state after newly blocked cells without calling global A*. |
| FR-037 | Weighted macro boundaries | Cross-parent macro edges use the lowest finite directional physical boundary cost rather than a constant weight. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-016 | Synthetic compatibility | Existing integer-grid LOS fixtures remain valid through the fallback helper. |
| NFR-017 | Bounded correction | No new public API, persistent Port-pair cache, or UI is introduced. |
