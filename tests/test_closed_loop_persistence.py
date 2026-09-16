"""Spec-derived RoutePlan file, GIS layer, and explicit selection tests."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest

from h3_offroad_planner.candidate_aggregation import CandidateAggregator
from h3_offroad_planner.factor_model import FactorModelConfig, evaluate_factor_model
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, PlanningInputError, VehicleProfile
from h3_offroad_planner.planners.deterministic_pareto import DeterministicParetoPlanner
from h3_offroad_planner.portsmap import PortsMapSearchContext
from h3_offroad_planner.route_models import RoutePlan, plan_id_for_payload
from h3_offroad_planner.route_persistence import (
    atomic_write_json,
    delivery_output_paths,
    load_route_graph_snapshot,
    load_route_plan,
    load_route_selection,
    select_route,
    write_route_plan_outputs,
    write_routes_gpkg,
)


def test_cl022_plan_round_trip_gpkg_layers_and_explicit_selection(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-022: plan writes all static route layers but no implicit RouteSelection."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    for name in (
        "route_candidates.geojson",
        "route_recommended.geojson",
        "style_manifest.json",
    ):
        (tmp_path / name).write_text("stale", encoding="utf-8")
    write_route_plan_outputs(plan, graph, str(tmp_path), {"artifact_kind": "tile_h3_cache"})
    assert not (tmp_path / "route_selection.json").exists()
    loaded = load_route_plan(str(tmp_path / "route_plan.json"))
    assert loaded.to_dict() == plan.to_dict()
    layers = set(gpd.list_layers(tmp_path / "routes.gpkg")["name"])
    assert {
        "h3_static_facts",
        "route_candidates",
        "route_recommended",
        "route_selected",
        "route_active",
        "confirmed_blockages",
        "h3_edges",
    }.issubset(layers)
    manifest = json.loads((tmp_path / "route_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert "graph_snapshot" not in manifest
    assert manifest["graph_storage"]["path"] == "routes.gpkg"
    restored = load_route_graph_snapshot(str(tmp_path / "route_manifest.json"))
    assert restored.cells == graph.cells
    assert restored.edges == graph.edges
    assert not (tmp_path / "route_candidates.geojson").exists()
    assert not (tmp_path / "route_recommended.geojson").exists()
    assert not (tmp_path / "style_manifest.json").exists()
    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    assert selection.state == "active"
    assert (tmp_path / "selected_route.geojson").exists()
    assert (tmp_path / "active_route.geojson").exists()
    assert load_route_selection(str(tmp_path / "route_selection.json")) == selection


def test_cl023_selection_is_idempotent_and_version_conflicts_are_rejected(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-023: repeated activation is idempotent and stale expected versions fail."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))
    first = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    second = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    assert first == second
    with pytest.raises(PlanningInputError, match="VERSION_CONFLICT"):
        select_route(
            str(tmp_path / "route_plan.json"),
            candidate_id=plan.recommended_candidate_id,
            expected_selection_version=first.selection_version - 1,
        )


def test_cl024_corrupt_selection_is_isolated(tmp_path: Path) -> None:
    """CL-024: malformed state JSON is moved aside instead of being overwritten silently."""
    path = tmp_path / "route_selection.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(PlanningInputError, match="isolated"):
        load_route_selection(str(path))
    assert not path.exists()
    assert (tmp_path / "route_selection.json.corrupt").exists()


def test_cl025_plan_json_is_canonical_and_deterministic(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-025: repeated equal plans preserve plan id and sorted JSON fields."""
    graph, first = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(first, graph, str(tmp_path))
    initial = (tmp_path / "route_plan.json").read_bytes()
    _, second = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(second, graph, str(tmp_path))
    assert first.plan_id == second.plan_id
    assert initial == (tmp_path / "route_plan.json").read_bytes()
    assert json.loads(initial)["planner_name"] == "DeterministicParetoPlanner"


def test_cl026_atomic_write_failure_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CL-026: replacement failure cannot destroy the previously committed JSON."""
    output = tmp_path / "state.json"
    output.write_text('{"version": 1}\n', encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_json(output, {"version": 2})

    assert output.read_text(encoding="utf-8") == '{"version": 1}\n'


def test_cl027_gpkg_candidate_metrics_match_route_plan(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-027: persisted GIS candidate metrics equal the authoritative RoutePlan."""
    graph, plan = _plan_fixture(tmp_path, vehicle)
    write_route_plan_outputs(plan, graph, str(tmp_path))

    layer = gpd.read_file(tmp_path / "routes.gpkg", layer="route_candidates")
    by_id = layer.set_index("candidate_id")
    for candidate in plan.candidates:
        record = by_id.loc[candidate.candidate_id]
        assert record["eta_s"] == pytest.approx(candidate.metrics.eta_s)
        assert record["distance_m"] == pytest.approx(candidate.metrics.distance_m)
        assert record["score_lower_min"] == pytest.approx(
            candidate.metrics.safety_margin_min
        )
        assert record["terrain_risk"] == pytest.approx(candidate.metrics.terrain_risk)
        assert record["travel_cost"] == pytest.approx(candidate.metrics.travel_cost)


