"""Versioned local routing index over immutable H3 tile facts."""

from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import cast
from uuid import uuid4

import h3  # type: ignore[import-untyped]
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import (
    canonical_hash,
    load_factor_model,
    load_static_planning_config,
)
from h3_offroad_planner.grid import H3GridBuilder
from h3_offroad_planner.models import GridBuildError, H3Graph, PlanningInputError
from h3_offroad_planner.offline_pairs import OfflinePairs, load_offline_pairs

__all__ = [
    "ROUTING_INDEX_KIND",
    "RoutingIndex",
    "build_routing_index",
    "open_routing_index",
    "register_port_pairs",
]

ROUTING_INDEX_KIND = "h3_routing_index"
ROUTING_INDEX_SCHEMA_VERSION = 1
MAX_BOUNDARY_PORTS = 8

CELL_SCHEMA = pa.schema(
    [
        pa.field("h3index", pa.string(), nullable=False),
        pa.field("parent_h3", pa.string(), nullable=False),
        pa.field("lat", pa.float64(), nullable=False),
        pa.field("lng", pa.float64(), nullable=False),
        pa.field("elevation", pa.float64(), nullable=False),
        pa.field("slope", pa.float64(), nullable=False),
        pa.field("tri", pa.float64(), nullable=False),
        pa.field("landcover_code", pa.int32()),
        pa.field("lc_factor", pa.float64(), nullable=False),
        pa.field("has_road", pa.bool_(), nullable=False),
        pa.field("is_passable", pa.bool_(), nullable=False),
        pa.field("depth", pa.float64()),
        pa.field("rowspacing", pa.float64()),
        pa.field("soil_code", pa.int32()),
        pa.field("soil_moisture", pa.float64()),
        pa.field("soil_source", pa.string()),
        pa.field("source_support_m", pa.float64()),
        pa.field("twi", pa.float64()),
        pa.field("drainage_sensitivity", pa.float64()),
        pa.field("drainage_valid", pa.bool_(), nullable=False),
        pa.field("drainage_boundary_affected", pa.bool_(), nullable=False),
        pa.field("surface_response", pa.float64()),
        pa.field("surface_evidence", pa.string()),
    ]
)

COARSE_SCHEMA = pa.schema(
    [
        pa.field("parent_a", pa.string(), nullable=False),
        pa.field("parent_b", pa.string(), nullable=False),
        pa.field("port_a", pa.string(), nullable=False),
        pa.field("port_b", pa.string(), nullable=False),
        pa.field("distance_m", pa.float64(), nullable=False),
        pa.field("slope_mean", pa.float64(), nullable=False),
        pa.field("tri_mean", pa.float64(), nullable=False),
        pa.field("road_fraction", pa.float64(), nullable=False),
        pa.field("passable_fraction", pa.float64(), nullable=False),
        pa.field("risk_proxy", pa.float64(), nullable=False),
        pa.field("environment_proxy", pa.float64(), nullable=False),
    ]
)


@dataclass(frozen=True)
class RoutingIndex:
    """Validated routing-index manifest and its immutable build directory."""

    pointer_path: Path
    build_dir: Path
    manifest: Mapping[str, object]
    coarse_graph: pd.DataFrame

    @property
    def build_id(self) -> str:
        return str(self.manifest["build_id"])

    def load_cells(self, parent_h3: set[str]) -> pd.DataFrame:
        """Read only row groups matching the requested res11 parents."""
        if not parent_h3:
            raise PlanningInputError("routing-index parent set must not be empty.")
        cells = _manifest_path(self.build_dir, self.manifest, "cells")
        table = ds.dataset(cells, format="parquet").to_table(
            filter=ds.field("parent_h3").isin(sorted(parent_h3))
        )
        if table.num_rows == 0:
            raise GridBuildError("routing index contains no cells for the requested parents.")
        frame = table.to_pandas()
        frame = _restore_catalog_columns(frame, self.build_dir, self.manifest)
        return frame.sort_values(["parent_h3", "h3index"], kind="stable").reset_index(drop=True)

    def load_graph(self, parent_h3: set[str]) -> H3Graph:
        frame = self.load_cells(parent_h3)
        return H3GridBuilder(
            res_fine=_manifest_int(self.manifest, "res_fine"),
            res_coarse=_manifest_int(self.manifest, "res_coarse"),
        ).build_graph(frame)

    @property
    def has_port_pairs(self) -> bool:
        files = _manifest_mapping(self.manifest, "files")
        return files.get("port_pairs") is not None

    def load_port_pairs(
        self,
        active_parents: Collection[str],
        *,
        load_paths: bool = False,
    ) -> OfflinePairs:
        """Read only port-pair rows matching the requested res11 parents."""
        if not self.has_port_pairs or not active_parents:
            return {}
        pairs_path = _manifest_path(self.build_dir, self.manifest, "port_pairs")
        return load_offline_pairs(pairs_path, active_parents=active_parents, load_paths=load_paths)


