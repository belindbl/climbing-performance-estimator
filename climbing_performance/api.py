from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from climbing_performance.gpx import GPXRoute, parse_gpx
from climbing_performance.models import Bike, Rider
from climbing_performance.weather import WeatherAPIError
from climbing_performance.workflow import (
    RouteSegmentAdjustment,
    summarise_gpx_performance,
)


PROTECTION_TYPES = {
    "protected": 0.65,
    "low": 0.82,
    "solo": 1.0,
}
DEFAULT_RIDER_MASS_KG = 60.0
DEFAULT_BIKE_MASS_KG = 8.0
DEFAULT_CDA_M2 = 0.37
DEFAULT_ROLLING_RESISTANCE_COEFFICIENT = 0.004
DEFAULT_INCLUDE_WEATHER = True
DEFAULT_WIND_EXPOSURE_FACTOR = 1.0


class RoutePayload(BaseModel):
    gpx_text: str | None = None


class PerformanceRequest(BaseModel):
    gpx_text: str | None = None
    rider: dict[str, Any] = Field(default_factory=dict)
    bike: dict[str, Any] = Field(default_factory=dict)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    include_weather: bool = DEFAULT_INCLUDE_WEATHER
    wind_exposure_factor: float = DEFAULT_WIND_EXPOSURE_FACTOR


def create_app(repo_root: Path | None = None) -> FastAPI:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    repo_root = repo_root.resolve()
    app = FastAPI(title="Climbing Performance API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/routes/la-redoute")
    def get_la_redoute_route() -> dict[str, Any]:
        return jsonable_encoder(route_payload(data_path(repo_root)))

    @app.post("/api/routes/parse")
    def post_route(payload: RoutePayload) -> dict[str, Any]:
        try:
            with gpx_path_from_text(payload.gpx_text, data_path(repo_root)) as gpx_path:
                return jsonable_encoder(route_payload(gpx_path))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/performance")
    def post_performance(payload: PerformanceRequest) -> dict[str, Any]:
        try:
            with gpx_path_from_text(payload.gpx_text, data_path(repo_root)) as gpx_path:
                result = performance_payload(payload.model_dump(), gpx_path)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WeatherAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return jsonable_encoder(result)

    app.mount("/", StaticFiles(directory=repo_root, html=True), name="static")
    return app


app = create_app()


def data_path(repo_root: Path) -> Path:
    return repo_root / "data" / "la_redoute.gpx"


class gpx_path_from_text:
    def __init__(self, gpx_text: str | None, fallback_path: Path) -> None:
        self.gpx_text = gpx_text
        self.fallback_path = fallback_path
        self._temp_file: tempfile.NamedTemporaryFile | None = None

    def __enter__(self) -> Path:
        if self.gpx_text is None:
            return self.fallback_path

        if not self.gpx_text.strip():
            raise ValueError("gpx_text must not be empty.")

        self._temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".gpx",
            encoding="utf-8",
            delete=False,
        )
        self._temp_file.write(self.gpx_text)
        self._temp_file.close()
        return Path(self._temp_file.name)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._temp_file is not None:
            Path(self._temp_file.name).unlink(missing_ok=True)


def route_payload(gpx_path: Path) -> dict[str, Any]:
    route = parse_gpx(gpx_path)
    return {
        "id": "la-redoute",
        "name": route_display_name(route, gpx_path),
        "distance_m": route.distance_m,
        "ascent_m": route.ascent_m,
        "descent_m": route.descent_m,
        "duration_s": route_duration_s(route),
        "avg_altitude_m": route_avg_altitude_m(route),
        "min_elevation_m": route.min_elevation_m,
        "max_elevation_m": route.max_elevation_m,
        "start_time": route.start_time,
        "end_time": route.end_time,
        "points": route_profile_points(route),
        "protection_types": [
            {
                "id": key,
                "label": label_for_protection_type(key),
                "aero_multiplier": value,
            }
            for key, value in PROTECTION_TYPES.items()
        ],
    }


def route_display_name(route: GPXRoute, gpx_path: Path) -> str:
    if gpx_path.name == "la_redoute.gpx":
        return "La Redoute"

    if route.name:
        return route.name

    return gpx_path.stem.replace("_", " ").replace("-", " ").strip() or "GPX Route"


