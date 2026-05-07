from datetime import datetime, timezone

from climbing_performance.weather import WeatherSample
from climbing_performance.weather_cache import SQLiteWeatherCache


def test_sqlite_weather_cache_reuses_cached_samples(tmp_path):
    calls = {"count": 0}

    def fetcher(
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        *,
        source: str,
    ) -> list[WeatherSample]:
        calls["count"] += 1
        return [
            WeatherSample(
                time=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
                temperature_c=15.4,
                relative_humidity_pct=51.0,
                wind_speed_m_s=3.28,
                wind_direction_deg=21.0,
                wind_gusts_m_s=7.6,
            )
        ]

    cache = SQLiteWeatherCache(tmp_path / "weather.sqlite")

    first = cache.get_or_fetch(
        50.488924,
        5.707557,
        "2026-04-26",
        "2026-04-26",
        source="archive",
        fetcher=fetcher,
    )
    second = cache.get_or_fetch(
        50.488924,
        5.707557,
        "2026-04-26",
        "2026-04-26",
        source="archive",
        fetcher=fetcher,
    )

    assert calls["count"] == 1
    assert first == second
    assert second[0].temperature_c == 15.4
