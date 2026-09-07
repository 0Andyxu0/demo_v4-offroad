"""Trafficability scoring and passability checks for H3 graphs."""

from __future__ import annotations

from collections.abc import Iterable
from math import inf, isfinite

from h3_offroad_planner.dynamics.bekker import BekkerChecker
from h3_offroad_planner.models import AssessmentError, H3Cell, H3Graph, VehicleProfile

__all__ = ["TrafficabilityAssessor"]

ALLOWED_WEIGHTS: frozenset[str] = frozenset({"slope", "lc_factor", "tri", "soil", "road_bonus"})


class TrafficabilityAssessor:
    """Legacy standalone evaluator retained outside the RoutePlan production chain."""

    def __init__(self, vehicle: VehicleProfile, weights: dict[str, float]) -> None:
        """Initialize the assessor with vehicle and non-negative feature weights."""
        if set(weights).difference(ALLOWED_WEIGHTS):
            unsupported = sorted(set(weights) - ALLOWED_WEIGHTS)
            raise ValueError(f"weights contain unsupported keys: {unsupported}")
        if any(not isfinite(value) or value < 0.0 for value in weights.values()):
            raise ValueError("all trafficability weights must be finite and non-negative.")
        if sum(weights.values()) <= 0.0:
            raise ValueError("trafficability weights must sum to a positive value.")
        self.vehicle = vehicle
        self.weights = weights
        self.bekker = BekkerChecker()

    def assess(self, graph: H3Graph) -> H3Graph:
        """Update cell `score` and `is_passable` fields in a graph."""
        if not graph.cells:
            raise AssessmentError("graph must contain at least one cell.")
        for cell in graph.cells.values():
            if cell.slope > self.vehicle.max_climb_angle_deg or cell.lc_factor == inf:
                cell.is_passable = False
            self.bekker.enrich_cell(cell, self.vehicle)
        _assign_soil_mobility(graph.cells.values())
        for cell in graph.cells.values():
            if not self.bekker.check(cell, self.vehicle):
                cell.is_passable = False
            cell.score = (
                0.0
                if not cell.is_passable
                else self._score_cell(
                    cell.slope,
                    cell.lc_factor,
                    cell.tri,
                    cell.soil_mobility,
                    cell.has_road,
                )
            )
            cell.cost_score = 1.0 - cell.score
        return graph

    def _score_cell(
        self,
        slope: float,
        lc_factor: float,
        tri: float,
        soil_mobility: float | None,
        has_road: bool,
    ) -> float:
        slope_score = max(0.0, 1.0 - slope / self.vehicle.max_climb_angle_deg)
        lc_score = 0.0 if lc_factor == inf else min(1.0, 1.0 / max(lc_factor, 1.0))
        tri_score = 1.0 / (1.0 + max(0.0, tri))
        soil_score = 0.8 if soil_mobility is None else soil_mobility
        road_score = 1.0 if has_road else 0.0
        total = (
            self.weights.get("slope", 0.0) * slope_score
            + self.weights.get("lc_factor", 0.0) * lc_score
            + self.weights.get("tri", 0.0) * tri_score
            + self.weights.get("soil", 0.0) * soil_score
            + self.weights.get("road_bonus", 0.0) * road_score
        )
        return min(max(total / sum(self.weights.values()), 0.0), 1.0)


def _assign_soil_mobility(cells: Iterable[H3Cell]) -> None:
    cell_list = list(cells)
    resistances = [
        cell.sinkage_resistance
        for cell in cell_list
        if cell.sinkage_resistance is not None and cell.soil_mobility != 0.0
    ]
    if not resistances:
        return
    min_resistance = min(resistances)
    max_resistance = max(resistances)
    span = max(max_resistance - min_resistance, 1.0e-6)
    for cell in cell_list:
        if cell.sinkage_resistance is not None and cell.soil_mobility != 0.0:
            normalized = (cell.sinkage_resistance - min_resistance) / span
            cell.soil_mobility = _mobility_from_normalized_resistance(normalized)


def _mobility_from_normalized_resistance(value: float) -> float:
    if value <= 0.2:
        return 0.9
    if value <= 0.5:
        return 0.8
    if value <= 0.8:
        return 0.7
    return 0.6
