"""Request-scoped Open-Meteo snapshot with bounded in-process caching."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from math import isfinite
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from h3_offroad_planner.factor_model import (
    EnvironmentConfig,
    WeatherConfig,
    canonical_hash,
)
from h3_offroad_planner.weather_fallback import resolve_precipitation_fallback

__all__ = [
    "EnvironmentSnapshot",
    "OpenMeteoProvider",
    "resolve_request_environment",
    "load_environment_snapshot",
]


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Validated point-in-time forcing used by one planning request."""

    provider: str
    model: str
    requested_at: str
    valid_at: str | None
    latitude: float
    longitude: float
    precipitation_24h_mm: float | None
    soil_moisture_surface_m3_m3: float | None
    et0_24h_mm: float | None
    age_s: float | None
    degraded: bool
    degradation_reason: str | None = None
    cache_hit: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "requested_at": self.requested_at,
            "valid_at": self.valid_at,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "spatial_support": "route_endpoint_centroid",
            "spatial_support_km": None,
            "precipitation_24h_mm": self.precipitation_24h_mm,
            "soil_moisture_surface_m3_m3": self.soil_moisture_surface_m3_m3,
            "soil_moisture_support_cm": "0-5_estimated_from_0-1_1-3_3-9",
            "et0_24h_mm": self.et0_24h_mm,
            "age_s": self.age_s,
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    snapshot: EnvironmentSnapshot


class OpenMeteoProvider:
    """Fetch one centroid snapshot; never performs I/O during graph search."""

    def __init__(
        self,
        config: WeatherConfig,
        *,
        opener: Callable[..., Any] = urlopen,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._config = config
        self._opener = opener
        self._now = now
        self._clock = clock
        self._cache: dict[tuple[float, float], _CacheEntry] = {}
        self._lock = Lock()

    def fetch(self, latitude: float, longitude: float) -> EnvironmentSnapshot:
        key = (round(latitude, 5), round(longitude, 5))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.expires_at > self._clock():
                return replace(cached.snapshot, cache_hit=True)
        requested_at = self._now()
        try:
            snapshot = self._request(latitude, longitude, requested_at)
            ttl = self._config.ttl_s
        except Exception as exc:  # Network and schema failures share a safe degradation path.
            snapshot = EnvironmentSnapshot(
                provider=self._config.provider,
                model=self._config.model,
                requested_at=requested_at.isoformat(),
                valid_at=None,
                latitude=latitude,
                longitude=longitude,
                precipitation_24h_mm=None,
                soil_moisture_surface_m3_m3=None,
                et0_24h_mm=None,
                age_s=None,
                degraded=True,
                degradation_reason=f"{type(exc).__name__}: {exc}",
            )
            ttl = self._config.failure_ttl_s
        with self._lock:
            self._cache[key] = _CacheEntry(self._clock() + ttl, snapshot)
        return snapshot

    def _request(
        self,
        latitude: float,
        longitude: float,
        requested_at: datetime,
    ) -> EnvironmentSnapshot:
        query = urlencode(
            {
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "hourly": (
                    "precipitation,soil_moisture_0_to_1cm,"
                    "soil_moisture_1_to_3cm,soil_moisture_3_to_9cm,"
                    "et0_fao_evapotranspiration"
                ),
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "UTC",
                "models": self._config.model,
            }
        )
        payload = self._load_with_deadline(f"{self._config.endpoint}?{query}")
        if not isinstance(payload, dict):
            raise ValueError("weather response must be a JSON object")
        return _snapshot_from_payload(
            cast(dict[str, object], payload),
            self._config,
            latitude,
            longitude,
            requested_at,
        )

    def _load_with_deadline(self, url: str) -> object:
        """Apply one wall-clock deadline around DNS, TLS, read, and JSON decode."""
        results: Queue[object] = Queue(maxsize=1)

        def load() -> None:
            try:
                with self._opener(url, timeout=self._config.timeout_s) as response:
                    results.put(json.load(response))
            except Exception as exc:
                results.put(exc)

        Thread(target=load, daemon=True, name="open-meteo-request").start()
        try:
            result = results.get(timeout=self._config.timeout_s)
        except Empty as exc:
            raise TimeoutError(
                f"weather request exceeded {self._config.timeout_s:g}s deadline"
            ) from exc
        if isinstance(result, Exception):
            raise result
        return result


@lru_cache(maxsize=8)
def _provider(config: WeatherConfig) -> OpenMeteoProvider:
    return OpenMeteoProvider(config)


def resolve_request_environment(
    environment: EnvironmentConfig,
    weather: WeatherConfig,
    latitude: float,
    longitude: float,
    replay_path: str | None = None,
) -> tuple[EnvironmentConfig, dict[str, object], str, tuple[str, ...]]:
    """Resolve one request pressure, preserving synthetic policy when evidence is unusable."""
    if not weather.enabled and replay_path is None:
        return environment, {}, "", ()
    snapshot = (
        load_environment_snapshot(replay_path, weather, latitude, longitude)
        if replay_path is not None
        else _provider(weather).fetch(latitude, longitude)
    )
    payload = snapshot.to_dict()
    payload["calibration_status"] = weather.calibration_status
    warnings: list[str] = []
    if snapshot.degraded:
        warnings.append("ENVIRONMENT_DATA_DEGRADED")
    moisture = snapshot.soil_moisture_surface_m3_m3
    if (
        not snapshot.degraded
        and moisture is not None
        and weather.theta_dry is not None
        and weather.theta_wet is not None
    ):
        pressure = min(
            1.0,
            max(0.0, (moisture - weather.theta_dry) / (weather.theta_wet - weather.theta_dry)),
        )
        pressure = round(pressure, 6)
        payload["derived_pressure"] = pressure
        environment = replace(
            environment,
            pressure_basis="model_snapshot_v1",
            comparison_pressures=tuple(
                sorted({*environment.comparison_pressures, pressure})
            ),
            request_pressures=(pressure,),
        )
        if weather.calibration_status == "provisional_cldas_spatial_20260101":
            warnings.append("ENVIRONMENT_PRESSURE_PROVISIONAL")
    else:
        fallback_pressure, basis, precip_warnings = resolve_precipitation_fallback(
            snapshot.to_dict(), weather.api_reference_mm
        )
        warnings.extend(precip_warnings)
        if fallback_pressure is not None and basis is not None:
            payload["derived_pressure"] = fallback_pressure
            environment = replace(
                environment,
                pressure_basis=basis,
                comparison_pressures=tuple(
                    sorted({*environment.comparison_pressures, fallback_pressure})
                ),
                request_pressures=(fallback_pressure,),
            )
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"requested_at", "cache_hit", "age_s"}
    }
    return environment, payload, canonical_hash(identity), tuple(warnings)


