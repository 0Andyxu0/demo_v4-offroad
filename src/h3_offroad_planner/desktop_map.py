# ruff: noqa: E501
"""PyQt5 QWebEngine map view for local H3 trafficability workflows."""

from __future__ import annotations

import json
from math import isfinite
from typing import cast

from PyQt5.QtCore import QUrl, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView

from h3_offroad_planner.map_config import TIANDITU_KEY, TIANDITU_LAYER_TYPE

__all__ = ["DesktopMapView"]

DEFAULT_CENTER_LAT: float = 32.03266
DEFAULT_CENTER_LNG: float = 119.03144
DEFAULT_ZOOM: int = 12
MAX_DESKTOP_MAP_SCRIPT_CHARS: int = 7_000_000

_MAP_TEMPLATE: str = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
<style>
html,body,#map{height:100%;width:100%;margin:0}
.leaflet-tooltip{background:#182633;color:#fff;border:1px solid #607d8b}
#map.selecting,#map.selecting *{cursor:crosshair!important}
.map-tools{display:flex;flex-direction:column;gap:5px;padding:7px;background:rgba(19,34,47,.88);border:1px solid rgba(255,255,255,.32);border-radius:7px;box-shadow:0 2px 9px rgba(0,0,0,.25)}
.map-tool{min-width:92px;padding:6px 8px;border:1px solid #7290a5;border-radius:4px;background:#fff;color:#182633;font-size:12px;text-align:left;cursor:pointer}
.map-tool:hover{background:#eaf4fb}.map-tool.active{background:#1479cf;color:#fff;border-color:#0a5ca3}.map-tool:disabled{opacity:.45;cursor:not-allowed}
.map-hint{margin-top:4px;max-width:150px;padding:5px 7px;border-radius:4px;background:rgba(19,34,47,.92);color:#fff;font-size:12px;line-height:1.35}
</style></head><body><div id="map"></div><script>
const KEY="__TIANDITU_KEY__";
const DEFAULT_LAYER="__TIANDITU_LAYER__";
const map=L.map("map",{center:[32.03266,119.03144],zoom:12,zoomControl:false,preferCanvas:true});
const image=L.tileLayer(`https://t{s}.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${KEY}`,{subdomains:"01234567",maxZoom:18});
const imageAnno=L.tileLayer(`https://t{s}.tianditu.gov.cn/cia_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cia&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${KEY}`,{subdomains:"01234567",maxZoom:18});
const vector=L.tileLayer(`https://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${KEY}`,{subdomains:"01234567",maxZoom:18});
const vectorAnno=L.tileLayer(`https://t{s}.tianditu.gov.cn/cva_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cva&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${KEY}`,{subdomains:"01234567",maxZoom:18});
if(DEFAULT_LAYER==="vector"){vector.addTo(map);vectorAnno.addTo(map);}else{image.addTo(map);imageAnno.addTo(map);}
L.control.layers({"卫星影像":image,"电子地图":vector},{"影像标注":imageAnno,"地图标注":vectorAnno},{position:"bottomleft"}).addTo(map);
L.control.zoom({position:"bottomright"}).addTo(map);
const drawn=new L.FeatureGroup().addTo(map);const markerLayer=L.layerGroup().addTo(map);let gridLayer=L.geoJSON(null);let routeLayer=L.geoJSON(null);let startMarker=null;let goalMarker=null;let mode="none";let eventSequence=0;let blockageEnabled=false;let blockedCells=new Set();let activeTheme="score";const tools={};let hint=null;
function emit(kind,payload){eventSequence+=1;document.title=`desktop:${eventSequence}:${kind}:${payload}`;}
function color(feature,theme){const value=feature.properties[theme];if(typeof value==="number"){const scaled=Math.max(0,Math.min(1,theme==="slope"?1-value/35:value));return `rgb(${Math.round(230*(1-scaled))},${Math.round(45+190*scaled)},70)`;}let hash=0;for(const char of String(value||"unknown"))hash=((hash<<5)-hash)+char.charCodeAt(0);return `hsl(${Math.abs(hash)%360},55%,48%)`;}
function tip(p){if(p.resolution==="parent")return `<b>父格网：</b>${p.h3index}<br><b>状态：</b>${p.status}<br><b>子格网：</b>${p.cell_count??0}<br><b>说明：</b>${p.error??(p.selectable?"点击查看子格网":"不可下钻")}`;return `<b>H3：</b>${p.h3index}<br><b>通行评分：</b>${p.score??"—"}<br><b>地物：</b>${p.landcover_type??"未知"}<br><b>坡度：</b>${p.slope??"—"}°<br><b>土壤：</b>${p.soil_type??"未知"}<br><b>高程：</b>${p.elevation??"—"} m`;}
function gridStyle(feature){const p=feature.properties||{};const cell=p.h3index;if(p.status==="failed")return{color:"#8b1e1e",weight:1.4,fillOpacity:.62,fillColor:"#d64545"};if(p.status==="empty")return{color:"#666",weight:1,fillOpacity:.30,fillColor:"#aaa"};if(blockedCells.has(cell))return{color:"#9e1b16",weight:2,fillOpacity:.78,fillColor:"#d92d20"};return{color:"#394e5c",weight:.55,fillOpacity:.58,fillColor:color(feature,activeTheme)};}
function drawGrid(geojson,theme){activeTheme=theme;if(gridLayer)map.removeLayer(gridLayer);gridLayer=L.geoJSON(geojson,{style:gridStyle,onEachFeature:(f,l)=>{l.bindTooltip(tip(f.properties),{sticky:true});l.on("click",event=>{const p=f.properties||{};if(p.resolution==="parent"){if(mode==="none"&&p.selectable&&p.h3index){L.DomEvent.stopPropagation(event);emit("parent_grid_click",p.h3index);}return;}if(mode==="blocked"&&blockageEnabled&&p.h3index){L.DomEvent.stopPropagation(event);emit("grid_click",p.h3index);}});}}).addTo(map);if(gridLayer.getLayers().length)map.fitBounds(gridLayer.getBounds());}
function drawRoute(geojson,html){if(routeLayer)map.removeLayer(routeLayer);if(!geojson)return;routeLayer=L.geoJSON(geojson,{style:{color:"#1479cf",weight:5},onEachFeature:(f,l)=>l.bindTooltip(html,{sticky:true})}).addTo(map);}
function marker(lat,lng,isStart){const markerColor=isStart?"#2e7d32":"#c62828";const label=isStart?"起点":"终点";return L.marker([lat,lng],{icon:L.divIcon({className:"",html:`<div style="background:${markerColor};width:14px;height:14px;border-radius:50%;border:2px solid white"></div>`})}).addTo(markerLayer).bindTooltip(label,{permanent:true,direction:"top"});}
function drawMarker(lat,lng,isStart){const next=marker(lat,lng,isStart);if(isStart){if(startMarker)markerLayer.removeLayer(startMarker);startMarker=next;}else{if(goalMarker)markerLayer.removeLayer(goalMarker);goalMarker=next;}}
function clearEndpoints(){if(startMarker)markerLayer.removeLayer(startMarker);if(goalMarker)markerLayer.removeLayer(goalMarker);startMarker=null;goalMarker=null;}
function setEndpoints(start,goal){clearEndpoints();if(Array.isArray(start))drawMarker(start[0],start[1],true);if(Array.isArray(goal))drawMarker(goal[0],goal[1],false);}
function setBlockedCells(cells){blockedCells=new Set(Array.isArray(cells)?cells:[]);if(gridLayer)gridLayer.setStyle(gridStyle);}
function setBlockageSelectionEnabled(enabled){blockageEnabled=Boolean(enabled);if(!blockageEnabled&&mode==="blocked")setSelectionMode("none");syncTools();}
function modeHint(next){return({study:"在地图上单击顶点并双击完成研究区。",start:"请点击地图选择起点。",goal:"请点击地图选择终点。",blocked:"请点击细层 H3 格网切换动态障碍。"})[next]||"";}
function syncTools(){for(const name of ["study","start","goal","blocked"]){if(tools[name])tools[name].classList.toggle("active",mode===name);}if(tools.blocked)tools.blocked.disabled=!blockageEnabled;if(hint)hint.textContent=modeHint(mode);const selecting=mode!=="none";document.getElementById("map").classList.toggle("selecting",selecting);}
function setSelectionMode(next){mode=next;syncTools();}
function beginStudyArea(){setSelectionMode("study");new L.Draw.Polygon(map,{shapeOptions:{color:"#ff7f32",weight:2,fillOpacity:.12}}).enable();}
function clearStudyArea(){drawn.clearLayers();setSelectionMode("none");emit("study_area","null");}
function resetProjectOverlays(){drawn.clearLayers();clearEndpoints();blockedCells=new Set();if(gridLayer){map.removeLayer(gridLayer);gridLayer=L.geoJSON(null);}setSelectionMode("none");}
function addTool(root,name,label,handler){const button=document.createElement("button");button.type="button";button.className="map-tool";button.textContent=label;button.onclick=handler;root.appendChild(button);tools[name]=button;}
const ToolControl=L.Control.extend({onAdd:function(){const root=L.DomUtil.create("div","map-tools");L.DomEvent.disableClickPropagation(root);L.DomEvent.disableScrollPropagation(root);addTool(root,"study","绘制研究区",beginStudyArea);addTool(root,"clearStudy","清除研究区",clearStudyArea);addTool(root,"start","选取起点",()=>setSelectionMode("start"));addTool(root,"goal","选取终点",()=>setSelectionMode("goal"));addTool(root,"blocked","标记动态障碍",()=>{if(blockageEnabled)setSelectionMode("blocked");});addTool(root,"clearEndpoints","清除端点",()=>{clearEndpoints();setSelectionMode("none");emit("action","clear_endpoints");});addTool(root,"clearBlocked","清空障碍",()=>{setBlockedCells([]);setSelectionMode("none");emit("action","clear_blocked");});addTool(root,"cancel","取消当前操作",()=>setSelectionMode("none"));hint=L.DomUtil.create("div","map-hint",root);syncTools();return root;}});
new ToolControl({position:"topright"}).addTo(map);
map.on(L.Draw.Event.CREATED,event=>{drawn.clearLayers();drawn.addLayer(event.layer);setSelectionMode("none");emit("study_area",JSON.stringify(event.layer.toGeoJSON()));});
map.on("click",event=>{if(mode==="start"||mode==="goal"){const role=mode;setSelectionMode("none");emit("map_click",role+":"+event.latlng.lat+","+event.latlng.lng);}});
</script></body></html>"""


class DesktopMapView(QWebEngineView):
    """Bridge one Leaflet/TianDiTu map to typed Qt signals and GeoJSON display."""

    study_area_selected = pyqtSignal(object)
    coordinate_selected = pyqtSignal(str, float, float)
    parent_grid_selected = pyqtSignal(str)
    grid_cell_selected = pyqtSignal(str)
    toolbar_action = pyqtSignal(str)
    map_error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._page_ready = False
        self._pending_scripts: list[str] = []
        page = self.page()
        if page is None:
            raise RuntimeError("QWebEngine page is unavailable.")
        page.titleChanged.connect(self._on_title_changed)
        self.loadFinished.connect(self._on_load_finished)
        rendered = _MAP_TEMPLATE.replace("__TIANDITU_KEY__", TIANDITU_KEY).replace(
            "__TIANDITU_LAYER__", TIANDITU_LAYER_TYPE
        )
        self.setHtml(rendered, QUrl("about:blank"))

    def begin_study_area(self) -> None:
        """Enable a one-polygon Leaflet.draw interaction."""
        self._run_js("beginStudyArea();")

    def clear_study_area(self) -> None:
        """Clear the selected ROI from the Leaflet study layer and notify Qt."""
        self._run_js("clearStudyArea();")

    def set_selection_mode(self, mode: str) -> None:
        """Set start, goal, blocked, or none selection mode for map clicks."""
        if mode not in {"none", "start", "goal", "blocked"}:
            raise ValueError("map selection mode is invalid.")
        self._run_js(f"setSelectionMode({json.dumps(mode)});")

    def draw_marker(self, lat: float, lng: float, is_start: bool) -> None:
        """Draw a WGS84 endpoint marker after desktop validation."""
        if not _is_wgs84_point(lat, lng):
            raise ValueError("marker coordinates must be finite WGS84 values.")
        self._run_js(f"drawMarker({lat}, {lng}, {'true' if is_start else 'false'});")

    def set_endpoints(
        self,
        start: tuple[float, float] | None,
        goal: tuple[float, float] | None,
    ) -> None:
        """Synchronize map endpoint markers from the canonical project state."""
        for value in (start, goal):
            if value is not None and not _is_wgs84_point(value[0], value[1]):
                raise ValueError("endpoint coordinates must be finite WGS84 values.")
        start_json = json.dumps(list(start) if start is not None else None)
        goal_json = json.dumps(list(goal) if goal is not None else None)
        self._run_js(f"setEndpoints({start_json}, {goal_json});")

    def set_blocked_cells(self, cells: list[str]) -> None:
        """Render the canonical dynamic blockage set on the current fine grid."""
        if any(not isinstance(cell, str) or not cell for cell in cells):
            raise ValueError("blocked cells must contain non-empty H3 ids.")
        self._run_js(f"setBlockedCells({json.dumps(cells)});")

    def set_blockage_selection_enabled(self, enabled: bool) -> None:
        """Enable blockage selection only while a fine grid is available."""
        self._run_js(f"setBlockageSelectionEnabled({'true' if enabled else 'false'});")

    def reset_project_overlays(self) -> None:
        """Clear visual map choices before loading another desktop project."""
        self._run_js("resetProjectOverlays();")

    def draw_grid(self, geojson: dict[str, object], theme: str) -> None:
        """Render bounded H3 grid GeoJSON with one supported thematic attribute."""
        if not theme.strip() or geojson.get("type") != "FeatureCollection":
            raise ValueError("grid must be a FeatureCollection and theme must be non-empty.")
        script = f"drawGrid({json.dumps(geojson, ensure_ascii=False)}, {json.dumps(theme)});"
        if len(script) > MAX_DESKTOP_MAP_SCRIPT_CHARS:
            self.map_error.emit(
                f"地图格网载荷包含 {len(script)} 个字符，超过桌面安全上限 "
                f"{MAX_DESKTOP_MAP_SCRIPT_CHARS}；已停止渲染。"
            )
            return
        self._run_js(script)

    def draw_route(self, geojson: dict[str, object] | None, tooltip_html: str) -> None:
        """Render route GeoJSON with pre-rendered escaped evaluation text."""
        if geojson is not None and geojson.get("type") != "FeatureCollection":
            raise ValueError("route GeoJSON must be a FeatureCollection when provided.")
        self._run_js(
            f"drawRoute({json.dumps(geojson, ensure_ascii=False)}, {json.dumps(tooltip_html)});"
        )

    def _run_js(self, script: str) -> None:
        if not self._page_ready:
            self._pending_scripts.append(script)
            return
        page = self.page()
        if page is None:
            self.map_error.emit("QWebEngine page is unavailable.")
            return
        page.runJavaScript(script)

    def _on_load_finished(self, success: bool) -> None:
        """Run state synchronization requested while the Leaflet page was loading."""
        if not success:
            self.map_error.emit("地图页面加载失败。")
            self._pending_scripts.clear()
            return
        self._page_ready = True
        page = self.page()
        if page is None:
            self.map_error.emit("QWebEngine page is unavailable.")
            self._pending_scripts.clear()
            return
        pending, self._pending_scripts = self._pending_scripts, []
        for script in pending:
            page.runJavaScript(script)

    def _on_title_changed(self, title: str) -> None:
        """Decode sequenced map events carried through the document-title bridge."""
        try:
            prefix, _event_id, kind, raw = title.split(":", maxsplit=3)
        except ValueError:
            return
        if prefix != "desktop":
            return
        if kind == "study_area":
            self._emit_study_area(raw)
        elif kind == "map_click":
            self._emit_coordinate(raw)
        elif kind == "grid_click":
            self._emit_grid_cell(raw)
        elif kind == "parent_grid_click":
            self._emit_parent_grid(raw)
        elif kind == "action":
            self.toolbar_action.emit(raw)

    def _emit_study_area(self, raw: str) -> None:
        if raw == "null":
            self.study_area_selected.emit(None)
            return
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            self.map_error.emit("地图返回了无效的研究区 GeoJSON。")
            return
        if not isinstance(value, dict):
            self.map_error.emit("地图研究区必须是 GeoJSON 对象。")
            return
        self.study_area_selected.emit(cast(dict[str, object], value))

    def _emit_coordinate(self, raw: str) -> None:
        try:
            role, values = raw.split(":", maxsplit=1)
            lat_text, lng_text = values.split(",", maxsplit=1)
            lat, lng = float(lat_text), float(lng_text)
        except ValueError:
            self.map_error.emit("地图返回了无效的坐标选择。")
            return
        if role not in {"start", "goal"} or not _is_wgs84_point(lat, lng):
            self.map_error.emit("地图坐标超出 WGS84 范围。")
            return
        self.coordinate_selected.emit(role, lat, lng)

    def _emit_grid_cell(self, cell_id: str) -> None:
        if not cell_id:
            self.map_error.emit("地图返回了空 H3 格网编号。")
            return
        self.grid_cell_selected.emit(cell_id)

    def _emit_parent_grid(self, parent_h3: str) -> None:
        if not parent_h3:
            self.map_error.emit("地图返回了空父格网编号。")
            return
        self.parent_grid_selected.emit(parent_h3)


def _is_wgs84_point(lat: float, lng: float) -> bool:
    """Return whether one latitude/longitude pair is finite and WGS84 bounded."""
    return isfinite(lat) and isfinite(lng) and -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0
