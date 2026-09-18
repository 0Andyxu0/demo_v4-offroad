"""Offline port-pair cache precomputation, export, and sliced import helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, cast

import h3
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import (
    FactorModelConfig,
    evaluate_factor_model,
)
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import VehicleProfile
from h3_offroad_planner.portsmap import PortsMapSearchContext, ScalarProfile

if TYPE_CHECKING:
    from h3_offroad_planner.routing_index import RoutingIndex

__all__ = [
    "BASE_PROFILE_NAMES",
    "OfflinePairs",
    "PORT_PAIRS_SCHEMA",
    "default_vehicle",
    "extract_offline_pairs",
    "load_offline_pairs",
    "precompute_port_pairs",
    "read_offline_pairs_vehicle_hash",
    "save_offline_pairs",
]

OfflinePairs = Mapping[
    tuple[str, str, str], Mapping[str, tuple[tuple[str, ...], float]]
]

BASE_PROFILE_NAMES: tuple[str, ...] = (
    "distance",
    "eta",
    "terrain_risk",
    "travel_cost",
)

PORT_PAIRS_SCHEMA = pa.schema(
    [
        pa.field("profile", pa.string(), nullable=False),
        pa.field("parent_h3", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("target", pa.string(), nullable=False),
        pa.field("path", pa.list_(pa.string()), nullable=False),
        pa.field("cost", pa.float64(), nullable=False),
    ]
)


def extract_offline_pairs(
    context: PortsMapSearchContext,
    profile_name: str,
) -> dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]]:
    """Extract unpenalized and unblocked port-pair paths from a warmed context."""
    result: dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]] = {}
    for cache_key, pairs in context._pair_cache.items():
        parent, _signature, local_penalty_key, local_blocked_key, _port_hash = cache_key
        if local_penalty_key or local_blocked_key:
            continue
        for (source, target), pair in pairs.items():
            key = (profile_name, parent, source)
            result.setdefault(key, {})[target] = (pair.h3_path, pair.scalar_cost)
    return result


def save_offline_pairs(
    pairs: OfflinePairs | pd.DataFrame | list[dict[str, object]],
    path: Path,
    vehicle_hash: str | None = None,
    row_group_size: int = 5000,
) -> None:
    """Write offline port pairs to a compressed Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = dict(PORT_PAIRS_SCHEMA.metadata or {})
    if vehicle_hash is not None:
        metadata[b"vehicle_hash"] = vehicle_hash.encode("utf-8")
    schema = PORT_PAIRS_SCHEMA.with_metadata(metadata) if metadata else PORT_PAIRS_SCHEMA
    if isinstance(pairs, pd.DataFrame):
        table = pa.Table.from_pandas(pairs, schema=schema, preserve_index=False)
    elif isinstance(pairs, list):
        table = pa.Table.from_pylist(pairs, schema=schema)
    else:
        rows: list[dict[str, object]] = []
        for (profile, parent, source), targets in pairs.items():
            for target, (h3_path, cost) in targets.items():
                rows.append(
                    {
                        "profile": profile,
                        "parent_h3": parent,
                        "source": source,
                        "target": target,
                        "path": list(h3_path),
                        "cost": float(cost),
                    }
                )
        table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression="zstd", row_group_size=row_group_size)


def read_offline_pairs_vehicle_hash(path: Path) -> str | None:
    """Read vehicle_hash stored in Parquet schema metadata if present."""
    if not path.is_file():
        return None
    try:
        metadata = pq.read_schema(path).metadata
        if metadata and b"vehicle_hash" in metadata:
            return metadata[b"vehicle_hash"].decode("utf-8")
    except Exception:
        pass
    return None


