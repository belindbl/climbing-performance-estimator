from pathlib import Path

from climbing_performance.models import Rider, Bike, Climb
from climbing_performance.metrics import summarise_full_performance
from climbing_performance.weather import WeatherAPIError
from climbing_performance.gpx import parse_gpx
from climbing_performance.workflow import (
    RouteSegmentAdjustment,
    motorcycle_draft_aero_multiplier,
    summarise_gpx_performance,
)


def print_performance_summary(summary: dict) -> None:
    print(f"Gradient: {summary['gradient_percent']:.2f} %")
    print(f"VAM: {summary['vam_m_per_h']:.1f} m/h")
    print(f"Road speed: {summary['road_speed_m_per_s']:.2f} m/s")
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
        print(f"Wind: {summary['weather_wind_speed_m_s']:.2f} m/s from "
              f"{summary['weather_wind_direction_deg']:.0f} deg")


def main() -> None:
    rider = Rider(mass_kg=66.0)

    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
        rolling_resistance_coefficient=0.004,
    )

    gpx_path = Path("data/la_redoute.gpx")
    if gpx_path.exists():
        route = parse_gpx(gpx_path)
        solo_remaining_m = 865.0
        segment_adjustments = [
            RouteSegmentAdjustment(
                name="moto_7_5m",
                start_distance_m=0.0,
                end_distance_m=route.distance_m - solo_remaining_m,
                aero_multiplier=motorcycle_draft_aero_multiplier(7.5),
            ),
            RouteSegmentAdjustment.from_remaining_distance(
                "solo",
                route.distance_m,
                start_remaining_m=solo_remaining_m,
                end_remaining_m=0.0,
                aero_multiplier=1.0,
            ),
        ]
        try:
            summary = summarise_gpx_performance(
                gpx_path,
                rider,
                bike,
                segment_adjustments=segment_adjustments,
            )
        except WeatherAPIError as exc:
            print(f"Weather unavailable, using GPX route without wind: {exc}")
            summary = summarise_gpx_performance(
                gpx_path,
                rider,
                bike,
                include_weather=False,
                segment_adjustments=segment_adjustments,
            )
    else:
        climb = Climb(
            distance_m=10000.0,
            elevation_gain_m=700.0,
            time_s=2400.0,
            avg_altitude_m=1200.0,
        )
        summary = summarise_full_performance(rider, bike, climb)

    print_performance_summary(summary)


if __name__ == "__main__":
    main()
