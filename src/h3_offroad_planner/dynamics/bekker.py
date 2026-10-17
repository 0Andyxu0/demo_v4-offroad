"""Bekker soil sinkage and cone-index checks for offline assessment."""

from __future__ import annotations

from math import exp, isfinite, log

from h3_offroad_planner.models import AssessmentError, H3Cell, VehicleProfile

__all__ = ["BekkerChecker", "_cell_bekker_soil"]

GRAVITY_MPS2: float = 9.81
PA_PER_KPA: float = 1000.0
PA_TO_N_PER_MM2: float = 1.0e-6
M_TO_MM: float = 1000.0
RHO_WATER_G_CM3: float = 1.0
DEFAULT_LOADING_SPEED_MM_S: float = 5.0
CI_THRESHOLD_KPA: float = 185.73

SOIL_CI_PARAMS: dict[str, dict[str, float]] = {
    "SW": {"rho_d": 1.876, "a": 3.970, "b": 0.815},
    "SP": {"rho_d": 1.876, "a": 3.987, "b": 0.815},
    "SM": {"rho_d": 1.474, "a": 12.542, "b": -2.955},
    "ML": {"rho_d": 1.180, "a": 11.936, "b": -2.407},
    "CL": {"rho_d": 1.390, "a": 15.506, "b": -3.530},
    "CH": {"rho_d": 1.370, "a": 13.686, "b": -2.705},
    "MH": {"rho_d": 1.060, "a": 23.641, "b": -5.191},
}
BEKKER_SOIL_CODE: dict[str, float] = {"clayloam": 1.3, "loam": 1.0}
BEKKER_DRY_DENSITY: dict[str, float] = {"clayloam": 1.4, "loam": 1.4}
LEGACY_SOIL_PARAMS: dict[str, dict[str, float]] = {
    "sand_dry": {"n": 1.1, "k_c": 0.99, "k_phi": 1528.43},
    "clay_wet": {"n": 0.5, "k_c": 13.19, "k_phi": 692.15},
    "loam": {"n": 0.7, "k_c": 5.27, "k_phi": 1515.04},
}