def load_offline_pairs(
    path: Path,
    active_parents: Collection[str] | None = None,
) -> dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]]:
    """Load offline pairs from Parquet, optionally slicing via PyArrow predicate pushdown."""
    if not path.is_file():
        raise FileNotFoundError(f"offline pairs file does not exist: {path}")

    dataset = ds.dataset(str(path), format="parquet")
    if active_parents is not None:
        parents_list = sorted(set(active_parents))
        if not parents_list:
            return {}
        filter_expr = ds.field("parent_h3").isin(parents_list)
        table = dataset.to_table(filter=filter_expr)
    else:
        table = dataset.to_table()

    result: dict[tuple[str, str, str], dict[str, tuple[tuple[str, ...], float]]] = {}
    if table.num_rows == 0:
        return result

    profiles = table["profile"].to_pylist()
    parents = table["parent_h3"].to_pylist()
    sources = table["source"].to_pylist()
    targets = table["target"].to_pylist()
    paths = table["path"].to_pylist()
    costs = table["cost"].to_pylist()

    for profile, parent, source, target, path_list, cost in zip(
        profiles, parents, sources, targets, paths, costs, strict=True
    ):
        result.setdefault((profile, parent, source), {})[target] = (
            tuple(path_list),
            float(cost),
        )
    return result


def default_vehicle() -> VehicleProfile:
    """Return a baseline vehicle profile for offline precomputations."""
    config_path = Path("configs/vehicle.yaml")
    if config_path.is_file():
        return load_vehicle(str(config_path))
    return VehicleProfile(
        name="baseline_vehicle",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=8000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )


def _extract_parent_ports(
    parent: str,
    cells_df: pd.DataFrame,
    res_coarse: int,
    known_parents: set[str],
    seed_ports: Collection[str] = (),
) -> list[str]:
    ports = set(seed_ports)
    for cell in cells_df["h3index"]:
        cell_str = str(cell)
        try:
            for neighbor in h3.grid_disk(cell_str, 1):
                neighbor_str = str(neighbor)
                neighbor_parent = h3.cell_to_parent(neighbor_str, res_coarse)
                if neighbor_parent != parent and neighbor_parent in known_parents:
                    ports.add(cell_str)
                    break
        except (ValueError, Exception):
            pass
    return sorted(ports)


def _precompute_chunk(
    chunk_parents: list[str],
    index: RoutingIndex,
    known_parents: set[str],
    ports_by_parent: dict[str, set[str]],
    builder: H3GridBuilder,
    vehicle: VehicleProfile,
    factor_config: FactorModelConfig,
    profiles: list[ScalarProfile],
    res_coarse: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    cells_df = index.load_cells(set(chunk_parents))
    for parent_val, group in cells_df.groupby("parent_h3"):
        parent_str = str(parent_val)
        ports = _extract_parent_ports(
            parent=parent_str,
            cells_df=group,
            res_coarse=res_coarse,
            known_parents=known_parents,
            seed_ports=ports_by_parent.get(parent_str, ()),
        )
        if len(ports) <= 1:
            continue
        parent_rows = _precompute_single_parent(
            parent=parent_str,
            ports=ports,
            cells_df=group,
            builder=builder,
            vehicle=vehicle,
            factor_config=factor_config,
            profiles=profiles,
        )
        rows.extend(parent_rows)
    return rows


def _worker_precompute_chunk(
    index_path_str: str,
    chunk_parents: list[str],
    known_parents: set[str],
    ports_by_parent: dict[str, set[str]],
    vehicle: VehicleProfile,
    factor_dict: dict[str, object],
    profiles: list[ScalarProfile],
    res_fine: int,
    res_coarse: int,
) -> list[dict[str, object]]:
    from h3_offroad_planner.routing_index import open_routing_index

    worker_index = open_routing_index(index_path_str)
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse)
    factor_config = FactorModelConfig(**factor_dict)  # type: ignore[arg-type]
    return _precompute_chunk(
        chunk_parents=chunk_parents,
        index=worker_index,
        known_parents=known_parents,
        ports_by_parent=ports_by_parent,
        builder=builder,
        vehicle=vehicle,
        factor_config=factor_config,
        profiles=profiles,
        res_coarse=res_coarse,
    )


