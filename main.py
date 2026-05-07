from __future__ import annotations

import argparse
from pathlib import Path

from climbing_performance.gpx import parse_gpx
from climbing_performance.models import Bike, Rider
from climbing_performance.weather import WeatherAPIError
from climbing_performance.api import (
    DEFAULT_BIKE_MASS_KG,
    DEFAULT_CDA_M2,
    DEFAULT_RIDER_MASS_KG,
    DEFAULT_ROLLING_RESISTANCE_COEFFICIENT,
    DEFAULT_WIND_EXPOSURE_FACTOR,
)
from climbing_performance.workflow import (
    RouteSegmentAdjustment,
    summarise_gpx_performance,
)


def print_performance_summary(summary: dict) -> None:
    print(f"Gradient: {summary['gradient_percent']:.2f} %")
    print(f"VAM: {summary['vam_m_per_h']:.1f} m/h")
    print(f"Road speed: {summary['road_speed_m_per_s']:.2f} m/s")
    print(f"Ground speed: {summary['road_speed_km_per_h']:.2f} km/h")
    print(f"Vertical speed: {summary['vertical_speed_m_per_s']:.2f} m/s")
    print(f"Headwind: {summary['headwind_m_s']:.2f} m/s")
    if "crosswind_m_s" in summary:
        print(f"Crosswind: {summary['crosswind_m_s']:.2f} m/s")
    print(f"Gravity power: {summary['power_gravity_w']:.1f} W")
    print(f"Rolling power: {summary['power_rolling_w']:.1f} W")
    print(f"Aero power: {summary['power_aero_w']:.1f} W")
    print(f"Total power: {summary['total_power_w']:.1f} W")
    print(f"W/kg: {summary['watts_per_kg']:.2f}")
    print(f"aSLP (sea-level equivalent): {summary['sea_level_equivalent_power_w']:.1f} W")
    print(f"aSLP W/kg: {summary['aslp_w_per_kg']:.2f}")
    print(f"Altitude loss estimate: {summary['altitude_power_loss_percent']:.1f} %")
    if "segment_adjustments" in summary:
        print("Segments:")
        for name, values in summary["segment_adjustments"].items():
            print(
                f"  {name}: {values['distance_m']:.0f} m, "
                f"{values['time_s']:.1f} s, "
                f"aero {values['aero_power_w']:.1f} W"
            )
    if "weather_sample_time" in summary:
        print(f"Weather sample: {summary['weather_sample_time']}")
        print(f"Temperature: {summary['weather_temperature_c']:.1f} C")
        print(
            f"Wind: {summary['weather_wind_speed_m_s']:.2f} m/s from "
            f"{summary['weather_wind_direction_deg']:.0f} deg"
        )


def main() -> None:
    args = parse_args()
    gpx_path = args.gpx_path
    if not gpx_path.exists():
        raise FileNotFoundError(f"GPX file not found: {gpx_path}")

    rider = Rider(mass_kg=args.rider_mass_kg)
    bike = Bike(
        mass_kg=args.bike_mass_kg,
        drag_coefficient=1.0,
        frontal_area_m2=args.cda_m2,
        rolling_resistance_coefficient=args.rolling_resistance_coefficient,
    )

    route = parse_gpx(gpx_path)
    segment_adjustments = [
        RouteSegmentAdjustment(
            name="protected",
            start_distance_m=0.0,
            end_distance_m=route.distance_m,
            aero_multiplier=0.65,
        )
    ]

    try:
        summary = summarise_gpx_performance(
            gpx_path,
            rider,
            bike,
            segment_adjustments=segment_adjustments,
            include_weather=not args.no_weather,
            wind_exposure_factor=args.wind_exposure_factor,
        )
    except WeatherAPIError as exc:
        if args.no_weather:
            raise
        print(f"Weather unavailable, using GPX route without wind: {exc}")
        summary = summarise_gpx_performance(
            gpx_path,
            rider,
            bike,
            segment_adjustments=segment_adjustments,
            include_weather=False,
        )

    print_performance_summary(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate climbing performance from a GPX route."
    )
    parser.add_argument(
        "gpx_path",
        type=Path,
        nargs="?",
        default=Path("data/la_redoute.gpx"),
        help="Path to the GPX file to analyse.",
    )
    parser.add_argument("--rider-mass-kg", type=float, default=DEFAULT_RIDER_MASS_KG)
    parser.add_argument("--bike-mass-kg", type=float, default=DEFAULT_BIKE_MASS_KG)
    parser.add_argument("--cda-m2", type=float, default=DEFAULT_CDA_M2)
    parser.add_argument(
        "--rolling-resistance-coefficient",
        type=float,
        default=DEFAULT_ROLLING_RESISTANCE_COEFFICIENT,
    )
    parser.add_argument(
        "--wind-exposure-factor",
        type=float,
        default=DEFAULT_WIND_EXPOSURE_FACTOR,
    )
    parser.add_argument(
        "--no-weather",
        action="store_true",
        help="Skip weather lookup and use still-air conditions.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
