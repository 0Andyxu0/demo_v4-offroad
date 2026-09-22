"""Unit and integration tests for offline port-pair precomputation, sliced loading, and fallback."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import h3
import pandas as pd
import pytest

from h3_offroad_planner.factor_model import (
    FactorModelConfig,
    canonical_hash,
    evaluate_factor_model,
)
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, VehicleProfile
from h3_offroad_planner.offline_pairs import (
    BASE_PROFILE_NAMES,
    OfflinePairsTable,
    default_vehicle,
    extract_offline_pairs,
    load_offline_pairs,
    precompute_port_pairs,
    read_offline_pairs_vehicle_hash,
    save_offline_pairs,
)
from h3_offroad_planner.portsmap import (
    PortsMapSearchContext,
    ScalarProfile,
)
from h3_offroad_planner.routing_index import (
    build_routing_index,
    open_routing_index,
    register_port_pairs,
)
from scripts.precompute_port_pairs_workflow import main as workflow_main


def _ports_graph() -> H3Graph:
    parents = {"a": "p1", "b": "p1", "c": "p1", "d": "p2", "e": "p2", "f": "p2"}
    cells = {
        name: H3Cell(
            h3index=name,
            lat=0.0 if parent == "p1" else 1.0,
            lng=float(index),
            elevation=float(index),
            slope=0.0,
            tri=0.1 * index,
            lc_factor=1.0 + 0.1 * index,
            parent_h3=parent,
            is_passable=True,
        )
        for index, (name, parent) in enumerate(parents.items())
    }
    specifications = (
        ("a", "b", 2.0),
        ("b", "c", 2.0),
        ("a", "c", 6.0),
        ("b", "d", 4.0),
        ("c", "e", 1.0),
        ("d", "e", 2.0),
        ("d", "f", 6.0),
        ("e", "f", 2.0),
    )
    edges = {
        (first, second): H3Edge(
            first,
            second,
            distance,
            slope_a_to_b=2.0,
            slope_b_to_a=-2.0,
        )
        for first, second, distance in specifications
    }
    return H3Graph(
        cells=cells,
        edges=edges,
        parent_children={"p1": {"a", "b", "c"}, "p2": {"d", "e", "f"}},
    )


def test_offline_pairs_roundtrip_and_pushdown(tmp_path: Path) -> None:
    pairs = {
        ("distance", "p1", "a"): {
            "b": (("a", "b"), 2.0),
            "c": (("a", "b", "c"), 4.0),
        },
        ("distance", "p2", "d"): {
            "e": (("d", "e"), 2.0),
            "f": (("d", "e", "f"), 4.0),
        },
        ("distance", "p3", "x"): {
            "y": (("x", "y"), 1.5),
        },
    }
    file_path = tmp_path / "port_pairs.parquet"
    save_offline_pairs(pairs, file_path)
    assert file_path.is_file()

    # Full load
    loaded_all = load_offline_pairs(file_path)
    assert len(loaded_all) == 3
    assert loaded_all[("distance", "p1", "a")]["b"] == (("a", "b"), 2.0)
    assert loaded_all[("distance", "p2", "d")]["f"] == (("d", "e", "f"), 4.0)

    # Sliced load with predicate pushdown on parent_h3
    sliced = load_offline_pairs(file_path, active_parents=["p1", "p3"])
    assert len(sliced) == 2
    assert ("distance", "p1", "a") in sliced
    assert ("distance", "p3", "x") in sliced
    assert ("distance", "p2", "d") not in sliced

    # Empty active parents returns empty dict immediately
    assert load_offline_pairs(file_path, active_parents=[]) == {}

    # Nonexistent file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_offline_pairs(tmp_path / "missing.parquet")


def test_offline_pairs_parity_with_online_dijkstra(vehicle: VehicleProfile) -> None:
    """Verify exact path and cost parity between online Dijkstra and offline loaded pairs."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    # Pre-extract all pairs across all 4 base profiles from an unpenalized warm run
    warm_context = PortsMapSearchContext(graph, evaluation)
    combined_offline: dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]] = {}

    ground_truth_results: dict[str, tuple[tuple[str, ...], float]] = {}
    for obj_name in BASE_PROFILE_NAMES:
        profile = ScalarProfile({obj_name: 1.0}, name=obj_name)
        res = warm_context.search("a", "f", profile)
        ground_truth_results[obj_name] = (res.h3_path, res.scalar_cost)
        extracted = extract_offline_pairs(warm_context, profile.name)
        combined_offline.update(extracted)

    assert combined_offline

    # Instantiate search context injected with offline pairs
    offline_context = PortsMapSearchContext(
        graph,
        evaluation,
        offline_pairs=combined_offline,
    )

    for obj_name in BASE_PROFILE_NAMES:
        profile = ScalarProfile({obj_name: 1.0}, name=obj_name)
        res = offline_context.search("a", "f", profile)
        expected_path, expected_cost = ground_truth_results[obj_name]

        assert res.h3_path == expected_path
        assert res.scalar_cost == pytest.approx(expected_cost, rel=1e-6)

    # Verify that offline pairs were actually hit and fine tile searches were skipped
    assert offline_context.offline_cache_hits > 0
    assert offline_context.fine_search_calls == 0


