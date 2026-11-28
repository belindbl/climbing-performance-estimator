import math
from climbing_performance.models import Rider, Bike, Climb
from climbing_performance.aslp import summarise_aslp
from climbing_performance.weather import WeatherSample

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

def air_density_from_weather(
    temperature_c: float,
    pressure_hpa: float,
    relative_humidity_pct: float,
) -> float:
    """
    Compute moist-air density from surface pressure, temperature and humidity.

    Parameters:
    - temperature_c: temperature in °C
    - pressure_hpa: pressure in hPa
    - relative_humidity_pct: relative humidity from 0 to 100

    Returns:
    - air density in kg/m³
    """
    temperature_k = temperature_c + 273.15
    pressure_pa = pressure_hpa * 100.0
    if temperature_k <= 0.0:
        raise ValueError("temperature_c must be above absolute zero.")
    validate_positive(pressure_hpa, "pressure_hpa")
    if not 0.0 <= relative_humidity_pct <= 100.0:
        raise ValueError("relative_humidity_pct must be between 0 and 100.")

    # Buck equation for saturation vapor pressure over liquid water.
    saturation_pressure_hpa = 6.1121 * math.exp(
        (18.678 - temperature_c / 234.5)
        * (temperature_c / (257.14 + temperature_c))
    )
    vapor_pressure_pa = (
        saturation_pressure_hpa * relative_humidity_pct / 100.0 * 100.0
    )
    dry_air_pressure_pa = pressure_pa - vapor_pressure_pa
    if dry_air_pressure_pa <= 0.0:
        raise ValueError("pressure_hpa is too low for the supplied temperature and humidity.")

    dry_air_gas_constant = 287.05
    water_vapor_gas_constant = 461.495
    return (
        dry_air_pressure_pa / (dry_air_gas_constant * temperature_k)
        + vapor_pressure_pa / (water_vapor_gas_constant * temperature_k)
    )

def air_density_at_altitude(avg_altitude_m: float) -> float:
    if avg_altitude_m < 0:
        avg_altitude_m = 0.0

    rho0 = 1.225  # kg/m³ at sea level
    scale_height_m = 8500.0
    return rho0 * math.exp(-avg_altitude_m / scale_height_m)

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
    reference_weather: WeatherSample | None = None,
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
        if reference_weather is None or reference_weather.surface_pressure_hpa is None:
            raise ValueError(
                "Air density requires air_density_kg_m3 or reference weather "
                "with surface pressure."
            )
        rho = air_density_from_weather(
            temperature_c=reference_weather.temperature_c,
            pressure_hpa=reference_weather.surface_pressure_hpa,
            relative_humidity_pct=reference_weather.relative_humidity_pct,
        )
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


def summarise_climb_performance(
    rider: Rider,
    bike: Bike,
    climb: Climb,
    *,
    headwind_m_s: float = 0.0,
    air_density_kg_m3: float | None = None,
    reference_weather: WeatherSample | None = None,
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
        reference_weather=reference_weather,
    )
    wkg = estimate_watts_per_kg(power["total_power_w"], rider)

    return {
        "gradient_percent": gradient_percent,
        "vam_m_per_h": vam_m_per_h,
        "road_speed_m_per_s": v_road,
        "vertical_speed_m_per_s": v_vertical,
        **power,
        "watts_per_kg": wkg,
    }

def summarise_full_performance(
    rider: Rider,
    bike: Bike,
    climb: Climb,
    *,
    headwind_m_s: float = 0.0,
    air_density_kg_m3: float | None = None,
    reference_weather: WeatherSample | None = None,
) -> dict:
    climb_summary = summarise_climb_performance(
        rider,
        bike,
        climb,
        headwind_m_s=headwind_m_s,
        air_density_kg_m3=air_density_kg_m3,
        reference_weather=reference_weather,
    )
    aslp_summary = summarise_aslp(
        estimated_power_w=climb_summary["total_power_w"],
        rider_mass_kg=rider.mass_kg,
        avg_altitude_m=climb.avg_altitude_m,
    )

    return {
        **climb_summary,
        **aslp_summary,
    }
