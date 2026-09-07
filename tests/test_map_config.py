"""Online basemap configuration remains explicit and outside route artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from h3_offroad_planner import map_config
from h3_offroad_planner.map_config import (
    LAYER_ENV,
    MAP_CONFIG_ENV,
    TOKEN_ENV,
    MapProviderConfig,
    load_map_provider_config,
)


def test_map_config_defaults_to_unset_without_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop and Web startup remain valid when no private token exists."""
    monkeypatch.delenv(MAP_CONFIG_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(LAYER_ENV, raising=False)
    monkeypatch.setattr(map_config, "_DEFAULT_PRIVATE_CONFIG_PATH", tmp_path / "missing.yaml")

    config = load_map_provider_config()

    assert config.token == ""
    assert config.token_source == "unset"


def test_map_config_discovers_ignored_project_private_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "map.private.yaml"
    private.write_text(
        "provider: tianditu\nlayer_type: imagery\ntoken: local-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(map_config, "_DEFAULT_PRIVATE_CONFIG_PATH", private)
    monkeypatch.delenv(MAP_CONFIG_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(LAYER_ENV, raising=False)

    config = load_map_provider_config()

    assert config.token == "local-secret"
    assert config.token_source == "local_config"


def test_map_config_environment_token_overrides_private_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "map.private.yaml"
    private.write_text(
        "provider: tianditu\nlayer_type: imagery\ntoken: local-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(TOKEN_ENV, " runtime-secret ")
    monkeypatch.setenv(LAYER_ENV, "vector")

    config = load_map_provider_config(str(private))

    assert config.layer_type == "vector"
    assert config.token == "runtime-secret"
    assert config.token_source == "environment"


def test_map_config_empty_environment_token_falls_back_to_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "map.private.yaml"
    private.write_text("token: local-secret\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV, "   ")

    config = load_map_provider_config(str(private))

    assert config.token == "local-secret"
    assert config.token_source == "local_config"


def test_explicit_map_config_path_precedes_environment_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "explicit.yaml"
    environment = tmp_path / "environment.yaml"
    explicit.write_text("token: explicit-secret\n", encoding="utf-8")
    environment.write_text("token: environment-file-secret\n", encoding="utf-8")
    monkeypatch.setenv(MAP_CONFIG_ENV, str(environment))
    monkeypatch.delenv(TOKEN_ENV, raising=False)

    config = load_map_provider_config(str(explicit))

    assert config.token == "explicit-secret"
    assert config.token_source == "local_config"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"provider": "osm"},
        {"layer_type": "terrain"},
        {"token": 1},
        {"token_source": "source_default"},
        {"token_source": "route_plan"},
    ),
)
def test_map_provider_value_object_rejects_implicit_or_unknown_settings(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        MapProviderConfig(**kwargs)  # type: ignore[arg-type]


def test_map_config_rejects_non_mapping_and_non_string_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    malformed = tmp_path / "map.yaml"
    malformed.write_text("- bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_map_provider_config(str(malformed))
    malformed.write_text("provider: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be strings"):
        load_map_provider_config(str(malformed))
    malformed.write_text("token: false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be strings"):
        load_map_provider_config(str(malformed))
    malformed.write_text("token: x\nunknown: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fields"):
        load_map_provider_config(str(malformed))
