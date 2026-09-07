"""GeoPackage, GeoJSON, and manifest exports for H3 planning artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from math import isfinite
from pathlib import Path

import geopandas as gpd
import h3
from shapely.geometry import LineString, Point, Polygon

from h3_offroad_planner.models import H3Cell, H3Graph, PlanningInputError
from h3_offroad_planner.models import Path as PlannerPath

__all__ = ["GISExporter"]

CRS_WGS84: str = "EPSG:4326"
GRAPH_CELLS_LAYER: str = "h3_cells"
GRAPH_EDGES_LAYER: str = "h3_edges"
THEME_LAYER_PREFIX: str = "h3_theme_"
THEME_COLORS: tuple[str, ...] = ("#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850")
NO_DATA_COLOR: str = "#bdbdbd"
SUPPORTED_THEME_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "cost_score",
        "elevation",
        "landcover_code",
        "landcover_type",
        "lc_factor",
        "score",
        "slope",
        "soil_code",
        "soil_mobility",
        "soil_type",
        "tri",
    }
)


class GISExporter:
    """Export H3 graph and path artifacts to GIS-friendly files."""

    @staticmethod
    def export_graph_gpkg(
        graph: H3Graph,
        path: str,
        theme_attributes: list[str] | None = None,
        style_manifest_path: str | None = None,
        layer_metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Write H3 cell polygons and edge lines to a GeoPackage.

        Args:
            graph: Non-empty in-memory H3 graph.
            path: Output GeoPackage path. Unit: filesystem path.
            theme_attributes: Optional H3 cell attributes exported as themed layers.
            style_manifest_path: Optional JSON style manifest path.
            layer_metadata: Optional scalar metadata copied into graph and theme layers.

        Raises:
            PlanningInputError: If the graph is empty.
            OSError: If the target cannot be written.
        """
        if not graph.cells:
            raise PlanningInputError("graph must contain at least one cell for export.")
        output_path = _prepare_parent(path)
        if output_path.exists():
            output_path.unlink()
        metadata = _metadata_fields(layer_metadata)
        _cells_gdf(graph, metadata).to_file(output_path, layer=GRAPH_CELLS_LAYER, driver="GPKG")
        _edges_gdf(graph, metadata).to_file(
            output_path,
            layer=GRAPH_EDGES_LAYER,
            driver="GPKG",
            mode="a",
        )
        attributes = _validated_theme_attributes(theme_attributes or [])
        if attributes:
            manifest = _export_theme_layers(graph, output_path, attributes, metadata)
            if style_manifest_path is not None:
                GISExporter.write_manifest(style_manifest_path, manifest)

    @staticmethod
    def export_path_gpkg(
        graph: H3Graph,
        path_result: PlannerPath,
        path: str,
        layer: str = "planned_path",
    ) -> None:
        """Write a planned path as a named GeoPackage layer."""
        if not layer.strip():
            raise PlanningInputError("GeoPackage path layer name must be non-empty.")
        output_path = _prepare_parent(path)
        mode = "a" if output_path.exists() else "w"
        _path_gdf(graph, path_result).to_file(
            output_path,
            layer=layer,
            driver="GPKG",
            mode=mode,
        )

    @staticmethod
    def export_path_geojson(graph: H3Graph, path_result: PlannerPath, path: str) -> None:
        """Write a planned path as a GeoJSON FeatureCollection."""
        output_path = _prepare_parent(path)
        _path_gdf(graph, path_result).to_file(output_path, driver="GeoJSON")

    @staticmethod
    def write_manifest(path: str, payload: Mapping[str, object]) -> None:
        """Write a UTF-8 JSON manifest for reproducing a demo run."""
        output_path = _prepare_parent(path)
        with output_path.open("w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")


