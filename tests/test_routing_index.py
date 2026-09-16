"""Local routing-index schema, identity and atomic-publication checks."""

from __future__ import annotations

import json
from pathlib import Path

import h3
import pandas as pd
import pyarrow.parquet as pq
import pytest

from h3_offroad_planner import routing_index
from h3_offroad_planner.routing_index import build_routing_index, open_routing_index


def test_routing_index_is_deterministic_and_reads_by_parent(tmp_path: Path) -> None:
    manifest, parents = _tile_manifest(tmp_path)

    first = build_routing_index(manifest)
    second = build_routing_index(manifest)

    assert first["build_id"] == second["build_id"]
    assert first["evidence_status"] == "INCOMPLETE"
    index = open_routing_index(tmp_path / "routing_index" / "current.json")
    frame = index.load_cells({parents[0]})
    assert set(frame["parent_h3"]) == {parents[0]}
    assert set(frame["landcover_type"]) == {"grass"}
    schema = pq.read_schema(index.build_dir / "cells" / "part-00000.parquet")
    assert all(field.type.id != 0 for field in schema)
    assert {
        "adjacency_json",
        "edge_length_m",
        "nodata",
        "sampling_mode",
        "static_input_hash",
    }.isdisjoint(schema.names)
    assert not (index.build_dir / "soil_catalog.parquet").exists()


def test_failed_build_keeps_current_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _ = _tile_manifest(tmp_path)
    built = build_routing_index(manifest)
    pointer = tmp_path / "routing_index" / "current.json"
    before = pointer.read_text(encoding="utf-8")

    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("forced index failure")

    monkeypatch.setattr(routing_index, "_write_cells", fail)
    with pytest.raises(RuntimeError, match="forced index failure"):
        build_routing_index(manifest)

    assert pointer.read_text(encoding="utf-8") == before
    assert json.loads(before)["build_id"] == built["build_id"]


def _tile_manifest(tmp_path: Path) -> tuple[dict[str, object], tuple[str, str]]:
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
                    "adjacency_json": "{}",
                    "edge_length_m": 1.0,
                    "nodata": False,
                    "sampling_mode": "center",
                    "static_input_hash": "legacy-row-hash",
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