def load_environment_snapshot(
    path: str,
    config: WeatherConfig,
    latitude: float,
    longitude: float,
) -> EnvironmentSnapshot:
    """Replay a persisted RoutePlan snapshot without contacting the provider."""
    with Path(path).open("r", encoding="utf-8") as stream:
        source = json.load(stream)
    if not isinstance(source, dict):
        raise ValueError("environment replay source must be a JSON object")
    if "aggregation_stats" in source:
        source = _mapping(_mapping(source, "aggregation_stats"), "environment_snapshot")
    if source.get("provider") != config.provider or source.get("model") != config.model:
        raise ValueError("environment replay provider/model mismatch")
    for key, expected in (("latitude", latitude), ("longitude", longitude)):
        value = source.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"environment replay {key} must be numeric")
        if abs(float(value) - expected) > 1e-5:
            raise ValueError(f"environment replay {key} does not match route centroid")
    for key in ("requested_at", "valid_at"):
        value = source.get(key)
        if key == "valid_at" and value is None:
            continue
        _parse_utc_time(value)
    for key, maximum in (
        ("soil_moisture_surface_m3_m3", 1.0),
        ("precipitation_24h_mm", None),
        ("et0_24h_mm", None),
        ("age_s", None),
    ):
        value = source.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or float(value) < 0.0
            or (maximum is not None and float(value) > maximum)
        ):
            raise ValueError(f"environment replay {key} is invalid")
    degraded = source.get("degraded")
    if not isinstance(degraded, bool):
        raise ValueError("environment replay degraded must be boolean")
    if not degraded and (
        source.get("valid_at") is None
        or source.get("soil_moisture_surface_m3_m3") is None
    ):
        raise ValueError("environment replay valid snapshot is incomplete")
    reason = source.get("degradation_reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("environment replay degradation_reason must be a string or null")
    return EnvironmentSnapshot(
        provider=config.provider,
        model=config.model,
        requested_at=cast(str, source["requested_at"]),
        valid_at=cast(str | None, source.get("valid_at")),
        latitude=latitude,
        longitude=longitude,
        precipitation_24h_mm=_optional_numeric(source, "precipitation_24h_mm"),
        soil_moisture_surface_m3_m3=_optional_numeric(
            source, "soil_moisture_surface_m3_m3"
        ),
        et0_24h_mm=_optional_numeric(source, "et0_24h_mm"),
        age_s=_optional_numeric(source, "age_s"),
        degraded=degraded,
        degradation_reason=cast(str | None, reason),
        cache_hit=source.get("cache_hit") is True,
    )


def _optional_numeric(source: Mapping[str, object], key: str) -> float | None:
    value = source.get(key)
    return None if value is None else float(cast(float, value))


def _snapshot_from_payload(
    payload: Mapping[str, object],
    config: WeatherConfig,
    latitude: float,
    longitude: float,
    requested_at: datetime,
) -> EnvironmentSnapshot:
    hourly = _mapping(payload, "hourly")
    units = _mapping(payload, "hourly_units")
    _require_unit(units, "precipitation", {"mm"})
    _require_unit(units, "soil_moisture_0_to_1cm", {"m³/m³", "m3/m3"})
    _require_unit(units, "soil_moisture_1_to_3cm", {"m³/m³", "m3/m3"})
    _require_unit(units, "soil_moisture_3_to_9cm", {"m³/m³", "m3/m3"})
    _require_unit(units, "et0_fao_evapotranspiration", {"mm"})
    raw_times = _sequence(hourly, "time")
    times = tuple(_parse_utc_time(value) for value in raw_times)
    if not times:
        raise ValueError("weather response contains no hourly timestamps")
    eligible = [index for index, value in enumerate(times) if value <= requested_at]
    if not eligible:
        raise ValueError("weather response has no observation valid at request time")
    latest = eligible[-1]
    valid_at = times[latest]
    age_s = (requested_at - valid_at).total_seconds()
    if age_s < 0.0 or age_s > config.max_age_s:
        raise ValueError(f"weather snapshot age {age_s:.0f}s exceeds max_age_s")
    precipitation = _numeric_sequence(hourly, "precipitation", len(times), minimum=0.0)
    moisture = _numeric_sequence(
        hourly, "soil_moisture_0_to_1cm", len(times), minimum=0.0, maximum=1.0
    )
    moisture_1_to_3 = _numeric_sequence(
        hourly, "soil_moisture_1_to_3cm", len(times), minimum=0.0, maximum=1.0
    )
    moisture_3_to_9 = _numeric_sequence(
        hourly, "soil_moisture_3_to_9cm", len(times), minimum=0.0, maximum=1.0
    )
    et0 = _numeric_sequence(
        hourly, "et0_fao_evapotranspiration", len(times), minimum=0.0
    )
    window_start = requested_at - timedelta(hours=24)
    window = [index for index in eligible if times[index] > window_start]
    if not window:
        raise ValueError("weather response has no values in the preceding 24 hours")
    return EnvironmentSnapshot(
        provider=config.provider,
        model=config.model,
        requested_at=requested_at.isoformat(),
        valid_at=valid_at.isoformat(),
        latitude=latitude,
        longitude=longitude,
        precipitation_24h_mm=round(sum(precipitation[index] for index in window), 6),
        soil_moisture_surface_m3_m3=round(
            (moisture[latest] + 2 * moisture_1_to_3[latest] + 2 * moisture_3_to_9[latest])
            / 5,
            6,
        ),
        et0_24h_mm=round(sum(et0[index] for index in window), 6),
        age_s=round(age_s, 3),
        degraded=False,
    )


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"weather response field {key!r} must be an object")
    return cast(dict[str, object], value)


def _sequence(payload: Mapping[str, object], key: str) -> tuple[object, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"weather response field {key!r} must be an array")
    return tuple(value)


def _numeric_sequence(
    payload: Mapping[str, object],
    key: str,
    expected_length: int,
    *,
    minimum: float,
    maximum: float | None = None,
) -> tuple[float, ...]:
    values = _sequence(payload, key)
    if len(values) != expected_length:
        raise ValueError(f"weather response field {key!r} has inconsistent length")
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"weather response field {key!r} must be numeric")
        numeric = float(value)
        if not isfinite(numeric) or numeric < minimum or (
            maximum is not None and numeric > maximum
        ):
            raise ValueError(f"weather response field {key!r} is out of range")
        result.append(numeric)
    return tuple(result)


def _parse_utc_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("weather timestamps must be strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _require_unit(
    units: Mapping[str, object], key: str, expected: set[str]
) -> None:
    value = units.get(key)
    if value not in expected:
        raise ValueError(f"weather response unit for {key!r} is unsupported: {value!r}")