def _prepare_parent(path: str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _cells_gdf(
    graph: H3Graph,
    layer_metadata: Mapping[str, object] | None = None,
) -> gpd.GeoDataFrame:
    records = [_cell_record(cell, layer_metadata) for cell in graph.cells.values()]
    geometries = [_cell_polygon(cell.h3index) for cell in graph.cells.values()]
    return gpd.GeoDataFrame(records, geometry=geometries, crs=CRS_WGS84)


def _cell_record(
    cell: H3Cell,
    layer_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "h3index": cell.h3index,
        "parent_h3": cell.parent_h3,
        "lat": _finite_or_none(cell.lat),
        "lng": _finite_or_none(cell.lng),
        "elevation": _finite_or_none(cell.elevation),
        "slope": _finite_or_none(cell.slope),
        "tri": _finite_or_none(cell.tri),
        "lc_factor": _finite_or_none(cell.lc_factor),
        "landcover_code": cell.landcover_code,
        "landcover_type": cell.landcover_type,
        "soil_code": cell.soil_code,
        "soil_type": cell.soil_type,
        "soil_texture": cell.soil_texture,
        "uscs": cell.uscs,
        "soil_moisture": _finite_or_none(cell.soil_moisture),
        "soil_mobility": _finite_or_none(cell.soil_mobility),
        "has_road": cell.has_road,
        "is_passable": cell.is_passable,
        "score": _finite_or_none(cell.score),
        "cost_score": _finite_or_none(cell.cost_score),
    }
    record.update(_metadata_fields(layer_metadata))
    return record


def _edges_gdf(
    graph: H3Graph,
    layer_metadata: Mapping[str, object] | None = None,
) -> gpd.GeoDataFrame:
    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    metadata = _metadata_fields(layer_metadata)
    for edge in graph.edges.values():
        first = graph.cells[edge.cell_a]
        second = graph.cells[edge.cell_b]
        record: dict[str, object] = {
            "cell_a": edge.cell_a,
            "cell_b": edge.cell_b,
            "distance_m": _finite_or_none(edge.geo_distance),
            "has_road": edge.has_road,
            "slope_a_b": _finite_or_none(edge.slope_a_to_b),
            "slope_b_a": _finite_or_none(edge.slope_b_to_a),
        }
        record.update(metadata)
        records.append(record)
        geometries.append(LineString([(first.lng, first.lat), (second.lng, second.lat)]))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=CRS_WGS84)


def _path_gdf(graph: H3Graph, path_result: PlannerPath) -> gpd.GeoDataFrame:
    coordinates = [_cell_lnglat(graph, cell_id) for cell_id in path_result.cells]
    geometry = Point(coordinates[0]) if len(coordinates) == 1 else LineString(coordinates)
    return gpd.GeoDataFrame(
        [
            {
                "cell_count": len(path_result.cells),
                "total_cost": _finite_or_none(path_result.total_cost),
                "start": path_result.cells[0],
                "goal": path_result.cells[-1],
            }
        ],
        geometry=[geometry],
        crs=CRS_WGS84,
    )


def _cell_lnglat(graph: H3Graph, cell_id: str) -> tuple[float, float]:
    if cell_id not in graph.cells:
        raise PlanningInputError(f"path cell={cell_id!r} is not present in graph.")
    cell = graph.cells[cell_id]
    return (cell.lng, cell.lat)


def _cell_polygon(h3index: str) -> Polygon:
    try:
        return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3index)])
    except (RuntimeError, ValueError) as exc:
        raise PlanningInputError(f"cell id is not a valid H3 index: {h3index!r}") from exc


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if isfinite(value) else None


def _validated_theme_attributes(attributes: list[str]) -> list[str]:
    seen: set[str] = set()
    valid: list[str] = []
    for raw_attribute in attributes:
        attribute = raw_attribute.strip()
        if attribute not in SUPPORTED_THEME_ATTRIBUTES:
            raise PlanningInputError(f"unsupported theme attribute: {attribute!r}")
        if attribute not in seen:
            seen.add(attribute)
            valid.append(attribute)
    return valid


