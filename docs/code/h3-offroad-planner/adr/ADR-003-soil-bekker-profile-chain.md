# ADR-003: Use SoilProfile Chain for Bekker Assessment

- **Status**: Accepted
- **Date**: 2026-07-08
- **Author(s)**: Codex coordinator
- **Triggered by**: Backtrack Protocol in Phase 3
- **Supersedes**: None

## Context

MVP-2 attached `soil_nanjing.tif` values as string codes only. That was enough to
prove real raster ingestion, but it did not satisfy the intended Bekker modeling
chain. The reference project `D:\Workspace\hexgrid_map\hexgrid_xw` models soil as:

`soil raster code -> soil type/texture -> USCS -> CI/RCI -> Bekker parameters -> sinkage and mobility`.

The Nanjing raster attribute table is available as
`D:\Download\geosptial\Export_Output.txt` and maps raster codes to Chinese soil
subclass names. Therefore the design must explicitly carry soil metadata instead of
using raw string codes.

## Decision

Introduce `SoilProfile` as the soil catalog record. Each sampled H3 cell may carry:

- soil raster code
- Chinese soil type name
- soil texture class
- USCS class
- volumetric soil moisture
- cone index
- Bekker sinkage
- sinkage resistance
- normalized soil mobility

`GISPreprocessor.load_soil_catalog()` parses `Export_Output.txt` into
`dict[int, SoilProfile]`. `H3GridBuilder.attach_soil()` accepts that catalog and
uses an area-dominance method for small rasters and a center-sampling fallback for
large rasters. `BekkerChecker` computes CI, Bekker parameters, sinkage, and soil
mobility from these fields during offline assessment.

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Keep raw soil codes only | Cannot perform Bekker or CI assessment |
| Direct Chinese soil type -> Bekker parameter mapping | Skips the USCS/texture intermediate model used by the reference implementation |
| Require live weather soil moisture | Adds network dependency and makes MVP-2.1 tests non-deterministic |

## Consequences

Positive:

- Real Nanjing soil data now participates in trafficability assessment.
- Bekker behavior is traceable to explicit soil profile fields.
- Future Open-Meteo/CLDAS soil moisture can replace the configurable default without planner changes.

Negative:

- Default profile mapping remains a conservative engineering approximation.
- Area-dominance soil assignment is more expensive than center sampling and must remain bounded.

Required follow-up actions:

- [x] Update Phase 1 API design and test specs.
- [x] Re-run Gate 1 scoring after the ADR update.
- [ ] In a later MVP, replace default soil moisture with dated meteorological input.
