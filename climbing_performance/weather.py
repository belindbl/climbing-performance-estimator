from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import requests


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherAPIError(RuntimeError):
    """Raised when weather data could not be retrieved or parsed."""


@dataclass(frozen=True)
class WindSample:
    time: datetime
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


def _parse_iso_datetime(value: str) -> datetime:
    # Open-Meteo returns ISO-like timestamps such as "2026-04-18T14:00"
    return datetime.fromisoformat(value)


def fetch_current_wind(
    latitude: float,
    longitude: float,
    *,
    timeout_s: float = 10.0,
) -> WindSample:
    """
    Fetch current wind conditions at a coordinate.

    Returns:
        WindSample with speed in m/s and direction in degrees.
    """
    _validate_lat_lon(latitude, longitude)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "ms",
        "timezone": "auto",
    }

    try:
        response = requests.get(
            OPEN_METEO_FORECAST_URL,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        raise WeatherAPIError(f"Weather API request failed: {exc}") from exc

    current = payload.get("current")
    if not current:
        raise WeatherAPIError("Weather API response missing 'current' field.")

    try:
        return WindSample(
            time=_parse_iso_datetime(current["time"]),
            wind_speed_m_s=float(current["wind_speed_10m"]),
            wind_direction_deg=float(current["wind_direction_10m"]),
            wind_gusts_m_s=(
                float(current["wind_gusts_10m"])
                if current.get("wind_gusts_10m") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherAPIError(f"Invalid current wind payload: {exc}") from exc


def fetch_hourly_wind(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    *,
    timeout_s: float = 10.0,
) -> list[WindSample]:
    """
    Fetch hourly wind forecast/history within a date window.

    Parameters:
        latitude, longitude:
            Geographic coordinates.
        start_date, end_date:
            ISO dates in YYYY-MM-DD format.

    Returns:
        List of hourly WindSample objects.
    """
    _validate_lat_lon(latitude, longitude)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "ms",
        "timezone": "auto",
        "start_date": start_date,
        "end_date": end_date,
    }

    try:
        response = requests.get(
            OPEN_METEO_FORECAST_URL,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        raise WeatherAPIError(f"Weather API request failed: {exc}") from exc

    hourly = payload.get("hourly")
    if not hourly:
        raise WeatherAPIError("Weather API response missing 'hourly' field.")

    try:
        times = hourly["time"]
        speeds = hourly["wind_speed_10m"]
        directions = hourly["wind_direction_10m"]
        gusts = hourly.get("wind_gusts_10m")
    except KeyError as exc:
        raise WeatherAPIError(f"Hourly payload missing field: {exc}") from exc

    if not (len(times) == len(speeds) == len(directions)):
        raise WeatherAPIError("Hourly weather arrays have inconsistent lengths.")

    samples: list[WindSample] = []
    for i, time_str in enumerate(times):
        gust_value = None
        if gusts is not None and i < len(gusts) and gusts[i] is not None:
            gust_value = float(gusts[i])

        samples.append(
            WindSample(
                time=_parse_iso_datetime(time_str),
                wind_speed_m_s=float(speeds[i]),
                wind_direction_deg=float(directions[i]),
                wind_gusts_m_s=gust_value,
            )
        )

    return samples


def nearest_wind_sample(
    samples: list[WindSample],
    target_time: datetime,
) -> WindSample:
    """
    Return the wind sample closest in time to target_time.
    """
    if not samples:
        raise ValueError("samples must not be empty")

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