import json, time
from pathlib import Path
from h3_offroad_planner.models import RouteRequest
from h3_offroad_planner.route_planning import run_route_plan

INDEX_PATH = 'outputs/qdx_tiles_upstream/routing_index/current.json'
tiers = {
    'tier_500m_690m': ((31.9905769003, 118.9960502257), (31.9931786713, 118.9894117713)),
    'tier_1000m_1075m': ((31.984000, 118.993600), (31.993683, 118.993599)),
    'tier_2000m_2051m': ((31.975238, 118.993667), (31.993683, 118.993599)),
}

for name, (start, goal) in tiers.items():
    out_dir = Path('outputs/scratch_tier_test') / name
    out_dir.mkdir(parents=True, exist_ok=True)
    req = RouteRequest(
        input_mode='coordinates',
        parquet_path=INDEX_PATH,
        start_lat=start[0],
        start_lng=start[1],
        goal_lat=goal[0],
        goal_lng=goal[1],
        roi_strategy='auto_corridor',
        corridor_buffer_deg=0.005,
        res_fine=14,
        res_coarse=11,
        max_estimated_cells=50000000,
        planner_config_path='configs/deterministic_pareto_planner.yaml',
        vehicle_path='configs/vehicle.yaml',
        factor_model_path='configs/static_factor_model.yaml',
        static_planning_path='configs/static_gis_planning.yaml',
        output_dir=str(out_dir),
        candidate_limit=24,
        max_candidate_paths=5,
    )
    t0 = time.perf_counter()
    plan = run_route_plan(req)
    total_time = time.perf_counter() - t0
    perf = json.loads((out_dir / 'performance.json').read_text())
    print(f"\n=== {name} ===")
    print(f"Total wall: {total_time:.2f}s | plan_ready_s: {perf.get('plan_ready_s', 0):.2f}s")
    print(f"Cells: {perf.get('cell_count')} | Active Parents: {perf.get('active_parent_count')}")
    print(f"  - factor_eval_s:      {perf.get('factor_eval_s', 0):.2f}s")
    print(f"  - candidate_search_s: {perf.get('candidate_search_s', 0):.2f}s")
    print(f"  - reachability_s:     {perf.get('reachability_s', 0):.2f}s")
    print(f"  - graph_build_s:      {perf.get('graph_build_s', 0):.2f}s")
    print(f"  - env/load/coarse:    {perf.get('environment_fetch_s', 0) + perf.get('corridor_load_s', 0) + perf.get('coarse_search_s', 0):.2f}s")
    print(f"Candidates returned: {len(plan.candidates)}")
