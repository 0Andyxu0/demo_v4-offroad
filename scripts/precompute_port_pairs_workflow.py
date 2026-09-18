"""Offline port-pair precomputation workflow.

Precomputes optimal paths and scalar costs across parent ports for base profiles
(distance, eta, terrain_risk, travel_cost) and writes them to port_pairs.parquet.

Usage:
    python scripts/precompute_port_pairs_workflow.py \
        --build-dir outputs/routing_index/builds/<id> \
        --output outputs/routing_index/builds/<id>/port_pairs.parquet \
        --register
"""

from __future__ import annotations

import argparse
from pathlib import Path

from h3_offroad_planner.config import load_vehicle
from h3_offroad_planner.factor_model import FactorModelConfig, load_factor_model
from h3_offroad_planner.offline_pairs import (
    default_vehicle,
    precompute_port_pairs,
    save_offline_pairs,
)
from h3_offroad_planner.routing_index import open_routing_index, register_port_pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precompute offline port pairs for a routing index."
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        required=True,
        help="Path to routing index build directory, routing_index.json, or current.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to output port_pairs.parquet (default: <build-dir>/port_pairs.parquet)",
    )
    parser.add_argument(
        "--max-parents",
        type=int,
        default=None,
        help="Limit number of parent tiles to precompute",
    )
    parser.add_argument(
        "--vehicle-path",
        type=Path,
        default=None,
        help="Path to vehicle YAML configuration file",
    )
    parser.add_argument(
        "--factor-model-path",
        type=Path,
        default=None,
        help="Path to factor model YAML configuration file",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register the generated port_pairs.parquet into routing_index.json",
    )
    args = parser.parse_args()

    target_path = args.build_dir
    if target_path.is_dir():
        if (target_path / "routing_index.json").is_file():
            target_path = target_path / "routing_index.json"
        elif (target_path / "current.json").is_file():
            target_path = target_path / "current.json"

    index = open_routing_index(target_path)

    if args.vehicle_path is not None and args.vehicle_path.is_file():
        vehicle = load_vehicle(str(args.vehicle_path))
    else:
        vehicle = default_vehicle()

    if args.factor_model_path is not None and args.factor_model_path.is_file():
        factor_config = load_factor_model(str(args.factor_model_path))
    elif Path("configs/static_factor_model.yaml").is_file():
        factor_config = load_factor_model("configs/static_factor_model.yaml")
    else:
        factor_config = FactorModelConfig()

    output_file = (
        args.output
        if args.output is not None
        else (index.build_dir / "port_pairs.parquet")
    )

    pairs_df = precompute_port_pairs(
        index,
        vehicle=vehicle,
        factor_config=factor_config,
        max_parents=args.max_parents,
    )

    save_offline_pairs(pairs_df, output_file)
    print(
        f"Wrote {len(pairs_df)} port pairs for "
        f"{pairs_df['parent_h3'].nunique()} parents to {output_file}"
    )

    if args.register:
        register_port_pairs(index.build_dir, output_file)
        print(f"Registered {output_file.name} in {index.build_dir / 'routing_index.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
