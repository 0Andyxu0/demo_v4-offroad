# Desktop Controller & State Overlap Resolution Analysis

> 历史证据（非活动规范）：记录桌面状态整合前的重叠分析，当前实现与接口以活动架构文档和代码为准。

This report addresses the redundancy and overlapping state abstractions within the desktop client framework, focusing on `DesktopBusinessController`, `DesktopSelection`, and `DesktopProject`.

---

## 1. Current Overlap and Redundancies

There are currently three parallel state and control pathways in the desktop codebase:

1.  **Stateful Configuration (`src/h3_offroad_planner/desktop_project.py`)**:
    *   Manages the state of the active project YAML (data file paths, vehicle paths, active selections).
2.  **UI Selection Data (`src/h3_offroad_planner/desktop_client.py:L76`)**:
    *   Uses `DesktopSelection` to hold map-view selections (coordinates, selected ROI).
    *   Uses `prepare_desktop_payload` to inject selections into a YAML dict. This function is **only invoked in tests** (`tests/test_mvp8.py`).
3.  **Transactional Controller (`src/h3_offroad_planner/client_controller.py:L45`)**:
    *   Defines `DesktopBusinessController` and `ClientState` to support asynchronous worker cancellation and transactional candidate view state.
    *   This class is **only invoked in tests** and is completely bypassed by the production PyQt app, which directly spawns `DesktopOperationWorker` and `_execute_desktop_operation`.

---

## 2. Redesign Architecture (Consolidated State & Control)

In a clean, non-compatibility-constrained redesign, we can merge these pathways into a unified Model-View-Controller (MVC) architecture.

```
       +---------------------------------------------+
       |                  View (UI)                  |
       |  - DesktopMainWindow & GIS Web Map View     |
       +-------+-----------------------------^-------+
               |                             |
(User Actions) |                             | (Renders State)
               v                             |
       +-------+-----------------------------+-------+
       |               Controller (MVC)              |
       |  - DesktopOperationWorker / CLI Adapters    |
       +-------+-----------------------------^-------+
               |                             |
 (Saves data)  |                             | (Reads properties)
               v                             |
       +-------+-----------------------------+-------+
       |                 Model (State)               |
       |  - Unified DesktopProject State             |
       |    (Combines configs & map selections)      |
       +---------------------------------------------+
```

### Action Item 1: Unify State Models
*   **Merge `DesktopSelection` into `DesktopProject`**:
    *   Delete the separate `DesktopSelection` class entirely.
    *   Extend `DesktopProject` to directly store the active session-level map parameters (e.g. `start_endpoint`, `goal_endpoint`, `blocked_cells`, and `study_area_geojson`).
    *   The map view and main window will interact directly with the `DesktopProject` instance, modifying its properties in response to user clicks.

### Action Item 2: Consolidate Payload Building
*   **Delete `prepare_desktop_payload`**:
    *   Delete `prepare_desktop_payload` from `desktop_client.py`.
    *   Move its payload injection logic (writing the session GeoJSON ROI, updating coordinates and blocked lists) directly into the unified `DesktopProject.build_run_payload(session_root)` method.
    *   Rewrite `tests/test_mvp8.py` to test payload building through `DesktopProject.build_run_payload()` instead of calling the orphaned adapter function.

### Action Item 3: Delete the Duplicate Business Controller
*   **Delete `DesktopBusinessController` and `ClientState`**:
    *   Delete `client_controller.py` entirely.
    *   Let both the production PyQt background workers and the offline CLI/integration tests dispatch tasks directly through the unified `_execute_desktop_operation` (which wraps the clean `run_route_payload` and `run_replan_payload` pipelines).
    *   If tests require verification of the background execution or thread-safety, they should execute the `DesktopOperationWorker` class directly or run it in a mock synchronous wrapper.

---

## 3. Benefits

*   **Single Source of Truth**: Eliminates sync bugs between UI selections (`DesktopSelection`) and project states (`DesktopProject`).
*   **Simpler Testing**: All tests exercise the exact same execution pipeline as the production app, reducing false positives in regression checks.
*   **Reduced Code Footprint**: Saves roughly ~300 lines of orphaned boilerplate state code.
