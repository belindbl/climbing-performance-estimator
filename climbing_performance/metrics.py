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


def compute_road_speed_km_per_h(distance_m: float, time_s: float) -> float:
    return compute_road_speed(distance_m, time_s) * 3.6


def compute_vertical_speed(elevation_gain_m: float, time_s: float) -> float:
    validate_positive(time_s, "time_s")
    validate_non_negative(elevation_gain_m, "elevation_gain_m")
    return elevation_gain_m / time_s  # m/s

def air_density_from_weather(
    altitude_m: float,
    temperature_c: float,
    pressure_hpa: float,
) -> float:
    """
    Compute air density using the ideal gas law.

    Parameters:
    - altitude_m: altitude (for validation only here)
    - temperature_c: temperature in °C
    - pressure_hpa: pressure in hPa

    Returns:
    - air density in kg/m³
    """
    if altitude_m < 0:
        altitude_m = 0.0

    temperature_k = temperature_c + 273.15
    pressure_pa = pressure_hpa * 100.0

    R = 287.05  # J/(kg·K) for dry air

    return pressure_pa / (R * temperature_k)

def air_density_at_altitude(avg_altitude_m: float) -> float:
    if avg_altitude_m < 0:
        avg_altitude_m = 0.0

    rho0 = 1.225  # kg/m³ at sea level
    scale_height_m = 8500.0
    return rho0 * math.exp(-avg_altitude_m / scale_height_m)


def air_density_at_altitude_and_temperature(
    avg_altitude_m: float,
    temperature_c: float,
) -> float:
    """Estimate density from altitude pressure decay and actual temperature."""
    if avg_altitude_m < 0:
        avg_altitude_m = 0.0

    standard_temperature_k = 288.15 - 0.0065 * avg_altitude_m
    actual_temperature_k = temperature_c + 273.15
    validate_positive(actual_temperature_k, "temperature_k")
    return air_density_at_altitude(avg_altitude_m) * (
        standard_temperature_k / actual_temperature_k
    )


def compute_air_speed(v_road: float, v_headwind_m_s: float) -> float:
    """"
    compute relative air speed
    
    v_headwind_m_s:
        positive = headwind
        negative = tailwind
    """
    return v_road + v_headwind_m_s

def estimate_power_components(
    rider: Rider,
    bike: Bike,
    climb: Climb,
    *,
    headwind_m_s: float = 0.0,
    air_density_kg_m3: float | None = None,
) -> dict:
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

    rho = air_density_kg_m3
    if rho is None:
        rho = air_density_at_altitude(climb.avg_altitude_m)
    validate_positive(rho, "air_density_kg_m3")

    cda = bike.drag_coefficient * bike.frontal_area_m2
    v_air = max(0.0, compute_air_speed(v_road, v_headwind_m_s=headwind_m_s))
    power_aero = 0.5 * rho * cda * (v_air ** 3)

    total_power = power_gravity + power_rolling + power_aero

    return {
        "power_gravity_w": power_gravity,
        "power_rolling_w": power_rolling,
        "power_aero_w": power_aero,
        "total_power_w": total_power,
        "headwind_m_s": headwind_m_s,
        "air_density_kg_m3": rho,
    }


def estimate_watts_per_kg(power_w: float, rider: Rider) -> float:
    validate_positive(rider.mass_kg, "rider.mass_kg")
    return power_w / rider.mass_kg


def drivetrain_adjusted_power(
    resistive_power_w: float,
    drivetrain_efficiency: float,
) -> float:
    validate_positive(resistive_power_w, "resistive_power_w")
    if not 0.0 < drivetrain_efficiency <= 1.0:
        raise ValueError("drivetrain_efficiency must be > 0 and <= 1.")

    return resistive_power_w / drivetrain_efficiency


def summarise_climb_performance(
    rider: Rider,
    bike: Bike,
    climb: Climb,
    *,
    headwind_m_s: float = 0.0,
    air_density_kg_m3: float | None = None,
    drivetrain_efficiency: float = 1.0,
) -> dict:
    gradient_percent = compute_gradient(climb.elevation_gain_m, climb.distance_m)
    vam_m_per_h = compute_vam(climb.elevation_gain_m, climb.time_s)
    v_road = compute_road_speed(climb.distance_m, climb.time_s)
    v_vertical = compute_vertical_speed(climb.elevation_gain_m, climb.time_s)

    power = estimate_power_components(
        rider,
        bike,
        climb,
        headwind_m_s=headwind_m_s,
        air_density_kg_m3=air_density_kg_m3,
    )
    wkg = estimate_watts_per_kg(power["total_power_w"], rider)
    crank_power_w = drivetrain_adjusted_power(
        power["total_power_w"],
        drivetrain_efficiency,
    )

    return {
        "gradient_percent": gradient_percent,
        "vam_m_per_h": vam_m_per_h,
        "road_speed_m_per_s": v_road,
        "road_speed_km_per_h": v_road * 3.6,
        "vertical_speed_m_per_s": v_vertical,
        **power,
        "watts_per_kg": wkg,
        "crank_power_w": crank_power_w,
        "crank_watts_per_kg": estimate_watts_per_kg(crank_power_w, rider),
        "drivetrain_efficiency": drivetrain_efficiency,
        "drivetrain_loss_w": crank_power_w - power["total_power_w"],
    }

def summarise_full_performance(
    rider: Rider,
    bike: Bike,
    climb: Climb,
    *,
    headwind_m_s: float = 0.0,
    air_density_kg_m3: float | None = None,
    drivetrain_efficiency: float = 1.0,
) -> dict:
    climb_summary = summarise_climb_performance(
        rider,
        bike,
        climb,
        headwind_m_s=headwind_m_s,
        air_density_kg_m3=air_density_kg_m3,
        drivetrain_efficiency=drivetrain_efficiency,
    )
    aslp_summary = summarise_aslp(
        observed_power_w=climb_summary["total_power_w"],
        rider_mass_kg=rider.mass_kg,
        avg_altitude_m=climb.avg_altitude_m,
    )

    return {
        **climb_summary,
        **aslp_summary,
    }
