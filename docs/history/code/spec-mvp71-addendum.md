# MVP-7.1 Requirements Addendum

- **Status**: Historical; current requirements are defined in `spec.md`
- **Scope**: Minimal GIS-to-route delivery command line
- **Decision ADR**: `ADR-014-mvp71-delivery-cli.md`

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-031 | Build cache from CLI | `build-tiles --request` converts one YAML mapping to `TileBuildRequest` and prints the tile manifest JSON. |
| FR-032 | Plan from CLI | `plan --request` converts one YAML mapping to `RouteRequest` and prints the route manifest JSON. |
| FR-033 | Run full delivery chain | `run --request` reads `tile_build` and `route` mappings, builds tiles, routes using the generated tile manifest, and returns both manifests. |
| FR-034 | Fail explicitly | Missing, malformed, or invalid request fields and expected GIS/planning failures produce one stderr error and exit code 2. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-014 | No duplicated domain logic | CLI calls existing `build_h3_tile_cache` and `run_route` APIs only. |
| NFR-015 | Reproducible handoff | Example YAML and bounded ROI are stored in `configs/`; manifests retain existing artifact metadata. |
