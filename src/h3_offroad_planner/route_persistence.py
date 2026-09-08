"""Atomic RoutePlan/selection persistence and GIS delivery artifact writers."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import warnings
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from h3_offroad_planner.factor_model import PathMetrics
from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, PlanningInputError
from h3_offroad_planner.route_models import (
    PATH_ROLES,
    BlockageRecord,
    RouteCandidate,
    RoutePlan,
    RouteSelection,
)

__all__ = [
    "atomic_write_json",
    "delivery_output_paths",
    "load_route_plan",
    "load_route_selection",
    "load_route_graph_snapshot",
    "select_route",
    "write_route_plan_outputs",
    "write_active_route_state",
]

CRS_WGS84: str = "EPSG:4326"
GRAPH_EDGE_TABLE: str = "h3_edges"
LEGACY_DUPLICATE_OUTPUTS: tuple[str, ...] = (
    "route_candidates.geojson",
    "route_recommended.geojson",
    "style_manifest.json",
)


def delivery_output_paths(output_dir: str) -> dict[str, str]:
    """Return the fixed file contract for one complete delivery directory."""
    root = Path(output_dir)
    names = (
        "effective_vehicle.yaml",
        "effective_factor_model.yaml",
        "tile_manifest.json",
        "route_manifest.json",
        "route_plan.json",
        "routes.gpkg",
        "route_selection.json",
        "selected_route.geojson",
        "active_route.geojson",
        "replan_history.jsonl",
    )
    return {Path(name).stem: str(root / name) for name in names}


def _safe_replace_file(temporary: Path, target: Path) -> Path:
    """Replace target with temporary, falling back to timestamped copy if target is locked by external processes."""
    try:
        temporary.replace(target)
        return target
    except OSError as exc:
        for _ in range(3):
            time.sleep(0.1)
            try:
                temporary.replace(target)
                return target
            except OSError:
                pass
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = target.with_name(f"{target.stem}_{timestamp}{target.suffix}")
        try:
            temporary.replace(fallback)
            warnings.warn(
                f"Target file {target.name} is locked by an external application; "
                f"saved to {fallback.name} instead: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return fallback
        except OSError:
            raise exc


def atomic_write_json(path: str | Path, payload: object) -> None:
    """Write canonical ordered JSON via same-directory temporary replacement."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    _safe_replace_file(temporary, output)


