"""Vectorized soil mechanics and Bekker computations for factor evaluation."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from h3_offroad_planner.dynamics.bekker import (
    BEKKER_DRY_DENSITY,
    BEKKER_SOIL_CODE,
    DEFAULT_LOADING_SPEED_MM_S,
    GRAVITY_MPS2,
    M_TO_MM,
    PA_TO_N_PER_MM2,
    RHO_WATER_G_CM3,
    SOIL_CI_PARAMS,
)
from h3_offroad_planner.models import VehicleProfile

__all__ = [
    "vectorized_bekker_sinkage",
    "vectorized_cone_index_kpa",
]


def vectorized_cone_index_kpa(
    uscs_values: npt.NDArray[np.str_],
    soil_moisture: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Compute cone index (kPa) for arrays of USCS soil classifications and moistures.

    Returns NaN for cells with unsupported USCS classes or non-positive moisture.
    """
    result = np.full(uscs_values.shape, np.nan, dtype=np.float64)
    for uscs, params in SOIL_CI_PARAMS.items():
        mask = uscs_values == uscs
        if not np.any(mask):
            continue
        moist = soil_moisture[mask]
        valid_moist = (moist > 0.0) & (moist <= 1.0) & np.isfinite(moist)
        if not np.any(valid_moist):
            continue
        sub_mask = mask.copy()
        sub_mask[mask] = valid_moist
        mg = soil_moisture[sub_mask] * RHO_WATER_G_CM3 / params["rho_d"] * 100.0
        result[sub_mask] = np.exp(params["a"] + params["b"] * np.log(mg)) * 6.89476
    return result


def vectorized_bekker_sinkage(
    bekker_soils: npt.NDArray[np.str_],
    soil_moistures: npt.NDArray[np.float64],
    vehicle: VehicleProfile,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Compute Bekker sinkage depth (m) and resistance (N) in batch for a vehicle.

    Returns (sinkage_m, sinkage_resistance_n) arrays. Unsupported soil types or
    invalid moisture values result in NaN entries.
    """
    sinkage_m = np.full(bekker_soils.shape, np.nan, dtype=np.float64)
    resistance_n = np.full(bekker_soils.shape, np.nan, dtype=np.float64)

    wheel_width_mm = vehicle.tire_width_m * M_TO_MM
    contact_area_m2 = vehicle.tire_width_m * vehicle.tire_radius_m * 0.5
    if contact_area_m2 <= 0.0:
        return sinkage_m, resistance_n

    pressure_pa = (vehicle.mass_kg * GRAVITY_MPS2) / (4.0 * contact_area_m2)
    pressure = pressure_pa * PA_TO_N_PER_MM2

    for soil_name in ("clayloam", "loam"):
        mask = (
            (bekker_soils == soil_name)
            & (soil_moistures > 0.0)
            & (soil_moistures <= 1.0)
            & np.isfinite(soil_moistures)
        )
        if not np.any(mask):
            continue
        moist = soil_moistures[mask]
        rho_d = BEKKER_DRY_DENSITY[soil_name]
        w_percent = moist * RHO_WATER_G_CM3 / rho_d * 100.0
        soil_code = BEKKER_SOIL_CODE[soil_name]
        n_val = (
            1.64757
            - 0.16264 * soil_code
            + 0.01483 * DEFAULT_LOADING_SPEED_MM_S
            - 0.008326 * w_percent
        )
        if soil_name == "clayloam":
            k_c = -34.53 * w_percent + 1075.7
            k_phi = -33.606 * w_percent + 2560.6
        else:
            k_c = -24.59 * w_percent + 1065.9
            k_phi = -24.482 * w_percent + 2087.4

        stiffness = k_c / wheel_width_mm + k_phi
        pos = (n_val > 0.0) & (stiffness > 0.0)
        if not np.any(pos):
            continue

        sub_mask = mask.copy()
        sub_mask[mask] = pos
        p_stiff = stiffness[pos]
        p_n = n_val[pos]
        s_mm = (pressure / p_stiff) ** (1.0 / p_n)
        s_m = s_mm / M_TO_MM
        r = wheel_width_mm * p_stiff * (s_mm ** (p_n + 1.0)) / (p_n + 1.0)
        sinkage_m[sub_mask] = s_m
        resistance_n[sub_mask] = r

    return sinkage_m, resistance_n
