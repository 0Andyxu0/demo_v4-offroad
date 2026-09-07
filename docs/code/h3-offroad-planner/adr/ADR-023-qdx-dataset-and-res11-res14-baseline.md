# ADR-023: QDX 多图层地物适配、高精度父格网res11+子格网res14基线与空间物理属性扩展

- 状态：Accepted（当前闭环决策）
- 日期：2026-09-07
- 依据：pm-project-initiation 工业级规范、Zero-Trust 契约与 Ponytail 极简主义

## 背景与问题

1. 原始演示工程基于南京大区域数据（约 20km 尺度），默认采用父格网 res10（约 66m 边长）与子格网 res13（约 4.4m 边长）。在小尺度高精度测试区（如 QDX 试验区约 11 km²），需要更高精度的几何解析能力以准确分辨水体边界、建筑物轮廓以及林地树木株距（rowspacing）。
2. QDX 地物覆盖数据采用多独立 Shapefile（`water.shp`, `forest.shp`, `building.shp`, `grass.shp`, `plowland.shp`, `shrubwood.shp`, `wasteland.shp`），字段名为 `type`（'01'~'07'）和 `fclass`，并附带 `depth`（水深）与 `rowspacing`（株距）等物理属性。原工程仅支持单栅格或单矢量，且地物编码字段名硬编码为数值型。
3. QDX 数据坐标系为 CGCS2000（EPSG:4490），需确保与 WGS84（EPSG:4326）的无缝投影转换与容错。

## 决策

1. **默认分辨率升级**：
   - 默认父格网分辨率由 `res10` 调整为 `res11`（六边形边长约 24.9m，面积约 2,161 m²）。
   - 默认子格网分辨率由 `res13` 调整为 `res14`（六边形边长约 1.34m，面积约 6.3 m²）。
   - `H3GridBuilder`, `TileBuildRequest`, `RouteRequest` 的默认参数统一变更为 `res_fine=14`, `res_coarse=11` / `tile_res=11`。
2. **多矢量地物覆盖与字段标准化**：
   - `GISPreprocessor.load_landcover` 支持传入包含多个 Shapefile 的目录，自动读取全部矢量并合并为统一 WGS84 GeoDataFrame。
   - `H3GridBuilder` 扩展字段识别列表，支持 `type`, `fclass` 等列名，并将 `'01'`, `'02'` 等字符型编码和名称映射为标准整数代码。
3. **空间物理属性透传**：
   - 在 `H3Cell` 与特征提取流中扩展 `depth: float | None` 与 `rowspacing: float | None` 字段，完成非负实数边界防御检查，为后续涉水深度与林木穿行物理验算建立数据契约。
4. **土壤缺失安全降级**：
   - QDX 区域无独立土壤栅格时，系统沿用 `soil_path: null` 的安全退化通道，使用不确定性区间与地物综合模型，保持无锁零崩毁。

## 后果与验证

- 试验区 11 km² 在 res14 下具有亚米级空间分辨率，完美支持株距和建筑物避障。
- 零依赖膨胀，完全复用现有 GeoPandas / Rasterio / H3 栈，符合 Ponytail 极简标准。
- 所有单元测试通过，双盲测试覆盖率保持语句 ≥80%、分支 ≥70%。
