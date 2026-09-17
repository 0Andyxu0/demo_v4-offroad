"""Pure helpers for precipitation-based environment pressure fallback.

This module is intentionally independent of :mod:`environment` so it can be
tested and reused once the main request environment resolver is updated.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

__all__ = ["precipitation_pressure", "resolve_precipitation_fallback"]


def precipitation_pressure(precipitation_24h_mm: float, api_reference_mm: float) -> float:
    """Map 24h precipitation to a bounded [0, 1] pressure proxy."""
    if not isfinite(precipitation_24h_mm) or precipitation_24h_mm < 0.0:
        raise ValueError("precipitation_24h_mm must be finite and non-negative.")
    if not isfinite(api_reference_mm) or api_reference_mm <= 0.0:
        raise ValueError("api_reference_mm must be finite and positive.")
    return min(1.0, precipitation_24h_mm / api_reference_mm)


def resolve_precipitation_fallback(
    snapshot: Mapping[str, object],
    api_reference_mm: float | None,
) -> tuple[float | None, str | None, tuple[str, ...]]:
    """Resolve a provisional pressure from precipitation when moisture is absent.

    Returns ``(pressure, pressure_basis, warnings)``.
    """
    if snapshot.get("degraded") is True:
        return None, None, ("ENVIRONMENT_DATA_DEGRADED",)
    if api_reference_mm is None:
        return None, None, ("ENVIRONMENT_PRESSURE_UNCALIBRATED",)
    precipitation = snapshot.get("precipitation_24h_mm")
    if not isinstance(precipitation, (int, float)) or isinstance(precipitation, bool):
        return None, None, ("ENVIRONMENT_PRESSURE_UNCALIBRATED",)
    try:
        pressure = precipitation_pressure(float(precipitation), api_reference_mm)
    except ValueError:
        return None, None, ("ENVIRONMENT_PRESSURE_UNCALIBRATED",)
    return pressure, "precipitation_apiv1", ("ENVIRONMENT_PRESSURE_PRECIPITATION_PROVISIONAL",)
