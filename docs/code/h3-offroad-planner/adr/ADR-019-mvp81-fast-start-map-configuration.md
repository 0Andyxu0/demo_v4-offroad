# ADR-019: Use Static TianDiTu Configuration and Lazy Data Catalogs

- **Status**: Amended on 2026-07-27
- **Date**: 2026-07-13
- **Supersedes**: ADR-018 bootstrap-time key extraction and eager catalog scan.

## Context

> Current amendment: no tracked Python or public YAML contains a default token. Runtime
> selection is explicit path, `H3_OFFROAD_MAP_CONFIG`, ignored
> `configs/map.private.yaml`, then unset. A non-empty
> `H3_OFFROAD_TIANDITU_TOKEN` overrides the selected YAML. The original static-token
> decision below is historical.

The MVP-8.1 page delayed first map render by calling `/api/bootstrap`, which recursively
scanned all compatible files under the project and `hexgrid_xw` roots before creating a
base map. It also re-read an external `hexpp` Python source file to find a value that is
necessarily visible to the browser when TianDiTu WMTS is used.

## Decision

Use the user-authorized TianDiTu key as the single `TIANDITU_KEY` constant in the local
loopback adapter. Render the key and default YAML into the HTML response; the page can
therefore initialise the `img + cia` satellite base or the `vec + cva` vector base without
an initial API request. Keep file selection server-side and controlled, but expose it only
through `GET /api/data-catalog?kind=<kind>` after the user selects a supported kind. Cache
each bounded catalog list for the lifetime of the process.

## Consequences

- First render does not recursively scan external data roots.
- The configured key is deliberately present in browser-delivered HTML, as required by
  TianDiTu client WMTS. Provider-side quota/source restrictions remain the key control.
- New files are discovered after restarting the loopback server; arbitrary browser paths
  and upload remain out of scope.

## Gate 1 Re-Validation

| Function / Module | In Design? | Range? | Unit? | Exception? | Recovery? | Detail Score |
|---|---:|---:|---:|---:|---:|---:|
| HTML runtime-config renderer | yes | yes | n/a | yes | yes | 1.00 |
| Lazy controlled catalog | yes | yes | n/a | yes | yes | 1.00 |
| TianDiTu layer setup | yes | yes | zoom 1-18 | yes | yes | 1.00 |

`C_func=1.00`, `C_detail=1.00`, `C_decouple=1.00`; therefore
`S_design=1.00 >= 0.95`. The web adapter continues to depend only on existing domain APIs.
