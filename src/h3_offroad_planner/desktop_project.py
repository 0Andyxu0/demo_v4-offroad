"""Structured desktop-project state shared by the Qt settings and map UI."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from h3_offroad_planner.cli import ROUTE_FIELDS, TILE_BUILD_FIELDS
from h3_offroad_planner.models import ConfigError

__all__ = ["DesktopProjectState", "load_project_yaml", "validate_study_area"]

_PROJECT_SECTIONS: frozenset[str] = frozenset({"tile_build", "route"})
_PRESENTATION_SECTIONS: frozenset[str] = frozenset({"map_display"})


@dataclass
class DesktopProjectState:
    """The only editable configuration source for the desktop client.

    The two request mappings deliberately retain every imported value.  This lets
    the settings dialog edit the fields it understands without discarding valid
    fields that have no current control.  A map-drawn study area is held as
    geometry until a run or export materializes it as GeoJSON.
    """

    tile_build: dict[str, object]
    route: dict[str, object]
    extra_sections: dict[str, object] = field(default_factory=dict)
    study_area_geojson: dict[str, object] | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> DesktopProjectState:
        """Create an editable project from a decoded delivery YAML mapping."""
        tile_build = value.get("tile_build")
        route = value.get("route")
        if not isinstance(tile_build, dict) or not isinstance(route, dict):
            raise ConfigError("desktop project YAML must contain tile_build and route mappings.")
        return cls(
            tile_build=copy.deepcopy(cast(dict[str, object], tile_build)),
            route=copy.deepcopy(cast(dict[str, object], route)),
            extra_sections={
                key: copy.deepcopy(item)
                for key, item in value.items()
                if key not in _PROJECT_SECTIONS
            },
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a detached delivery mapping without materializing map geometry."""
        payload = copy.deepcopy(self.extra_sections)
        payload["tile_build"] = copy.deepcopy(self.tile_build)
        payload["route"] = copy.deepcopy(self.route)
        return payload

    def unsupported_fields(self) -> list[str]:
        """List imported field paths that the existing request adapters cannot run."""
        unsupported = [
            str(key) for key in self.extra_sections if key not in _PRESENTATION_SECTIONS
        ]
        unsupported.extend(
            f"tile_build.{key}" for key in self.tile_build if key not in TILE_BUILD_FIELDS
        )
        unsupported.extend(f"route.{key}" for key in self.route if key not in ROUTE_FIELDS)
        return sorted(unsupported)

    def ensure_runnable(self) -> None:
        """Reject preserved, but backend-unsupported, fields before any operation starts."""
        unsupported = self.unsupported_fields()
        if unsupported:
            raise ConfigError(
                "desktop project contains backend-unsupported fields: " + ", ".join(unsupported)
            )

    def set_study_area(self, geojson: dict[str, object]) -> None:
        """Use a map-drawn Polygon or MultiPolygon as the active research area."""
        validate_study_area(geojson)
        self.study_area_geojson = copy.deepcopy(geojson)

    def clear_study_area(self) -> None:
        """Return to the ROI layer path stored in the project configuration."""
        self.study_area_geojson = None

    def endpoint(self, role: str) -> tuple[float, float] | None:
        """Return one stored coordinate endpoint when it is complete and valid."""
        if role not in {"start", "goal"}:
            raise ValueError("endpoint role must be start or goal.")
        lat = self.route.get(f"{role}_lat")
        lng = self.route.get(f"{role}_lng")
        if lat is None and lng is None:
            return None
        if not _is_wgs84_point(lat, lng):
            return None
        return cast(float, lat), cast(float, lng)

    def set_endpoint(self, role: str, lat: float, lng: float) -> None:
        """Apply a map endpoint and explicitly select coordinate-input mode."""
        if role not in {"start", "goal"} or not _is_wgs84_point(lat, lng):
            raise ConfigError("endpoint must be a finite WGS84 latitude/longitude pair.")
        self.route[f"{role}_lat"] = lat
        self.route[f"{role}_lng"] = lng
        self.route["input_mode"] = "coordinates"

    def clear_endpoints(self) -> None:
        """Remove map-coordinate endpoints without discarding an endpoint-layer path."""
        for key in ("start_lat", "start_lng", "goal_lat", "goal_lng"):
            self.route.pop(key, None)

    def blocked_cells(self) -> list[str]:
        """Return validated dynamic H3 blockages from the canonical route mapping."""
        value = self.route.get("blocked_cells", [])
        if not isinstance(value, list) or any(
            not isinstance(cell, str) or not cell for cell in value
        ):
            raise ConfigError("route.blocked_cells must contain non-empty H3 ids.")
        if len(set(value)) != len(value):
            raise ConfigError("route.blocked_cells must contain unique H3 ids.")
        return list(value)

    def toggle_blocked_cell(self, cell_id: str) -> bool:
        """Toggle a blockage and return whether the cell is now blocked."""
        if not isinstance(cell_id, str) or not cell_id:
            raise ConfigError("H3 blockage id must be non-empty.")
        blocked = self.blocked_cells()
        if cell_id in blocked:
            blocked.remove(cell_id)
            active = False
        else:
            blocked.append(cell_id)
            active = True
        self.route["blocked_cells"] = blocked
        return active

    def clear_blocked_cells(self) -> None:
        """Clear every map-selected dynamic blockage."""
        self.route["blocked_cells"] = []

    def candidate_index(self) -> int:
        """Return the active candidate index, retaining backend validation semantics."""
        value = self.route.get("candidate_index", 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ConfigError("route.candidate_index must be a non-negative integer.")
        return value

    def set_candidate_index(self, index: int) -> None:
        """Store the result-panel candidate choice in the canonical route mapping."""
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ConfigError("route.candidate_index must be a non-negative integer.")
        self.route["candidate_index"] = index

    def build_run_payload(self, session_root: Path) -> dict[str, object]:
        """Create one execution payload and materialize any map research geometry."""
        self.ensure_runnable()
        payload = self.to_mapping()
        payload.pop("map_display", None)
        if self.study_area_geojson is not None:
            roi_path = write_session_study_area(self.study_area_geojson, session_root)
            tile = _mapping(payload, "tile_build")
            route = _mapping(payload, "route")
            tile["roi_layer_path"] = roi_path
            route["roi_layer_path"] = roi_path
        return payload

    def orthophoto_overlay(self) -> tuple[Path, list[list[float]], float] | None:
        """Read optional display-only orthophoto preview metadata from the project."""
        display = self.extra_sections.get("map_display")
        if display is None:
            return None
        if not isinstance(display, dict):
            raise ConfigError("map_display must be a mapping.")
        metadata_value = display.get("orthophoto_preview_metadata_path")
        if metadata_value is None:
            return None
        if not isinstance(metadata_value, str) or not metadata_value:
            raise ConfigError("map_display.orthophoto_preview_metadata_path must be a path string.")
        metadata_path = Path(metadata_value)
        if not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read orthophoto preview metadata: {metadata_path}") from exc
        if not isinstance(metadata, dict):
            raise ConfigError("orthophoto preview metadata must be a JSON object.")
        preview_value = metadata.get("preview_path")
        bounds = metadata.get("bounds_wgs84")
        if not isinstance(preview_value, str) or not isinstance(bounds, list):
            raise ConfigError("orthophoto preview metadata lacks preview_path or bounds_wgs84.")
        opacity = display.get("orthophoto_opacity", 0.8)
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)):
            raise ConfigError("map_display.orthophoto_opacity must be numeric.")
        return Path(preview_value), cast(list[list[float]], bounds), float(opacity)

    def export_yaml(self, path: Path) -> Path | None:
        """Write YAML and, for drawn geometry, a paired relative-path GeoJSON artifact."""
        payload = self.to_mapping()
        roi_path: Path | None = None
        if self.study_area_geojson is not None:
            roi_path = path.with_name(f"{path.stem}.roi.geojson")
            write_study_area_file(self.study_area_geojson, roi_path)
            tile = _mapping(payload, "tile_build")
            route = _mapping(payload, "route")
            relative_path = roi_path.name
            tile["roi_layer_path"] = relative_path
            route["roi_layer_path"] = relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return roi_path