def _export_theme_layers(
    graph: H3Graph,
    gpkg_path: Path,
    attributes: list[str],
    layer_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    manifest: dict[str, object] = {"attributes": {}, "color_ramp": list(THEME_COLORS)}
    for attribute in attributes:
        spec = _theme_spec(graph, attribute)
        _theme_gdf(graph, attribute, spec, layer_metadata).to_file(
            gpkg_path,
            layer=f"{THEME_LAYER_PREFIX}{attribute}",
            driver="GPKG",
            mode="a",
        )
        cast_attributes = manifest["attributes"]
        if isinstance(cast_attributes, dict):
            cast_attributes[attribute] = spec
    return manifest


def _theme_spec(graph: H3Graph, attribute: str) -> dict[str, object]:
    values = [_theme_value(cell, attribute) for cell in graph.cells.values()]
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    if len(numeric_values) == len([value for value in values if value is not None]):
        return _numeric_theme_spec(attribute, numeric_values)
    categories = sorted({str(value) for value in values if value is not None})
    return {
        "attribute": attribute,
        "field": "style_value",
        "kind": "categorical",
        "categories": categories,
        "colors": {
            category: THEME_COLORS[index % len(THEME_COLORS)]
            for index, category in enumerate(categories)
        },
    }


def _numeric_theme_spec(attribute: str, values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "attribute": attribute,
            "field": "style_value",
            "kind": "numeric",
            "max": None,
            "min": None,
        }
    return {
        "attribute": attribute,
        "field": "style_value",
        "kind": "numeric",
        "min": min(values),
        "max": max(values),
        "colors": list(THEME_COLORS),
    }


def _theme_gdf(
    graph: H3Graph,
    attribute: str,
    spec: dict[str, object],
    layer_metadata: Mapping[str, object] | None = None,
) -> gpd.GeoDataFrame:
    records = []
    geometries = []
    for cell in graph.cells.values():
        record = _cell_record(cell, layer_metadata)
        value = _theme_value(cell, attribute)
        record.update(_style_fields(value, spec))
        records.append(record)
        geometries.append(_cell_polygon(cell.h3index))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=CRS_WGS84)


def _style_fields(value: object, spec: dict[str, object]) -> dict[str, object]:
    if value is None:
        return {"style_value": None, "style_bin": "no_data", "style_color": NO_DATA_COLOR}
    if spec.get("kind") == "numeric" and isinstance(value, (int, float)):
        return _numeric_style_fields(float(value), spec)
    categories = spec.get("colors")
    if isinstance(categories, dict):
        color = str(categories.get(str(value), NO_DATA_COLOR))
    else:
        color = NO_DATA_COLOR
    return {"style_value": str(value), "style_bin": str(value), "style_color": color}


def _numeric_style_fields(value: float, spec: dict[str, object]) -> dict[str, object]:
    min_value = spec.get("min")
    max_value = spec.get("max")
    if not isinstance(min_value, (int, float)) or not isinstance(max_value, (int, float)):
        return {"style_value": value, "style_bin": 0, "style_color": NO_DATA_COLOR}
    span = max(float(max_value) - float(min_value), 1.0e-9)
    raw_bin = int((value - float(min_value)) / span * len(THEME_COLORS))
    bin_index = min(raw_bin, len(THEME_COLORS) - 1)
    return {"style_value": value, "style_bin": bin_index, "style_color": THEME_COLORS[bin_index]}


def _theme_value(cell: H3Cell, attribute: str) -> object:
    value: object = getattr(cell, attribute)
    if isinstance(value, float):
        return _finite_or_none(value)
    return value


def _metadata_fields(payload: Mapping[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    aliases = (
        ("artifact_kind", "artifact_kind"),
        ("coverage_mode", "coverage_mode"),
        ("is_continuous", "is_continuous"),
        ("is_continuous_coverage", "is_continuous"),
        ("source_is_continuous_coverage", "is_continuous"),
        ("res_fine", "source_res_fine"),
        ("source_res_fine", "source_res_fine"),
        ("res_coarse", "source_res_coarse"),
        ("source_res_coarse", "source_res_coarse"),
        ("sample_stride", "sample_stride"),
        ("source_sample_stride", "sample_stride"),
        ("max_cells", "max_cells"),
        ("source_max_cells", "max_cells"),
    )
    fields: dict[str, object] = {}
    for source_key, target_key in aliases:
        if source_key in payload and target_key not in fields:
            value = payload[source_key]
            if target_key == "is_continuous":
                fields[target_key] = int(bool(value))
            else:
                fields[target_key] = _metadata_scalar(value)
    return fields


def _metadata_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
