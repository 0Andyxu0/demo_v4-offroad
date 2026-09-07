# ADR-008: MVP-4.1 Tile-Based Res13 Cache Build

- **Date**: 2026-07-08
- **Status**: Accepted
- **Scope**: MVP-4.1 tile-based continuous H3 cache construction

## Context

MVP-4 can build a continuous ROI H3 graph, but it still runs a single bounded ROI build.
Production `res13` regions can contain millions of cells, so a one-shot Parquet/GPKG
artifact is not suitable for recovery, ArcGIS inspection, or route-time graph loading.

The current data also shows that center sampling is much faster than full
area-dominance sampling. Area-dominance is useful for ambiguous soil boundaries, but it
is not a safe default for every 10 km or 50 km scale `res13` construction window.

## Decision

MVP-4.1 adds a parent-H3 tile cache pipeline:

- `TileBuildRequest` describes raw GIS paths, ROI layer, output directory, `res_fine`,
  `tile_res`, and tile/cell limits.
- `build_h3_tile_cache(request)` splits ROI into parent H3 tiles, builds each tile
  independently, and writes per-tile Parquet under `tiles/parent_res=<r>/parent_h3=<id>.parquet`.
- `tile_manifest.json` records one entry per tile with status, counts, path, bounds, and
  error text when a tile fails.
- Boundary sliver tiles whose parent polygon intersects ROI but whose clipped fine
  polyfill has no cells are recorded as `empty`, not `failed`.
- The default production shape is `res_fine=13`, `tile_res=10`.
- Landcover is assigned by center sampling in MVP-4.1 tile builds. Soil reuses the
  existing bounded area-dominance implementation when the raster window is small enough,
  and falls back to center sampling when that path would be too expensive or invalid.
- Water is a hard block. Generic impervious landcover is not hard-blocked unless a later
  building-footprint layer is introduced.
- Route graph edges skip impassable cells, while the Parquet table keeps all cells for
  thematic maps.

## Consequences

- A failed tile can be retried without discarding completed tiles.
- Large ROI construction is bounded by tile and cell guards instead of a single global
  memory allocation.
- MVP-4.1 produces route-ready partitioned caches, but route-time corridor loading from
  multiple tiles remains MVP-4.2.
