# ADR-017: Replace Remote Map Dependencies with a Local SVG Route Preview

- **Status**: Accepted
- **Date**: 2026-07-13
- **Author(s)**: Coordinator
- **Triggered by**: Backtrack Protocol in Phase 4
- **Supersedes**: The remote-map implementation detail in ADR-016

## Context

The MVP-8 console contract requires a loopback-only interface that renders returned
route coordinates without an external network, third-party map service, or credential.
The delivered page instead loaded Leaflet, remote fonts, public map tiles, and a
TianDiTu key. That made a valid local delivery dependent on the Internet and exposed a
credential in a bundled static asset. This contradicts FR-041 and NFR-019.

The affected scope is the static `web/index.html` asset and the missing black-box tests
for T-104 through T-106. The HTTP API and the existing GIS/planning workflow remain
unchanged.

## Decision

Replace all remote page dependencies with a self-contained HTML/CSS/JavaScript asset.
The page will render returned GeoJSON LineString coordinates in an inline SVG viewport,
including safe coordinate normalization and an empty-route message. It will retain the
existing `GET /` and `POST /api/run` interfaces, editable YAML input, and manifest
display. No map tile, font, script, or API-key URL may be present in the asset.

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Keep Leaflet and external tile providers | Violates the no-network/no-credential contract. |
| Vendor Leaflet and a basemap cache | Adds a large static dependency and still exceeds the simple route-preview requirement. |
| Use a native browser SVG | Meets the route-coordinate preview requirement with no new dependency. |

## Consequences

**Positive consequences:**

- A successful local delivery can be previewed offline after the browser has loaded the console.
- The static asset contains no external credentials or remote resource dependencies.
- T-104 through T-106 now exercise the documented browser boundary.

**Trade-offs:**

- The preview is a normalized route diagram, not a geographically referenced basemap.
- No interactive pan, zoom, or satellite imagery is provided in this MVP.

**Required follow-up actions:**

- [x] Re-run Gate 1 scoring with the refined local preview contract.
- [x] Update `api-design.md` and `test-specs.md` for the affected interface.
- [x] Confirm the component dependency graph remains unchanged.
- [x] Add spec-derived HTTP tests for the console.

## Gate 1 Re-Validation

- **Previous score**: $S_{design} = 1.00$
- **Updated score**: $S_{design} = 1.00$

| Function / Module | In Design? | Range? | Unit? | Exception? | Recovery? | Detail Score |
|---|---:|---:|---:|---:|---:|---:|
| `POST /api/run` | yes | yes | yes | yes | yes | 1.00 |
| `GET /` local SVG preview | yes | yes | yes | yes | yes | 1.00 |

```text
C_func = 2/2 = 1.00
C_detail = (1.00 + 1.00) / 2 = 1.00
C_decouple = 1.00 (static asset -> HTTP API -> existing CLI delivery DAG)

S_design = 0.4 * 1.00 + 0.3 * 1.00 + 0.3 * 1.00 = 1.00
```

Devil's-advocate review: the console has no implicit remote service dependency; HTTP
400 is an executable recovery for malformed input; the static client dependency graph
is acyclic; the 1 MiB request limit is a concrete bound; and the HTTP tests distinguish
a local asset from one that silently reintroduces remote resources. Gate 1 passes, so
Phase 3 implementation may resume.
