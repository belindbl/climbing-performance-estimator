from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import tempfile
from typing import Any

from climbing_performance.gpx import GPXRoute, parse_gpx
from climbing_performance.weather import (
    WeatherAPIError,
    WeatherSample,
    fetch_hourly_weather,
    select_weather_source,
)


WeatherFetcher = Callable[..., list[WeatherSample]]


def hydrate_route_payload(
    payload: dict[str, Any],
    repo_root: Path,
    *,
    fetcher: WeatherFetcher = fetch_hourly_weather,
) -> dict[str, Any]:
    route_id = payload.get("route_id")

    if route_id == "la-redoute" and not payload.get("gpx_text"):
        gpx_path = repo_root / "data" / "la_redoute.gpx"
        route = parse_gpx(gpx_path)
        return hydrated_payload(
            route,
            weather_payload=static_la_redoute_weather(repo_root),
            fallback_name="La Redoute",
        )

    gpx_text = str(payload.get("gpx_text") or "")
    if not gpx_text.strip():
        raise ValueError("gpx_text is required unless route_id is 'la-redoute'.")

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".gpx",
        encoding="utf-8",
        delete=False,
    ) as temp_file:
        temp_file.write(gpx_text)
        temp_path = Path(temp_file.name)

    try:
        route = parse_gpx(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    weather_payload = weather_for_uploaded_route(route, repo_root, fetcher=fetcher)
    return hydrated_payload(
        route,
        weather_payload=weather_payload,
        fallback_name=payload.get("file_name"),
    )


def weather_for_uploaded_route(
    route: GPXRoute,
    repo_root: Path,
    *,
    fetcher: WeatherFetcher = fetch_hourly_weather,
) -> dict[str, Any]:
    if route.start_time is None or route.end_time is None:
        return {
            "status": "unavailable",
            "source": None,
            "samples": [],
            "warning": "Weather requires GPX timestamps.",
        }

    window = route.weather_query_window(location="midpoint")
    selected_source = select_weather_source(window.start_date, window.end_date, "auto")
    cache_key = weather_cache_key(
        window.latitude,
        window.longitude,
        window.start_date,
        window.end_date,
        selected_source,
    )
    cache_path = repo_root / "data" / "cache" / "weather_payloads.json"
    cached = read_weather_cache(cache_path).get(cache_key)
    if cached is not None:
        return cached

    try:
        samples = fetcher(
            latitude=window.latitude,
            longitude=window.longitude,
            start_date=window.start_date,
            end_date=window.end_date,
            source=selected_source,
        )
    except WeatherAPIError as exc:
        return {
            "status": "unavailable",
            "source": selected_source,
            "samples": [],
            "latitude": window.latitude,
            "longitude": window.longitude,
            "start_date": window.start_date,
            "end_date": window.end_date,
            "warning": str(exc),
        }

    payload = {
        "status": "available",
        "source": selected_source,
        "samples": [weather_sample_payload(sample) for sample in samples],
        "latitude": window.latitude,
        "longitude": window.longitude,
        "start_date": window.start_date,
        "end_date": window.end_date,
        "warning": None,
    }
    cache = read_weather_cache(cache_path)
    cache[cache_key] = payload
    write_weather_cache(cache_path, cache)
    return payload


def hydrated_payload(
    route: GPXRoute,
    *,
    weather_payload: dict[str, Any],
    fallback_name: str | None = None,
) -> dict[str, Any]:
    return {
        "route": route_payload(route, fallback_name=fallback_name),
        "weather": weather_payload,
    }


def route_payload(route: GPXRoute, *, fallback_name: str | None = None) -> dict[str, Any]:
    cumulative = 0.0
    segments = []
    for segment in route.segments:
        start_distance = cumulative
        end_distance = cumulative + segment.distance_m
        cumulative = end_distance
        segments.append(
            {
                "start_distance_m": start_distance,
                "end_distance_m": end_distance,
                "distance_m": segment.distance_m,
                "elevation_delta_m": segment.elevation_delta_m,
                "elapsed_s": segment.elapsed_s,
                "bearing_deg": segment.bearing_deg,
                "start_time": (
                    segment.start.time.isoformat()
                    if segment.start.time is not None
                    else None
                ),
                "end_time": (
                    segment.end.time.isoformat()
                    if segment.end.time is not None
                    else None
                ),
                "start_elevation_m": segment.start.elevation_m,
                "end_elevation_m": segment.end.elevation_m,
            }
        )

    elevations = [point.elevation_m for point in route.points if point.elevation_m is not None]
    avg_altitude = sum(elevations) / len(elevations) if elevations else None

    return {
        "name": clean_route_name(fallback_name) or route.name or "GPX Route",
        "points": [
            {
                "latitude": point.latitude,
                "longitude": point.longitude,
                "elevation_m": point.elevation_m,
                "time": point.time.isoformat() if point.time is not None else None,
                "distance_m": point.distance_m,
            }
            for point in route.points
        ],
        "segments": segments,
        "distance_m": route.distance_m,
        "ascent_m": route.ascent_m,
        "descent_m": route.descent_m,
        "duration_s": (
            (route.end_time - route.start_time).total_seconds()
            if route.start_time is not None and route.end_time is not None
            else None
        ),
        "avg_altitude_m": avg_altitude,
        "min_elevation_m": route.min_elevation_m,
        "max_elevation_m": route.max_elevation_m,
        "start_time": route.start_time.isoformat() if route.start_time else None,
        "end_time": route.end_time.isoformat() if route.end_time else None,
    }


def clean_route_name(value: str | None) -> str | None:
    if value is None:
        return None

    name = Path(str(value)).stem.replace("_", " ").replace("-", " ").strip()
    return name or None


def static_la_redoute_weather(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "data" / "la_redoute_weather.json"
    return json.loads(path.read_text(encoding="utf-8"))


def weather_sample_payload(sample: WeatherSample) -> dict[str, Any]:
    payload = asdict(sample)
    payload["time"] = sample.time.isoformat()
    return payload


def weather_sample_from_payload(payload: dict[str, Any]) -> WeatherSample:
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


def weather_cache_key(
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


def read_weather_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_weather_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
