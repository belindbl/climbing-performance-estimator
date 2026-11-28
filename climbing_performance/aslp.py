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

# Approximate ranges for the group-mean CP remaining fraction. These are
# derived from Townsend et al. (2017)'s reported 95% CIs for the CP decrease
# versus 250 m, divided by the reported 250 m group mean CP (269.9 W). This
# does not propagate baseline uncertainty or between-rider variability.
_CP_REMAINING_RANGES = [
    (0.25, 1.0000, 1.0000),
    (1.25, 1.0 - 20.3 / 269.9, 1.0 - 5.6 / 269.9),
    (2.25, 1.0 - 44.9 / 269.9, 1.0 - 24.8 / 269.9),
    (3.25, 1.0 - 64.8 / 269.9, 1.0 - 39.9 / 269.9),
    (4.25, 1.0 - 90.1 / 269.9, 1.0 - 59.7 / 269.9),
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


def cp_remaining_fraction_range_at_altitude(
    avg_altitude_m: float,
) -> tuple[float, float]:
    """Return approximate low/high group-mean CP fractions at this altitude.

    Bounds interpolate the published 95% confidence intervals for CP decline.
    They are not individual-rider prediction intervals.
    """
    validate_non_negative(avg_altitude_m, "avg_altitude_m")
    x = avg_altitude_m / 1000.0
    if x <= _CP_REMAINING_RANGES[0][0]:
        return 1.0, 1.0

    for (x0, low0, high0), (x1, low1, high1) in zip(
        _CP_REMAINING_RANGES, _CP_REMAINING_RANGES[1:]
    ):
        if x0 <= x <= x1:
            low = _linear_interpolate(x, x0, low0, x1, low1)
            high = _linear_interpolate(x, x0, high0, x1, high1)
            return max(0.50, low), min(1.0, high)

    x0, low0, high0 = _CP_REMAINING_RANGES[-2]
    x1, low1, high1 = _CP_REMAINING_RANGES[-1]
    low = _linear_interpolate(x, x0, low0, x1, low1)
    high = _linear_interpolate(x, x0, high0, x1, high1)
    low = max(0.50, low)
    high = max(low, min(1.0, high))
    return low, high


def sea_level_equivalent_power(estimated_power_w: float, avg_altitude_m: float) -> float:
    """
    Convert observed sustained climb power at altitude to a sea-level-equivalent power.
    """
    validate_positive(estimated_power_w, "estimated_power_w")
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    return estimated_power_w / fraction


def altitude_power_loss_percent(avg_altitude_m: float) -> float:
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    return (1.0 - fraction) * 100.0


def estimate_aslp_wkg(estimated_power_w: float, rider_mass_kg: float, avg_altitude_m: float) -> float:
    validate_positive(rider_mass_kg, "rider_mass_kg")
    sea_level_power = sea_level_equivalent_power(estimated_power_w, avg_altitude_m)
    return sea_level_power / rider_mass_kg


def summarise_aslp(estimated_power_w: float, rider_mass_kg: float, avg_altitude_m: float) -> dict:
    validate_positive(rider_mass_kg, "rider_mass_kg")
    fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    fraction_low, fraction_high = cp_remaining_fraction_range_at_altitude(avg_altitude_m)
    sea_level_power = sea_level_equivalent_power(estimated_power_w, avg_altitude_m)
    sea_level_power_low = estimated_power_w / fraction_high
    sea_level_power_high = estimated_power_w / fraction_low

    return {
        "estimated_power_w": estimated_power_w,
        "avg_altitude_m": avg_altitude_m,
        "cp_remaining_fraction": fraction,
        "cp_remaining_fraction_low": fraction_low,
        "cp_remaining_fraction_high": fraction_high,
        "altitude_power_loss_percent": altitude_power_loss_percent(avg_altitude_m),
        "sea_level_equivalent_power_w": sea_level_power,
        "sea_level_equivalent_power_low_w": sea_level_power_low,
        "sea_level_equivalent_power_high_w": sea_level_power_high,
        "aslp_w_per_kg": sea_level_power / rider_mass_kg,
        "aslp_w_per_kg_low": sea_level_power_low / rider_mass_kg,
        "aslp_w_per_kg_high": sea_level_power_high / rider_mass_kg,
        "uncertainty_method": (
            "Approximate group-mean range from published 95% CIs for CP decline; "
            "baseline uncertainty and individual-rider variability are not propagated."
        ),
    }
