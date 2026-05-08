from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from climbing_performance.route_hydration import hydrate_route_payload
from climbing_performance.weather import WeatherSample, select_weather_source


LA_REDOUTE_GPX = Path(__file__).parents[1] / "data" / "la_redoute.gpx"
REPO_ROOT = Path(__file__).parents[1]


def fake_weather_fetcher(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    source: str,
) -> list[WeatherSample]:
    assert 50.0 < latitude < 51.0
    assert 5.0 < longitude < 6.0
    assert start_date == "2026-04-26"
    assert end_date == "2026-04-26"
    assert source == select_weather_source(start_date, end_date, "auto")
    return [
        WeatherSample(
            time=datetime(2026, 4, 26, 15, 0, tzinfo=timezone.utc),
            temperature_c=12.0,
            relative_humidity_pct=70.0,
            wind_speed_m_s=4.5,
            wind_direction_deg=210.0,
            wind_gusts_m_s=6.0,
        )
    ]


def test_select_weather_source_uses_archive_for_past_dates():
    assert select_weather_source("2000-01-01", "2000-01-01") == "archive"


def test_select_weather_source_uses_forecast_for_future_dates():
    assert select_weather_source("2999-01-01", "2999-01-01") == "forecast"


def test_bundled_la_redoute_uses_static_weather_without_fetching():
    def forbidden_fetcher(**kwargs):
        raise AssertionError("Bundled route should not call Open-Meteo")

    payload = hydrate_route_payload(
        {"route_id": "la-redoute"},
        REPO_ROOT,
        fetcher=forbidden_fetcher,
    )

    assert payload["route"]["distance_m"] > 1000
    assert payload["weather"]["status"] == "static"
    assert payload["weather"]["samples"][0]["temperature_c"] == pytest.approx(15.4)


def test_uploaded_timestamped_gpx_returns_weather_samples(tmp_path):
    repo_root = tmp_path
    (repo_root / "data" / "cache").mkdir(parents=True)
    payload = hydrate_route_payload(
        {"gpx_text": LA_REDOUTE_GPX.read_text(encoding="utf-8")},
        repo_root,
        fetcher=fake_weather_fetcher,
    )

    assert payload["route"]["segments"]
    assert payload["weather"]["status"] == "available"
    assert payload["weather"]["samples"][0]["wind_speed_m_s"] == pytest.approx(4.5)


def test_uploaded_untimestamped_gpx_returns_route_without_fetching(tmp_path):
    def forbidden_fetcher(**kwargs):
        raise AssertionError("Untimestamped routes should not fetch weather")

    gpx_text = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="50.0" lon="5.0"><ele>100</ele></trkpt>
    <trkpt lat="50.001" lon="5.001"><ele>110</ele></trkpt>
  </trkseg></trk>
</gpx>
"""

    payload = hydrate_route_payload(
        {"gpx_text": gpx_text},
        tmp_path,
        fetcher=forbidden_fetcher,
    )

    assert payload["route"]["distance_m"] > 0
    assert payload["route"]["duration_s"] is None
    assert payload["weather"]["status"] == "unavailable"
    assert payload["weather"]["samples"] == []
    assert "timestamps" in payload["weather"]["warning"]
