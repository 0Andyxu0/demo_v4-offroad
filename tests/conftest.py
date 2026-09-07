"""Pytest fixtures for in-memory graph planner validation."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from h3_offroad_planner.models import H3Cell, H3Edge, H3Graph, VehicleProfile


@pytest.fixture
def vehicle() -> VehicleProfile:
    """Return a valid wheeled vehicle profile for tests."""
    return VehicleProfile(
        name="test_truck",
        mass_kg=2000.0,
        max_climb_angle_deg=30.0,
        max_speed_kmh=80.0,
        tire_width_m=0.35,
        ground_clearance_m=0.4,
        max_thrust_n=8000.0,
        tire_radius_m=0.45,
        min_turn_radius_m=5.0,
    )


def make_grid_graph(
    width: int,
    height: int,
    blocked: Iterable[str] = (),
    high_barrier_column: int | None = None,
) -> H3Graph:
    """Build a rectangular in-memory graph for spec-derived tests."""
    blocked_set = set(blocked)
    cells: dict[str, H3Cell] = {}
    edges: dict[tuple[str, str], H3Edge] = {}
    for y_coord in range(height):
        for x_coord in range(width):
            cell_id = f"{x_coord},{y_coord}"
            cells[cell_id] = H3Cell(
                h3index=cell_id,
                lat=float(y_coord),
                lng=float(x_coord),
                elevation=float(x_coord),
                slope=0.0,
                tri=0.0,
                lc_factor=1.0,
                is_passable=cell_id not in blocked_set,
            )
    for y_coord in range(height):
        for x_coord in range(width):
            _add_grid_edges(edges, width, height, x_coord, y_coord, high_barrier_column)
    return H3Graph(cells=cells, edges=edges)


def _add_grid_edges(
    edges: dict[tuple[str, str], H3Edge],
    width: int,
    height: int,
    x_coord: int,
    y_coord: int,
    high_barrier_column: int | None,
) -> None:
    source = f"{x_coord},{y_coord}"
    for dx, dy in ((1, 0), (0, 1)):
        next_x = x_coord + dx
        next_y = y_coord + dy
        if next_x >= width or next_y >= height:
            continue
        target = f"{next_x},{next_y}"
        slope_forward = 40.0 if high_barrier_column == x_coord else 0.0
        edges[(source, target)] = H3Edge(
            cell_a=source,
            cell_b=target,
            geo_distance=1.0,
            slope_a_to_b=slope_forward,
            slope_b_to_a=-slope_forward,
        )

