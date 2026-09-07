# MVP-6.1 Requirements Addendum

- **Status**: Historical; current requirements are defined in `spec.md`
- **Scope**: Corrective integrity fixes before MVP-7
- **Decision ADR**: `ADR-012-mvp61-corrective-integrity-fixes.md`

MVP-6.1 fixes current-contract defects found after MVP-6. It does not promote full
PortsMap, true incremental D* Lite, full PBS branching, task allocation, time windows,
fleet-level NSGA-II scheduling, or formal UI into the current implementation scope.

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-023 | Fix legacy Bekker unit handling | Legacy soil sinkage uses kPa-consistent pressure/stiffness and light vehicles can pass plausible legacy soils. |
| FR-024 | Attach vector landcover | GeoDataFrame landcover inputs assign cell code/type/factor by largest polygon overlap instead of being ignored. |
| FR-025 | Configure landcover and speed controls | Landcover factors, unknown-code default factor, and Bekker speed floor can be configured without editing source constants. |
| FR-026 | Stabilize pentagon neighbors | Pentagon ring-1 neighbor handling is deterministic and does not silently truncate unordered neighbors. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-010 | Backward compatibility | Existing constructors and demos continue to work with default arguments. |
| NFR-011 | No new product scope | Corrective fixes do not add UI, full PBS, true D* Lite, or full PortsMap as hidden scope. |
