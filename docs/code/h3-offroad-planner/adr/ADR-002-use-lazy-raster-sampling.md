# ADR-002: Use Lazy Raster Sampling for MVP-2 GIS Ingestion

- **Status**: Accepted
- **Date**: 2026-07-07
- **Author(s)**: Codex coordinator
- **Triggered by**: Backtrack Protocol in Phase 3
- **Supersedes**: None

## Context

During MVP-2 implementation, the real `land_nanjing.tif` layer was found to be
`132000 x 84000` pixels. The original Phase 1 API implied loading landcover as a
full `np.ndarray`, which is unsafe for this data volume and would exceed normal
memory budgets.

## Decision

Introduce a `RasterLayer` lazy descriptor in `preprocessing.gis_preprocessor`.
Large rasters such as landcover and soil are kept on disk and sampled at H3 cell
centers during `H3GridBuilder.attach_landcover()` and `attach_soil()`.

`H3GridBuilder` gains bounded sampling controls: `sample_stride`, `max_cells`, and
`road_buffer_deg`. These are implementation controls for MVP-2 and do not change
the planner-facing graph contract.

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Load full landcover array | Requires roughly 11 GB for one uint8 band and more when processed |
| Ignore landcover/soil | Would fail the real-data MVP-2 requirement |
| Force Res13 full-city graph | Computationally explosive for first real-data validation |

## Consequences

Positive:

- Real Nanjing rasters can be used safely in MVP-2.
- Sampling controls make small reproducible smoke tests possible.

Negative:

- Full-resolution cartographic fidelity is deferred.
- Sampling density must be tuned before production-scale planning.

Required follow-up actions:

- [x] Update Phase 1 API design to include `RasterLayer` and `attach_soil`.
- [x] Re-run Gate 1 scoring after the ADR update.
- [ ] In a later MVP, decide production H3 resolution and tiling strategy.

