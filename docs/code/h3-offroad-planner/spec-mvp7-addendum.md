# MVP-7 Requirements Addendum

- **Status**: Superseded by ADR-022; historical requirements only
- **Scope**: Hierarchical PortsMap and macro A* corridor planning
- **Decision ADR**: `ADR-013-mvp7-hierarchical-portsmap.md`

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-027 | Build parent PortsMap | Passable fine-cell edges crossing `parent_h3` groups create deterministic bidirectional parent adjacency. |
| FR-028 | Route through macro graph | Start and goal attach through their parent group; macro search returns all parent hops or raises `PlanningFailedError`. |
| FR-029 | Bound fine corridor | Fine A* uses only passable cells in macro parents plus `dilation` parent-neighbor rings; unrelated parent components are excluded. |
| FR-030 | Preserve legacy graph behavior | Empty `parent_h3` uses the fine cell id as a synthetic parent and existing MVP-1 paths stay valid. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-012 | Determinism | Neighbor and queue traversal are sorted; repeated calls return the same macro route for the same graph. |
| NFR-013 | No hidden scope | This batch adds neither persistent PortsMap caching, weighted macro optimization, true D* Lite, full PBS, nor UI. |