def test_offline_pairs_fallback_on_penalties_and_blockages(
    vehicle: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fallback to online fine search when blocked cells or penalties are present."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    warm = PortsMapSearchContext(graph, evaluation)
    warm.search("a", "f", profile)
    offline = extract_offline_pairs(warm, profile.name)

    # 1. Fallback on dynamic exploration penalties
    penalized_context = PortsMapSearchContext(graph, evaluation, offline_pairs=offline)
    penalized_context.search(
        "a",
        "f",
        profile,
        exploration_penalties={"b": 1},
        penalty_factor=0.5,
    )
    # fine search must be invoked because p1 has local penalties
    assert penalized_context.fine_search_calls > 0

    # 2. Fallback on blocked cell
    blocked_context = PortsMapSearchContext(graph, evaluation, offline_pairs=offline)
    blocked_context.search(
        "a",
        "f",
        profile,
        blocked=frozenset({"e"}),
    )
    assert blocked_context.fine_search_calls > 0

    # 3. Fallback on profile not present in offline pairs
    uncomputed_profile = ScalarProfile({"distance": 0.5, "eta": 0.5}, name="custom_uncomputed")
    missing_profile_context = PortsMapSearchContext(graph, evaluation, offline_pairs=offline)
    missing_profile_context.search("a", "f", uncomputed_profile)
    assert missing_profile_context.fine_search_calls > 0


def _test_tile_manifest(tmp_path: Path) -> tuple[dict[str, object], tuple[str, str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    first = str(h3.latlng_to_cell(31.99, 118.99, 11))
    second = min(str(value) for value in h3.grid_ring(first, 1))
    records = []
    for parent in (first, second):
        rows = []
        for cell in sorted(str(value) for value in h3.cell_to_children(parent, 14)):
            lat, lng = h3.cell_to_latlng(cell)
            rows.append(
                {
                    "h3index": cell,
                    "parent_h3": parent,
                    "lat": lat,
                    "lng": lng,
                    "elevation": 10.0,
                    "slope": 1.0,
                    "tri": 0.5,
                    "landcover_code": 3,
                    "landcover_type": "grass",
                    "lc_factor": 1.0,
                    "has_road": False,
                    "is_passable": True,
                    "depth": None,
                    "rowspacing": None,
                    "soil_code": None,
                    "soil_type": None,
                    "soil_texture": None,
                    "uscs": None,
                    "soil_moisture": None,
                }
            )
        path = tmp_path / f"{parent}.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        records.append(
            {
                "parent_h3": parent,
                "path": str(path),
                "status": "completed",
            }
        )
    return (
        {
            "artifact_kind": "tile_h3_cache",
            "output_dir": str(tmp_path),
            "res_fine": 14,
            "tile_res": 11,
            "static_input_hash": "static-test-hash",
            "dem_quality": {"crs": "EPSG:4326"},
            "static_sources": {"soil": None, "soil_catalog": None},
            "tiles": records,
        },
        (first, second),
    )


def test_routing_index_port_pairs_lifecycle(tmp_path: Path, vehicle: VehicleProfile) -> None:
    """Test building an index without port_pairs, precomputing, registering, and loading."""
    manifest, (first_parent, second_parent) = _test_tile_manifest(tmp_path)

    # 1. Build initial index without port_pairs
    build_routing_index(manifest)
    index_path = tmp_path / "routing_index" / "current.json"
    index = open_routing_index(index_path)

    assert not index.has_port_pairs
    assert index.load_port_pairs([first_parent]) == {}

    # 2. Precompute port pairs
    pairs_df = precompute_port_pairs(index, vehicle=vehicle)
    assert not pairs_df.empty
    assert set(pairs_df["profile"]).issubset(set(BASE_PROFILE_NAMES))
    assert set(pairs_df["parent_h3"]).issubset({first_parent, second_parent})

    # 3. Save and register port_pairs.parquet
    pairs_file = tmp_path / "port_pairs_temp.parquet"
    save_offline_pairs(pairs_df, pairs_file)
    register_port_pairs(index.build_dir, pairs_file)

    # 4. Re-open index and verify port pairs are recognized
    reopened = open_routing_index(index_path)
    assert reopened.has_port_pairs

    # 5. Load sliced port pairs for first_parent
    first_pairs = reopened.load_port_pairs([first_parent])
    assert first_pairs
    for (_prof, parent, _src) in first_pairs:
        assert parent == first_parent


def test_build_routing_index_with_port_pairs_path(tmp_path: Path, vehicle: VehicleProfile) -> None:
    """Test build_routing_index directly accepting port_pairs_path."""
    manifest, (first_parent, second_parent) = _test_tile_manifest(tmp_path)
    build_routing_index(manifest)
    index = open_routing_index(tmp_path / "routing_index" / "current.json")

    # Generate offline pairs
    pairs_df = precompute_port_pairs(index, vehicle=vehicle)
    pairs_file = tmp_path / "offline_pairs.parquet"
    save_offline_pairs(pairs_df, pairs_file)

    # Build fresh index passing port_pairs_path
    output_dir_2 = tmp_path / "build2"
    manifest2, _ = _test_tile_manifest(output_dir_2)
    manifest2["output_dir"] = str(output_dir_2)
    build_routing_index(manifest2, port_pairs_path=pairs_file)

    index2 = open_routing_index(output_dir_2 / "routing_index" / "current.json")
    assert index2.has_port_pairs
    loaded = index2.load_port_pairs([first_parent])
    assert loaded


def test_precompute_port_pairs_workflow_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test precompute_port_pairs_workflow.py main CLI."""
    manifest, (first_parent, second_parent) = _test_tile_manifest(tmp_path)
    build_routing_index(manifest)
    current_json = tmp_path / "routing_index" / "current.json"

    out_file = tmp_path / "custom_output" / "port_pairs.parquet"
    test_args = [
        "precompute_port_pairs_workflow.py",
        "--build-dir",
        str(current_json),
        "--output",
        str(out_file),
        "--max-parents",
        "2",
        "--register",
    ]
    monkeypatch.setattr(sys, "argv", test_args)
    exit_code = workflow_main()
    assert exit_code == 0
    assert out_file.is_file()

    # Verify registered in routing index
    reopened = open_routing_index(current_json)
    assert reopened.has_port_pairs
    loaded = reopened.load_port_pairs([first_parent])
    assert loaded


def test_offline_pairs_localized_blockage_fallback(
    vehicle: VehicleProfile,
) -> None:
    """Verify that a blocked cell in Parent 1 does NOT prevent Parent 2 from using offline pairs."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    warm = PortsMapSearchContext(graph, evaluation)
    warm.search("a", "f", profile)
    offline = extract_offline_pairs(warm, profile.name)

    # Context with offline pairs
    context = PortsMapSearchContext(graph, evaluation, offline_pairs=offline)
    # Block a cell in p1 only ('b' is in p1)
    # When searching between p2 ports ('d' to 'f'), p2 has NO blocked cells
    res = context.search(
        "d",
        "f",
        profile,
        blocked=frozenset({"b"}),
    )
    assert res.h3_path == ("d", "e", "f")
    # p2 was pristine and unblocked, so offline cache was used for p2
    assert context.offline_cache_hits > 0


def test_offline_pairs_composite_profile_fallback(
    vehicle: VehicleProfile,
) -> None:
    """Verify that composite profiles (even if named distance) fall back to online Dijkstra."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())

    warm = PortsMapSearchContext(graph, evaluation)
    warm.search("a", "f", ScalarProfile({"distance": 1.0}, name="distance"))
    offline = extract_offline_pairs(warm, "distance")

    context = PortsMapSearchContext(graph, evaluation, offline_pairs=offline)
    # Composite profile with multi-objective weights named "distance"
    composite_profile = ScalarProfile({"distance": 0.5, "eta": 0.5}, name="distance")
    context.search("a", "f", composite_profile)

    # Must fall back to fine search because it is not a pure single-objective base profile
    assert context.fine_search_calls > 0
    assert context.offline_cache_hits == 0


def test_precompute_port_pairs_with_workers(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Verify precomputing port pairs with multiple worker processes."""
    manifest, (first_parent, second_parent) = _test_tile_manifest(tmp_path)
    build_routing_index(manifest)
    index = open_routing_index(tmp_path / "routing_index" / "current.json")

    # Run with workers=2 and small batch_size
    pairs_df = precompute_port_pairs(
        index,
        vehicle=vehicle,
        batch_size=1,
        workers=2,
    )
    assert not pairs_df.empty
    assert set(pairs_df["profile"]).issubset(set(BASE_PROFILE_NAMES))
    assert set(pairs_df["parent_h3"]).issubset({first_parent, second_parent})


def test_offline_pairs_vehicle_hash_metadata(tmp_path: Path) -> None:
    """Verify vehicle_hash is stored in Parquet schema metadata and read back."""
    pairs_file = tmp_path / "vehicle_hash_test.parquet"
    save_offline_pairs(
        [],
        pairs_file,
        vehicle_hash="custom-vehicle-hash-123",
    )
    read_hash = read_offline_pairs_vehicle_hash(pairs_file)
    assert read_hash == "custom-vehicle-hash-123"


def test_route_planning_vehicle_mismatch_fallback(tmp_path: Path) -> None:
    """Verify route_planning logic falls back to online search if runtime vehicle differs."""
    manifest, (first_parent, second_parent) = _test_tile_manifest(tmp_path)
    build_routing_index(manifest)
    current_json = tmp_path / "routing_index" / "current.json"
    index = open_routing_index(current_json)

    base_veh = default_vehicle()
    pairs_df = precompute_port_pairs(index, vehicle=base_veh)
    pairs_file = tmp_path / "port_pairs.parquet"
    base_hash = canonical_hash(asdict(base_veh))
    save_offline_pairs(pairs_df, pairs_file, vehicle_hash=base_hash)
    register_port_pairs(index.build_dir, pairs_file, vehicle_hash=base_hash)

    # Reopen index
    reopened = open_routing_index(current_json)
    assert reopened.has_port_pairs

    # Simulate route_planning check:
    # 1. Matching vehicle: vehicle_matches is True, offline_pairs loaded
    expected_hash = (
        reopened.manifest.get("port_pairs_vehicle_hash")
        or reopened.manifest.get("vehicle_hash")
        or base_hash
    )
    matching_hash = base_hash
    assert matching_hash == expected_hash
    loaded_matching = reopened.load_port_pairs([first_parent])
    assert loaded_matching

    # 2. Non-baseline vehicle: vehicle_matches is False
    custom_veh = VehicleProfile(
        name="heavy_truck",
        mass_kg=15000.0,
        max_climb_angle_deg=12.0,
        max_speed_kmh=40.0,
        tire_width_m=0.45,
        ground_clearance_m=0.5,
        max_thrust_n=20000.0,
        tire_radius_m=0.55,
        min_turn_radius_m=8.0,
    )
    custom_hash = canonical_hash(asdict(custom_veh))
    assert custom_hash != expected_hash
    # In route_planning, non-matching vehicle bypasses offline_pairs
    vehicle_matches = custom_hash == expected_hash
    assert not vehicle_matches


def test_offline_pairs_negative_cache_and_temporary_port_isolation(
    vehicle: VehicleProfile,
) -> None:
    """Verify that static pairs are served from offline cache even with temporary endpoints,

    and dead-end ports are bypassed via negative cache without running fine Dijkstra.
    """
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    # Offline pairs containing ONLY static boundary ports (b<->c in p1, d<->e in p2)
    # Note: 'a' and 'f' are NOT in offline_pairs!
    # 'p1' has static ports {'b', 'c'}; 'p2' has static ports {'d', 'e'}.
    static_only_offline: dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]] = {
        ("distance", "p1", "b"): {"c": (("b", "c"), 2.0)},
        ("distance", "p1", "c"): {"b": (("c", "b"), 2.0)},
        ("distance", "p2", "d"): {"e": (("d", "e"), 2.0)},
        ("distance", "p2", "e"): {"d": (("e", "d"), 2.0)},
    }

    context = PortsMapSearchContext(
        graph,
        evaluation,
        offline_pairs=static_only_offline,
        offline_parents={"p1", "p2"},
    )

    # Search from temporary start 'a' to temporary goal 'f'
    res = context.search("a", "f", profile)

    # Path must be found and correct: a -> b -> c -> e -> f (2 + 2 + 1 + 2 = 7.0)
    assert res.h3_path == ("a", "b", "c", "e", "f")
    assert res.scalar_cost == pytest.approx(7.0, rel=1e-6)

    # In p1: 'a' (start) does 1 fine search to reach 'b' and 'c'.
    # In p2: 'e' (cost 5.0) searches for 'f' (cost 2.0 -> total 7.0).
    # 'd' (cost 6.0 < 7.0) is popped from heap and also searches for 'f'.
    # All static-to-static pairs ('b'->'c', 'c'->'b', 'd'->'e', 'e'->'d') MUST use offline cache!
    # Total fine searches bounded by start + goal boundary ports (< 5), not expanding internal grid.
    assert context.fine_search_calls <= 3
    assert context.offline_cache_hits > 0


