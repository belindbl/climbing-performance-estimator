import pytest

from climbing_performance.models import Rider, Bike, Climb
from climbing_performance.metrics import (
    compute_gradient,
    compute_vam,
    compute_road_speed,
    compute_vertical_speed,
    air_density_at_altitude,
    estimate_power_components,
    estimate_watts_per_kg,
    summarise_climb_performance,
    summarise_full_performance,
)


def test_compute_gradient():
    result = compute_gradient(elevation_gain_m=700.0, distance_m=10000.0)
    assert result == pytest.approx(7.0)


def test_compute_vam():
    result = compute_vam(elevation_gain_m=600.0, time_s=1800.0)
    assert result == pytest.approx(1200.0)


def test_compute_road_speed():
    result = compute_road_speed(distance_m=10000.0, time_s=2000.0)
    assert result == pytest.approx(5.0)


def test_compute_vertical_speed():
    result = compute_vertical_speed(elevation_gain_m=500.0, time_s=2000.0)
    assert result == pytest.approx(0.25)


def test_air_density_decreases_with_altitude():
    sea_level = air_density_at_altitude(0.0)
    high_altitude = air_density_at_altitude(2000.0)

    assert high_altitude < sea_level
    assert sea_level == pytest.approx(1.225, rel=1e-3)


def test_estimate_watts_per_kg():
    rider = Rider(mass_kg=70.0)
    result = estimate_watts_per_kg(350.0, rider)
    assert result == pytest.approx(5.0)


def test_estimate_power_components_returns_expected_keys():
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
        avg_altitude_m=1000.0,
    )

    result = estimate_power_components(rider, bike, climb)

    assert "power_gravity_w" in result
    assert "power_rolling_w" in result
    assert "power_aero_w" in result
    assert "total_power_w" in result

    assert result["power_gravity_w"] > 0
    assert result["power_rolling_w"] > 0
    assert result["power_aero_w"] > 0
    assert result["total_power_w"] == pytest.approx(
        result["power_gravity_w"] +
        result["power_rolling_w"] +
        result["power_aero_w"]
    )


def test_summarise_climb_performance_contains_all_metrics():
    rider = Rider(mass_kg=70.0)
    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
    )
    climb = Climb(
        distance_m=12000.0,
        elevation_gain_m=840.0,
        time_s=3000.0,
        avg_altitude_m=500.0,
    )

    result = summarise_climb_performance(rider, bike, climb)

    expected_keys = {
        "gradient_percent",
        "vam_m_per_h",
        "road_speed_m_per_s",
        "vertical_speed_m_per_s",
        "power_gravity_w",
        "power_rolling_w",
        "power_aero_w",
        "total_power_w",
        "watts_per_kg",
    }

    assert expected_keys.issubset(result.keys())
    assert result["gradient_percent"] == pytest.approx(7.0)
    assert result["vam_m_per_h"] == pytest.approx(1008.0)


def test_zero_distance_raises_error():
    with pytest.raises(ValueError):
        compute_gradient(elevation_gain_m=500.0, distance_m=0.0)


def test_zero_time_raises_error():
    with pytest.raises(ValueError):
        compute_vam(elevation_gain_m=500.0, time_s=0.0)


def test_negative_elevation_raises_error():
    with pytest.raises(ValueError):
        compute_vam(elevation_gain_m=-10.0, time_s=1000.0)


def test_zero_rider_mass_raises_error_for_wkg():
    rider = Rider(mass_kg=0.0)
    with pytest.raises(ValueError):
        estimate_watts_per_kg(300.0, rider)


def test_total_power_increases_with_faster_ascent():
    rider = Rider(mass_kg=70.0)
    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
    )

    slower_climb = Climb(
        distance_m=10000.0,
        elevation_gain_m=700.0,
        time_s=3000.0,
        avg_altitude_m=0.0,
    )
    faster_climb = Climb(
        distance_m=10000.0,
        elevation_gain_m=700.0,
        time_s=2400.0,
        avg_altitude_m=0.0,
    )

    slower_power = estimate_power_components(rider, bike, slower_climb)["total_power_w"]
    faster_power = estimate_power_components(rider, bike, faster_climb)["total_power_w"]

    assert faster_power > slower_power
    
    
def test_gravity_power_matches_hand_calculation():
    rider = Rider(mass_kg=70.0)
    
    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
        rolling_resistance_coefficient=0.004,
    )
    climb = Climb(
        distance_m=10000.0,
        elevation_gain_m=600.0,
        time_s=1800.0,
        avg_altitude_m=0.0,
    )

    result = estimate_power_components(rider, bike, climb)

    expected_gravity = (70.0 + 8.0) * 9.81 * (600.0 / 1800.0)
    assert result["power_gravity_w"] == pytest.approx(expected_gravity)

def test_summarise_full_performance_contains_aslp_metrics():
    rider = Rider(mass_kg=70.0)
    bike = Bike(
        mass_kg=8.0,
        drag_coefficient=0.88,
        frontal_area_m2=0.5,
    )
    climb = Climb(
        distance_m=10000.0,
        elevation_gain_m=700.0,
        time_s=2400.0,
        avg_altitude_m=1200.0,
    )

    result = summarise_full_performance(rider, bike, climb)

    expected_keys = {
        "gradient_percent",
        "vam_m_per_h",
        "road_speed_m_per_s",
        "vertical_speed_m_per_s",
        "power_gravity_w",
        "power_rolling_w",
        "power_aero_w",
        "total_power_w",
        "watts_per_kg",
        "observed_power_w",
        "avg_altitude_m",
        "cp_remaining_fraction",
        "altitude_power_loss_percent",
        "sea_level_equivalent_power_w",
        "aslp_w_per_kg",
    }

    assert expected_keys.issubset(result.keys())