from dataclasses import dataclass


# Empirical CP remaining fraction vs altitude, derived from Townsend et al. 2017
# Baseline is effectively sea-level/low-altitude performance.
_CP_REMAINING_POINTS = [
    (0.25, 1.0000),   # 250 m
    (1.25, 0.9518),   # 1250 m
    (2.25, 0.8707),   # 2250 m
    (3.25, 0.8062),   # 3250 m
    (4.25, 0.7258),   # 4250 m
]


def validate_non_negative(value: float, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def validate_positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


def _linear_interpolate(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))


def cp_remaining_fraction_at_altitude(avg_altitude_m: float) -> float:
    """
    Fraction of sea-level-equivalent sustained climbing power expected to remain
    at a given altitude.

    This is a pragmatic interpolation of Townsend et al. (2017) group mean CP data.
    For altitudes below 250 m, returns 1.0.
    For altitudes above 4250 m, linearly extrapolates using the final segment,
    but is clipped to a minimum of 0.50 to avoid nonsense values.
    """
    validate_non_negative(avg_altitude_m, "avg_altitude_m")
    x = avg_altitude_m / 1000.0

    if x <= _CP_REMAINING_POINTS[0][0]:
        return 1.0

    for i in range(len(_CP_REMAINING_POINTS) - 1):
        x0, y0 = _CP_REMAINING_POINTS[i]
        x1, y1 = _CP_REMAINING_POINTS[i + 1]
        if x0 <= x <= x1:
            return _linear_interpolate(x, x0, y0, x1, y1)

    # Extrapolate above final point using final segment slope
    x0, y0 = _CP_REMAINING_POINTS[-2]
    x1, y1 = _CP_REMAINING_POINTS[-1]
    y = _linear_interpolate(x, x0, y0, x1, y1)

    return max(0.50, y)


def sea_level_equivalent_power(observed_power_w: float, avg_altitude_m: float) -> float:
    """
    Convert observed sustained climb power at altitude to a sea-level-equivalent power.
    """
    validate_positive(observed_power_w, "observed_power_w")
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    return observed_power_w / fraction


def altitude_power_loss_percent(avg_altitude_m: float) -> float:
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    return (1.0 - fraction) * 100.0


def estimate_aslp_wkg(observed_power_w: float, rider_mass_kg: float, avg_altitude_m: float) -> float:
    validate_positive(rider_mass_kg, "rider_mass_kg")
    sea_level_power = sea_level_equivalent_power(observed_power_w, avg_altitude_m)
    return sea_level_power / rider_mass_kg


def summarise_aslp(observed_power_w: float, rider_mass_kg: float, avg_altitude_m: float) -> dict:
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    sea_level_power = sea_level_equivalent_power(observed_power_w, avg_altitude_m)

    return {
        "observed_power_w": observed_power_w,
        "avg_altitude_m": avg_altitude_m,
        "cp_remaining_fraction": fraction,
        "altitude_power_loss_percent": altitude_power_loss_percent(avg_altitude_m),
        "sea_level_equivalent_power_w": sea_level_power,
        "aslp_w_per_kg": sea_level_power / rider_mass_kg,
    }