def performance_payload(payload: dict[str, Any], gpx_path: Path) -> dict[str, Any]:
    rider_payload = payload.get("rider", {})
    bike_payload = payload.get("bike", {})
    cda_m2 = float(
        bike_payload.get(
            "cda_m2",
            float(bike_payload.get("drag_coefficient", 1.0))
            * float(bike_payload.get("frontal_area_m2", DEFAULT_CDA_M2)),
        )
    )
    rider = Rider(mass_kg=float(rider_payload.get("mass_kg", DEFAULT_RIDER_MASS_KG)))
    bike = Bike(
        mass_kg=float(bike_payload.get("mass_kg", DEFAULT_BIKE_MASS_KG)),
        drag_coefficient=1.0,
        frontal_area_m2=cda_m2,
        rolling_resistance_coefficient=float(
            bike_payload.get(
                "rolling_resistance_coefficient",
                DEFAULT_ROLLING_RESISTANCE_COEFFICIENT,
            )
        ),
    )
    route = parse_gpx(gpx_path)
    adjustments = segment_adjustments_from_payload(
        payload.get("segments", []),
        route.distance_m,
    )

    summary = summarise_gpx_performance(
        gpx_path,
        rider,
        bike,
        include_weather=bool(payload.get("include_weather", DEFAULT_INCLUDE_WEATHER)),
        wind_exposure_factor=float(
            payload.get("wind_exposure_factor", DEFAULT_WIND_EXPOSURE_FACTOR)
        ),
        segment_adjustments=adjustments,
    )

    return {
        "route": route_payload(gpx_path),
        "summary": summary,
        "segments": segment_breakdown(route, adjustments, summary),
        "protection_types": [
            {
                "id": key,
                "label": label_for_protection_type(key),
                "aero_multiplier": value,
            }
            for key, value in PROTECTION_TYPES.items()
        ],
    }


def segment_adjustments_from_payload(
    segments: list[dict[str, Any]],
    route_distance_m: float,
) -> list[RouteSegmentAdjustment]:
    if not segments:
        segments = [
            {
                "name": "protected",
                "type": "protected",
                "start_distance_m": 0.0,
                "end_distance_m": route_distance_m,
            }
        ]

    adjustments = []
    for index, segment in enumerate(segments):
        segment_type = str(segment.get("type", "solo"))
        if segment_type not in PROTECTION_TYPES:
            raise ValueError(f"Unknown segment type: {segment_type}")

        adjustments.append(
            RouteSegmentAdjustment(
                name=str(segment.get("name", f"segment-{index + 1}")),
                start_distance_m=float(segment["start_distance_m"]),
                end_distance_m=float(segment["end_distance_m"]),
                aero_multiplier=PROTECTION_TYPES[segment_type],
                rolling_resistance_coefficient=(
                    float(segment["rolling_resistance_coefficient"])
                    if segment.get("rolling_resistance_coefficient") is not None
                    else None
                ),
            )
        )

    return adjustments


def segment_breakdown(
    route: GPXRoute,
    adjustments: list[RouteSegmentAdjustment],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    summary_segments = summary.get("segment_adjustments", {})
    breakdown = []
    for adjustment in adjustments:
        values = summary_segments.get(adjustment.name, {})
        distance_m = adjustment.end_distance_m - adjustment.start_distance_m
        time_s = float(values.get("time_s", 0.0))
        ascent_m = ascent_between(route, adjustment.start_distance_m, adjustment.end_distance_m)
        total_power_w = (
            float(values.get("aero_work_j", 0.0)) / time_s
            if time_s > 0
            else 0.0
        )
        breakdown.append(
            {
                "name": adjustment.name,
                "start_distance_m": adjustment.start_distance_m,
                "end_distance_m": adjustment.end_distance_m,
                "distance_m": distance_m,
                "ascent_m": ascent_m,
                "time_s": time_s,
                "avg_gradient_percent": (
                    100.0 * ascent_m / distance_m if distance_m > 0 else 0.0
                ),
                "vam_m_per_h": ascent_m / (time_s / 3600.0) if time_s > 0 else 0.0,
                "aero_power_w": float(values.get("aero_power_w", 0.0)),
                "aero_work_j": float(values.get("aero_work_j", 0.0)),
                "aero_only_power_w": total_power_w,
            }
        )

    return breakdown


def route_profile_points(route: GPXRoute) -> list[dict[str, Any]]:
    if not route.points:
        return []

    return [
        {
            "distance_m": point.distance_m,
            "latitude": point.latitude,
            "longitude": point.longitude,
            "elevation_m": point.elevation_m,
            "time": point.time,
        }
        for point in route.points
    ]


def route_duration_s(route: GPXRoute) -> float | None:
    if route.start_time is None or route.end_time is None:
        return None
    return (route.end_time - route.start_time).total_seconds()


def route_avg_altitude_m(route: GPXRoute) -> float | None:
    elevations = [point.elevation_m for point in route.points if point.elevation_m is not None]
    if not elevations:
        return None
    return sum(elevations) / len(elevations)


def ascent_between(route: GPXRoute, start_distance_m: float, end_distance_m: float) -> float:
    ascent_m = 0.0
    cumulative = 0.0
    for segment in route.segments:
        segment_start = cumulative
        segment_end = cumulative + segment.distance_m
        cumulative = segment_end

        overlap_start = max(start_distance_m, segment_start)
        overlap_end = min(end_distance_m, segment_end)
        if overlap_end <= overlap_start:
            continue

        fraction = (overlap_end - overlap_start) / segment.distance_m
        ascent_m += max(0.0, segment.elevation_delta_m or 0.0) * fraction

    return ascent_m


def label_for_protection_type(protection_type: str) -> str:
    return {
        "protected": "Protected",
        "low": "Low protection",
        "solo": "Solo",
    }[protection_type]