class BekkerChecker:
    """Check soil mobility using CI and Bekker sinkage formulas."""

    def __init__(
        self,
        speed_score_floor: float = 0.2,
        ci_threshold_kpa: float = CI_THRESHOLD_KPA,
    ) -> None:
        """Initialize configurable Bekker helper controls.

        Args:
            speed_score_floor: Minimum score multiplier used by `compute_max_speed`.
                Unit: ratio. Valid range: [0, 1].
            ci_threshold_kpa: Minimum cone index threshold in kPa below which soil mobility is zero.
                Unit: kPa. Positive float.

        Raises:
            ValueError: If `speed_score_floor` is outside [0, 1] or `ci_threshold_kpa` <= 0.
        """
        if not isfinite(speed_score_floor) or not 0.0 <= speed_score_floor <= 1.0:
            raise ValueError("speed_score_floor must be finite and in [0, 1].")
        if not isfinite(ci_threshold_kpa) or ci_threshold_kpa <= 0.0:
            raise ValueError("ci_threshold_kpa must be finite and positive.")
        self.speed_score_floor = speed_score_floor
        self.ci_threshold_kpa = ci_threshold_kpa

    def check(self, cell: H3Cell, vehicle: VehicleProfile) -> bool:
        """Return whether a vehicle passes the cell sinkage constraint."""
        if not cell.is_passable:
            return False
        if cell.uscs is not None:
            self.enrich_cell(cell, vehicle)
            return cell.soil_mobility != 0.0 and _sinkage_passes(cell, vehicle)
        if cell.soil_type in LEGACY_SOIL_PARAMS:
            sinkage_m = self._legacy_sinkage_m(vehicle, LEGACY_SOIL_PARAMS[str(cell.soil_type)])
            return sinkage_m < vehicle.ground_clearance_m
        return True

    def compute_cone_index_kpa(self, uscs: str, soil_moisture: float) -> float:
        """Compute cone index from USCS class and volumetric soil moisture."""
        if uscs not in SOIL_CI_PARAMS:
            raise AssessmentError(f"unsupported USCS soil class: {uscs!r}")
        _require_ratio("soil_moisture", soil_moisture)
        params = SOIL_CI_PARAMS[uscs]
        mg = soil_moisture * RHO_WATER_G_CM3 / params["rho_d"] * 100.0
        if mg <= 0.0:
            raise AssessmentError("soil moisture mass percentage must be positive.")
        return float(exp(params["a"] + params["b"] * log(mg)) * 6.89476)

    def compute_sinkage(self, cell: H3Cell, vehicle: VehicleProfile) -> dict[str, float]:
        """Compute Bekker parameters and sinkage for one soil-equipped cell."""
        bekker_soil = _cell_bekker_soil(cell)
        if bekker_soil not in BEKKER_SOIL_CODE:
            raise AssessmentError(f"unsupported Bekker soil group: {bekker_soil!r}")
        soil_moisture = cell.soil_moisture
        if soil_moisture is None:
            raise AssessmentError("soil_moisture is required for Bekker sinkage.")
        _require_ratio("soil_moisture", soil_moisture)
        pressure = _ground_pressure_n_per_mm2(vehicle)
        wheel_width_mm = vehicle.tire_width_m * M_TO_MM
        w_percent = _water_percent(bekker_soil, soil_moisture)
        n_value = _bekker_exponent(bekker_soil, w_percent)
        k_c, k_phi = _bekker_stiffness(bekker_soil, w_percent)
        if not all(isfinite(value) and value > 0.0 for value in (n_value, k_c, k_phi)):
            raise AssessmentError("Bekker parameters must be finite positive values.")
        sinkage_mm = (pressure / (k_c / wheel_width_mm + k_phi)) ** (1.0 / n_value)
        resistance = wheel_width_mm * (k_c / wheel_width_mm + k_phi) * sinkage_mm ** (n_value + 1.0)
        return {
            "n": n_value,
            "k_c": k_c,
            "k_phi": k_phi,
            "sinkage_m": sinkage_mm / M_TO_MM,
            "sinkage_resistance": resistance / (n_value + 1.0),
        }

    def enrich_cell(self, cell: H3Cell, vehicle: VehicleProfile) -> None:
        """Populate CI, sinkage, resistance, and raw mobility fields on a cell."""
        if cell.uscs is None or cell.soil_moisture is None:
            return
        if cell.cone_index_kpa is None:
            cell.cone_index_kpa = self.compute_cone_index_kpa(cell.uscs, cell.soil_moisture)
        if cell.cone_index_kpa < self.ci_threshold_kpa:
            cell.soil_mobility = 0.0
            return
        if _cell_bekker_soil(cell) is None:
            return
        if cell.sinkage_m is not None and cell.sinkage_resistance is not None:
            return
        try:
            terms = self.compute_sinkage(cell, vehicle)
            cell.sinkage_m = terms["sinkage_m"]
            cell.sinkage_resistance = terms["sinkage_resistance"]
        except AssessmentError:
            # When Bekker parameters are not applicable (e.g. out of empirical moisture range),
            # fall back to declared soil/CI evaluation rules without forcing infinite sinkage.
            pass

    def compute_max_speed(self, cell: H3Cell, vehicle: VehicleProfile) -> float:
        """Return a conservative terrain speed cap in meters per second."""
        if not cell.is_passable:
            return 0.0
        mobility = 1.0 if cell.soil_mobility is None else max(cell.soil_mobility, 0.0)
        score_multiplier = max(self.speed_score_floor, cell.score)
        return max(vehicle.max_speed_kmh / 3.6 * score_multiplier * mobility, 0.0)

    def _legacy_sinkage_m(self, vehicle: VehicleProfile, params: dict[str, float]) -> float:
        tire_width_m = vehicle.tire_width_m
        contact_area_m2 = tire_width_m * vehicle.tire_radius_m * 0.5
        if contact_area_m2 <= 0.0:
            raise AssessmentError("vehicle tire contact area must be positive.")
        ground_pressure_kpa = (vehicle.mass_kg * GRAVITY_MPS2) / (
            4.0 * contact_area_m2 * PA_PER_KPA
        )
        stiffness = params["k_c"] / tire_width_m + params["k_phi"]
        exponent = params["n"]
        if not all(isfinite(value) and value > 0.0 for value in (stiffness, exponent)):
            raise AssessmentError("Bekker soil parameters must be finite positive values.")
        return float((ground_pressure_kpa / stiffness) ** (1.0 / exponent))


