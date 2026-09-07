# ADR-012: MVP-6.1 Corrective Integrity Fixes

- **Status**: Accepted
- **Date**: 2026-07-10
- **Scope**: Correct current Phase0-MVP6 implementation defects before MVP-7

## Context

The MVP-6 code path passes the current test suite, but an external audit identified
several issues that are inside the existing Phase0-MVP6 contracts rather than new
MVP-7 features:

- Legacy Bekker soil sinkage mixes Pa pressure with kPa stiffness parameters.
- Vector landcover input is accepted by the API but currently ignored.
- Landcover factors and Bekker speed floor are hard-coded.
- Pentagon neighbor handling slices an unordered list and is unnecessarily fragile.

The audit also flagged simplified H3AStar PortsMap, D* Lite-compatible A* fallback,
formal UI absence, and full PBS branching. Those are known MVP simplifications and
remain outside this corrective batch.

## Decision

MVP-6.1 fixes the current-contract defects with backward-compatible changes:

- Preserve the existing public constructors while adding optional configuration knobs.
- Convert legacy Bekker pressure to kPa before applying legacy stiffness parameters.
- Attach vector landcover by intersecting H3 cell polygons with vector features and
  assigning the largest-overlap feature code.
- Replace pentagon neighbor truncation with deterministic sorting and exact count
  validation.

## Consequences

- Existing callers keep working with default behavior.
- Vector landcover files no longer silently degrade to neutral terrain.
- Legacy soil types can produce physically plausible pass/fail outcomes.
- Full PortsMap, true incremental D* Lite, full PBS constraint tree, and formal UI
  are explicitly left for later MVP batches.

