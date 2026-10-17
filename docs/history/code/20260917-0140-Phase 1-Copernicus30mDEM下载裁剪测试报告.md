# Phase 1: Copernicus 30m DEM 下载、裁剪与测试报告

> 时间：2026-09-17 01:40
> 分支：fix/independent-backup-and-sampling
> 状态：已完成可用上游 DEM 获取与验证

## 1. 数据源

使用 AWS 公开 Copernicus DEM 30m COG：

```text
https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com
```

该数据源无需登录，可直接 HTTP 下载。

## 2. 下载文件

已下载 4 个 1 度分幅：

```text
data/dem_copernicus_30m/Copernicus_DSM_COG_10_N31_00_E118_00_DEM.tif
data/dem_copernicus_30m/Copernicus_DSM_COG_10_N31_00_E119_00_DEM.tif
data/dem_copernicus_30m/Copernicus_DSM_COG_10_N32_00_E118_00_DEM.tif
data/dem_copernicus_30m/Copernicus_DSM_COG_10_N32_00_E119_00_DEM.tif
```

## 3. 裁剪范围

为了覆盖 QDX ROI 以及可能的上游汇水区，裁剪范围设置为：

```text
west:  118.85
south: 31.85
east:  119.15
north: 32.15
```

输出文件：

```text
data/dem_copernicus_30m/qdx_upstream_30m.tif
```

## 4. 裁剪结果

```text
size: 1080 x 1080
crs: EPSG:4326
res: 0.0002777778 deg (约 30m)
bounds:
  left:   118.849861
  bottom: 31.850139
  right:  119.149861
  top:    32.150139
valid_pixels: 1,166,400 / 1,166,400
nodata_ratio: 0.0%
min: -3.81
max: 437.19
mean: 44.06
```

## 5. 相对 QDX ROI 的缓冲区

QDX pilot ROI 范围：

```text
118.987 ~ 118.992 E
31.974 ~ 31.979 N
```

新 DEM 相对 ROI 的缓冲：

```text
西侧: 约 0.137 deg
南侧: 约 0.124 deg
东侧: 约 0.158 deg
北侧: 约 0.171 deg
```

约合 13~19 km，远大于原先 25~33m 的边界外扩。

## 6. DEM 可用性测试

执行：

```text
python scripts/validate_dem_asset.py data/dem_copernicus_30m/qdx_upstream_30m.tif
```

结果：

```text
DEM_VALIDATION_PASSED
```

判定依据：

- 原始高程范围合理；
- nodata 比例 0%；
- CRS 明确；
- 分辨率约 30m，符合上游宏观水文分析需求。

## 7. 新增脚本

`scripts/prepare_copernicus_dem.py`

功能：

- 合并 Copernicus 30m 分幅；
- 按指定 bounds 裁剪；
- 输出带压缩的 GeoTIFF；
- 打印裁剪结果统计。

## 8. 后续使用方式

- 将 `qdx_upstream_30m.tif` 作为宏观上游 DEM；
- 与 QDX 2m DEM 做混合，ROI 内保留高分辨率，外部使用 30m；
- 重新运行 GRASS r.watershed；
- 更新 TWI 阈值与 `upstream_complete`。

## 9. 结论

已获得可用的 Copernicus 30m 上游 DEM，并完成下载、裁剪、验证。下一步可以进入水文重建。
