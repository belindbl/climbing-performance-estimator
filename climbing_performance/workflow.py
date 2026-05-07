from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from climbing_performance.gpx import GPXRoute, parse_gpx
from climbing_performance.aslp import summarise_aslp
from climbing_performance.metrics import (
    air_density_at_altitude,
    compute_air_speed,
    compute_gradient,
    compute_road_speed,
    compute_vam,
    compute_vertical_speed,
    estimate_watts_per_kg,
    summarise_full_performance,
)
from climbing_performance.models import Bike, Climb, Rider
from climbing_performance.weather import (
    WeatherSample,
    fetch_hourly_weather,
    nearest_weather_sample,
    wind_to_components,
)


WeatherFetcher = Callable[[float, float, str, str], list[WeatherSample]]


@dataclass(frozen=True)
class RouteWeatherContext:
    sample: WeatherSample
    rider_heading_deg: float
    headwind_m_s: float
    crosswind_m_s: float


@dataclass(frozen=True)
class RouteSegmentAdjustment:
    name: str
    start_distance_m: float
    end_distance_m: float
    aero_multiplier: float = 1.0
    rolling_resistance_coefficient: float | None = None

    @staticmethod
    def from_remaining_distance(
        name: str,
        route_distance_m: float,
        *,
        start_remaining_m: float,
        end_remaining_m: float,
        aero_multiplier: float = 1.0,
        rolling_resistance_coefficient: float | None = None,
    ) -> "RouteSegmentAdjustment":
        start_distance_m = route_distance_m - start_remaining_m
        end_distance_m = route_distance_m - end_remaining_m
        return RouteSegmentAdjustment(
            name=name,
            start_distance_m=start_distance_m,
            end_distance_m=end_distance_m,
            aero_multiplier=aero_multiplier,
            rolling_resistance_coefficient=rolling_resistance_coefficient,
        )


def route_to_performance_climb(route: GPXRoute) -> Climb:
    if route.start_time is None or route.end_time is None:
        raise ValueError(
            "Route has no timestamps. Use assign_estimated_times() first "
            "or provide a GPX file with time data."
        )

    duration_s = (route.end_time - route.start_time).total_seconds()
    if duration_s <= 0:
        raise ValueError("Route duration must be positive.")

    elevations = [p.elevation_m for p in route.points if p.elevation_m is not None]
    if not elevations:
        raise ValueError("Route must contain elevation data.")

    return Climb(
        distance_m=route.distance_m,
        elevation_gain_m=route.ascent_m,
        time_s=duration_s,
        avg_altitude_m=sum(elevations) / len(elevations),
    )


def fetch_route_weather_context(
    route: GPXRoute,
    *,
    source: str = "auto",
    fetcher: WeatherFetcher | None = None,
) -> RouteWeatherContext:
    if route.start_time is None:
        raise ValueError(
            "Route has no timestamps. Use assign_estimated_times() first "
            "or provide a GPX file with time data."
        )

    weather_window = route.weather_query_window(location="midpoint")
    fetch = fetcher or _default_weather_fetcher(source)
    samples = fetch(
        weather_window.latitude,
        weather_window.longitude,
        weather_window.start_date,
        weather_window.end_date,
    )
    sample = nearest_weather_sample(samples, route.start_time)
    heading = route_heading_at_distance_fraction(route, 0.5)
    headwind, crosswind = wind_to_components(
        wind_speed_m_s=sample.wind_speed_m_s,
        wind_direction_deg=sample.wind_direction_deg,
        rider_heading_deg=heading,
    )

    return RouteWeatherContext(
        sample=sample,
        rider_heading_deg=heading,
        headwind_m_s=headwind,
        crosswind_m_s=crosswind,
    )