def write_route_plan_outputs(
    plan: RoutePlan,
    graph: H3Graph,
    output_dir: str,
    tile_manifest: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Write RoutePlan JSON, GeoJSON, GPKG and style/manifest artifacts atomically."""
    paths = delivery_output_paths(output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    actual_routes_path = _write_routes_gpkg(paths["routes"], graph, plan)
    paths["routes"] = actual_routes_path
    output_files = dict(plan.output_files)
    output_files["routes"] = actual_routes_path
    object.__setattr__(plan, "output_files", output_files)
    atomic_write_json(paths["route_plan"], plan.to_dict())
    atomic_write_json(
        paths["route_manifest"],
        {
            "schema_version": 2,
            "plan_id": plan.plan_id,
            "planner_name": plan.planner_name,
            "candidate_count": len(plan.candidates),
            "recommended_candidate_id": plan.recommended_candidate_id,
            "vehicle_hash": plan.vehicle_hash,
            "factor_model_hash": plan.factor_model_hash,
            "static_input_hash": plan.static_input_hash,
            "graph_topology_hash": plan.graph_topology_hash,
            "output_files": output_files,
            "graph_storage": {
                "format": "gpkg",
                "path": Path(actual_routes_path).name,
                "cells_layer": "h3_static_facts",
                "edges_table": GRAPH_EDGE_TABLE,
                "resolution_fine": graph.resolution_fine,
                "resolution_coarse": graph.resolution_coarse,
            },
        },
    )
    if tile_manifest is not None:
        cleaned = {key: value for key, value in tile_manifest.items() if key != "source_manifest"}
        atomic_write_json(paths["tile_manifest"], cleaned)
    _remove_legacy_duplicate_outputs(Path(output_dir))
    return paths


def load_route_plan(path: str) -> RoutePlan:
    """Load and validate a persisted RoutePlan, isolating corrupt JSON on failure."""
    payload = _load_json_object(Path(path), isolate_corrupt=True)
    candidates_raw = payload.get("candidates")
    if not isinstance(candidates_raw, list):
        raise PlanningInputError("RoutePlan candidates must be an array.")
    candidates = tuple(_candidate_from_mapping(item) for item in candidates_raw)
    return RoutePlan(
        plan_id=_required_string(payload, "plan_id"),
        mission_profile=_required_string(payload, "mission_profile"),
        recommended_candidate_id=_required_string(payload, "recommended_candidate_id"),
        independence_reference_candidate_id=_optional_string(
            payload,
            "independence_reference_candidate_id",
        ),
        vehicle_hash=_required_string(payload, "vehicle_hash"),
        factor_model_hash=_required_string(payload, "factor_model_hash"),
        static_input_hash=_required_string(payload, "static_input_hash"),
        graph_topology_hash=_required_string(payload, "graph_topology_hash"),
        candidates=candidates,
        aggregation_stats=_mapping(payload, "aggregation_stats"),
        output_files=_string_mapping(payload, "output_files"),
        warnings=tuple(_string_sequence(payload, "warnings")),
        planner_name=_required_string(payload, "planner_name"),
        schema_version=_required_int(payload, "schema_version"),
    )


def load_route_selection(path: str) -> RouteSelection:
    """Load and validate persisted explicit route selection state."""
    payload = _load_json_object(Path(path), isolate_corrupt=True)
    active_path = tuple(_string_sequence(payload, "active_h3_path"))
    return RouteSelection(
        plan_id=_required_string(payload, "plan_id"),
        candidate_id=_required_string(payload, "candidate_id"),
        selected_role=_required_string(payload, "selected_role"),
        active_h3_path=active_path,
        active_metrics=_metrics_from_mapping(_mapping(payload, "active_metrics")),
        vehicle_hash=_required_string(payload, "vehicle_hash"),
        factor_model_hash=_required_string(payload, "factor_model_hash"),
        static_input_hash=_required_string(payload, "static_input_hash"),
        graph_topology_hash=_required_string(payload, "graph_topology_hash"),
        state=_required_string(payload, "state"),
        replan_version=_required_int(payload, "replan_version"),
        selection_version=_required_int(payload, "selection_version"),
    )


def load_route_graph_snapshot(path: str) -> H3Graph:
    """Restore a graph from compact GPKG storage or a legacy JSON snapshot."""
    manifest_path = Path(path)
    payload = _load_json_object(manifest_path, isolate_corrupt=True)
    snapshot = payload.get("graph_snapshot")
    if isinstance(snapshot, dict):
        return _graph_from_json_snapshot(cast(dict[str, object], snapshot))
    storage = _mapping(payload, "graph_storage")
    if _required_string(storage, "format") != "gpkg":
        raise PlanningInputError("route graph storage format must be 'gpkg'.")
    graph_path = Path(_required_string(storage, "path"))
    if not graph_path.is_absolute():
        graph_path = manifest_path.parent / graph_path
    return _graph_from_gpkg(graph_path, storage)


def _graph_from_json_snapshot(snapshot: Mapping[str, object]) -> H3Graph:
    """Restore the legacy embedded JSON graph representation."""
    cells_raw = snapshot.get("cells")
    edges_raw = snapshot.get("edges")
    if not isinstance(cells_raw, list) or not isinstance(edges_raw, list):
        raise PlanningInputError("graph snapshot cells and edges must be arrays.")
    cells = {
        _required_string(item, "h3index"): _cell_from_mapping(item)
        for item in _objects(cells_raw)
    }
    edges = {}
    for item in _objects(edges_raw):
        edge = _edge_from_mapping(item)
        edges[(edge.cell_a, edge.cell_b)] = edge
    parent_children: dict[str, set[str]] = {}
    for cell in cells.values():
        parent_children.setdefault(cell.parent_h3, set()).add(cell.h3index)
    return H3Graph(
        resolution_fine=_required_int(snapshot, "resolution_fine"),
        resolution_coarse=_required_int(snapshot, "resolution_coarse"),
        cells=cells,
        edges=edges,
        parent_children=parent_children,
    )


def _graph_from_gpkg(path: Path, storage: Mapping[str, object]) -> H3Graph:
    """Restore the canonical graph from one relocatable GeoPackage."""
    if not path.is_file():
        raise PlanningInputError(f"route graph GeoPackage does not exist: {path}")
    cells_layer = _required_string(storage, "cells_layer")
    edges_table = _required_string(storage, "edges_table")
    if cells_layer != "h3_static_facts" or edges_table != GRAPH_EDGE_TABLE:
        raise PlanningInputError("route graph GeoPackage schema is unsupported.")
    try:
        frame = gpd.read_file(path, layer=cells_layer)
    except (OSError, ValueError) as exc:
        raise PlanningInputError(f"route graph cells are unreadable: {path}") from exc
    required = {
        "h3index",
        "parent_h3",
        "elevation",
        "slope",
        "tri",
        "lc_factor",
        "lc_factor_infinite",
        "landcover_code",
        "landcover_type",
        "soil_code",
        "soil_type",
        "soil_texture",
        "uscs",
        "soil_moisture",
        "has_road",
        "static_passable",
        "geometry",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise PlanningInputError(f"route graph cells omit fields: {sorted(missing)}")
    cells: dict[str, H3Cell] = {}
    ordered_columns = [*sorted(required - {"geometry"}), "geometry"]
    for values in frame[ordered_columns].itertuples(
        index=False,
        name=None,
    ):
        record = dict(zip(ordered_columns, values, strict=True))
        geometry = record["geometry"]
        if not isinstance(geometry, Point):
            raise PlanningInputError("route graph cell geometry must be a Point.")
        cell_id = _gpkg_string(record["h3index"], "h3index")
        infinite = bool(record["lc_factor_infinite"])
        cells[cell_id] = H3Cell(
            h3index=cell_id,
            lat=float(geometry.y),
            lng=float(geometry.x),
            elevation=_gpkg_float(record["elevation"], "elevation"),
            slope=_gpkg_float(record["slope"], "slope"),
            tri=_gpkg_float(record["tri"], "tri"),
            lc_factor=(
                float("inf")
                if infinite
                else _gpkg_float(record["lc_factor"], "lc_factor")
            ),
            landcover_code=_gpkg_optional_int(record["landcover_code"]),
            landcover_type=_gpkg_optional_string(record["landcover_type"]),
            soil_code=_gpkg_optional_int(record["soil_code"]),
            soil_type=_gpkg_optional_string(record["soil_type"]),
            soil_texture=_gpkg_optional_string(record["soil_texture"]),
            uscs=_gpkg_optional_string(record["uscs"]),
            soil_moisture=_gpkg_optional_float(record["soil_moisture"]),
            has_road=bool(record["has_road"]),
            parent_h3=_gpkg_string(record["parent_h3"], "parent_h3", allow_empty=True),
            is_passable=bool(record["static_passable"]),
        )
    database = sqlite3.connect(path)
    try:
        cursor = database.execute(
            "SELECT cell_a, cell_b, geo_distance, has_road, "
            "slope_a_to_b, slope_b_to_a FROM h3_edges"
        )
        try:
            edges = {
                (str(row[0]), str(row[1])): H3Edge(
                    cell_a=str(row[0]),
                    cell_b=str(row[1]),
                    geo_distance=float(row[2]),
                    has_road=bool(row[3]),
                    slope_a_to_b=float(row[4]),
                    slope_b_to_a=float(row[5]),
                )
                for row in cursor
            }
        finally:
            cursor.close()
    except sqlite3.Error as exc:
        raise PlanningInputError(f"route graph edges are unreadable: {path}") from exc
    finally:
        database.close()
    parent_children: dict[str, set[str]] = {}
    for cell in cells.values():
        parent_children.setdefault(cell.parent_h3, set()).add(cell.h3index)
    return H3Graph(
        resolution_fine=_required_int(storage, "resolution_fine"),
        resolution_coarse=_required_int(storage, "resolution_coarse"),
        cells=cells,
        edges=edges,
        parent_children=parent_children,
    )


def _gpkg_string(value: object, key: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise PlanningInputError(f"route graph field {key!r} must be a string.")
    return value


def _gpkg_float(value: object, key: str) -> float:
    if isinstance(value, bool) or _is_missing_table_value(value):
        raise PlanningInputError(f"route graph field {key!r} must be numeric.")
    try:
        return float(cast(float, value))
    except (TypeError, ValueError) as exc:
        raise PlanningInputError(f"route graph field {key!r} must be numeric.") from exc


def _gpkg_optional_float(value: object) -> float | None:
    return None if _is_missing_table_value(value) else _gpkg_float(value, "optional_float")


def _gpkg_optional_int(value: object) -> int | None:
    if _is_missing_table_value(value):
        return None
    numeric = _gpkg_float(value, "optional_int")
    if not numeric.is_integer():
        raise PlanningInputError("route graph optional integer field is invalid.")
    return int(numeric)


def _gpkg_optional_string(value: object) -> str | None:
    if _is_missing_table_value(value):
        return None
    return _gpkg_string(value, "optional_string")


def _is_missing_table_value(value: object) -> bool:
    if value is None:
        return True
    return bool(pd.isna(cast(Any, value)))


def _remove_legacy_duplicate_outputs(root: Path) -> None:
    """Remove obsolete reproducible formats after canonical outputs succeed."""
    for name in LEGACY_DUPLICATE_OUTPUTS:
        (root / name).unlink(missing_ok=True)


def write_active_route_state(
    output_dir: str,
    selection: RouteSelection,
    graph: H3Graph,
    blockages: tuple[BlockageRecord, ...],
) -> None:
    """Atomically replace active GeoJSON and corresponding GPKG state layers."""
    root = Path(output_dir)
    feature = _active_feature(selection, graph)
    atomic_write_json(root / "active_route.geojson", feature)
    gpkg = root / "routes.gpkg"
    if not gpkg.exists():
        return
    temporary = gpkg.with_name(f".{gpkg.stem}.active.tmp.gpkg")
    shutil.copy2(gpkg, temporary)
    _feature_gdf(feature).to_file(temporary, layer="route_active", driver="GPKG", mode="w")
    confirmed = tuple(record for record in blockages if record.state == "confirmed")
    _blockage_gdf(confirmed, graph).to_file(
        temporary,
        layer="confirmed_blockages",
        driver="GPKG",
        mode="w",
    )
    _safe_replace_file(temporary, gpkg)


def select_route(
    plan_path: str,
    candidate_id: str | None = None,
    role: str | None = None,
    expected_selection_version: int | None = None,
) -> RouteSelection:
    """Explicitly activate one plan candidate by stable id or assigned role."""
    if (candidate_id is None) == (role is None):
        raise ValueError("provide exactly one of candidate_id or role.")
    if role is not None and role not in PATH_ROLES:
        raise ValueError("role is not a known candidate role.")
    plan = load_route_plan(plan_path)
    candidate = _selected_candidate(plan, candidate_id, role)
    selected_role = role or candidate.roles[0]
    root = Path(plan_path).parent
    selection_path = root / "route_selection.json"
    existing = _existing_selection(selection_path)
    if existing is not None:
        if (
            expected_selection_version is not None
            and existing.selection_version != expected_selection_version
        ):
            raise PlanningInputError("ROUTE_SELECTION_VERSION_CONFLICT")
        if (
            existing.plan_id == plan.plan_id
            and existing.candidate_id == candidate.candidate_id
            and existing.selected_role == selected_role
        ):
            return existing
    version = 1 if existing is None else existing.selection_version + 1
    selection = RouteSelection(
        plan_id=plan.plan_id,
        candidate_id=candidate.candidate_id,
        selected_role=selected_role,
        active_h3_path=candidate.h3_path,
        active_metrics=candidate.metrics,
        vehicle_hash=plan.vehicle_hash,
        factor_model_hash=plan.factor_model_hash,
        static_input_hash=plan.static_input_hash,
        graph_topology_hash=plan.graph_topology_hash,
        selection_version=version,
    )
    atomic_write_json(selection_path, selection.to_dict())
    feature = _candidate_feature(candidate)
    atomic_write_json(root / "selected_route.geojson", feature)
    atomic_write_json(root / "active_route.geojson", feature)
    _replace_active_gpkg_layers(root / "routes.gpkg", feature)
    return selection


def _cell_from_mapping(payload: Mapping[str, object]) -> H3Cell:
    lc_raw = payload.get("lc_factor")
    lc_factor = float("inf") if lc_raw == "inf" else _number(lc_raw, "lc_factor")
    return H3Cell(
        h3index=_required_string(payload, "h3index"),
        lat=_required_float(payload, "lat"),
        lng=_required_float(payload, "lng"),
        elevation=_required_float(payload, "elevation"),
        slope=_required_float(payload, "slope"),
        tri=_required_float(payload, "tri"),
        lc_factor=lc_factor,
        landcover_code=_optional_int(payload, "landcover_code"),
        landcover_type=_optional_string(payload, "landcover_type"),
        soil_code=_optional_int(payload, "soil_code"),
        soil_type=_optional_string(payload, "soil_type"),
        soil_texture=_optional_string(payload, "soil_texture"),
        uscs=_optional_string(payload, "uscs"),
        soil_moisture=_optional_float(payload, "soil_moisture"),
        has_road=_required_bool(payload, "has_road"),
        parent_h3=_string_allow_empty(payload, "parent_h3"),
        is_passable=_required_bool(payload, "is_passable"),
    )


def _edge_from_mapping(payload: Mapping[str, object]) -> H3Edge:
    return H3Edge(
        cell_a=_required_string(payload, "cell_a"),
        cell_b=_required_string(payload, "cell_b"),
        geo_distance=_required_float(payload, "geo_distance"),
        has_road=_required_bool(payload, "has_road"),
        slope_a_to_b=_required_float(payload, "slope_a_to_b"),
        slope_b_to_a=_required_float(payload, "slope_b_to_a"),
    )


def _active_feature(selection: RouteSelection, graph: H3Graph) -> dict[str, object]:
    coordinates = [
        [graph.cells[cell_id].lng, graph.cells[cell_id].lat]
        for cell_id in selection.active_h3_path
    ]
    return {
        "type": "Feature",
        "properties": {
            "plan_id": selection.plan_id,
            "candidate_id": selection.candidate_id,
            "selected_role": selection.selected_role,
            "state": selection.state,
            "replan_version": selection.replan_version,
            **selection.active_metrics.to_dict(),
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def _feature_gdf(feature: dict[str, object]) -> gpd.GeoDataFrame:
    geometry = cast(dict[str, object], feature["geometry"])
    properties = cast(dict[str, object], feature["properties"])
    coordinates = cast(list[list[float]], geometry["coordinates"])
    return gpd.GeoDataFrame(
        [properties],
        geometry=[LineString(coordinates)],
        crs=CRS_WGS84,
    )


def _blockage_gdf(
    records: tuple[BlockageRecord, ...],
    graph: H3Graph,
) -> gpd.GeoDataFrame:
    rows = []
    geometries = []
    for record in records:
        if record.h3index not in graph.cells:
            continue
        cell = graph.cells[record.h3index]
        rows.append(
            {
                "blockage_id": record.blockage_id,
                "h3index": record.h3index,
                "state": record.state,
                "confirmation_count": record.confirmation_count,
                "source": record.source,
            }
        )
        geometries.append(Point(cell.lng, cell.lat))
    if not rows:
        return _empty_blockage_gdf()
    return gpd.GeoDataFrame(rows, geometry=geometries, crs=CRS_WGS84)


def _write_routes_gpkg(path: str, graph: H3Graph, plan: RoutePlan) -> str:
    output = Path(path)
    temporary = output.with_name(f".{output.stem}.tmp.gpkg")
    if temporary.exists():
        temporary.unlink()
    _static_facts_gdf(graph).to_file(temporary, layer="h3_static_facts", driver="GPKG")
    candidate_gdf = _candidate_gdf(plan.candidates)
    candidate_gdf.to_file(temporary, layer="route_candidates", driver="GPKG", mode="a")
    recommended = tuple(
        candidate
        for candidate in plan.candidates
        if candidate.candidate_id == plan.recommended_candidate_id
    )
    _candidate_gdf(recommended).to_file(
        temporary,
        layer="route_recommended",
        driver="GPKG",
        mode="a",
    )
    for layer in ("route_selected", "route_active"):
        _empty_route_gdf().to_file(temporary, layer=layer, driver="GPKG", mode="a")
    _empty_blockage_gdf().to_file(
        temporary,
        layer="confirmed_blockages",
        driver="GPKG",
        mode="a",
    )
    _write_graph_edge_table(temporary, graph)
    return str(_safe_replace_file(temporary, output))


def _write_graph_edge_table(path: Path, graph: H3Graph) -> None:
    """Append graph edges as one compact non-spatial GeoPackage attribute table."""
    database = sqlite3.connect(path)
    try:
        database.execute(f"DROP TABLE IF EXISTS {GRAPH_EDGE_TABLE}")
        database.execute(
            f"""
            CREATE TABLE {GRAPH_EDGE_TABLE} (
                cell_a TEXT NOT NULL,
                cell_b TEXT NOT NULL,
                geo_distance REAL NOT NULL,
                has_road INTEGER NOT NULL,
                slope_a_to_b REAL NOT NULL,
                slope_b_to_a REAL NOT NULL,
                PRIMARY KEY (cell_a, cell_b)
            )
            """
        )
        database.executemany(
            f"INSERT INTO {GRAPH_EDGE_TABLE} VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    edge.cell_a,
                    edge.cell_b,
                    edge.geo_distance,
                    int(edge.has_road),
                    edge.slope_a_to_b,
                    edge.slope_b_to_a,
                )
                for edge in graph.edges.values()
            ),
        )
        database.execute(
            "DELETE FROM gpkg_contents WHERE table_name = ?",
            (GRAPH_EDGE_TABLE,),
        )
        database.execute(
            "INSERT INTO gpkg_contents "
            "(table_name, data_type, identifier, description) VALUES (?, ?, ?, ?)",
            (
                GRAPH_EDGE_TABLE,
                "attributes",
                GRAPH_EDGE_TABLE,
                "H3 graph edges for exact route replanning",
            ),
        )
        database.commit()
    finally:
        database.close()


def _replace_active_gpkg_layers(path: Path, feature: dict[str, object]) -> None:
    if not path.exists():
        return
    temporary = path.with_name(f".{path.stem}.selection.tmp.gpkg")
    shutil.copy2(path, temporary)
    geometry = cast(dict[str, object], feature["geometry"])
    properties = cast(dict[str, object], feature["properties"])
    coordinates = cast(list[list[float]], geometry["coordinates"])
    frame = gpd.GeoDataFrame(
        [properties],
        geometry=[LineString(coordinates)],
        crs=CRS_WGS84,
    )
    for layer in ("route_selected", "route_active"):
        frame.to_file(temporary, layer=layer, driver="GPKG", mode="w")
    _safe_replace_file(temporary, path)


def _static_facts_gdf(graph: H3Graph) -> gpd.GeoDataFrame:
    records = []
    geometries = []
    for cell_id in sorted(graph.cells):
        cell = graph.cells[cell_id]
        records.append(
            {
                "h3index": cell.h3index,
                "parent_h3": cell.parent_h3,
                "elevation": cell.elevation,
                "slope": cell.slope,
                "tri": cell.tri,
                "lc_factor": None if cell.lc_factor == float("inf") else cell.lc_factor,
                "lc_factor_infinite": cell.lc_factor == float("inf"),
                "landcover_code": cell.landcover_code,
                "landcover_type": cell.landcover_type,
                "soil_code": cell.soil_code,
                "soil_type": cell.soil_type,
                "soil_texture": cell.soil_texture,
                "uscs": cell.uscs,
                "soil_moisture": cell.soil_moisture,
                "has_road": cell.has_road,
                "static_passable": cell.is_passable,
                "authority_for_new_routing": True,
            }
        )
        geometries.append(Point(cell.lng, cell.lat))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=CRS_WGS84)


def _candidate_gdf(candidates: tuple[RouteCandidate, ...]) -> gpd.GeoDataFrame:
    records = []
    geometries = []
    for candidate in candidates:
        feature = _candidate_feature(candidate)
        geometry = cast(dict[str, object], feature["geometry"])
        coordinates = cast(list[list[float]], geometry["coordinates"])
        records.append(cast(dict[str, object], feature["properties"]))
        geometries.append(LineString(coordinates))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=CRS_WGS84)


def _empty_route_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "candidate_id": pd.Series(dtype="str"),
            "roles": pd.Series(dtype="str"),
        },
        geometry=gpd.GeoSeries([], crs=CRS_WGS84),
        crs=CRS_WGS84,
    )


def _empty_blockage_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "blockage_id": pd.Series(dtype="str"),
            "h3index": pd.Series(dtype="str"),
            "state": pd.Series(dtype="str"),
        },
        geometry=gpd.GeoSeries([], crs=CRS_WGS84),
        crs=CRS_WGS84,
    )


def _candidate_feature(candidate: RouteCandidate) -> dict[str, object]:
    geometry = dict(cast(Mapping[str, object], candidate.geojson.get("geometry", {})))
    return {
        "type": "Feature",
        "properties": {
            "candidate_id": candidate.candidate_id,
            "roles": ",".join(candidate.roles),
            "is_recommended": candidate.is_recommended,
            "eta_s": candidate.metrics.eta_s,
            "eta_lower_s": candidate.metrics.eta_lower_s,
            "eta_upper_s": candidate.metrics.eta_upper_s,
            "distance_m": candidate.metrics.distance_m,
            "score_lower_min": candidate.metrics.safety_margin_min,
            "terrain_risk": candidate.metrics.terrain_risk,
            "travel_cost": candidate.metrics.travel_cost,
            "generation_profile": candidate.generation_profile,
            "replan_profile": candidate.replan_profile,
        },
        "geometry": geometry,
    }


def _candidate_from_mapping(value: object) -> RouteCandidate:
    if not isinstance(value, dict):
        raise PlanningInputError("RoutePlan candidate entries must be objects.")
    payload = cast(dict[str, object], value)
    return RouteCandidate(
        candidate_id=_required_string(payload, "candidate_id"),
        h3_path=tuple(_string_sequence(payload, "h3_path")),
        roles=tuple(_string_sequence(payload, "roles")),
        is_recommended=_required_bool(payload, "is_recommended"),
        objectives=_float_mapping(payload, "objectives"),
        metrics=_metrics_from_mapping(_mapping(payload, "metrics")),
        corridor_signature=tuple(_string_sequence(payload, "corridor_signature")),
        independence_evidence=_mapping(payload, "independence_evidence"),
        geojson=_mapping(payload, "geojson"),
        generation_profile=_required_string(payload, "generation_profile"),
        replan_profile=_required_string(payload, "replan_profile"),
    )


def _metrics_from_mapping(payload: Mapping[str, object]) -> PathMetrics:
    eta_upper_raw = payload.get("eta_upper_s")
    eta_upper = None if eta_upper_raw is None else _number(eta_upper_raw, "eta_upper_s")
    return PathMetrics(
        distance_m=_required_float(payload, "distance_m"),
        eta_lower_s=_required_float(payload, "eta_lower_s"),
        eta_s=_required_float(payload, "eta_s"),
        eta_upper_s=eta_upper,
        eta_upper_bounded=_required_bool(payload, "eta_upper_bounded"),
        terrain_risk=_required_float(payload, "terrain_risk"),
        travel_cost=_required_float(payload, "travel_cost"),
        safety_margin_min=_required_float(payload, "score_lower_min"),
        safety_margin_mean=_required_float(payload, "score_nominal_mean"),
        edge_count=_required_int(payload, "edge_count"),
    )


def _selected_candidate(
    plan: RoutePlan,
    candidate_id: str | None,
    role: str | None,
) -> RouteCandidate:
    if candidate_id is not None:
        selected = next(
            (candidate for candidate in plan.candidates if candidate.candidate_id == candidate_id),
            None,
        )
    else:
        selected = next(
            (candidate for candidate in plan.candidates if role in candidate.roles),
            None,
        )
    if selected is None:
        raise PlanningInputError("selected route candidate or role is absent from RoutePlan.")
    return selected


def _existing_selection(path: Path) -> RouteSelection | None:
    return load_route_selection(str(path)) if path.exists() else None


def _load_json_object(path: Path, isolate_corrupt: bool) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if isolate_corrupt:
            _isolate_corrupt(path)
        raise PlanningInputError(f"state JSON is unreadable and was isolated: {path}") from exc
    if not isinstance(payload, dict):
        if isolate_corrupt:
            _isolate_corrupt(path)
        raise PlanningInputError(f"state JSON must be an object and was isolated: {path}")
    return cast(dict[str, object], payload)


def _isolate_corrupt(path: Path) -> None:
    candidate = path.with_suffix(f"{path.suffix}.corrupt")
    index = 1
    while candidate.exists():
        candidate = path.with_suffix(f"{path.suffix}.corrupt.{index}")
        index += 1
    path.replace(candidate)


def _mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise PlanningInputError(f"state field {key!r} must be an object.")
    return cast(dict[str, object], value)


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PlanningInputError(f"state field {key!r} must be a non-empty string.")
    return value


def _string_allow_empty(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise PlanningInputError(f"state field {key!r} must be a string.")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise PlanningInputError(f"state field {key!r} must be null or a non-empty string.")
    return value


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"state field {key!r} must be null or an integer.")
    return value


def _optional_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    return None if value is None else _number(value, key)


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise PlanningInputError(f"state field {key!r} must be boolean.")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"state field {key!r} must be an integer.")
    return value


def _required_float(payload: Mapping[str, object], key: str) -> float:
    if key not in payload:
        raise PlanningInputError(f"state field {key!r} is required.")
    return _number(payload[key], key)


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"state field {key!r} must be numeric.")
    return float(value)


def _string_sequence(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise PlanningInputError(f"state field {key!r} must be an array of strings.")
    return cast(list[str], value)


def _string_mapping(payload: Mapping[str, object], key: str) -> dict[str, str]:
    value = _mapping(payload, key)
    if any(not isinstance(item, str) for item in value.values()):
        raise PlanningInputError(f"state field {key!r} values must be strings.")
    return cast(dict[str, str], value)


def _float_mapping(payload: Mapping[str, object], key: str) -> dict[str, float]:
    value = _mapping(payload, key)
    return {name: _number(item, f"{key}.{name}") for name, item in value.items()}


def _objects(values: list[object]) -> list[dict[str, object]]:
    if any(not isinstance(value, dict) for value in values):
        raise PlanningInputError("graph snapshot entries must be objects.")
    return [cast(dict[str, object], value) for value in values]
