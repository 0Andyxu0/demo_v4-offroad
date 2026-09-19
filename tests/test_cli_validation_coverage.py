"""Boundary tests for CLI payload decoding and command dispatch helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from h3_offroad_planner import cli
from h3_offroad_planner.models import ConfigError


def test_cli_scalar_decoders_cover_defaults_nulls_and_invalid_types() -> None:
    """Every scalar decoder distinguishes absent, valid, and malformed YAML values."""
    payload: dict[str, object] = {
        "text": "value",
        "integer": 3,
        "number": 2.5,
        "truth": True,
        "items": ["one", "two"],
    }
    assert cli._required_string(payload, "text") == "value"
    assert cli._optional_string(payload, "missing") is None
    assert cli._optional_string({"field": None}, "field") is None
    assert cli._integer_or_default(payload, "missing", 4) == 4
    assert cli._integer_or_default(payload, "integer", 4) == 3
    assert cli._optional_float(payload, "missing") is None
    assert cli._optional_float({"field": None}, "field") is None
    assert cli._optional_float(payload, "number") == 2.5
    assert cli._float_or_default(payload, "missing", 1.5) == 1.5
    assert cli._float_or_default(payload, "number", 1.5) == 2.5
    assert cli._bool_or_default(payload, "missing", False) is False
    assert cli._bool_or_default(payload, "truth", False) is True
    assert cli._string_or_default(payload, "missing", "fallback") == "fallback"
    assert cli._string_or_default(payload, "text", "fallback") == "value"
    assert cli._string_list_or_default(payload, "missing", ["fallback"]) == ["fallback"]
    assert cli._string_list_or_default(payload, "items", []) == ["one", "two"]

    with pytest.raises(ConfigError, match="must be a string"):
        cli._required_string({}, "missing")
    with pytest.raises(ConfigError, match="string or null"):
        cli._optional_string({"field": 1}, "field")
    with pytest.raises(ConfigError, match="integer"):
        cli._integer_or_default({"field": True}, "field", 0)
    with pytest.raises(ConfigError, match="numeric"):
        cli._number_as_float(True, "field")
    with pytest.raises(ConfigError, match="bool"):
        cli._bool_or_default({"field": 1}, "field", False)
    with pytest.raises(ConfigError, match="string"):
        cli._string_or_default({"field": 1}, "field", "")
    with pytest.raises(ConfigError, match="list of strings"):
        cli._string_list_or_default({"field": [1]}, "field", [])


def test_cli_mapping_and_unknown_field_validation() -> None:
    """Mapping decoders reject structural contract violations."""
    with pytest.raises(ConfigError, match="unsupported fields"):
        cli._reject_unknown_fields({"unexpected": 1}, frozenset())
    with pytest.raises(ConfigError, match="must be a mapping"):
        cli._required_mapping({"section": []}, "section")
    with pytest.raises(ConfigError, match="required"):
        cli._required_float({}, "missing")
    with pytest.raises(ConfigError, match="array"):
        cli._blockage_records({"blockage_observations": {}}, 1.0)
    with pytest.raises(ConfigError, match="must be mappings"):
        cli._blockage_records({"blockage_observations": [1]}, 1.0)
    records = cli._blockage_records(
        {"blockage_observations": [{"blockage_id": "b", "h3index": "cell"}]}, 1.0
    )
    assert records[0].source == "user"
    with pytest.raises(ConfigError, match="policy must be a mapping"):
        cli._replan_policy({"policy": []})


def test_cl036_cli_progress_and_route_plan_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI route requests use the single RoutePlan construction flow."""
    events: list[tuple[str, int, str]] = []
    cli._report_progress(lambda *args: events.append(args), "module", 50, "message")
    assert events == [("module", 50, "message")]

    route_payload = {
        "input_mode": "coordinates",
        "parquet_path": "graph.parquet",
        "planner_config_path": "planner.yaml",
        "vehicle_path": "vehicle.yaml",
        "output_dir": "output",
        "start_lat": 0.0,
        "start_lng": 0.0,
        "goal_lat": 1.0,
        "goal_lng": 1.0,
    }
    class Plan:
        def to_dict(self) -> dict[str, object]:
            return {"flow": "route_plan"}

    monkeypatch.setattr(cli, "run_route_plan", lambda request: Plan())
    assert cli.run_route_payload(
        {**route_payload, "factor_model_path": "factor.yaml"}
    ) == {"flow": "route_plan"}


def test_cli_plan_accepts_delivery_request_with_nested_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI plan payload normalization unrolls delivery YAML structures containing 'route'."""
    captured: list[object] = []

    class Plan:
        def to_dict(self) -> dict[str, object]:
            return {"flow": "route_plan"}

    monkeypatch.setattr(cli, "run_route_plan", lambda request: captured.append(request) or Plan())

    delivery_payload = {
        "tile_build": {
            "output_dir": "outputs/my_tiles",
        },
        "route": {
            "input_mode": "coordinates",
            "planner_config_path": "planner.yaml",
            "vehicle_path": "vehicle.yaml",
            "factor_model_path": "factor.yaml",
            "output_dir": "output",
            "start_lat": 31.99,
            "start_lng": 118.99,
            "goal_lat": 31.995,
            "goal_lng": 118.995,
        },
    }
    result = cli.run_route_payload(delivery_payload)
    assert result == {"flow": "route_plan"}
    assert len(captured) == 1
    req = captured[0]
    assert isinstance(req, cli.RouteRequest)
    assert req.parquet_path.endswith("tile_manifest.json")


def test_cli_collects_candidate_reuse_penalty_in_route_request() -> None:
    """Candidate diversity tuning is carried by the task contract, not planner YAML."""
    request = cli._route_request(
        {
            "input_mode": "coordinates",
            "parquet_path": "graph.parquet",
            "planner_config_path": "planner.yaml",
            "vehicle_path": "vehicle.yaml",
            "factor_model_path": "factor.yaml",
            "output_dir": "output",
            "start_lat": 0.0,
            "start_lng": 0.0,
            "goal_lat": 1.0,
            "goal_lng": 1.0,
            "penalty_factor": 0.75,
        }
    )

    assert request.penalty_factor == 0.75


def test_cli_yaml_loading_and_unknown_command_errors(tmp_path: Path) -> None:
    """Invalid file content and unsupported dispatch commands use ConfigError contracts."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        cli._load_yaml_mapping(missing)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("tile_build: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        cli._load_yaml_mapping(invalid)

    empty = tmp_path / "empty.yaml"
    empty.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty mapping"):
        cli._load_yaml_mapping(empty)

    valid = tmp_path / "valid.yaml"
    valid.write_text("tile_build: {}", encoding="utf-8")
    with pytest.raises(ConfigError, match="unsupported CLI command"):
        cli._dispatch("other", valid)
