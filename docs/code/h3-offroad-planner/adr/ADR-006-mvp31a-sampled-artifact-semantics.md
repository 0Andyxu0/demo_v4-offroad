# ADR-006: MVP-3.1a Sampled Artifact Semantics

- **Date**: 2026-07-08
- **Status**: Accepted
- **Scope**: MVP-3.1a corrective delivery before dense ROI H3 construction

## Context

MVP-2 and MVP-3.1 currently use `outputs/nanjing_h3_sample.parquet`, a sampled real-data cache generated from DEM pixels with `sample_stride=60`, `max_cells=5000`, `res_fine=7`, and `res_coarse=5`. This artifact is useful for algorithm smoke tests, but it is not a continuous H3 coverage of the Nanjing ROI.

When loaded in ArcGIS, the sampled cache can look like a H3 grid with holes. That is expected for a sampled cache, but it is ambiguous unless the exported GeoPackage and manifests explicitly record artifact semantics. A separate smoke route also used an adjacent edge, producing a route of length 2 that was technically valid but not representative for product inspection.

## Decision

MVP-3.1a keeps the public route API stable and adds explicit artifact metadata:

- Parquet sidecar manifest: `*.manifest.json` beside sampled Parquet files.
- Route manifest fields: source artifact kind, coverage mode, continuity flag, source resolutions, sampling stride, max cell cap, and warning text.
- GeoPackage feature fields on `h3_cells`, `h3_edges`, and themed layers: compact metadata suitable for ArcGIS inspection.
- A non-adjacent route smoke script that selects distant endpoints from a finite connected component.

MVP-3.1a does not claim to produce production `res13` continuous grids. Dense ROI polyfill/tile construction remains MVP-4.

## Consequences

- ArcGIS users can distinguish sampled demo artifacts from continuous production grids without reading source code.
- Tests no longer allow route smoke validation to depend only on a two-cell adjacent route.
- Existing public API remains backward compatible because metadata is optional.
- MVP-4 must still implement continuous ROI H3 construction before production map acceptance.