def build_routing_index(
    tile_manifest: Mapping[str, object],
    *,
    vehicle_path: str | None = None,
    factor_model_path: str | None = None,
    static_planning_path: str | None = None,
    port_pairs_path: str | Path | None = None,
    port_pairs_vehicle_hash: str | None = None,
) -> dict[str, object]:
    """Build, validate and atomically publish one immutable routing index."""
    output_dir = Path(_manifest_string(tile_manifest, "output_dir"))
    index_root = output_dir / "routing_index"
    builds_root = index_root / "builds"
    builds_root.mkdir(parents=True, exist_ok=True)
    temporary = builds_root / f".building-{uuid4().hex}"
    temporary.mkdir()
    try:
        records = _usable_tile_records(tile_manifest)
        cells_dir = temporary / "cells"
        cells_dir.mkdir()
        cells_path = cells_dir / "part-00000.parquet"
        summaries, parent_cells, landcover, soil = _write_cells(records, cells_path)
        coarse = _coarse_rows(summaries, parent_cells)
        coarse_path = temporary / "coarse_graph.parquet"
        pq.write_table(
            pa.Table.from_pylist(coarse, schema=COARSE_SCHEMA),
            coarse_path,
            compression="zstd",
        )
        landcover_path = temporary / "landcover_catalog.parquet"
        _write_landcover_catalog(landcover_path, landcover)
        soil_path = temporary / "soil_catalog.parquet"
        has_soil_catalog = bool(soil)
        if has_soil_catalog:
            _write_soil_catalog(soil_path, soil)
        has_port_pairs = port_pairs_path is not None
        port_pairs_target = temporary / "port_pairs.parquet"
        if has_port_pairs:
            source_pairs = Path(port_pairs_path)  # type: ignore[arg-type]
            if source_pairs.resolve() != port_pairs_target.resolve():
                shutil.copy2(source_pairs, port_pairs_target)
        topology_hash = canonical_hash(
            [
                {key: row[key] for key in ("parent_a", "parent_b", "port_a", "port_b")}
                for row in coarse
            ]
        )
        static_hash = _manifest_string(tile_manifest, "static_input_hash")
        build_id = canonical_hash(
            {
                "schema_version": ROUTING_INDEX_SCHEMA_VERSION,
                "static_input_hash": static_hash,
                "topology_hash": topology_hash,
            }
        )[:24]
        project = _project_identity(vehicle_path, factor_model_path, static_planning_path)
        missing = _missing_evidence(tile_manifest, project)
        manifest: dict[str, object] = {
            "artifact_kind": ROUTING_INDEX_KIND,
            "schema_version": ROUTING_INDEX_SCHEMA_VERSION,
            "build_id": build_id,
            "created_at": datetime.now(UTC).isoformat(),
            "crs": _source_crs(tile_manifest),
            "res_fine": _manifest_int(tile_manifest, "res_fine"),
            "res_coarse": _manifest_int(tile_manifest, "tile_res"),
            "static_input_hash": static_hash,
            "topology_hash": topology_hash,
            "vehicle_hash": project.get("vehicle_hash"),
            "factor_model_hash": project.get("factor_model_hash"),
            "scenario_hash": project.get("scenario_hash"),
            "project_config_snapshot": project.get("snapshot", {}),
            "evidence_status": "COMPLETE" if not missing else "INCOMPLETE",
            "missing_physical_inputs": missing,
            "applicability": "static GIS routing facts; final vehicle constraints remain online",
            "cells_count": sum(len(cells) for cells in parent_cells.values()),
            "parents_count": len(parent_cells),
            "boundary_port_count": len(coarse),
            "files": {
                "cells": _file_record(temporary, cells_path),
                "coarse_graph": _file_record(temporary, coarse_path),
                "landcover_catalog": _file_record(temporary, landcover_path),
                "soil_catalog": _file_record(temporary, soil_path) if has_soil_catalog else None,
                "port_pairs": (
                    _file_record(temporary, port_pairs_target) if has_port_pairs else None
                ),
            },
            "column_compressed_bytes": _compressed_column_sizes(cells_path),
            "source_tile_count": len(records),
        }
        if has_port_pairs and port_pairs_vehicle_hash is not None:
            manifest["port_pairs_vehicle_hash"] = port_pairs_vehicle_hash
        _write_json_strict(temporary / "routing_index.json", manifest)
        _validate_build(temporary, manifest)
        final = builds_root / build_id
        if final.exists():
            existing = _read_json(final / "routing_index.json")
            if existing.get("static_input_hash") != static_hash:
                raise GridBuildError(f"routing-index build id collision: {build_id}")
            _remove_temporary(temporary, builds_root)
        else:
            _replace_directory_strict(temporary, final)
        _publish_current(index_root, build_id)
        return cast(dict[str, object], _read_json(final / "routing_index.json"))
    except Exception:
        if temporary.exists():
            _remove_temporary(temporary, builds_root)
        raise


