# Dynamic Obstacles & Lifecycle Representation Analysis

> 历史证据（非活动规范）：记录动态障碍生命周期收敛前的分析，当前接口以活动架构文档和代码为准。

This report evaluates the redundancy and semantic mismatch of the `dynamic_obstacles: dict[str, float]` parameter within the low-level path planning interfaces (`models.py`, `dstar_lite.py`, `facade.py`).

---

## 1. The Core Issue

The low-level planner interface defines:
*   `dynamic_obstacles: dict[str, float]` (in `src/h3_offroad_planner/models.py:L500`), where the `float` represents an observation timestamp or weight.

However, the algorithms using this parameter ignore the values:
*   In **`DStarLiteReplanner.replan`** (`src/h3_offroad_planner/planners/dstar_lite.py:L88`):
    ```python
    affected = _mark_unpassable(graph, blocked.union(dynamic_obstacles))
    ```
    Since iterating over a dictionary only yields its keys, the timestamp values are immediately discarded. The planner treats these cells identically to static blockages.
*   In **`PathPlannerFacade._global_fallback`** (`src/h3_offroad_planner/planners/facade.py:L53`):
    ```python
    for cell_id in blocked.union(dynamic_obstacles.keys()):
        if cell_id in graph.cells:
            graph.cells[cell_id].is_passable = False
    ```
    The keys are extracted explicitly, discarding the time values.

---

## 2. Architectural Analysis: Where Should Lifecycle Live?

There is a fundamental question of architectural separation of concerns: **Should the pathfinder/planner manage obstacle lifecycles (timestamps, confirmation, expiration)?**

In the closed-loop system, this is already resolved at a higher layer:
*   **Controller Level (`src/h3_offroad_planner/replanning.py:L21-L34`)**:
    *   The dynamic controller (`replan_route`) manages obstacle states using **`BlockageRecord`** (which tracks `state` as `tentative/confirmed/cleared/expired`, `confirmation_count`, `observed_at_epoch_s`, and `trusted_source`).
    *   The controller handles time-based expiration (e.g. `recent_failed_corridor_ttl_s`) and confirmation debounce logic.
    *   Once the active blockages are resolved, the controller passes them to the planner as a simplified binary set of cell IDs (`blocked`).
*   **Planner Level**:
    *   The pathfinder (`dstar_lite` or `astar`) only needs a binary state: **"Is this cell passable right now?"**
    *   Passing `dynamic_obstacles: dict[str, float]` to the planner represents a **leaky abstraction**. It forces the planner interface to declare time-related parameters that it has no business evaluating.

---

## 3. Proposed Redesign

In a clean redesign discarding legacy constraints, we should simplify the boundaries by unifying all blockages under a single binary type.

```
+-------------------------------------------------------------+
|                     Controller Layer                        |
|  - Manages BlockageRecord (tentative, cleared, expired)     |
|  - Resolves time-based TTLs and confirmations               |
+------------------------------+------------------------------+
                               |
                               | (Passes active cell IDs)
                               v
+-------------------------------------------------------------+
|                       Planner Layer                         |
|  - PlannerInput (blocked_cells: set[str])                   |
|  - replan(blocked_cells: set[str])                          |
|  - Pathfinder only sees binary passability                  |
+-------------------------------------------------------------+
```

### Action Items

1.  **Simplify Planner Interfaces**:
    *   In `interfaces.py` and `facade.py`, modify the `replan` signature to remove the `dynamic_obstacles` parameter:
        ```python
        def replan(
            self,
            graph: H3Graph,
            blocked_cells: set[str],
            current_path: Path,
        ) -> Path:
        ```
    *   In `src/h3_offroad_planner/models.py:L500`, remove `dynamic_obstacles` from `PlannerInput`.

2.  **Simplify D* Lite Implementation**:
    *   In `src/h3_offroad_planner/planners/dstar_lite.py:L88`, change:
        ```python
        affected = _mark_unpassable(graph, blocked_cells)
        ```

3.  **Ensure Proper Separation of Concerns**:
    *   Keep the temporal lifecycle logic (expiration, state machine) strictly inside `replanning.py` using `BlockageRecord`.
    *   This keeps the core routing algorithms completely stateless with respect to real-world clock time.
