# ADR-005: MVP-3.1 Parameterized Route and Theme Map

- **Status**: Accepted
- **Date**: 2026-07-08
- **Scope**: MVP-3.1 user-controlled route planning and ArcGIS-friendly theme output

## Context

MVP-3 proves that a persisted H3 graph can be loaded, planned over, replanned after
a blockage, smoothed, and exported to GIS files. It still chooses start and goal
automatically and exports only generic graph/path layers.

The next delivery step needs user-selected start/goal inputs, route output, H3
trafficability maps that can be styled by attributes in ArcGIS, and stable score
fields for later NSGA-II objectives.

## Decision

MVP-3.1 adds a route-level public boundary:

- `RouteEndpoint` models start, goal/end, and optional blockage point inputs.
- `RouteRequest` models coordinate or point-layer route requests.
- `run_route(request)` loads an existing H3 Parquet cache, resolves endpoints,
  applies ROI filtering, snaps endpoints to passable cells, plans one route, and
  exports route and theme artifacts.
- `H3Cell` stores `landcover_code`, `landcover_type`, and `cost_score`.
- `CostFunction` accepts `score_coefficient`; the default is `0.0` for backward
  compatibility.
- `GISExporter.export_graph_gpkg(...)` accepts `theme_attributes` and an optional
  `style_manifest_path`.

The fine H3 resolution defaults to res13 for production requests. Source raster
resolution does not dynamically change H3 resolution; it only affects sampling and
performance estimates. The parent grid defaults to res10 and may be supplied as
res9 or res8. MVP-3.1 rejects oversized ROI estimates with actionable guidance
instead of asking interactively inside core library code.

## Consequences

- ArcGIS/QGIS can read route layers and attribute-driven H3 theme layers without
  ArcPy or proprietary style files.
- Existing MVP-3 callers remain valid because new cost/theme parameters have
  backward-compatible defaults.
- Full raw-GIS res13 tiled construction remains MVP-4. MVP-3.1 operates primarily
  on existing Parquet caches and introduces the estimation contract needed for
  later tiling.
