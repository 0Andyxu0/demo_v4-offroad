# ADR-020: Promote a PyQt5 Desktop Client to the Main Interface

- **Status**: Amended on 2026-07-27
- **Date**: 2026-07-13
- **Supersedes**: Browser console as the primary MVP-8.1 user interface.

## Context

> Current amendment: the desktop remains the primary UI, but production operations run
> through `Thread -> background runner -> SimpleQueue -> QTimer -> UI`.
> `DesktopOperationWorker` remains only as a Legacy Qt compatibility shim. The original
> worker decision below is historical and does not define current scheduling.

The project runs local, compute-heavy GIS workflows against user-selected raster and
vector files. A browser console added HTTP/NDJSON/GeoJSON transport and a separate
filesystem catalog before users could invoke the same Python operations. `hexpp` already
validates the desktop interaction pattern of `PyQt5 + QWebEngineView + Leaflet` and the
authorized TianDiTu layer composition.

## Decision

Add `h3_offroad_planner.desktop_client:run_desktop_client` as the primary UI entry point.
The desktop shell uses native `QFileDialog` buttons to update the existing YAML request,
executes `run_tile_payload`, `run_route_payload`, or `run_delivery_payload` in a `QThread`,
and receives progress, warnings/errors, and output through Qt signals. A `QWebEngineView`
uses Leaflet with the explicit TianDiTu `img+cia` and `vec+cva` layers. Map events use
document-title signals to deliver Polygon, start/goal, and fine-H3 blockage selections to
the shell. The existing Web console remains unchanged as a backup/debug interface.

## Consequences

- The domain tiling/routing implementations are not moved or duplicated.
- Heavy work no longer blocks Qt's GUI event loop; all UI mutation stays on its main thread.
- `PyQt5` and `PyQtWebEngine` are optional desktop dependencies and carry their respective
  licensing/deployment requirements.
- The QWebEngine map still needs network access for Leaflet assets and TianDiTu tiles.

## Gate 1 Re-Validation

| Function / Module | In Design? | Range? | Unit? | Exception? | Recovery? | Detail Score |
|---|---:|---:|---:|---:|---:|---:|
| Native file selection/YAML update | yes | yes | path | yes | yes | 1.00 |
| Background delivery worker | yes | progress 0-100 | percent | yes | yes | 1.00 |
| Desktop map event bridge | yes | WGS84/H3 | degrees | yes | yes | 1.00 |
| Artifact display bridge | yes | max 50,000 features | count | yes | yes | 1.00 |

`C_func=1.00`, `C_detail=1.00`, `C_decouple=1.00`; therefore
`S_design=1.00 >= 0.95`. The dependency direction is `desktop_client -> cli/web serializer
-> existing domain modules`, with no domain import of PyQt.