def test_indexed_plan_uses_light_outputs_and_one_layer_export(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    graph, plan = _plan_fixture(tmp_path, vehicle)
    index_manifest = tmp_path / "routing_index" / "builds" / "build-1" / "routing_index.json"
    source = {
        "artifact_kind": "h3_routing_index",
        "source_manifest": str(tmp_path / "routing_index" / "current.json"),
        "routing_index_manifest": str(index_manifest),
        "build_id": "build-1",
        "active_parent_h3": ["pa", "pb"],
        "evidence_status": "INCOMPLETE",
        "missing_physical_inputs": ["vehicle.width_m"],
    }

    write_route_plan_outputs(
        plan,
        graph,
        str(tmp_path),
        source,
        export_gpkg=False,
    )

    assert (tmp_path / "route_plan.json").is_file()
    assert (tmp_path / "route_manifest.json").is_file()
    assert (tmp_path / "routes.geojson").is_file()
    assert not (tmp_path / "routes.gpkg").exists()
    manifest = json.loads((tmp_path / "route_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["graph_storage"] == {
        "format": "routing_index",
        "path": str(index_manifest),
        "build_id": "build-1",
        "active_parent_h3": ["pa", "pb"],
        "resolution_fine": graph.resolution_fine,
        "resolution_coarse": graph.resolution_coarse,
    }

    selection = select_route(str(tmp_path / "route_plan.json"), role="fastest_eta")
    collection = json.loads((tmp_path / "routes.geojson").read_text(encoding="utf-8"))
    active = [
        feature
        for feature in collection["features"]
        if feature["properties"]["is_active"]
    ]
    assert [feature["properties"]["candidate_id"] for feature in active] == [
        selection.candidate_id
    ]
    assert not (tmp_path / "routes.gpkg").exists()

    write_routes_gpkg(str(tmp_path / "routes.gpkg"), plan)
    assert list(gpd.list_layers(tmp_path / "routes.gpkg")["name"]) == ["route_candidates"]
    exported = gpd.read_file(tmp_path / "routes.gpkg", layer="route_candidates")
    assert {
        "candidate_id",
        "roles",
        "is_recommended",
        "is_selected",
        "is_active",
        "eta_s",
        "eta_lower_s",
        "eta_upper_s",
        "distance_m",
        "score_lower_min",
        "terrain_risk",
        "travel_cost",
        "trajectory_status",
        "environment_distance_m",
    }.issubset(exported.columns)
    assert {"generation_profile", "replan_profile", "trajectory_id"}.isdisjoint(
        exported.columns
    )


def test_cl040_complete_route_plan_identity_is_deterministic(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """CL-040: equal closed-loop inputs reproduce plan, candidates, roles, and hashes."""
    _, first = _plan_fixture(tmp_path, vehicle)
    _, second = _plan_fixture(tmp_path, vehicle)

    assert first.to_dict() == second.to_dict()


def _plan_fixture(tmp_path: Path, vehicle: VehicleProfile) -> tuple[H3Graph, RoutePlan]:
    graph = _graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    context = PortsMapSearchContext(graph, evaluation)
    raw = DeterministicParetoPlanner(context).plan("s", "g")
    aggregation = CandidateAggregator(graph, context).aggregate(raw, "fastest", 5)
    identity = {
        "schema_version": 1,
        "mission_profile": "fastest",
        "recommended_candidate_id": aggregation.recommended_candidate_id,
        "independence_reference_candidate_id": aggregation.independence_reference_candidate_id,
        "vehicle_hash": evaluation.vehicle_hash,
        "factor_model_hash": evaluation.factor_model_hash,
        "static_input_hash": evaluation.static_input_hash,
        "graph_topology_hash": evaluation.graph_topology_hash,
        "candidate_ids": [candidate.candidate_id for candidate in aggregation.candidates],
        "candidate_roles": [list(candidate.roles) for candidate in aggregation.candidates],
    }
    plan = RoutePlan(
        plan_id=plan_id_for_payload(identity),
        mission_profile="fastest",
        recommended_candidate_id=aggregation.recommended_candidate_id,
        independence_reference_candidate_id=aggregation.independence_reference_candidate_id,
        vehicle_hash=evaluation.vehicle_hash,
        factor_model_hash=evaluation.factor_model_hash,
        static_input_hash=evaluation.static_input_hash,
        graph_topology_hash=evaluation.graph_topology_hash,
        candidates=aggregation.candidates,
        aggregation_stats=aggregation.statistics,
        output_files=delivery_output_paths(str(tmp_path)),
        warnings=aggregation.warnings,
    )
    return graph, plan


def _graph() -> H3Graph:
    parent_by_cell = {
        "s": "ps",
        "a": "pa",
        "b": "pa",
        "c": "pb",
        "d": "pb",
        "g": "pg",
    }
    cells = {
        name: H3Cell(
            h3index=name,
            lat=float(index % 2),
            lng=float(index),
            elevation=0.0,
            slope=0.0,
            tri=0.1,
            lc_factor=1.0 if parent != "pb" else 1.5,
            parent_h3=parent,
            has_road=parent == "pa",
            is_passable=True,
        )
        for index, (name, parent) in enumerate(parent_by_cell.items())
    }
    edge_specs = (
        ("s", "a", 2.0),
        ("a", "b", 2.0),
        ("b", "g", 2.0),
        ("s", "c", 1.5),
        ("c", "d", 1.5),
        ("d", "g", 1.5),
    )
    edges = {
        (first, second): H3Edge(first, second, distance)
        for first, second, distance in edge_specs
    }
    parent_children: dict[str, set[str]] = {}
    for cell_id, parent in parent_by_cell.items():
        parent_children.setdefault(parent, set()).add(cell_id)
    return H3Graph(cells=cells, edges=edges, parent_children=parent_children)
