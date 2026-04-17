from climbing_performance.models import Rider, Bike, Climb
from climbing_performance.metrics import summarise_full_performance


def print_performance_summary(summary: dict) -> None:
    print(f"Gradient: {summary['gradient_percent']:.2f} %")
    print(f"VAM: {summary['vam_m_per_h']:.1f} m/h")
    print(f"Road speed: {summary['road_speed_m_per_s']:.2f} m/s")
    print(f"Vertical speed: {summary['vertical_speed_m_per_s']:.2f} m/s")
    print(f"Gravity power: {summary['power_gravity_w']:.1f} W")
    print(f"Rolling power: {summary['power_rolling_w']:.1f} W")
    print(f"Aero power: {summary['power_aero_w']:.1f} W")
    print(f"Total power: {summary['total_power_w']:.1f} W")
    print(f"W/kg: {summary['watts_per_kg']:.2f}")
    print(f"aSLP (sea-level equivalent): {summary['sea_level_equivalent_power_w']:.1f} W")
    print(f"aSLP W/kg: {summary['aslp_w_per_kg']:.2f}")
    print(f"Altitude loss estimate: {summary['altitude_power_loss_percent']:.1f} %")


def main() -> None:
    rider = Rider(mass_kg=70.0)

    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
        rolling_resistance_coefficient=0.004,
    )

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