def register_port_pairs(
    build_dir: Path,
    port_pairs_path: Path,
    vehicle_hash: str | None = None,
) -> dict[str, object]:
    """Register or copy port_pairs.parquet into an existing routing index build."""
    manifest_path = build_dir / "routing_index.json"
    manifest = _read_json(manifest_path)
    target_path = build_dir / "port_pairs.parquet"
    source_path = Path(port_pairs_path)
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
    files = _manifest_mapping(manifest, "files")
    files["port_pairs"] = _file_record(build_dir, target_path)
    manifest["files"] = files
    if vehicle_hash is not None:
        manifest["port_pairs_vehicle_hash"] = vehicle_hash
    _write_json_strict(manifest_path, manifest)
    _validate_build(build_dir, manifest)
    return manifest


def open_routing_index(path: str | Path) -> RoutingIndex:
    """Open a current pointer or a build manifest and validate all referenced files."""
    requested = Path(path)
    if requested.name == "current.json":
        pointer = _read_json(requested)
        build_id = _manifest_string(pointer, "build_id")
        build_dir = requested.parent / "builds" / build_id
        manifest_path = build_dir / "routing_index.json"
        pointer_path = requested
    elif requested.name == "routing_index.json":
        manifest_path = requested
        build_dir = requested.parent
        pointer_path = requested.parent.parent.parent / "current.json"
    else:
        raise PlanningInputError("routing index path must name current.json or routing_index.json.")
    manifest = _read_json(manifest_path)
    if manifest.get("artifact_kind") != ROUTING_INDEX_KIND:
        raise PlanningInputError(f"unsupported routing-index artifact: {manifest_path}")
    _validate_build(build_dir, manifest)
    coarse_path = _manifest_path(build_dir, manifest, "coarse_graph")
    return RoutingIndex(pointer_path, build_dir, manifest, pd.read_parquet(coarse_path))


def _write_cells(
    records: list[dict[str, object]],
    path: Path,
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, list[str]],
    dict[int, tuple[str, float]],
    dict[int, tuple[str | None, str | None, str | None]],
]:
    writer = pq.ParquetWriter(path, CELL_SCHEMA, compression="zstd", use_dictionary=True)
    summaries: dict[str, dict[str, float]] = {}
    parent_cells: dict[str, list[str]] = defaultdict(list)
    landcover: dict[int, tuple[str, float]] = {}
    soil: dict[int, tuple[str | None, str | None, str | None]] = {}
    try:
        for record in records:
            tile_path = Path(_manifest_string(record, "path"))
            frame = pd.read_parquet(tile_path)
            frame = frame.sort_values(["parent_h3", "h3index"], kind="stable")
            table = _cell_table(frame)
            writer.write_table(table, row_group_size=max(1, len(frame)))
            _collect_catalogs(frame, landcover, soil)
            for parent, group in frame.groupby("parent_h3", sort=True):
                parent_id = str(parent)
                ids = [str(value) for value in group["h3index"]]
                parent_cells[parent_id].extend(ids)
                summaries[parent_id] = _parent_summary(group)
    finally:
        writer.close()
    return summaries, dict(parent_cells), landcover, soil