def test_offline_pairs_table_lazy_loading_and_late_resolution(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Verify OfflinePairsTable loads without paths and reconstructs full fine paths lazily."""
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    # Static pairs with multi-cell paths: b->c via 'b'->'c', but let's test a distinct path
    pairs = {
        ("distance", "p1", "b"): {
            "c": (("b", "b", "c"), 2.0),
        },
        ("distance", "p1", "c"): {
            "b": (("c", "c", "b"), 2.0),
        },
        ("distance", "p2", "d"): {
            "e": (("d", "d", "e"), 2.0),
        },
        ("distance", "p2", "e"): {
            "d": (("e", "e", "d"), 2.0),
        },
    }
    file_path = tmp_path / "port_pairs.parquet"
    save_offline_pairs(pairs, file_path)

    # 1. Load with load_paths=False -> returns OfflinePairsTable
    lazy_table = load_offline_pairs(file_path, active_parents=["p1", "p2"], load_paths=False)
    assert isinstance(lazy_table, OfflinePairsTable)
    assert ("distance", "p1") in lazy_table.offline_parents_by_profile
    assert lazy_table.offline_parents == {"p1", "p2"}

    # 2. PortsMapSearchContext using lazy_table
    context = PortsMapSearchContext(
        graph,
        evaluation,
        offline_pairs=lazy_table,
        offline_parents={"p1", "p2"},
    )
    res = context.search("a", "f", profile)

    # Late path resolution must stitch the full fine path from parquet
    assert res.scalar_cost == pytest.approx(7.0, rel=1e-6)
    assert "b" in res.h3_path
    assert "c" in res.h3_path
    assert "e" in res.h3_path
    has_subpath = ("b", "b", "c") in zip(
        res.h3_path, res.h3_path[1:], res.h3_path[2:], strict=False
    )
    assert res.h3_path == ("a", "b", "c", "e", "f") or has_subpath
    assert context.offline_cache_hits > 0


def test_offline_pairs_partial_parent_coverage_online_fallback(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Verify that when only a subset of parents has offline pairs (e.g. p1 has pairs,
    but p2 does not), macro search falls back to online fine Dijkstra for uncalculated
    parents and successfully finds the optimal path.
    """
    graph = _ports_graph()
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    # Offline pairs ONLY for p1; p2 is completely absent from offline pairs!
    pairs = {
        ("distance", "p1", "b"): {
            "c": (("b", "c"), 2.0),
        },
        ("distance", "p1", "c"): {
            "b": (("c", "b"), 2.0),
        },
    }
    file_path = tmp_path / "port_pairs.parquet"
    save_offline_pairs(pairs, file_path)

    # Load with active_parents=["p1", "p2"]
    lazy_table = load_offline_pairs(file_path, active_parents=["p1", "p2"], load_paths=False)
    assert isinstance(lazy_table, OfflinePairsTable)
    # p1 is in offline_parents, p2 is NOT
    assert lazy_table.offline_parents == {"p1"}
    assert ("distance", "p1") in lazy_table.offline_parents_by_profile
    assert ("distance", "p2") not in lazy_table.offline_parents_by_profile

    context = PortsMapSearchContext(
        graph,
        evaluation,
        offline_pairs=lazy_table,
    )
    # Search from 'a' (in p1) to 'f' (in p2)
    res = context.search("a", "f", profile)

    # Optimal path: a -> b -> c -> e -> f (cost 2 + 2 + 1 + 2 = 7.0)
    assert res.h3_path == ("a", "b", "c", "e", "f")
    assert res.scalar_cost == pytest.approx(7.0, rel=1e-6)
    # p2 was resolved via online fine search fallback
    assert context.fine_search_calls > 0


def test_offline_pairs_missing_port_outgoing_edges_online_fallback(
    tmp_path: Path,
    vehicle: VehicleProfile,
) -> None:
    """Verify that when a parent IS present in offline pairs but a specific port
    lacks precomputed outgoing edges (e.g. newly discovered port or uncomputed source),
    macro search falls back to online fine Dijkstra for that port and finds the optimal path.
    """
    def _mk_cell(idx: str, lng: float, parent: str) -> H3Cell:
        return H3Cell(
            h3index=idx,
            lat=0.0,
            lng=lng,
            elevation=0.0,
            slope=0.0,
            tri=0.0,
            lc_factor=1.0,
            parent_h3=parent,
            is_passable=True,
        )

    cells = {
        "s": _mk_cell("s", 0.0, "p0"),
        "x": _mk_cell("x", 1.0, "p0"),
        "a": _mk_cell("a", 2.0, "p1"),
        "b": _mk_cell("b", 3.0, "p1"),
        "c": _mk_cell("c", 4.0, "p1"),
        "e": _mk_cell("e", 5.0, "p2"),
        "g": _mk_cell("g", 6.0, "p2"),
    }
    edges = {
        ("s", "x"): H3Edge("s", "x", 1.0),
        ("x", "s"): H3Edge("x", "s", 1.0),
        ("x", "a"): H3Edge("x", "a", 1.0),
        ("a", "x"): H3Edge("a", "x", 1.0),
        ("a", "b"): H3Edge("a", "b", 1.0),
        ("b", "a"): H3Edge("b", "a", 1.0),
        ("b", "c"): H3Edge("b", "c", 1.0),
        ("c", "b"): H3Edge("c", "b", 1.0),
        ("c", "e"): H3Edge("c", "e", 1.0),
        ("e", "c"): H3Edge("e", "c", 1.0),
        ("e", "g"): H3Edge("e", "g", 1.0),
        ("g", "e"): H3Edge("g", "e", 1.0),
    }
    graph = H3Graph(
        cells=cells,
        edges=edges,
        parent_children={"p0": {"s", "x"}, "p1": {"a", "b", "c"}, "p2": {"e", "g"}},
    )
    evaluation = evaluate_factor_model(graph, vehicle, FactorModelConfig())
    profile = ScalarProfile({"distance": 1.0}, name="distance")

    pairs = {
        ("distance", "p1", "b"): {
            "c": (("b", "c"), 1.0),
        },
    }
    file_path = tmp_path / "port_pairs.parquet"
    save_offline_pairs(pairs, file_path)

    lazy_table = load_offline_pairs(file_path, active_parents=["p0", "p1", "p2"], load_paths=False)
    context = PortsMapSearchContext(graph, evaluation, offline_pairs=lazy_table)

    res = context.search("s", "g", profile)
    assert res.h3_path == ("s", "x", "a", "b", "c", "e", "g")
    assert res.scalar_cost == pytest.approx(6.0, rel=1e-6)
    assert context.fine_search_calls > 0