def load_project_yaml(path: Path) -> DesktopProjectState:
    """Parse a selected YAML file without changing the current desktop project on error."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML project: {path}") from exc
    if not isinstance(value, dict):
        raise ConfigError("desktop project YAML must contain a mapping.")
    return DesktopProjectState.from_mapping(cast(dict[str, object], value))


def validate_study_area(geojson: dict[str, object]) -> BaseGeometry:
    """Validate the Polygon/MultiPolygon geometry used by map selection and export."""
    if not isinstance(geojson, dict):
        raise ConfigError("study area must be a GeoJSON object.")
    try:
        geometry = shape(geojson.get("geometry", geojson))
    except (TypeError, ValueError) as exc:
        raise ConfigError("study area must be valid GeoJSON.") from exc
    if (
        geometry.geom_type not in {"Polygon", "MultiPolygon"}
        or not geometry.is_valid
        or geometry.area <= 0.0
    ):
        raise ConfigError("study area must be a non-empty valid Polygon or MultiPolygon.")
    return geometry


def write_session_study_area(geojson: dict[str, object], session_root: Path) -> str:
    """Write the active map research area to a run-specific session directory."""
    output = session_root / uuid.uuid4().hex / "study_area.geojson"
    write_study_area_file(geojson, output)
    return str(output)


def write_study_area_file(geojson: dict[str, object], output: Path) -> None:
    """Write validated map geometry as a single-feature GeoJSON collection."""
    geometry = validate_study_area(geojson)
    output.parent.mkdir(parents=True, exist_ok=True)
    feature = {
        "type": "Feature",
        "properties": {},
        "geometry": json.loads(json.dumps(geometry.__geo_interface__)),
    }
    output.write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"request field {key!r} must be a mapping.")
    return cast(dict[str, object], value)


def _is_wgs84_point(lat: object, lng: object) -> bool:
    return (
        not isinstance(lat, bool)
        and not isinstance(lng, bool)
        and isinstance(lat, (int, float))
        and isinstance(lng, (int, float))
        and isfinite(float(lat))
        and isfinite(float(lng))
        and -90.0 <= float(lat) <= 90.0
        and -180.0 <= float(lng) <= 180.0
    )