def summarise_gpx_performance(
    gpx_path: str | Path,
    rider: Rider,
    bike: Bike,
    *,
    weather_source: str = "auto",
    include_weather: bool = True,
    wind_exposure_factor: float = 0.0,
    segment_adjustments: list[RouteSegmentAdjustment] | None = None,
    weather_fetcher: WeatherFetcher | None = None,
) -> dict:
    if not 0.0 <= wind_exposure_factor <= 1.0:
        raise ValueError("wind_exposure_factor must be between 0 and 1.")

    route = parse_gpx(gpx_path)
    climb = route_to_performance_climb(route)

    weather_context = None
    headwind_m_s = 0.0

    if include_weather:
        weather_context = fetch_route_weather_context(
            route,
            source=weather_source,
            fetcher=weather_fetcher,
        )
        headwind_m_s = weather_context.headwind_m_s * wind_exposure_factor

    if segment_adjustments:
        summary = summarise_segmented_route_performance(
            route,
            rider,
            bike,
            segment_adjustments=segment_adjustments,
            weather_context=weather_context,
            wind_exposure_factor=wind_exposure_factor,
        )
    else:
        summary = summarise_full_performance(
            rider,
            bike,
            climb,
            headwind_m_s=headwind_m_s,
        )

    result = {
        **summary,
        "climb_distance_m": climb.distance_m,
        "climb_elevation_gain_m": climb.elevation_gain_m,
        "climb_time_s": climb.time_s,
        "route_distance_m": route.distance_m,
        "route_ascent_m": route.ascent_m,
        "route_descent_m": route.descent_m,
        "route_start_time": route.start_time,
        "route_end_time": route.end_time,
        "route_point_count": len(route.points),
    }

    if weather_context is not None:
        result.update(
            {
                "weather_sample_time": weather_context.sample.time,
                "weather_temperature_c": weather_context.sample.temperature_c,
                "weather_relative_humidity_pct": (
                    weather_context.sample.relative_humidity_pct
                ),
                "weather_wind_speed_m_s": weather_context.sample.wind_speed_m_s,
                "weather_wind_direction_deg": (
                    weather_context.sample.wind_direction_deg
                ),
                "weather_wind_gusts_m_s": weather_context.sample.wind_gusts_m_s,
                "rider_heading_deg": weather_context.rider_heading_deg,
                "raw_headwind_m_s": weather_context.headwind_m_s,
                "wind_exposure_factor": wind_exposure_factor,
                "crosswind_m_s": weather_context.crosswind_m_s,
            }
        )

    return result


def summarise_segmented_route_performance(
    route: GPXRoute,
    rider: Rider,
    bike: Bike,
    *,
    segment_adjustments: list[RouteSegmentAdjustment],
    weather_context: RouteWeatherContext | None = None,
    wind_exposure_factor: float = 0.0,
) -> dict:
    climb = route_to_performance_climb(route)
    total_mass = rider.mass_kg + bike.mass_kg
    cda = bike.drag_coefficient * bike.frontal_area_m2
    rho = air_density_at_altitude(climb.avg_altitude_m)
    g = 9.81

    gravity_work_j = 0.0
    rolling_work_j = 0.0
    aero_work_j = 0.0
    adjusted_segments = _validated_adjustments(segment_adjustments, route.distance_m)
    adjustment_summaries = {
        adjustment.name: {
            "distance_m": 0.0,
            "time_s": 0.0,
            "aero_work_j": 0.0,
        }
        for adjustment in adjusted_segments
    }

    cumulative_distance = 0.0

    for route_segment in route.segments:
        start_distance = cumulative_distance
        end_distance = cumulative_distance + route_segment.distance_m
        cumulative_distance = end_distance

        elapsed_s = route_segment.elapsed_s
        if elapsed_s is None or elapsed_s <= 0:
            continue

        ascent_m = max(0.0, route_segment.elevation_delta_m or 0.0)
        gravity_work_j += total_mass * g * ascent_m

        v_road = route_segment.distance_m / elapsed_s
        headwind = 0.0
        if weather_context is not None:
            raw_headwind, _ = wind_to_components(
                wind_speed_m_s=weather_context.sample.wind_speed_m_s,
                wind_direction_deg=weather_context.sample.wind_direction_deg,
                rider_heading_deg=route_segment.bearing_deg,
            )
            headwind = raw_headwind * wind_exposure_factor

        v_air = max(0.0, compute_air_speed(v_road, headwind))

        overlaps = _segment_adjustment_slices(
            start_distance,
            end_distance,
            adjusted_segments,
        )

        for overlap_distance_m, adjustment in overlaps:
            fraction = overlap_distance_m / route_segment.distance_m
            overlap_time_s = elapsed_s * fraction
            crr = (
                adjustment.rolling_resistance_coefficient
                if adjustment.rolling_resistance_coefficient is not None
                else bike.rolling_resistance_coefficient
            )
            rolling_work_j += crr * total_mass * g * overlap_distance_m

            aero_work = (
                0.5
                * rho
                * cda
                * adjustment.aero_multiplier
                * (v_air ** 3)
                * overlap_time_s
            )
            aero_work_j += aero_work

            if adjustment.name in adjustment_summaries:
                adjustment_summaries[adjustment.name]["distance_m"] += overlap_distance_m
                adjustment_summaries[adjustment.name]["time_s"] += overlap_time_s
                adjustment_summaries[adjustment.name]["aero_work_j"] += aero_work

    total_power = (gravity_work_j + rolling_work_j + aero_work_j) / climb.time_s
    power_gravity = gravity_work_j / climb.time_s
    power_rolling = rolling_work_j / climb.time_s
    power_aero = aero_work_j / climb.time_s
    aslp_summary = summarise_aslp(
        observed_power_w=total_power,
        rider_mass_kg=rider.mass_kg,
        avg_altitude_m=climb.avg_altitude_m,
    )

    return {
        "gradient_percent": compute_gradient(
            climb.elevation_gain_m,
            climb.distance_m,
        ),
        "vam_m_per_h": compute_vam(climb.elevation_gain_m, climb.time_s),
        "road_speed_m_per_s": compute_road_speed(climb.distance_m, climb.time_s),
        "vertical_speed_m_per_s": compute_vertical_speed(
            climb.elevation_gain_m,
            climb.time_s,
        ),
        "power_gravity_w": power_gravity,
        "power_rolling_w": power_rolling,
        "power_aero_w": power_aero,
        "total_power_w": total_power,
        "watts_per_kg": estimate_watts_per_kg(total_power, rider),
        "headwind_m_s": 0.0,
        "air_density_kg_m3": rho,
        "segment_adjustments": {
            name: {
                **values,
                "aero_power_w": values["aero_work_j"] / climb.time_s,
            }
            for name, values in adjustment_summaries.items()
        },
        **aslp_summary,
    }


