# ADR-014: MVP-7.1 GIS-to-Route Delivery CLI

- **Status**: Accepted
- **Date**: 2026-07-10
- **Scope**: Basic command-line delivery workflow

## Context

Raw GIS tile construction and route output already have stable Python APIs, but users
must currently choose and connect several demonstration scripts themselves. That is not
a minimal operational delivery path.

## Decision

- Add `h3-offroad-planner` and `python -m h3_offroad_planner` command-line entry points.
- Accept YAML mappings for `build-tiles`, `plan`, and combined `run` commands.
- `run` constructs the tile cache first, injects its generated `tile_manifest.json` into
  the route request, then writes the existing route GeoPackage, GeoJSON, style manifest,
  and route manifest.
- Return JSON manifests to stdout and return exit code 2 with a clear stderr error for
  expected request, GIS, build, or planning failures.

## Consequences

- The CLI adds an outer composition layer only; it does not duplicate GIS, routing, or
  export logic and introduces no reverse dependency.
- Production runs remain bounded by `TileBuildRequest` and `RouteRequest` limits.
- Formal GUI/WebGIS and long-running scheduler/resume orchestration remain later work.
