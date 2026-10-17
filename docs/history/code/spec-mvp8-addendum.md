# MVP-8.1 Requirements Addendum

- **Status**: Historical; current requirements are defined in `spec.md`
- **Scope**: GIS quality, configurable trafficability, TianDiTu WebGIS console
- **Decision ADR**: `ADR-018-mvp81-tianditu-webgis-console.md`

## Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-038 | Inspect raster quality | `GISPreprocessor.inspect_raster` returns CRS, dimensions, nodata ratio, finite range, and rejects unreadable or terrain-empty rasters. |
| FR-039 | Configure tile assessment | `TileBuildRequest` accepts assessment vehicle YAML and allowed weight overrides; the tile manifest records effective values. |
| FR-040 | Run local Web console | Loopback server retains the compatible JSON delivery endpoint and provides an NDJSON stream for build, plan, replan, and combined operations. |
| FR-041 | TianDiTu map controls | Web console renders the authorized TianDiTu key and default YAML into the initial page, then uses Leaflet/Leaflet.draw to switch `img+cia` and `vec+cva` layers, draw one Polygon/MultiPolygon study area, and select start/goal points. |
| FR-042 | Controlled data input | Users can load default YAML or choose compatible raw GIS/config paths from the project and `hexgrid_xw` catalogs. |
| FR-043 | Grouped workflows | Left navigation separates data input, trafficability-map build, global/preplan plus dynamic replan, and evaluation/display. |
| FR-044 | Visible progress | Frontend shows current module and percent; the backend console displays streamed INFO/WARN/ERROR events and terminal results. |
| FR-045 | H3 map display | Completed tile caches render fine and parent H3 GeoJSON layers on the TianDiTu map. |
| FR-046 | Attribute visualization | Users select supported numeric/categorical fields for thematic coloring and see H3 score, landcover, slope, soil, and related attributes on hover. |
| FR-047 | NSGA-II selection and replan | Web results expose Pareto candidates; a user selects one and may mark fine H3 cells blocked for D* Lite replan. |
| FR-048 | Route evaluation | Route hover reports quality, candidate labels, landcover distance share, minimum turn radius, total distance, and score-corrected travel time. |
| FR-049 | Fast first render | The initial HTML must initialise the TianDiTu map without a catalog/bootstrap fetch; compatible data files are listed only after a user selects a data kind. |
| FR-050 | Desktop main interface | The default user interface is a PyQt5 client: native file dialogs update YAML data paths, QWebEngine hosts the TianDiTu map, and the prior Web console remains an optional backup. |
| FR-051 | Responsive desktop execution | Tile building, route planning, and re-planning run outside the Qt GUI thread and stream module progress, warnings, errors, and results back to the visible client panes. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| NFR-018 | GIS safety | DEM with zero finite cells is rejected; nodata ratio remains visible in build output. |
| NFR-019 | Loopback service | Default bind address is `127.0.0.1`; browser network access is limited to Leaflet assets and TianDiTu WMTS using the authorized configured key. |
| NFR-022 | Startup responsiveness | No recursive `hexgrid_xw` scan may occur while serving `GET /`; per-kind catalogs are bounded and cached for the server lifetime. |
| NFR-023 | GUI thread safety | Worker threads must never mutate Qt widgets directly; only Qt signals may carry status/result data to the GUI thread. |
| NFR-020 | Backward compatibility | Existing tile and CLI requests work without new assessment fields. |
| NFR-021 | Temporary bounded visualization | Web and desktop map payloads temporarily contain at most 500,000 fine cells; this is a display-only guard, not an H3-build or route-planning limit. Oversized requests return a resolution-reduction error until viewport/LOD loading replaces full-grid serialization. |
