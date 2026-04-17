import math
from climbing_performance.models import Rider, Bike, Climb
from climbing_performance.aslp import summarise_aslp

def validate_positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


def validate_non_negative(value: float, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def compute_gradient(elevation_gain_m: float, distance_m: float) -> float:
    validate_positive(distance_m, "distance_m")
    validate_non_negative(elevation_gain_m, "elevation_gain_m")
    return (elevation_gain_m / distance_m) * 100.0


def compute_vam(elevation_gain_m: float, time_s: float) -> float:
    validate_positive(time_s, "time_s")
    validate_non_negative(elevation_gain_m, "elevation_gain_m")
    return elevation_gain_m / (time_s / 3600.0)  # m/h


def compute_road_speed(distance_m: float, time_s: float) -> float:
    validate_positive(distance_m, "distance_m")
    validate_positive(time_s, "time_s")
    return distance_m / time_s  # m/s


def compute_vertical_speed(elevation_gain_m: float, time_s: float) -> float:
    validate_positive(time_s, "time_s")
    validate_non_negative(elevation_gain_m, "elevation_gain_m")
    return elevation_gain_m / time_s  # m/s


def air_density_at_altitude(avg_altitude_m: float) -> float:
    if avg_altitude_m < 0:
        avg_altitude_m = 0.0

    rho0 = 1.225
    scale_height_m = 8500.0
    return rho0 * math.exp(-avg_altitude_m / scale_height_m)


def estimate_power_components(rider: Rider, bike: Bike, climb: Climb) -> dict:
    validate_positive(rider.mass_kg, "rider.mass_kg")
    validate_positive(bike.mass_kg, "bike.mass_kg")
    validate_positive(bike.frontal_area_m2, "bike.frontal_area_m2")
    validate_positive(climb.distance_m, "climb.distance_m")
    validate_positive(climb.time_s, "climb.time_s")
    validate_non_negative(climb.elevation_gain_m, "climb.elevation_gain_m")

    total_mass = rider.mass_kg + bike.mass_kg
    g = 9.81

    v_road = compute_road_speed(climb.distance_m, climb.time_s)
    v_vertical = compute_vertical_speed(climb.elevation_gain_m, climb.time_s)

    power_gravity = total_mass * g * v_vertical
    power_rolling = bike.rolling_resistance_coefficient * total_mass * g * v_road

    rho = air_density_at_altitude(climb.avg_altitude_m)
    cda = bike.drag_coefficient * bike.frontal_area_m2
    power_aero = 0.5 * rho * cda * (v_road ** 3)

    total_power = power_gravity + power_rolling + power_aero

    return {
        "power_gravity_w": power_gravity,
        "power_rolling_w": power_rolling,
        "power_aero_w": power_aero,
        "total_power_w": total_power,
    }


def estimate_watts_per_kg(power_w: float, rider: Rider) -> float:
    validate_positive(rider.mass_kg, "rider.mass_kg")
    return power_w / rider.mass_kg


def summarise_climb_performance(rider: Rider, bike: Bike, climb: Climb) -> dict:
    gradient_percent = compute_gradient(climb.elevation_gain_m, climb.distance_m)
    vam_m_per_h = compute_vam(climb.elevation_gain_m, climb.time_s)
    v_road = compute_road_speed(climb.distance_m, climb.time_s)
    v_vertical = compute_vertical_speed(climb.elevation_gain_m, climb.time_s)

    power = estimate_power_components(rider, bike, climb)
    wkg = estimate_watts_per_kg(power["total_power_w"], rider)

    return {
        "gradient_percent": gradient_percent,
        "vam_m_per_h": vam_m_per_h,
        "road_speed_m_per_s": v_road,
        "vertical_speed_m_per_s": v_vertical,
        **power,
        "watts_per_kg": wkg,
    }

def summarise_full_performance(rider: Rider, bike: Bike, climb: Climb) -> dict:
    climb_summary = summarise_climb_performance(rider, bike, climb)
    aslp_summary = summarise_aslp(
        observed_power_w=climb_summary["total_power_w"],
        rider_mass_kg=rider.mass_kg,
        avg_altitude_m=climb.avg_altitude_m,
    )

    return {
        **climb_summary,
        **aslp_summary,
    }