def route_heading_at_distance_fraction(
    route: GPXRoute,
    fraction: float = 0.5,
) -> float:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1.")

    if not route.segments:
        raise ValueError("Route has no segments.")

    target_distance = route.distance_m * fraction
    cumulative = 0.0

    for segment in route.segments:
        cumulative += segment.distance_m
        if cumulative >= target_distance:
            return segment.bearing_deg

    return route.segments[-1].bearing_deg


def _validated_adjustments(
    adjustments: list[RouteSegmentAdjustment],
    route_distance_m: float,
) -> list[RouteSegmentAdjustment]:
    validated = []
    for adjustment in sorted(adjustments, key=lambda item: item.start_distance_m):
        if adjustment.start_distance_m < 0.0:
            raise ValueError(f"{adjustment.name} start_distance_m must be >= 0.")
        if adjustment.end_distance_m > route_distance_m:
            raise ValueError(f"{adjustment.name} end_distance_m exceeds route distance.")
        if adjustment.end_distance_m <= adjustment.start_distance_m:
            raise ValueError(f"{adjustment.name} end must be after start.")
        if adjustment.aero_multiplier < 0.0:
            raise ValueError(f"{adjustment.name} aero_multiplier must be >= 0.")
        if (
            adjustment.rolling_resistance_coefficient is not None
            and adjustment.rolling_resistance_coefficient <= 0.0
        ):
            raise ValueError(
                f"{adjustment.name} rolling_resistance_coefficient must be > 0."
            )
        validated.append(adjustment)

    for previous, current in zip(validated, validated[1:]):
        if current.start_distance_m < previous.end_distance_m:
            raise ValueError(
                f"{current.name} overlaps previous adjustment {previous.name}."
            )

    return validated


def _segment_adjustment_slices(
    start_distance_m: float,
    end_distance_m: float,
    adjustments: list[RouteSegmentAdjustment],
) -> list[tuple[float, RouteSegmentAdjustment]]:
    slices = []
    cursor = start_distance_m

    for adjustment in adjustments:
        overlap_start = max(start_distance_m, adjustment.start_distance_m)
        overlap_end = min(end_distance_m, adjustment.end_distance_m)
        if overlap_end <= overlap_start:
            continue

        if overlap_start > cursor:
            slices.append(
                (
                    overlap_start - cursor,
                    RouteSegmentAdjustment(
                        name="unadjusted",
                        start_distance_m=cursor,
                        end_distance_m=overlap_start,
                    ),
                )
            )

        if overlap_end > overlap_start:
            slices.append((overlap_end - overlap_start, adjustment))
            cursor = overlap_end

    if cursor < end_distance_m:
        slices.append(
            (
                end_distance_m - cursor,
                RouteSegmentAdjustment(
                    name="unadjusted",
                    start_distance_m=cursor,
                    end_distance_m=end_distance_m,
                ),
            )
        )

    return slices


def _default_weather_fetcher(source: str) -> WeatherFetcher:
    def fetch(latitude: float, longitude: float, start_date: str, end_date: str):
        return fetch_hourly_weather(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
            source=source,
        )

    return fetch
