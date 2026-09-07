# ADR-001: Use Python H3/GIS Stack for the Single-Vehicle Demo

- **Status**: Accepted
- **Date**: 2026-07-07
- **Author(s)**: Codex coordinator
- **Triggered by**: Phase 0 tech stack selection
- **Supersedes**: None

## Context

The project needs a validated MVP for off-road path planning over GIS-derived H3 graphs. The current scope is a single-vehicle Demo, not a full multi-vehicle fleet system.

## Decision

Use Python 3.11+ with rasterio, geopandas, shapely, h3/h3ronpy, pandas, pyarrow, pytest, ruff, and mypy. Keep NSGA-II, PBS, and formal UI out of MVP-1.

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| C++ first | Higher GIS integration cost for the initial validated loop |
| Java first | Less direct fit for the existing Python-oriented GIS/H3 plan |
| GUI first | Does not reduce algorithmic risk |
| Fleet coordination first | Violates MVP scope and overcomplicates the first validation |

## Consequences

Positive:

- Faster MVP validation.
- Strong GIS/H3 library support.
- Easy pytest-based verification.

Negative:

- Large Res 13 datasets may need later optimization.
- Native GIS dependency installation may need environment care.

Required follow-up actions:

- [ ] Pin dependencies in `pyproject.toml`.
- [ ] Load Python style convention before Phase 3.
- [ ] Run ruff, mypy, pytest-cov in Phase 4.

