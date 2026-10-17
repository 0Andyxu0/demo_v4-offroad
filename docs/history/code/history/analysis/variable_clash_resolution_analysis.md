# Variable Naming Clash Resolution Analysis

> 历史证据（非活动规范）：记录变量语义收敛前的分析，当前字段定义以活动 API 和闭环合同为准。

This report addresses the semantic naming clash and optimization-direction conflict of the `trafficability` and `score_lower/nominal/upper` variables between the legacy single-path flow and the new multi-objective physical margin planning flow.

---

## 1. The Core Conflict

There is a fundamental semantic mismatch between the two development phases:

*   **Legacy Flow (`src/h3_offroad_planner/planners/nsga2.py:L199`)**:
    *   `trafficability` = `cost_score * distance`.
    *   It acts as a **cumulative penalty** (cost).
    *   Optimization direction: **Minimization** (the smaller the better).
*   **New Physical Flow (`src/h3_offroad_planner/factor_model.py:L725`)**:
    *   `trafficability` = `safety_margin`.
    *   It represents a physical **safety margin fraction** in `[0, 1]`.
    *   Optimization direction: **Maximization** (the larger the better).

Additionally, the fields `score_lower`, `score_nominal`, and `score_upper` are legacy placeholders originally meant for weighted utility scores but now store physical safety margin fractions.

---

## 2. Proposed De-coupling Architecture

To resolve this conflict cleanly in a demo environment without breaking downstream APIs or GIS layers, we recommend the **Boundary Adapter Pattern** to isolate internal domain representations from external database schemas.

```
+-------------------------------------------------+
|               Internal Domain Model             |
|  - safety_margin (0 to 1, larger is better)     |
|  - passability_deficit (1 - margin, minimize)   |
+-----------------------+-------------------------+
                        |
                        v [Serialization Layer]
+-------------------------------------------------+
|               External GIS / JSON               |
|  - trafficability (backward compatible alias)  |
|  - score_lower/nominal/upper                    |
+-------------------------------------------------+
```

### Action Item 1: Internal Domain Renaming
Rename the core variables in the Python domain classes to reflect physical facts:
*   In `NodeFactorMetrics` (`src/h3_offroad_planner/factor_model.py:L126`):
    *   `trafficability` $\rightarrow$ `safety_margin`
*   In `DirectedEdgeMetrics` (`src/h3_offroad_planner/factor_model.py:L158`):
    *   `score_lower` $\rightarrow$ `safety_margin_lower`
    *   `score_nominal` $\rightarrow$ `safety_margin_nominal`
    *   `score_upper` $\rightarrow$ `safety_margin_upper`

### Action Item 2: Normalize Optimization Objectives
In the multi-objective planner (`src/h3_offroad_planner/planners/deterministic_pareto.py`), keep all comparison targets aligned to **minimization**:
$$\text{passability\_deficit} = 1.0 - \text{safety\_margin\_lower}$$
The search algorithm only minimizes `passability_deficit`, eliminating conflicts with maximization variables.

### Action Item 3: Boundary Isolation via Exporters
Keep legacy names strictly constrained to output serialization. Do not allow them to leak into the planning logic.
*   In `route_persistence.py` or `gis_exporter.py`, perform explicit translation when writing GPKG or GeoJSON files:
    ```python
    gpkg_record["score_lower"] = edge_metrics.safety_margin_lower
    gpkg_record["trafficability"] = node_metrics.safety_margin.nominal
    ```

---

## 3. Benefits

*   **Zero Semantic Ambiguity**: The internal code refers exclusively to physical margins (larger is better) or deficits (smaller is better).
*   **Decoupled Schema Lifecycle**: Downstream clients can continue to query old database fields (`score_lower`) without forcing the core planning library to maintain confusing class attributes.