def precompute_port_pairs(
    index: RoutingIndex,
    *,
    vehicle: VehicleProfile | None = None,
    factor_config: FactorModelConfig | None = None,
    parents: Collection[str] | None = None,
    profiles: Sequence[ScalarProfile] | None = None,
    max_parents: int | None = None,
    batch_size: int = 50,
    workers: int = 1,
) -> pd.DataFrame:
    """Precompute optimal port-pair paths and scalar costs across parent tiles."""
    active_vehicle = vehicle if vehicle is not None else default_vehicle()
    active_factor = factor_config if factor_config is not None else FactorModelConfig()
    active_profiles = (
        list(profiles)
        if profiles is not None
        else [ScalarProfile({name: 1.0}, name=name) for name in BASE_PROFILE_NAMES]
    )

    coarse_df = index.coarse_graph
    known_parents = set(coarse_df["parent_a"]).union(coarse_df["parent_b"])
    ports_by_parent: dict[str, set[str]] = defaultdict(set)
    for row in coarse_df.itertuples(index=False):
        ports_by_parent[str(row.parent_a)].add(str(row.port_a))
        ports_by_parent[str(row.parent_b)].add(str(row.port_b))

    if parents is not None:
        candidate_parents = sorted(set(parents))
    else:
        candidate_parents = sorted(known_parents if known_parents else ports_by_parent.keys())

    if max_parents is not None:
        candidate_parents = candidate_parents[:max_parents]

    active_parents = [
        parent
        for parent in candidate_parents
        if parent in known_parents or len(ports_by_parent.get(parent, ())) >= 1
    ]

    res_fine = cast(int, index.manifest["res_fine"])
    res_coarse = cast(int, index.manifest["res_coarse"])
    builder = H3GridBuilder(res_fine=res_fine, res_coarse=res_coarse)

    chunks = [
        active_parents[offset : offset + batch_size]
        for offset in range(0, len(active_parents), batch_size)
    ]

    all_rows: list[dict[str, object]] = []
    if workers > 1 and len(chunks) > 1:
        index_target = (
            str(index.pointer_path)
            if index.pointer_path.is_file()
            else str(index.build_dir / "routing_index.json")
        )
        factor_dict: dict[str, object] = {
            k: dict(v) if isinstance(v, Mapping) else v
            for k, v in active_factor.__dict__.items()
        }
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _worker_precompute_chunk,
                    index_target,
                    chunk,
                    known_parents,
                    dict(ports_by_parent),
                    active_vehicle,
                    factor_dict,
                    active_profiles,
                    res_fine,
                    res_coarse,
                )
                for chunk in chunks
            ]
            for future in futures:
                all_rows.extend(future.result())
    else:
        for chunk in chunks:
            rows = _precompute_chunk(
                chunk_parents=chunk,
                index=index,
                known_parents=known_parents,
                ports_by_parent=ports_by_parent,
                builder=builder,
                vehicle=active_vehicle,
                factor_config=active_factor,
                profiles=active_profiles,
                res_coarse=res_coarse,
            )
            all_rows.extend(rows)

    return pd.DataFrame(
        all_rows,
        columns=["profile", "parent_h3", "source", "target", "path", "cost"],
    )


def _precompute_single_parent(
    parent: str,
    ports: list[str],
    cells_df: pd.DataFrame,
    builder: H3GridBuilder,
    vehicle: VehicleProfile,
    factor_config: FactorModelConfig,
    profiles: Sequence[ScalarProfile],
) -> list[dict[str, object]]:
    if len(ports) <= 1 or cells_df.empty:
        return []
    graph = builder.build_graph(cells_df)
    eval_result = evaluate_factor_model(graph, vehicle, factor_config)
    allowed = {c for c, m in eval_result.node_metrics.items() if m.is_passable}
    context = PortsMapSearchContext(graph, eval_result)

    rows: list[dict[str, object]] = []
    targets_set = set(ports)
    for profile in profiles:
        for source in ports:
            query_targets = targets_set - {source}
            search_results = context._fine_tile_search(
                source,
                allowed,
                profile,
                penalties={},
                penalty_factor=0.0,
                targets=query_targets,
            )
            for target in sorted(query_targets):
                if target not in search_results:
                    continue
                cost, path = search_results[target]
                rows.append(
                    {
                        "profile": profile.name,
                        "parent_h3": parent,
                        "source": source,
                        "target": target,
                        "path": list(path),
                        "cost": float(cost),
                    }
                )
    return rows
