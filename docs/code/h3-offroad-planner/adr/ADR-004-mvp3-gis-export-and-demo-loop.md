# ADR-004: MVP-3 Persisted Graph Loading and GIS Export

- **Status**: Accepted
- **Date**: 2026-07-08
- **Scope**: MVP-3 end-to-end single-vehicle demo

## Context

MVP-2 produces `outputs/nanjing_h3_sample.parquet`, but the file is a tabular H3
attribute cache, not a GIS-native layer. It has no geometry column or CRS metadata.
ArcGIS/QGIS workflows need vector layers for cells, edges, and planned paths.

The reference projects `hexgrid_xw` and `pp-project-py` both convert H3 cells to
polygons and paths to polylines for Shapefile/Leaflet display. Their approach is
useful, but their pickle/bin storage and dynamic cell fields are not compatible with
the current typed contract.

## Decision

MVP-3 will keep Parquet as the internal offline cache and add explicit read/export
boundaries:

- `H3GridBuilder.load_parquet(path)` reads and validates an H3 table.
- `H3GridBuilder.load_graph(path)` rebuilds an `H3Graph` using the builder's locked
  fine/coarse resolutions.
- `GISExporter.export_graph_gpkg(...)` writes `h3_cells` and `h3_edges` layers.
- `GISExporter.export_path_gpkg(...)` writes named path layers.
- `GISExporter.export_path_geojson(...)` writes path debug GeoJSON.
- `GISExporter.write_manifest(...)` writes the reproducibility manifest.
- `run_demo(...)` chooses an internal blockage cell only after confirming that
  removing that cell leaves the selected start and goal connected in the finite
  adjacency graph.

GeoPackage is the preferred GIS output because it preserves long field names and
multiple layers in one file. GeoJSON is retained for lightweight debug previews.
Shapefile is not the primary target because of field-name and encoding constraints.

The default Nanjing sample cache is generated with `sample_stride=60` and
`max_cells=5000`. The earlier sparse cache was valid for MVP-2 smoke testing, but
too fragmented for a blockage-and-replan demo.

## Consequences

- MVP-3 can run from the MVP-2 Parquet artifact without reprocessing large rasters.
- ArcGIS/QGIS can import the generated cell, edge, and path layers directly.
- The formal UI remains out of scope; optional HTML preview may be added later only
  after the core GIS export contract is stable.
- Full PortsMap/abstract road network generation remains a future batch. MVP-3 uses
  the existing full-graph A*/D* Lite-compatible interfaces.
- If a caller supplies an overly sparse Parquet cache with no alternate route,
  MVP-3 fails explicitly with `PlanningFailedError` rather than inventing a route.
