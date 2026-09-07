"""Line-of-sight path shortcutting for in-memory graph paths."""

from __future__ import annotations

from collections.abc import Iterable

import h3

from h3_offroad_planner.models import H3Graph

__all__ = ["LOSPathSmoother"]


class LOSPathSmoother:
    """Smooth a path by greedily shortcutting across visible graph segments."""

    def __init__(self, graph: H3Graph) -> None:
        """Initialize the smoother.

        Args:
            graph: In-memory planning graph. Must contain all path cells.
        """
        self.graph = graph

    def smooth(self, raw_path: list[str]) -> list[str]:
        """Return a path with redundant visible intermediate cells removed.

        Args:
            raw_path: Non-empty ordered cell id path.

        Returns:
            Smoothed path. The first and last cells are unchanged, and the length is
            never greater than `raw_path`.

        Raises:
            ValueError: If `raw_path` is empty.
        """
        if not raw_path:
            raise ValueError("raw_path must be non-empty.")
        result = [raw_path[0]]
        anchor_index = 0
        while anchor_index < len(raw_path) - 1:
            next_index = self._farthest_visible_index(raw_path, anchor_index)
            result.append(raw_path[next_index])
            anchor_index = next_index
        return result

    def to_latlng(self, smoothed_path: list[str]) -> list[tuple[float, float]]:
        """Convert a cell-id path to latitude/longitude coordinates in degrees."""
        coordinates: list[tuple[float, float]] = []
        for cell_id in smoothed_path:
            if cell_id not in self.graph.cells:
                raise KeyError(f"cell_id={cell_id!r} is not present in graph.")
            cell = self.graph.cells[cell_id]
            coordinates.append((cell.lat, cell.lng))
        return coordinates

    def _farthest_visible_index(self, raw_path: list[str], anchor_index: int) -> int:
        candidate_index = len(raw_path) - 1
        while candidate_index > anchor_index + 1:
            if self._line_of_sight(raw_path[anchor_index], raw_path[candidate_index]):
                return candidate_index
            candidate_index -= 1
        return anchor_index + 1

    def _line_of_sight(self, cell_a: str, cell_b: str) -> bool:
        if cell_a not in self.graph.cells or cell_b not in self.graph.cells:
            return False
        if (cell_a, cell_b) in self.graph.edges or (cell_b, cell_a) in self.graph.edges:
            return self.graph.cells[cell_a].is_passable and self.graph.cells[cell_b].is_passable
        visible_cells = self._h3_line_cells(cell_a, cell_b)
        if visible_cells is not None:
            return all(
                cell_id in self.graph.cells and self.graph.cells[cell_id].is_passable
                for cell_id in visible_cells
            )
        visible_cells = self._axis_aligned_cells(cell_a, cell_b)
        if visible_cells is None:
            return False
        return all(self.graph.cells[cell_id].is_passable for cell_id in visible_cells)

    def _h3_line_cells(self, cell_a: str, cell_b: str) -> list[str] | None:
        """Return an H3 grid path for real H3 indexes without coordinate rounding."""
        try:
            return [str(cell) for cell in h3.grid_path_cells(cell_a, cell_b)]
        except (h3.H3BaseException, ValueError):
            return None

    def _axis_aligned_cells(self, cell_a: str, cell_b: str) -> list[str] | None:
        first = self.graph.cells[cell_a]
        second = self.graph.cells[cell_b]
        if first.lat != second.lat and first.lng != second.lng:
            return None
        if not (first.lat.is_integer() and first.lng.is_integer()):
            return None
        if not (second.lat.is_integer() and second.lng.is_integer()):
            return None
        if first.lat == second.lat:
            return self._horizontal_cells(int(first.lat), int(first.lng), int(second.lng))
        return self._vertical_cells(int(first.lng), int(first.lat), int(second.lat))

    def _horizontal_cells(self, lat: int, start_lng: int, end_lng: int) -> list[str] | None:
        step = 1 if end_lng >= start_lng else -1
        coordinates = ((lng, lat) for lng in range(start_lng, end_lng + step, step))
        return self._cells_from_coordinates(coordinates)

    def _vertical_cells(self, lng: int, start_lat: int, end_lat: int) -> list[str] | None:
        step = 1 if end_lat >= start_lat else -1
        coordinates = ((lng, lat) for lat in range(start_lat, end_lat + step, step))
        return self._cells_from_coordinates(coordinates)

    def _cells_from_coordinates(self, coordinates: Iterable[tuple[int, int]]) -> list[str] | None:
        cell_ids: list[str] = []
        for lng, lat in coordinates:
            matching = [
                cell_id
                for cell_id, cell in self.graph.cells.items()
                if int(cell.lng) == lng and int(cell.lat) == lat
            ]
            if len(matching) != 1:
                return None
            cell_ids.append(matching[0])
        return cell_ids
