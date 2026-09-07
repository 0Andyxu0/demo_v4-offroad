# ADR-016: MVP-8 GIS Quality, Configurable Assessment, and Local Web Console

- **Status**: Accepted
- **Date**: 2026-07-10
- **Scope**: Operational GIS quality and user-facing local delivery controls

## Decision

- Add raster quality metadata for CRS, dimensions, nodata ratio, and finite-value range;
  reject DEM sources with no finite terrain values before terrain derivatives run.
- Let `TileBuildRequest` accept optional assessment vehicle YAML and trafficability
  weight overrides; write the effective profile into tile manifests.
- Add a standard-library local Web console that serves a bundled single-page interface,
  accepts a delivery YAML request, invokes the existing full delivery flow, and renders
  returned manifests plus the generated route GeoJSON.

## Constraints

- The console binds only to loopback by default and is not an authentication service.
- It composes existing tiling/routing APIs and does not import into domain modules.
- Formal multi-user WebGIS, remote job queueing, and live moisture feeds remain later work.
- Preserve the HTML/JSON API boundary so a later PyQt5 `QWebEngineView` desktop shell can
  embed the same console without duplicating GIS or planning logic.