def _cell_table(frame: pd.DataFrame) -> pa.Table:
    arrays = []
    for field in CELL_SCHEMA:
        if field.name in frame:
            values = frame[field.name]
        elif field.name in {"drainage_valid", "drainage_boundary_affected"}:
            values = pd.Series(False, index=frame.index)
        else:
            values = pd.Series(None, index=frame.index)
        try:
            arrays.append(pa.array(values, type=field.type, from_pandas=True, safe=True))
        except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
            raise GridBuildError(f"cannot cast routing-index column {field.name!r}") from exc
    return pa.Table.from_arrays(arrays, schema=CELL_SCHEMA)


def _collect_catalogs(
    frame: pd.DataFrame,
    landcover: dict[int, tuple[str, float]],
    soil: dict[int, tuple[str | None, str | None, str | None]],
) -> None:
    landcover_rows = frame[["landcover_code", "landcover_type", "lc_factor"]].dropna(
        subset=["landcover_code"]
    )
    for row in landcover_rows.to_dict("records"):
        code = int(float(str(row["landcover_code"])))
        landcover_value = (
            "" if pd.isna(row["landcover_type"]) else str(row["landcover_type"]),
            float(str(row["lc_factor"])),
        )
        previous_landcover = landcover.setdefault(code, landcover_value)
        if previous_landcover != landcover_value:
            raise GridBuildError(f"landcover catalog is inconsistent for code {code}.")
    if "soil_code" not in frame:
        return
    columns = ["soil_code", "soil_type", "soil_texture", "uscs"]
    for column in columns:
        if column not in frame:
            frame[column] = None
    for row in frame[columns].dropna(subset=["soil_code"]).to_dict("records"):
        code = int(float(str(row["soil_code"])))
        soil_value = cast(
            tuple[str | None, str | None, str | None],
            tuple(None if pd.isna(row[key]) else str(row[key]) for key in columns[1:]),
        )
        previous_soil = soil.setdefault(code, soil_value)
        if previous_soil != soil_value:
            raise GridBuildError(f"soil catalog is inconsistent for code {code}.")


def _parent_summary(group: pd.DataFrame) -> dict[str, float]:
    return {
        "slope_mean": float(pd.to_numeric(group["slope"]).mean()),
        "tri_mean": float(pd.to_numeric(group["tri"]).mean()),
        "road_fraction": float(group["has_road"].astype(bool).mean()),
        "passable_fraction": float(group["is_passable"].astype(bool).mean()),
    }


