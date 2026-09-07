"""Explicit non-persisted online-map configuration for Client and backup Web UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

__all__ = [
    "MAP_PROVIDER_CONFIG",
    "TIANDITU_KEY",
    "TIANDITU_LAYER_TYPE",
    "TIANDITU_TOKEN_SOURCE",
    "MapProviderConfig",
    "load_map_provider_config",
]

MAP_CONFIG_ENV: str = "H3_OFFROAD_MAP_CONFIG"
TOKEN_ENV: str = "H3_OFFROAD_TIANDITU_TOKEN"
LAYER_ENV: str = "H3_OFFROAD_MAP_LAYER"
SUPPORTED_LAYERS: frozenset[str] = frozenset({"imagery", "vector"})
_DEFAULT_PRIVATE_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "map.private.yaml"
)


@dataclass(frozen=True)
class MapProviderConfig:
    """Runtime-only basemap settings that are never written to route artifacts."""

    provider: str = "tianditu"
    layer_type: str = "imagery"
    token: str = ""
    token_source: str = "unset"

    def __post_init__(self) -> None:
        if self.provider != "tianditu":
            raise ValueError("map provider must be 'tianditu'.")
        if self.layer_type not in SUPPORTED_LAYERS:
            raise ValueError(f"map layer_type must be one of {sorted(SUPPORTED_LAYERS)}.")
        if not isinstance(self.token, str):
            raise TypeError("map token must be a string.")
        if self.token_source not in {
            "unset",
            "environment",
            "local_config",
        }:
            raise ValueError("map token_source is invalid.")


def load_map_provider_config(path: str | None = None) -> MapProviderConfig:
    """Load optional private YAML, then allow a non-empty environment token to override it."""
    configured_path = _resolve_config_path(path)
    payload: dict[str, object] = {}
    if configured_path is not None:
        loaded = yaml.safe_load(configured_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("local map config must contain a YAML mapping.")
        payload = cast(dict[str, object], loaded)
        unknown = set(payload).difference({"provider", "layer_type", "token"})
        if unknown:
            raise ValueError(f"local map config has unsupported fields: {sorted(unknown)}")

    configured_token = payload.get("token", "")
    layer = os.environ.get(LAYER_ENV, payload.get("layer_type", "imagery"))
    provider = payload.get("provider", "tianditu")
    if (
        not isinstance(provider, str)
        or not isinstance(layer, str)
        or not isinstance(configured_token, str)
    ):
        raise ValueError("map provider, layer_type, and token must be strings.")

    environment_token = os.environ.get(TOKEN_ENV, "").strip()
    local_token = configured_token.strip()
    if environment_token:
        token = environment_token
        token_source = "environment"
    elif local_token:
        token = local_token
        token_source = "local_config"
    else:
        token = ""
        token_source = "unset"
    return MapProviderConfig(
        provider=provider,
        layer_type=layer,
        token=token,
        token_source=token_source,
    )


def _resolve_config_path(path: str | None) -> Path | None:
    if path is not None:
        return Path(path)
    environment_path = os.environ.get(MAP_CONFIG_ENV, "").strip()
    if environment_path:
        return Path(environment_path)
    if _DEFAULT_PRIVATE_CONFIG_PATH.is_file():
        return _DEFAULT_PRIVATE_CONFIG_PATH
    return None


MAP_PROVIDER_CONFIG: MapProviderConfig = load_map_provider_config()
TIANDITU_KEY: str = MAP_PROVIDER_CONFIG.token
TIANDITU_LAYER_TYPE: str = MAP_PROVIDER_CONFIG.layer_type
TIANDITU_TOKEN_SOURCE: str = MAP_PROVIDER_CONFIG.token_source
