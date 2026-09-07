"""Boundary and invariant tests for the new immutable planning contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from h3_offroad_planner.factor_model import (
    DirectedEdgeMetrics,
    FactorEvaluation,
    FactorInterval,
    FactorModelConfig,
    NodeFactorMetrics,
    PathMetrics,
    _factor_model_from_mapping,
    _known_interval,
    build_directed_edge_cache,
    evaluate_factor_model,
    evaluate_path_metrics,
    load_factor_model,
    write_effective_snapshots,
)
from h3_offroad_planner.models import (
    ConfigError,
    H3Cell,
    H3Graph,
    PlanningInputError,
    VehicleProfile,
)
from h3_offroad_planner.route_models import (
    BlockageRecord,
    ReplanRequest,
    ReplanResult,
    RouteCandidate,
    RoutePlan,
    RouteSelection,
    candidate_id_for_path,
    plan_id_for_payload,
)
from h3_offroad_planner.route_planning import _validate_route_plan_planner


def _metrics() -> PathMetrics:
    return PathMetrics(10.0, 1.0, 2.0, 3.0, True, 4.0, 5.0, 0.5, 0.7, 1)


def _candidate(path: tuple[str, ...] = ("a", "b")) -> RouteCandidate:
    return RouteCandidate(
        candidate_id=candidate_id_for_path(path),
        h3_path=path,
        roles=("fastest_eta",),
        is_recommended=True,
        objectives={"eta": 2.0},
        metrics=_metrics(),
        corridor_signature=("p",),
        generation_profile="eta",
        replan_profile="eta",
    )


def _plan_kwargs() -> dict[str, object]:
    candidate = _candidate()
    identity = {
        "schema_version": 1,
        "mission_profile": "fastest",
        "recommended_candidate_id": candidate.candidate_id,
        "independence_reference_candidate_id": None,
        "vehicle_hash": "v",
        "factor_model_hash": "f",
        "static_input_hash": "s",
        "graph_topology_hash": "g",
        "candidate_ids": [candidate.candidate_id],
        "candidate_roles": [list(candidate.roles)],
    }
    return {
        "plan_id": plan_id_for_payload(identity),
        "mission_profile": "fastest",
        "recommended_candidate_id": candidate.candidate_id,
        "independence_reference_candidate_id": None,
        "vehicle_hash": "v",
        "factor_model_hash": "f",
        "static_input_hash": "s",
        "graph_topology_hash": "g",
        "candidates": (candidate,),
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"candidate_id": ""}, "non-empty"),
        ({"candidate_id": "wrong"}, "stable H3 path hash"),
        ({"roles": ("fastest_eta", "fastest_eta")}, "unique known"),
        ({"roles": ("unknown",)}, "unique known"),
        ({"objectives": {"eta": -1.0}}, "finite and non-negative"),
        ({"generation_profile": ""}, "profiles must be non-empty"),
    ),
)
def test_route_candidate_rejects_invalid_contract(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_candidate(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"mission_profile": "unknown"}, "mission_profile"),
        ({"candidates": ()}, "one to five"),
        ({"candidates": (_candidate(), _candidate())}, "unique"),
        ({"recommended_candidate_id": "missing"}, "identify a candidate"),
        ({"candidates": (replace(_candidate(), is_recommended=False),)}, "exactly one"),
        ({"planner_name": "LegacyDeterministicParetoPlanner"}, "DeterministicParetoPlanner"),
        ({"plan_id": "wrong"}, "canonical plan identity"),
    ),
)
def test_route_plan_rejects_invalid_contract(changes: dict[str, object], message: str) -> None:
    kwargs = _plan_kwargs()
    kwargs.update(changes)
    with pytest.raises(ValueError, match=message):
        RoutePlan(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"plan_id": ""},
        {"selected_role": "unknown"},
        {"state": "paused"},
        {"replan_version": -1},
        {"selection_version": 0},
    ),
)
def test_route_selection_rejects_invalid_contract(changes: dict[str, object]) -> None:
    kwargs: dict[str, object] = {
        "plan_id": "plan",
        "candidate_id": "candidate",
        "selected_role": "fastest_eta",
        "active_h3_path": ("a", "b"),
        "active_metrics": _metrics(),
        "vehicle_hash": "v",
        "factor_model_hash": "f",
        "static_input_hash": "s",
        "graph_topology_hash": "g",
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        RouteSelection(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"blockage_id": ""},
        {"state": "bad"},
        {"confirmation_count": 0},
        {"observed_at_epoch_s": -1.0},
        {"observed_at_epoch_s": float("nan")},
        {"expires_at_epoch_s": float("inf")},
        {"expires_at_epoch_s": 1.0},
    ),
)
def test_blockage_record_rejects_invalid_lifecycle(changes: dict[str, object]) -> None:
    kwargs: dict[str, object] = {
        "blockage_id": "b",
        "h3index": "cell",
        "state": "tentative",
        "confirmation_count": 1,
        "trusted_source": False,
        "observed_at_epoch_s": 1.0,
        "expires_at_epoch_s": 2.0,
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        BlockageRecord(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"selection_path": ""},
        {"current_h3": None},
        {"current_lat": 0.0, "current_lng": 0.0},
        {"current_h3": None, "current_lat": 0.0},
        {"current_h3": None, "current_lat": 91.0, "current_lng": 0.0},
        {"current_h3": None, "current_lat": 0.0, "current_lng": 181.0},
        {"snap_distance_m": 0.0},
        {"now_epoch_s": -1.0},
    ),
)
def test_cl033_replan_request_requires_explicit_valid_position(
    changes: dict[str, object],
) -> None:
    kwargs: dict[str, object] = {
        "selection_path": "selection.json",
        "blockage_observations": (),
        "current_h3": "cell",
        "now_epoch_s": 1.0,
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        ReplanRequest(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "paused"},
        {"algorithm": "AStar"},
        {"replan_version": -1},
    ),
)
def test_replan_result_rejects_unknown_state_or_algorithm(changes: dict[str, object]) -> None:
    kwargs: dict[str, object] = {
        "plan_id": "p",
        "candidate_id": "c",
        "algorithm": "DStarLite",
        "status": "active",
        "replan_version": 1,
        "old_path_hash": "old",
        "new_path_hash": "new",
        "metrics_before": _metrics(),
        "metrics_after": _metrics(),
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        ReplanResult(**kwargs)  # type: ignore[arg-type]


def test_empty_candidate_path_has_no_stable_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        candidate_id_for_path([])


@pytest.mark.parametrize(
    "values",
    ((-0.1, 0.2, 0.3), (0.2, 0.1, 0.3), (0.1, 0.2, float("nan"))),
)
def test_factor_interval_rejects_unordered_or_nonfinite(values: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        FactorInterval(*values)


def test_factor_metric_value_objects_enforce_bounds() -> None:
    interval = FactorInterval(0.2, 0.5, 0.8)
    node = NodeFactorMetrics(
        "a",
        interval,
        interval,
        interval,
        interval,
        interval,
        interval,
        1.0,
        2.0,
        3.0,
        True,
        0.8,
    )
    with pytest.raises(ValueError, match="ordered"):
        replace(node, speed_lower_mps=4.0)
    with pytest.raises(ValueError, match="non-negative"):
        replace(node, speed_lower_mps=-1.0)
    with pytest.raises(ValueError, match="confidence"):
        replace(node, confidence=2.0)
    with pytest.raises(ValueError, match="non-empty"):
        replace(node, h3index="")

    edge = DirectedEdgeMetrics("a", "b", 10, 1, 2, 3, True, 4, 5, 0.2, 0.5, 0.8, 0)
    with pytest.raises(ValueError, match="distinct"):
        replace(edge, to_h3="a")
    with pytest.raises(ValueError, match="positive"):
        replace(edge, distance_m=0.0)
    with pytest.raises(ValueError, match="non-negative"):
        replace(edge, terrain_risk=-1.0)
    with pytest.raises(ValueError, match="bounded"):
        replace(edge, eta_upper_s=None)
    with pytest.raises(ValueError, match="below"):
        replace(edge, eta_upper_s=1.0)
    with pytest.raises(ValueError, match="ordered"):
        replace(edge, safety_margin_lower=0.9)

    with pytest.raises(ValueError, match="edge_count"):
        replace(_metrics(), edge_count=-1)
    with pytest.raises(ValueError, match="non-negative"):
        replace(_metrics(), terrain_risk=-1.0)
    with pytest.raises(ValueError, match="safety-margin aggregates"):
        replace(_metrics(), safety_margin_min=0.9)
    with pytest.raises(ValueError, match="presence"):
        replace(_metrics(), eta_upper_s=None)


@pytest.mark.parametrize(
    "changes",
    (
        {"tri_best": 2.0, "tri_worst": 1.0},
        {"tri_worst": float("inf")},
        {"missing_confidence": 0.0},
        {"missing_speed_lower": 0.8, "missing_speed_nominal": 0.7},
        {"epsilon": 0.0},
        {"epsilon": 1.1},
        {"tri_coefficient": -1.0},
        {"max_ports": 0},
        {"max_ports": 1.5},
        {"max_port_pairs": True},
        {"landcover_speed_by_code": {1: 2.0}},
    ),
)
def test_factor_model_config_rejects_invalid_ranges(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        FactorModelConfig(**changes)  # type: ignore[arg-type]


def test_cl010_schema_v2_rejects_unknown_sections_and_fields() -> None:
    with pytest.raises(ConfigError, match="unknown fields"):
        _factor_model_from_mapping({"schema_version": 2, "obsolete": {}})
    with pytest.raises(ConfigError, match="unknown fields"):
        _factor_model_from_mapping(
            {"schema_version": 2, "risk": {"epsilon": 0.1, "obsolete": 1}}
        )


def test_factor_mapping_decoder_rejects_malformed_sections_and_fields() -> None:
    with pytest.raises(ConfigError, match="section"):
        _factor_model_from_mapping({"schema_version": 2, "speed": []})
    with pytest.raises(ConfigError, match="three values"):
        _factor_model_from_mapping(
            {
                "schema_version": 2,
                "uncertainty": {"missing_speed_interval": [0.1]},
            }
        )
    with pytest.raises(ConfigError, match="unsupported"):
        _factor_model_from_mapping({"schema_version": 3})
    with pytest.raises(ValueError, match="must not be None"):
        _known_interval(None)


@pytest.mark.parametrize(
    "speed_yaml,error",
    (
        ("landcover_by_code:\n    true: 0.5", "integer keys"),
        ("landcover_by_code:\n    0: true", "integers to numbers"),
        ("soil_by_uscs:\n    1: 0.5", "non-empty string keys"),
        (
            'landcover_by_code:\n    1: 0.5\n    "1": 0.6',
            "duplicate normalized key",
        ),
    ),
)
def test_factor_yaml_rejects_implicit_mapping_types(
    tmp_path: Path,
    speed_yaml: str,
    error: str,
) -> None:
    path = tmp_path / "factor.yaml"
    path.write_text(f"schema_version: 2\nspeed:\n  {speed_yaml}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=error):
        load_factor_model(str(path))


def test_cl009_schema_v1_ignores_unused_fields_and_normalizes_to_v2() -> None:
    legacy = {
        "schema_version": 1,
        "uncertainty": {"missing_interval": [0.2, 0.5, 0.8]},
        "benefit": {"tri_best": 1.0, "tri_worst": 9.0, "obsolete": 1},
        "retired_evaluator": {"calibration": "ignored"},
    }
    with pytest.warns(UserWarning, match="unused"):
        config = _factor_model_from_mapping(legacy)
    assert config.tri_best == pytest.approx(1.0)
    assert config.tri_worst == pytest.approx(9.0)
    assert config.to_dict()["schema_version"] == 2
    assert "benefit" not in config.to_dict()


def test_cl011_effective_snapshot_contains_only_schema_v2_active_sections(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    config = FactorModelConfig(
        landcover_speed_by_code={1: 0.8},
        soil_speed_by_uscs={"CL": 0.6},
    )
    _, model_path = write_effective_snapshots(str(tmp_path), vehicle, config)
    payload = yaml.safe_load(Path(model_path).read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "uncertainty",
        "speed",
        "hard_constraints",
        "risk",
        "cost",
        "portsmap",
    }
    assert payload["schema_version"] == 2
    assert load_factor_model(model_path) == config


def test_factor_evaluation_requires_four_nonempty_hashes() -> None:
    with pytest.raises(ValueError, match="hashes"):
        FactorEvaluation({}, {}, "", "f", "s", "g")


def test_factor_public_boundaries_reject_missing_files_graphs_and_paths(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Public factor APIs fail explicitly for incomplete state instead of guessing."""
    with pytest.raises(ConfigError, match="does not exist"):
        load_factor_model(str(tmp_path / "missing.yaml"))
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="contain a mapping"):
        load_factor_model(str(invalid))
    with pytest.raises(PlanningInputError, match="non-empty graph"):
        evaluate_factor_model(H3Graph(cells={}, edges={}), vehicle, FactorModelConfig())

    cell = H3Cell("a", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    graph = H3Graph(cells={"a": cell}, edges={})
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    with pytest.raises(PlanningInputError, match="cover every"):
        build_directed_edge_cache(graph, {}, vehicle, FactorModelConfig())
    with pytest.raises(PlanningInputError, match="at least one"):
        evaluate_path_metrics([], evaluation)
    with pytest.raises(PlanningInputError, match="absent"):
        evaluate_path_metrics(["missing"], evaluation)
    single = evaluate_path_metrics(["a"], evaluation)
    assert single.edge_count == 0
    with pytest.raises(PlanningInputError, match="missing or impassable edge"):
        evaluate_path_metrics(["a", "a"], evaluation)


def test_route_plan_planner_config_rejects_legacy_and_task_owned_fields(
    tmp_path: Path,
) -> None:
    """New planning accepts one algorithm name and keeps task knobs in RouteRequest."""
    current = tmp_path / "current.yaml"
    current.write_text("global_planner: DeterministicParetoPlanner\n", encoding="utf-8")
    _validate_route_plan_planner(str(current))
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text(
        "global_planner: LegacyDeterministicParetoPlanner\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="RoutePlan requires"):
        _validate_route_plan_planner(str(legacy))
    task_owned = tmp_path / "task-owned.yaml"
    task_owned.write_text(
        "global_planner: DeterministicParetoPlanner\n"
        "deterministic_pareto:\n  penalty_factor: 0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="task-owned"):
        _validate_route_plan_planner(str(task_owned))
    unsupported = tmp_path / "unsupported.yaml"
    unsupported.write_text("global_planner: H3AStar\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="RoutePlan requires"):
        _validate_route_plan_planner(str(unsupported))
