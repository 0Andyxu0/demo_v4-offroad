"""Directional physical edge-cost calculation for the MVP planner."""

from __future__ import annotations

from math import inf, isfinite, sqrt

from h3_offroad_planner.models import H3Edge, H3Graph, VehicleProfile

__all__ = ["CostFunction"]


class CostFunction:
    """Compute single-step movement cost with directional slope constraints."""

    def __init__(
        self,
        vehicle: VehicleProfile,
        k_r: float = 0.1,
        gravity_coeff: float = 5.0,
        score_coefficient: float = 0.0,
    ) -> None:
        """Initialize the cost function.

        Args:
            vehicle: Vehicle physical profile.
            k_r: TRI roughness coefficient. Unit: dimensionless. Valid range: >= 0.
            gravity_coeff: Uphill elevation penalty. Unit: cost per meter. Range: >= 0.
            score_coefficient: Cost multiplier for low trafficability score.
                Unit: dimensionless. Valid range: >= 0.

        Raises:
            ValueError: If coefficients are negative or non-finite.
        """
        if not isfinite(k_r) or k_r < 0.0:
            raise ValueError(f"k_r must be finite and non-negative, got {k_r!r}.")
        if not isfinite(gravity_coeff) or gravity_coeff < 0.0:
            raise ValueError(
                f"gravity_coeff must be finite and non-negative, got {gravity_coeff!r}."
            )
        if not isfinite(score_coefficient) or score_coefficient < 0.0:
            raise ValueError(
                f"score_coefficient must be finite and non-negative, got {score_coefficient!r}."
            )
        self.vehicle = vehicle
        self.k_r = k_r
        self.gravity_coeff = gravity_coeff
        self.score_coefficient = score_coefficient

    def compute(self, graph: H3Graph, from_cell: str, to_cell: str) -> float:
        """Compute directional movement cost from one cell to an adjacent cell.

        Args:
            graph: In-memory planning graph.
            from_cell: Source cell id. Must exist in `graph`.
            to_cell: Destination cell id. Must exist in `graph`.

        Returns:
            Movement cost. Unit: abstract non-negative cost. Returns infinity when
            the transition is physically impossible.
        """
        if from_cell not in graph.cells or to_cell not in graph.cells:
            raise KeyError(f"from_cell={from_cell!r} or to_cell={to_cell!r} is missing.")
        edge = _get_directed_edge(graph, from_cell, to_cell)
        if edge is None:
            return inf
        cell_from = graph.cells[from_cell]
        cell_to = graph.cells[to_cell]
        direction_slope = _directional_slope(edge, from_cell, to_cell)
        if not cell_to.is_passable or cell_to.lc_factor == inf:
            return inf
        if direction_slope > self.vehicle.max_climb_angle_deg:
            return inf
        theta_ratio = abs(direction_slope) / self.vehicle.max_climb_angle_deg
        terrain_factor = 1.0 + theta_ratio**2 + self.k_r * cell_to.tri
        score_factor = 1.0 + self.score_coefficient * float(cell_to.cost_score or 0.0)
        gravity_penalty = max(0.0, cell_to.elevation - cell_from.elevation) * self.gravity_coeff
        movement_cost = edge.geo_distance * cell_to.lc_factor * terrain_factor * score_factor
        return movement_cost + gravity_penalty

    def heuristic(self, graph: H3Graph, first: str, second: str) -> float:
        """Return a conservative coordinate-distance lower bound for legacy cost."""
        if first not in graph.cells or second not in graph.cells:
            raise KeyError("heuristic endpoints must exist in graph.")
        cell_a = graph.cells[first]
        cell_b = graph.cells[second]
        return sqrt((cell_a.lat - cell_b.lat) ** 2 + (cell_a.lng - cell_b.lng) ** 2)


def _get_directed_edge(graph: H3Graph, from_cell: str, to_cell: str) -> H3Edge | None:
    edge = graph.edges.get((from_cell, to_cell))
    if edge is not None:
        return edge
    return graph.edges.get((to_cell, from_cell))


def _directional_slope(edge: H3Edge, from_cell: str, to_cell: str) -> float:
    if edge.cell_a == from_cell and edge.cell_b == to_cell:
        return edge.slope_a_to_b
    if edge.cell_b == from_cell and edge.cell_a == to_cell:
        return edge.slope_b_to_a
    raise ValueError("edge endpoints do not match the requested direction.")
