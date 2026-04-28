from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from typing import Any
import requests


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


class WeatherAPIError(RuntimeError):
    """Raised when weather data could not be retrieved or parsed."""


@dataclass(frozen=True)
class WeatherSample:
    time: datetime
    temperature_c: float
    relative_humidity_pct: float
    wind_speed_m_s: float
    wind_direction_deg: float
    wind_gusts_m_s: float | None = None


def _kmh_to_ms(value_kmh: float) -> float:
    return value_kmh / 3.6


def _validate_lat_lon(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"Latitude out of range: {latitude}")

    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(f"Longitude out of range: {longitude}")



def _select_weather_url(start_date: str, end_date: str, source: str) -> str:
    if source == "forecast":
        return OPEN_METEO_FORECAST_URL

    if source == "archive":
        return OPEN_METEO_ARCHIVE_URL

    if source != "auto":
        raise ValueError("source must be 'auto', 'forecast', or 'archive'.")

    end = date.fromisoformat(end_date)
    today = date.today()

    if end < today:
        return OPEN_METEO_ARCHIVE_URL

    return OPEN_METEO_FORECAST_URL

def _parse_open_meteo_time(value: str, utc_offset_seconds: int) -> datetime:
    tz = timezone(timedelta(seconds=utc_offset_seconds))
    return datetime.fromisoformat(value).replace(tzinfo=tz)


def fetch_hourly_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    *,
    source: str = "auto",
    timeout_s: float = 10.0,
) -> list[WeatherSample]:
    """
    Fetch hourly weather for a coordinate and date range.

    source:
        "auto"     -> archive for fully past ranges, forecast otherwise
        "forecast" -> Open-Meteo forecast API
        "archive"  -> Open-Meteo historical archive API
    """
    _validate_lat_lon(latitude, longitude)

    api_url = _select_weather_url(start_date, end_date, source)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "wind_gusts_10m"
        ),
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "timezone": "auto",
        "start_date": start_date,
        "end_date": end_date,
    }

    try:
        response = requests.get(api_url, params=params, timeout=timeout_s)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        raise WeatherAPIError(f"Weather API request failed: {exc}") from exc

    hourly = payload.get("hourly")
    if not hourly:
        raise WeatherAPIError("Weather API response missing 'hourly' field.")

    utc_offset_seconds = int(payload.get("utc_offset_seconds", 0))

    try:
        times = hourly["time"]
        temperatures = hourly["temperature_2m"]
        humidities = hourly["relative_humidity_2m"]
        wind_speeds = hourly["wind_speed_10m"]
        wind_directions = hourly["wind_direction_10m"]
        wind_gusts = hourly.get("wind_gusts_10m")
    except KeyError as exc:
        raise WeatherAPIError(f"Hourly payload missing field: {exc}") from exc

    samples: list[WeatherSample] = []

    for i, time_str in enumerate(times):
        gust_value = None
        if wind_gusts is not None and i < len(wind_gusts):
            if wind_gusts[i] is not None:
                gust_value = float(wind_gusts[i])

        samples.append(
            WeatherSample(
                time=_parse_open_meteo_time(time_str, utc_offset_seconds),
                temperature_c=float(temperatures[i]),
                relative_humidity_pct=float(humidities[i]),
                wind_speed_m_s=float(wind_speeds[i]),
                wind_direction_deg=float(wind_directions[i]),
                wind_gusts_m_s=gust_value,
            )
        )

    return samples


def nearest_weather_sample(
    samples: list[WeatherSample],
    target_time: datetime,
) -> WeatherSample:
    if not samples:
        raise ValueError("samples must not be empty")

    if target_time.tzinfo is None:
        raise ValueError("target_time should be timezone-aware.")

    return min(samples, key=lambda s: abs(s.time - target_time))


def wind_to_components(
    wind_speed_m_s: float,
    wind_direction_deg: float,
    rider_heading_deg: float,
) -> tuple[float, float]:
    """
    Convert meteorological wind direction into rider-relative components.

    Meteorological convention:
        wind_direction_deg is the direction the wind is coming *from*.

    Returns:
        (headwind_m_s, crosswind_m_s)

    Sign convention:
        headwind_m_s > 0  => headwind
        headwind_m_s < 0  => tailwind
        crosswind_m_s magnitude is unsigned here
    """
    import math

    # Convert "from" direction into "to" direction
    wind_to_deg = (wind_direction_deg + 180.0) % 360.0

    rel_deg = (wind_to_deg - rider_heading_deg) % 360.0
    rel_rad = math.radians(rel_deg)

    along = wind_speed_m_s * math.cos(rel_rad)
    across = wind_speed_m_s * math.sin(rel_rad)

    headwind_m_s = -along
    crosswind_m_s = abs(across)

    return headwind_m_s, crosswind_m_s