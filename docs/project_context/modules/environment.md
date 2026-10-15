# 模块参考：environment

按需附件；不要默认和所有模块一起上传。先读 `PROJECT_HOLOGRAM.md`，按 `INDEX.md` 选择主题。

- 来源：`src/h3_offroad_planner/environment.py`；扫描日期：2026-10-14；HEAD：`986bd58eef846f6f8a34961a43b208c315471110`。
- 源码 SHA-256：`172602724ac3eea6bd5dd69aaf7e232d7bb7b1fd08c5aed77651fa70d5c234b3`；类 3 个，函数/方法 16 个（含嵌套定义）。
- 项目内导入依赖：`factor_model`, `weather_fallback`。
- 直接导入本模块者：`route_planning`。
- 这是静态 import 邻接关系，不保证调用图完备；包 re-export、回调和动态分派需要结合源码。

## 数据结构与存储契约

字段/默认值/别名、显式 Schema、字典键表达式和部分校验条件来自 AST。`未注解` 不补造类型；`字段 => 表达式` 是源码证据，不是所有字段必填的 JSON Schema。条件分支、动态键和浅冻结须按原语义理解。`L` 数字是上述源文件的行号。

```python
# EnvironmentSnapshot — src/h3_offroad_planner/environment.py:35
@dataclass(frozen=True)
class EnvironmentSnapshot:
    'Validated point-in-time forcing used by one planning request.'
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
    ...

# _CacheEntry — src/h3_offroad_planner/environment.py:74
@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    snapshot: EnvironmentSnapshot
    ...

# OpenMeteoProvider — src/h3_offroad_planner/environment.py:79
class OpenMeteoProvider:
    'Fetch one centroid snapshot; never performs I/O during graph search.'
    # self._config: 未注解; L90; initial=config
    # self._opener: 未注解; L91; initial=opener
    # self._now: 未注解; L92; initial=now
    # self._clock: 未注解; L93; initial=clock
    _cache: dict[tuple[float, float], _CacheEntry]  # instance; L94; initial={}
    # self._lock: 未注解; L95; initial=Lock()
    ...
```

```text
# L53 EnvironmentSnapshot.to_dict
'provider' => self.provider
'model' => self.model
'requested_at' => self.requested_at
'valid_at' => self.valid_at
'latitude' => self.latitude
'longitude' => self.longitude
'spatial_support' => 'route_endpoint_centroid'
'spatial_support_km' => None
'precipitation_24h_mm' => self.precipitation_24h_mm
'soil_moisture_surface_m3_m3' => self.soil_moisture_surface_m3_m3
'soil_moisture_support_cm' => '0-5_estimated_from_0-1_1-3_3-9'
'et0_24h_mm' => self.et0_24h_mm
'age_s' => self.age_s
'degraded' => self.degraded
'degradation_reason' => self.degradation_reason
'cache_hit' => self.cache_hit

# L134 OpenMeteoProvider._request
'latitude' => f'{latitude:.6f}'
'longitude' => f'{longitude:.6f}'
'hourly' => 'precipitation,soil_moisture_0_to_1cm,soil_moisture_1_to_3cm,soil_moisture_3_to_9cm,et0_fao_evapotranspiration'
'past_days' => 1
'forecast_days' => 1
'timezone' => 'UTC'
'models' => self._config.model
```

```text
L203: payload['calibration_status'] <- weather.calibration_status
L219: payload['derived_pressure'] <- pressure
L238: payload['derived_pressure'] <- fallback_pressure
```

## 接口签名与原始 Docstring

保留参数、类型、默认值、返回值、decorator 和原始 Docstring；函数体均为 `...`。嵌套函数单列词法作用域。Docstring 可能落后于实现，不能用它证明算法性质；需要推导实现时，请求源代码而非继续猜测。

```python
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
from h3_offroad_planner.factor_model import EnvironmentConfig, WeatherConfig, canonical_hash
from h3_offroad_planner.weather_fallback import resolve_precipitation_fallback

# EnvironmentSnapshot — L35
@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Validated point-in-time forcing used by one planning request."""

    def to_dict(self) -> dict[str, object]:
        ...

# _CacheEntry — L74
@dataclass(frozen=True)
class _CacheEntry:
    ...

# OpenMeteoProvider — L79
class OpenMeteoProvider:
    """Fetch one centroid snapshot; never performs I/O during graph search."""

    def __init__(self, config: WeatherConfig, *, opener: Callable[..., Any]=urlopen, now: Callable[[], datetime]=lambda: datetime.now(UTC), clock: Callable[[], float]=monotonic) -> None:
        ...

    def fetch(self, latitude: float, longitude: float) -> EnvironmentSnapshot:
        ...

    def _request(self, latitude: float, longitude: float, requested_at: datetime) -> EnvironmentSnapshot:
        ...

    def _load_with_deadline(self, url: str) -> object:
        """Apply one wall-clock deadline around DNS, TLS, read, and JSON decode."""
        ...

# OpenMeteoProvider._load_with_deadline.load — L163
def load() -> None:
    ...

# _provider — L183
@lru_cache(maxsize=8)
def _provider(config: WeatherConfig) -> OpenMeteoProvider:
    ...

# resolve_request_environment — L187
def resolve_request_environment(environment: EnvironmentConfig, weather: WeatherConfig, latitude: float, longitude: float, replay_path: str | None=None) -> tuple[EnvironmentConfig, dict[str, object], str, tuple[str, ...]]:
    """Resolve one request pressure, preserving synthetic policy when evidence is unusable."""
    ...

# load_environment_snapshot — L255
def load_environment_snapshot(path: str, config: WeatherConfig, latitude: float, longitude: float) -> EnvironmentSnapshot:
    """Replay a persisted RoutePlan snapshot without contacting the provider."""
    ...

# _optional_numeric — L326
def _optional_numeric(source: Mapping[str, object], key: str) -> float | None:
    ...

# _snapshot_from_payload — L331
def _snapshot_from_payload(payload: Mapping[str, object], config: WeatherConfig, latitude: float, longitude: float, requested_at: datetime) -> EnvironmentSnapshot:
    ...

# _mapping — L393
def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    ...

# _sequence — L400
def _sequence(payload: Mapping[str, object], key: str) -> tuple[object, ...]:
    ...

# _numeric_sequence — L407
def _numeric_sequence(payload: Mapping[str, object], key: str, expected_length: int, *, minimum: float, maximum: float | None=None) -> tuple[float, ...]:
    ...

# _parse_utc_time — L431
def _parse_utc_time(value: object) -> datetime:
    ...

# _require_unit — L440
def _require_unit(units: Mapping[str, object], key: str, expected: set[str]) -> None:
    ...
```
