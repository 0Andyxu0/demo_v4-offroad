# ADR-018: Add TianDiTu WebGIS Controls to MVP-8

- **Status**: Accepted
- **Date**: 2026-07-13
- **Triggered by**: Backtrack Protocol in Phase 1
- **Supersedes**: The offline-only rendering decision in ADR-017

## Context

MVP-8 must now use the validated TianDiTu Leaflet controls from `D:\Workspace\hexpp`,
allow map-drawn study areas and endpoints, and expose the existing GIS/planning workflow
as grouped WebGIS operations. The prior self-contained SVG preview cannot satisfy these
interactive map requirements.

## Decision

Keep the domain GIS, routing, NSGA-II, and D* Lite modules intact. Add only optional
progress callbacks and a Web console adapter that streams NDJSON events, writes
validated map selections under `outputs/web_sessions`, and serializes existing tile and
route artifacts as parent/fine H3 GeoJSON. Obtain the TianDiTu key at runtime from the
`hexpp` source, with `TIANDITU_API_KEY` as an override; do not duplicate it in this
repository.

## Consequences

- Leaflet, Leaflet.draw, and TianDiTu WMTS require network access in the browser.
- Data choices are restricted to configured project roots; browser file upload and
  arbitrary filesystem paths remain out of scope.
- The existing synchronous `/api/run` endpoint remains compatible; `/api/run-stream`
  adds progress output without introducing a job database.

## Gate 1 Re-Validation

| Function / Module | In Design? | Range? | Unit? | Exception? | Recovery? | Detail Score |
|---|---:|---:|---:|---:|---:|---:|
| Web bootstrap/catalog | yes | yes | yes | yes | yes | 1.00 |
| NDJSON operation stream | yes | yes | yes | yes | yes | 1.00 |
| Map selection adapter | yes | yes | yes | yes | yes | 1.00 |
| H3 visualization/evaluation | yes | yes | yes | yes | yes | 1.00 |

`C_func=1.00`, `C_detail=1.00`, and `C_decouple=1.00`; therefore
`S_design=1.00 >= 0.95`. The Web adapter depends on existing domain APIs only, so the
core component DAG remains acyclic.
