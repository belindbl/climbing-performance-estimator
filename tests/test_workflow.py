from datetime import datetime, timezone
from pathlib import Path

import pytest

from climbing_performance.models import Bike, Rider
from climbing_performance.weather import WeatherSample
from climbing_performance.workflow import (
    RouteSegmentAdjustment,
    route_to_performance_climb,
    summarise_gpx_performance,
)
from climbing_performance.gpx import parse_gpx


LA_REDOUTE_GPX = Path(__file__).parents[1] / "data" / "la_redoute.gpx"


def fake_weather_fetcher(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> list[WeatherSample]:
    assert 50.0 < latitude < 51.0
    assert 5.0 < longitude < 6.0
    assert start_date == "2026-04-26"
    assert end_date == "2026-04-26"

    return [
        WeatherSample(
            time=datetime(2026, 4, 26, 15, 0, tzinfo=timezone.utc),
            temperature_c=15.4,
            relative_humidity_pct=51.0,
            wind_speed_m_s=3.28,
            wind_direction_deg=21.0,
            wind_gusts_m_s=7.6,
        )
    ]


def test_route_to_performance_climb_from_la_redoute_gpx():
    route = parse_gpx(LA_REDOUTE_GPX)

    climb = route_to_performance_climb(route)

    assert climb.distance_m > 1000.0
    assert climb.elevation_gain_m > 100.0
    assert climb.time_s == pytest.approx(226.0)
    assert 100.0 < climb.avg_altitude_m < 300.0


def test_summarise_gpx_performance_integrates_weather_and_route():
    rider = Rider(mass_kg=70.0)
    bike = Bike.default()

    summary = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        weather_fetcher=fake_weather_fetcher,
    )

    assert summary["route_point_count"] > 100
    assert summary["route_distance_m"] == pytest.approx(
        summary["climb_distance_m"],
        rel=1e-9,
    )
    assert summary["weather_temperature_c"] == pytest.approx(15.4)
    assert "headwind_m_s" in summary
    assert "raw_headwind_m_s" in summary
    assert summary["headwind_m_s"] == pytest.approx(summary["raw_headwind_m_s"])
    assert summary["wind_exposure_factor"] == pytest.approx(1.0)
    assert "crosswind_m_s" in summary
    assert summary["total_power_w"] > 0.0
    assert summary["sea_level_equivalent_power_w"] >= summary["total_power_w"]


def test_summarise_gpx_performance_can_apply_explicit_wind_exposure():
    rider = Rider(mass_kg=70.0)
    bike = Bike.default()

    summary = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        wind_exposure_factor=1.0,
        weather_fetcher=fake_weather_fetcher,
    )

    assert summary["headwind_m_s"] == pytest.approx(summary["raw_headwind_m_s"])
    assert summary["wind_exposure_factor"] == pytest.approx(1.0)


def test_summarise_gpx_performance_can_override_weather_direction():
    rider = Rider(mass_kg=70.0)
    bike = Bike.default()

    baseline = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        weather_fetcher=fake_weather_fetcher,
    )
    overridden = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        weather_wind_direction_deg=(
            baseline["weather_wind_direction_deg"] + 180.0
        ) % 360.0,
        weather_fetcher=fake_weather_fetcher,
    )

    assert overridden["weather_wind_direction_deg"] == pytest.approx(
        (baseline["weather_wind_direction_deg"] + 180.0) % 360.0
    )
    assert overridden["headwind_m_s"] != pytest.approx(baseline["headwind_m_s"])
    assert overridden["power_aero_w"] != pytest.approx(baseline["power_aero_w"])
    assert overridden["total_power_w"] != pytest.approx(baseline["total_power_w"])


def test_summarise_gpx_performance_can_run_without_weather():
    rider = Rider.default()
    bike = Bike.default()

    summary = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        include_weather=False,
    )

    assert summary["headwind_m_s"] == pytest.approx(0.0)
    assert "weather_sample_time" not in summary


def test_summarise_gpx_performance_supports_drafting_breakpoint():
    rider = Rider(mass_kg=66.0)
    bike = Bike.default()
    route = parse_gpx(LA_REDOUTE_GPX)
    solo_remaining_m = 865.0
    adjustments = [
        RouteSegmentAdjustment(
            name="protected",
            start_distance_m=0.0,
            end_distance_m=route.distance_m - solo_remaining_m,
            aero_multiplier=0.65,
        ),
        RouteSegmentAdjustment.from_remaining_distance(
            "solo",
            route.distance_m,
            start_remaining_m=solo_remaining_m,
            end_remaining_m=0.0,
            aero_multiplier=1.0,
        ),
    ]

    unadjusted = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        include_weather=False,
    )
    adjusted = summarise_gpx_performance(
        LA_REDOUTE_GPX,
        rider,
        bike,
        include_weather=False,
        segment_adjustments=adjustments,
    )

    assert adjusted["total_power_w"] < unadjusted["total_power_w"]
    assert adjusted["segment_adjustments"]["protected"]["distance_m"] == pytest.approx(
        route.distance_m - solo_remaining_m,
    )
    assert adjusted["segment_adjustments"]["solo"]["distance_m"] == pytest.approx(
        solo_remaining_m,
    )
