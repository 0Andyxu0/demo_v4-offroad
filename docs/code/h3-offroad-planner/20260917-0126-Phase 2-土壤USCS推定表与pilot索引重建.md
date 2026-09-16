# Phase 2: 土壤 USCS 推定表与 pilot 索引重建

> 时间：2026-09-17 01:26
> 分支：fix/independent-backup-and-sampling
> 状态：完成 USCS 推定映射，pilot 索引已重建并验证

## 1. 本阶段目标

- 将土壤目录从仅有中文土类名提升为带 USCS 与土质推定；
- 保留工程诚实性：推定值不是实验室或现场实测；
- 重建 pilot 索引，验证 soil_catalog 可用。

## 2. 已完成内容

### 2.1 USCS 推定映射启用

文件：src/h3_offroad_planner/preprocessing/gis_preprocessor.py

- 启用已有但未接入的 _soil_texture_mapping；
- load_soil_catalog 现在会为土壤代码填充：

```text
soil_texture
uscs
bekker_soil
```

映射规则为工程推定，来源基于南京土壤类型与常见岩土工程近似：

| 土壤类别 | soil_texture | uscs |
|---|---|---|
| 水稻土/沼泽水稻土/渗育水稻等 | ClLo | CL |
| 冲积土/潮土/灰潮土 | SiLo | ML |
| 棕色石灰/石灰土/紫色土/基性岩火 | SaLo | SM |
| 黄褐土/黄棕壤/红壤等 | Lo | CL |
| 水域/城区 | None | None |

### 2.2 新增测试

文件：tests/test_soil_catalog_mapping.py

```text
3 passed
```

覆盖：

- 水稻土映射为 CL/ClLo；
- 黄褐土映射为 CL/Lo；
- 水域/城区不生成 USCS。

### 2.3 恢复中心采样守卫

文件：src/h3_offroad_planner/grid/h3_grid_builder.py

- 面优势取样在大幅土壤栅格上会全部落空；
- 恢复源栅格过大则回退中心采样的守卫；
- 当前正式土壤栅格统一走中心采样，结果可靠。

### 2.4 pilot 索引重建验证

重建输出目录：

```text
.artifacts/phase2_pilot_tiles_v2
```

结果：

```text
cells_count: 53676
soil_code 非空: 53676
soil_catalog:
  44 水稻土 ClLo CL
  49 黄褐土 Lo   CL
sampling_mode: center
evidence_status: INCOMPLETE
missing_physical_inputs: [hydrology.upstream_complete]
```

说明土壤 USCS 已经进入 pilot 路由索引，当前唯一剩余物理证据缺口是上游水文完整性。

## 3. 关于 Open-Meteo 土壤含水率

- Open-Meteo 可以获取路线中心点附近的 0-5cm 表层土壤体积含水率；
- 当前系统已经在请求级环境快照中使用它计算 derived_pressure；
- 它不是逐 H3 格元的土壤物理属性，因此不能替代静态土壤 USCS/持水参数；
- 静态索引中 soil_moisture 仍保留为空，由请求时天气快照动态提供。

## 4. 当前完成度

| 项目 | 状态 |
|---|---|
| USCS 推定映射 | 完成 |
| 土壤目录测试 | 通过 |
| pilot 索引重建 | 完成 |
| 土壤含水率逐格静态化 | 不启用，保留请求级 Open-Meteo |
| 现场/实验室标定 | 未完成，作为后续增强项 |

整体完成度：约 60%。

## 5. 模块功能说明

- _profile_from_soil_code：将土壤代码转换为带 USCS/土质推定的 SoilProfile；
- _soil_texture_mapping：集中管理南京土壤代码到 USCS/土质的推定规则；
- H3GridBuilder：大栅格土壤回退中心采样，保证 soil_code 不丢失。

## 6. 下一步

- 等可用原始 DEM 后完成 Phase 1；
- 基于新 pilot 索引重新跑通端到端路线；
- 继续推进全 QDX 新索引重建。
