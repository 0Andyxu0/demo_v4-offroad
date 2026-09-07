# ADR-009: MVP-4.2 Route-Time Tile Cache Loading

- **Date**: 2026-07-10
- **Status**: Accepted
- **Scope**: MVP-4.2 route-time graph loading from tile cache outputs

## Context

MVP-4.1 produces resumable H3 tile caches, but `run_route()` still loads one Parquet
graph. That prevents route planning from using the partitioned cache without first
manually merging tiles into a monolithic file.

## Decision

MVP-4.2 extends the existing `run_route(RouteRequest)` source path contract:

- `RouteRequest.parquet_path` remains the backward-compatible field name, but it may now
  point either to a single H3 Parquet file or to a `tile_manifest.json`.
- When the source is `tile_manifest.json`, `run_route()` selects completed/skipped tile
  records whose bounds intersect the resolved route ROI, loads their Parquet files,
  concatenates the H3 rows, rebuilds one temporary `H3Graph`, and then applies the
  existing ROI filter, endpoint snapping, planner, and exporter flow.
- `empty` tile records are ignored. `failed` tile records intersecting the route ROI
  raise `GridBuildError` because the route corridor has incomplete source coverage.
- Tile Parquet paths may be absolute or relative to the current working directory or
  the manifest directory.
- Route manifests copy tile-cache source metadata and record the loaded tile count.

## Consequences

- No new route request dataclass is needed for MVP-4.2.
- The route graph remains an in-memory graph for the selected corridor only.
- Parallel tile scheduling, cache invalidation, and streaming search remain future work.
