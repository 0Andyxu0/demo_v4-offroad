"""Benchmark runner for the 5 typical 2km+ routes in Phase E."""

from __future__ import annotations

import json
import time
from pathlib import Path

from h3_offroad_planner.models import RouteRequest
from h3_offroad_planner.route_planning import run_route_plan

BENCHMARK_ROUTES = {
    "legacy_case_1": {
        "start": (31.9905769003, 118.9960502257),
        "goal": (31.9931786713, 118.9894117713),
        "linear_distance_m": 689.7,
    },
    "route1": {
        "start": (31.975238, 118.993667),
        "goal": (31.993683, 118.993599),
        "linear_distance_m": 2051.0,
    },
    "route3": {
        "start": (31.970000, 118.990000),
        "goal": (31.995000, 119.000000),
        "linear_distance_m": 2935.5,
    },
    "route4b": {
        "start": (31.975238, 118.993667),
        "goal": (31.995000, 118.993600),
        "linear_distance_m": 2197.4,
    },
    "route5b": {
        "start": (31.975238, 118.993667),
        "goal": (31.995000, 119.000000),
        "linear_distance_m": 2277.2,
    },
    "route6b": {
        "start": (31.975238, 118.993667),
        "goal": (31.993000, 119.000000),
        "linear_distance_m": 2063.4,
    },
}

BASE_DIR = Path("D:/Workspace/demo_v4")
INDEX_PATH = "outputs/qdx_tiles_upstream/routing_index/current.json"
OUTPUT_ROOT = Path("outputs/benchmark_phase_e")


def run_single_route(
    name: str,
    info: dict[str, object],
    skip_if_done: bool = False,
) -> dict[str, object]:
    start = info["start"]
    goal = info["goal"]
    assert isinstance(start, tuple) and isinstance(goal, tuple)
    out_dir = OUTPUT_ROOT / name
    perf_file = out_dir / "performance.json"

    if skip_if_done and perf_file.is_file():
        try:
            perf = json.loads(perf_file.read_text(encoding="utf-8"))
            print(f"Skipping already completed {name} (plan_ready_s={perf.get('plan_ready_s')})")
            return perf
        except Exception:
            pass

    out_dir.mkdir(parents=True, exist_ok=True)
    req = RouteRequest(
        input_mode="coordinates",
        parquet_path=INDEX_PATH,
        start_lat=start[0],
        start_lng=start[1],
        goal_lat=goal[0],
        goal_lng=goal[1],
        roi_strategy="auto_corridor",
        corridor_buffer_deg=0.005,
        res_fine=14,
        res_coarse=11,
        max_estimated_cells=50000000,
        planner_config_path="configs/deterministic_pareto_planner.yaml",
        vehicle_path="configs/vehicle.yaml",
        factor_model_path="configs/static_factor_model.yaml",
        static_planning_path="configs/static_gis_planning.yaml",
        output_dir=str(out_dir),
        candidate_limit=24,
        max_candidate_paths=5,
    )

    print("\n=======================================================")
    print(f"Executing {name} (linear dist: {info['linear_distance_m']}m)...")
    t0 = time.perf_counter()
    plan = run_route_plan(req)
    total_wall = time.perf_counter() - t0
    print(f"SUCCESS {name} in {total_wall:.2f}s, candidates: {len(plan.candidates)}")

    perf = json.loads(perf_file.read_text(encoding="utf-8"))
    perf["name"] = name
    perf["linear_distance_m"] = info["linear_distance_m"]
    perf["candidate_count"] = len(plan.candidates)
    perf["wall_time_s"] = total_wall
    return perf


def main() -> None:
    results: dict[str, object] = {}
    for name, info in BENCHMARK_ROUTES.items():
        try:
            res = run_single_route(name, info, skip_if_done=True)
            results[name] = res
        except Exception as e:
            print(f"ERROR on {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = {"error": str(e)}

    summary_path = OUTPUT_ROOT / "phase_e_benchmark_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote all benchmark results to {summary_path}")


if __name__ == "__main__":
    main()