def _coarse_rows(
    summaries: Mapping[str, Mapping[str, float]],
    parent_cells: Mapping[str, list[str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    parent_sets = {parent: set(cells) for parent, cells in parent_cells.items()}
    for parent_a in sorted(parent_sets):
        for parent_b in sorted(str(value) for value in h3.grid_disk(parent_a, 1)):
            if parent_b <= parent_a or parent_b not in parent_sets:
                continue
            ports = _boundary_ports(parent_sets[parent_a], parent_sets[parent_b])
            if not ports:
                continue
            first = summaries[parent_a]
            second = summaries[parent_b]
            slope = (first["slope_mean"] + second["slope_mean"]) / 2.0
            tri = (first["tri_mean"] + second["tri_mean"]) / 2.0
            road = (first["road_fraction"] + second["road_fraction"]) / 2.0
            passable = (first["passable_fraction"] + second["passable_fraction"]) / 2.0
            distance = float(
                h3.great_circle_distance(
                    h3.cell_to_latlng(parent_a), h3.cell_to_latlng(parent_b), unit="m"
                )
            )
            for port_a, port_b in ports:
                rows.append(
                    {
                        "parent_a": parent_a,
                        "parent_b": parent_b,
                        "port_a": port_a,
                        "port_b": port_b,
                        "distance_m": distance,
                        "slope_mean": slope,
                        "tri_mean": tri,
                        "road_fraction": road,
                        "passable_fraction": passable,
                        "risk_proxy": slope + tri,
                        "environment_proxy": 1.0 - passable,
                    }
                )
    return rows


def _boundary_ports(first: set[str], second: set[str]) -> list[tuple[str, str]]:
    ports: list[tuple[str, str]] = []
    for cell in sorted(first):
        for neighbor in sorted(str(value) for value in h3.grid_disk(cell, 1)):
            if neighbor in second:
                ports.append((cell, neighbor))
                if len(ports) == MAX_BOUNDARY_PORTS:
                    return ports
    return ports


def _write_landcover_catalog(path: Path, values: Mapping[int, tuple[str, float]]) -> None:
    schema = pa.schema(
        [
            pa.field("landcover_code", pa.int32(), nullable=False),
            pa.field("landcover_type", pa.string()),
            pa.field("lc_factor", pa.float64(), nullable=False),
        ]
    )
    rows = [
        {"landcover_code": code, "landcover_type": value[0] or None, "lc_factor": value[1]}
        for code, value in sorted(values.items())
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def _write_soil_catalog(
    path: Path,
    values: Mapping[int, tuple[str | None, str | None, str | None]],
) -> None:
    schema = pa.schema(
        [
            pa.field("soil_code", pa.int32(), nullable=False),
            pa.field("soil_type", pa.string()),
            pa.field("soil_texture", pa.string()),
            pa.field("uscs", pa.string()),
        ]
    )
    rows = [
        {"soil_code": code, "soil_type": value[0], "soil_texture": value[1], "uscs": value[2]}
        for code, value in sorted(values.items())
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def _restore_catalog_columns(
    frame: pd.DataFrame, build_dir: Path, manifest: Mapping[str, object]
) -> pd.DataFrame:
    landcover = pd.read_parquet(_manifest_path(build_dir, manifest, "landcover_catalog"))
    frame = frame.merge(
        landcover[["landcover_code", "landcover_type"]],
        on="landcover_code",
        how="left",
    )
    files = _manifest_mapping(manifest, "files")
    if files.get("soil_catalog") is not None:
        soil = pd.read_parquet(_manifest_path(build_dir, manifest, "soil_catalog"))
        frame = frame.merge(soil, on="soil_code", how="left")
    return frame


def _project_identity(
    vehicle_path: str | None,
    factor_model_path: str | None,
    static_planning_path: str | None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    result: dict[str, object] = {"snapshot": snapshot}
    if vehicle_path is not None:
        vehicle = asdict(load_vehicle(vehicle_path))
        snapshot["vehicle"] = vehicle
        result["vehicle_hash"] = canonical_hash(vehicle)
    if factor_model_path is not None:
        factor = load_factor_model(factor_model_path).to_dict()
        snapshot["factor_model"] = factor
        result["factor_model_hash"] = canonical_hash(factor)
    if static_planning_path is not None:
        static = load_static_planning_config(static_planning_path)
        snapshot["static_planning"] = static.to_dict()
        result["scenario_hash"] = canonical_hash(list(static.environment.request_pressures))
    return result


def _missing_evidence(
    tile_manifest: Mapping[str, object], project: Mapping[str, object]
) -> list[str]:
    missing: list[str] = []
    snapshot = cast(dict[str, object], project.get("snapshot", {}))
    vehicle = cast(dict[str, object], snapshot.get("vehicle", {}))
    for key in ("width_m", "wheelbase_m", "front_overhang_m", "rear_overhang_m"):
        if vehicle.get(key) is None:
            missing.append(f"vehicle.{key}")
    static = cast(dict[str, object], snapshot.get("static_planning", {}))
    hydrology = cast(dict[str, object], static.get("hydrology", {}))
    for key in ("mapping_t0", "mapping_t1"):
        if hydrology.get(key) is None:
            missing.append(f"hydrology.{key}")
    if hydrology.get("upstream_complete") is not True:
        missing.append("hydrology.upstream_complete")
    sources = cast(dict[str, object], tile_manifest.get("static_sources", {}))
    for key in (
        "soil",
        "soil_catalog",
        "twi",
        "drainage",
        "drainage_validity",
        "drainage_boundary",
    ):
        if sources.get(key) is None:
            missing.append(f"static_sources.{key}")
    return sorted(set(missing))


def _usable_tile_records(tile_manifest: Mapping[str, object]) -> list[dict[str, object]]:
    raw = tile_manifest.get("tiles")
    if not isinstance(raw, list):
        raise PlanningInputError("tile manifest must contain a tiles array.")
    failed = [
        record
        for record in raw
        if isinstance(record, dict) and record.get("status") == "failed"
    ]
    if failed:
        raise GridBuildError("routing index requires a tile build with no failed records.")
    records = [
        cast(dict[str, object], record)
        for record in raw
        if isinstance(record, dict) and record.get("status") in {"completed", "skipped"}
    ]
    if not records:
        raise GridBuildError("routing index requires at least one completed tile.")
    return sorted(records, key=lambda item: _manifest_string(item, "parent_h3"))


def _source_crs(tile_manifest: Mapping[str, object]) -> str:
    quality = tile_manifest.get("dem_quality")
    return str(quality.get("crs", "")) if isinstance(quality, dict) else ""


def _compressed_column_sizes(path: Path) -> dict[str, int]:
    parquet = pq.ParquetFile(path)
    try:
        metadata = parquet.metadata
        totals: dict[str, int] = defaultdict(int)
        for row_group_index in range(metadata.num_row_groups):
            row_group = metadata.row_group(row_group_index)
            for column_index in range(row_group.num_columns):
                column = row_group.column(column_index)
                totals[column.path_in_schema] += column.total_compressed_size
        return dict(sorted(totals.items()))
    finally:
        parquet.close()


def _file_record(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_build(build_dir: Path, manifest: Mapping[str, object]) -> None:
    if _manifest_int(manifest, "schema_version") != ROUTING_INDEX_SCHEMA_VERSION:
        raise PlanningInputError("routing-index schema version is unsupported.")
    files = _manifest_mapping(manifest, "files")
    for key, record in files.items():
        if record is None:
            continue
        if not isinstance(record, dict):
            raise PlanningInputError(f"routing-index file record is invalid: {key}")
        path = build_dir / _manifest_string(record, "path")
        if not path.is_file() or path.stat().st_size != _manifest_int(record, "size_bytes"):
            raise PlanningInputError(f"routing-index file is missing or truncated: {path}")


def _manifest_path(build_dir: Path, manifest: Mapping[str, object], key: str) -> Path:
    record = _manifest_mapping(manifest, "files").get(key)
    if not isinstance(record, dict):
        raise PlanningInputError(f"routing-index manifest omits file: {key}")
    return build_dir / _manifest_string(record, "path")


def _manifest_mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PlanningInputError(f"manifest field must be a mapping: {key}")
    return cast(dict[str, object], value)


def _manifest_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PlanningInputError(f"manifest field must be a non-empty string: {key}")
    return value


def _manifest_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningInputError(f"manifest field must be an integer: {key}")
    return value


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningInputError(f"invalid routing-index JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PlanningInputError(f"routing-index JSON must be an object: {path}")
    return cast(dict[str, object], payload)


def _write_json_strict(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _publish_current(index_root: Path, build_id: str) -> None:
    pointer = index_root / "current.json"
    temporary = index_root / ".current.json.tmp"
    temporary.write_text(
        json.dumps({"build_id": build_id}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, pointer)


def _replace_directory_strict(source: Path, target: Path) -> None:
    """Retry a transient Windows handle race without changing the fixed target."""
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            sleep(0.1)


def _remove_temporary(path: Path, builds_root: Path) -> None:
    if path.parent.resolve() != builds_root.resolve() or not path.name.startswith(".building-"):
        raise RuntimeError(f"refusing to remove non-temporary routing-index path: {path}")
    shutil.rmtree(path)