def _require_ratio(name: str, value: float) -> None:
    if not isfinite(value) or not 0.0 < value <= 1.0:
        raise AssessmentError(f"{name} must be a finite ratio in (0, 1].")


def _ground_pressure_n_per_mm2(vehicle: VehicleProfile) -> float:
    contact_area_m2 = vehicle.tire_width_m * vehicle.tire_radius_m * 0.5
    if contact_area_m2 <= 0.0:
        raise AssessmentError("vehicle tire contact area must be positive.")
    pressure_pa = (vehicle.mass_kg * GRAVITY_MPS2) / (4.0 * contact_area_m2)
    return pressure_pa * PA_TO_N_PER_MM2


def _water_percent(bekker_soil: str, soil_moisture: float) -> float:
    """Convert volumetric moisture theta_v (m3/m3) to gravimetric moisture w% using dry density rho_d.

    w% = (theta_v * rho_water / rho_d) * 100%
    where rho_water = 1.0 g/cm3 and rho_d is soil dry bulk density in g/cm3.
    """
    rho_d = BEKKER_DRY_DENSITY[bekker_soil]
    return soil_moisture * RHO_WATER_G_CM3 / rho_d * 100.0


def _bekker_exponent(bekker_soil: str, w_percent: float) -> float:
    soil_code = BEKKER_SOIL_CODE[bekker_soil]
    return (
        1.64757
        - 0.16264 * soil_code
        + 0.01483 * DEFAULT_LOADING_SPEED_MM_S
        - 0.008326 * w_percent
    )


def _bekker_stiffness(bekker_soil: str, w_percent: float) -> tuple[float, float]:
    """Compute Bekker stiffness parameters (k_c, k_phi) from gravimetric moisture percentage.

    Equations based on Shahgholi et al. (2024) for clay loam and loam:
    - clay loam: k_c = -34.53 * w% + 1475.7, k_phi = -33.606 * w% + 2560.6
      (in 10%~40% range: k_c in [1130.4, 94.5], k_phi in [2224.5, 1216.4])
    - loam: k_c = -24.59 * w% + 1065.9, k_phi = -24.482 * w% + 2087.4
      (in 10%~40% range: k_c in [820.0, 82.3], k_phi in [1842.6, 1108.1])
    """
    if bekker_soil == "clayloam":
        return -34.53 * w_percent + 1475.7, -33.606 * w_percent + 2560.6
    if bekker_soil == "loam":
        return -24.59 * w_percent + 1065.9, -24.482 * w_percent + 2087.4
    raise AssessmentError(f"unsupported Bekker soil group: {bekker_soil!r}")


def _sinkage_passes(cell: H3Cell, vehicle: VehicleProfile) -> bool:
    if cell.sinkage_m is None:
        return cell.cone_index_kpa is None or cell.cone_index_kpa >= CI_THRESHOLD_KPA
    return cell.sinkage_m < vehicle.ground_clearance_m


def _cell_bekker_soil(cell: H3Cell) -> str | None:
    if cell.soil_texture in {"ClLo", "SiClLo"}:
        return "clayloam"
    if cell.soil_texture in {"SaLo", "Lo", "SiLo"}:
        return "loam"
    if cell.uscs == "CL":
        return "clayloam"
    if cell.uscs in {"ML", "SM"}:
        return "loam"
    return None
