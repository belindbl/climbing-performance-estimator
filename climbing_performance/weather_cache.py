from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from climbing_performance.weather import WeatherSample, fetch_hourly_weather


DEFAULT_CACHE_PATH = Path("data/cache/weather.sqlite")
WeatherFetcher = Callable[..., list[WeatherSample]]


class SQLiteWeatherCache:
    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def get_or_fetch(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        *,
        source: str = "auto",
        fetcher: WeatherFetcher = fetch_hourly_weather,
    ) -> list[WeatherSample]:
        key = self._cache_key(latitude, longitude, start_date, end_date, source)
        cached = self._get(key)
        if cached is not None:
            return cached

        samples = fetcher(
            latitude,
            longitude,
            start_date,
            end_date,
            source=source,
        )
        self._put(key, samples)
        return samples

    def _initialise(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS weather_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _get(self, key: str) -> list[WeatherSample] | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM weather_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        payload = json.loads(row[0])
        return [_sample_from_payload(item) for item in payload]

    def _put(self, key: str, samples: list[WeatherSample]) -> None:
        payload = json.dumps([_sample_to_payload(sample) for sample in samples])
        created_at = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO weather_cache (cache_key, payload, created_at)
                VALUES (?, ?, ?)
                """,
                (key, payload, created_at),
            )

    @staticmethod
    def _cache_key(
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        source: str,
    ) -> str:
        return "|".join(
            [
                f"{latitude:.5f}",
                f"{longitude:.5f}",
                start_date,
                end_date,
                source,
            ]
        )


def cached_fetch_hourly_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    *,
    source: str = "auto",
    cache_path: str | Path = DEFAULT_CACHE_PATH,
) -> list[WeatherSample]:
    cache = SQLiteWeatherCache(cache_path)
    return cache.get_or_fetch(
        latitude,
        longitude,
        start_date,
        end_date,
        source=source,
    )


def _sample_to_payload(sample: WeatherSample) -> dict[str, Any]:
    payload = asdict(sample)
    payload["time"] = sample.time.isoformat()
    return payload


def _sample_from_payload(payload: dict[str, Any]) -> WeatherSample:
    return WeatherSample(
        time=datetime.fromisoformat(payload["time"]),
        temperature_c=float(payload["temperature_c"]),
        relative_humidity_pct=float(payload["relative_humidity_pct"]),
        wind_speed_m_s=float(payload["wind_speed_m_s"]),
        wind_direction_deg=float(payload["wind_direction_deg"]),
        wind_gusts_m_s=(
            float(payload["wind_gusts_m_s"])
            if payload.get("wind_gusts_m_s") is not None
            else None
        ),
    )
