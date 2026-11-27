from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import bisect
import math
import tempfile
from typing import Any

from climbing_performance.aslp import summarise_aslp
from climbing_performance.gpx import GPXRoute, TrackPoint, parse_gpx
from climbing_performance.metrics import air_density_at_altitude
from climbing_performance.route_hydration import clean_route_name, route_payload


G = 9.81
DEFAULT_DISTANCE_STEP_M = 5.0
DEFAULT_REFERENCE_INDEX = 0
DEFAULT_RIDER_MASS_KG = 60.0
DEFAULT_BIKE_MASS_KG = 8.0
DEFAULT_CDA_M2 = 0.33
DEFAULT_CRR = 0.004
SYNC_MODE_DISTANCE = "distance"
SYNC_MODE_LOCATION = "location"
SYNC_MODES = {SYNC_MODE_DISTANCE, SYNC_MODE_LOCATION}


@dataclass(frozen=True)
class LoadedComparisonTrack:
    route: GPXRoute
    name: str
    rider_mass_kg: float = DEFAULT_RIDER_MASS_KG
    color: str | None = None


@dataclass(frozen=True)
class InterpolatedPoint:
    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float | None
    time: datetime | None


@dataclass(frozen=True)
class SegmentStats:
    start_distance_m: float
    end_distance_m: float
    distance_m: float
    elapsed_s: float | None
    ascent_m: float
    descent_m: float
    elevation_delta_m: float
    avg_altitude_m: float


@dataclass(frozen=True)
class TrackSegmentMapping:
    start_distance_m: float
    end_distance_m: float
    start_match_delta_m: float | None = None
    end_match_delta_m: float | None = None


def load_gpx_file(gpx_path: str | Path, *, rider_mass_kg: float = DEFAULT_RIDER_MASS_KG) -> LoadedComparisonTrack:
    path = Path(gpx_path)
    if not path.exists():
        raise FileNotFoundError(f"GPX file not found: {path}")

    route = parse_gpx(path)
    return LoadedComparisonTrack(
        route=route,
        name=clean_route_name(path.name) or route.name or "GPX Route",
        rider_mass_kg=rider_mass_kg,
    )


def load_gpx_text(
    gpx_text: str,
    *,
    name: str | None = None,
    rider_mass_kg: float = DEFAULT_RIDER_MASS_KG,
    color: str | None = None,
) -> LoadedComparisonTrack:
    if not gpx_text.strip():
        raise ValueError("gpx_text is required.")

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

    return LoadedComparisonTrack(
        route=route,
        name=clean_route_name(name) or route.name or "GPX Route",
        rider_mass_kg=rider_mass_kg,
        color=color,
    )


def load_tracks_from_payload(payload: dict[str, Any]) -> list[LoadedComparisonTrack]:
    tracks_payload = payload.get("tracks")
    if not isinstance(tracks_payload, list) or not tracks_payload:
        raise ValueError("tracks must contain at least one GPX payload.")

    tracks = []
    for index, item in enumerate(tracks_payload):
        if not isinstance(item, dict):
            raise ValueError(f"tracks[{index}] must be an object.")

        rider_mass_kg = float(item.get("rider_mass_kg") or DEFAULT_RIDER_MASS_KG)
        tracks.append(
            load_gpx_text(
                str(item.get("gpx_text") or ""),
                name=item.get("name") or item.get("file_name"),
                rider_mass_kg=rider_mass_kg,
                color=item.get("color"),
            )
        )

    return tracks


def comparison_load_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tracks = load_tracks_from_payload(payload)
    min_distance_m = min(track.route.distance_m for track in tracks)
    max_distance_m = max(track.route.distance_m for track in tracks)

    return {
        "tracks": [
            {
                "index": index,
                "name": track.name,
                "rider_mass_kg": track.rider_mass_kg,
                "color": track.color,
                "route": route_payload(track.route, fallback_name=track.name),
            }
            for index, track in enumerate(tracks)
        ],
        "common_distance_m": min_distance_m,
        "max_distance_m": max_distance_m,
    }


def compare_segment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tracks = load_tracks_from_payload(payload)
    assumptions = payload.get("assumptions") or {}
    return compare_loaded_segment(
        tracks,
        reference_index=int(payload.get("reference_index", DEFAULT_REFERENCE_INDEX)),
        sync_mode=str(payload.get("sync_mode") or SYNC_MODE_DISTANCE),
        start_distance_m=float(payload.get("start_distance_m", 0.0)),
        end_distance_m=(
            float(payload["end_distance_m"])
            if payload.get("end_distance_m") is not None
            else None
        ),
        bike_mass_kg=float(assumptions.get("bike_mass_kg", DEFAULT_BIKE_MASS_KG)),
        cda_m2=float(assumptions.get("cda_m2", DEFAULT_CDA_M2)),
        crr=float(assumptions.get("crr", DEFAULT_CRR)),
        distance_step_m=float(payload.get("distance_step_m", DEFAULT_DISTANCE_STEP_M)),
    )


def compare_loaded_segment(
    tracks: list[LoadedComparisonTrack],
    *,
    reference_index: int = DEFAULT_REFERENCE_INDEX,
    sync_mode: str = SYNC_MODE_DISTANCE,
    start_distance_m: float = 0.0,
    end_distance_m: float | None = None,
    bike_mass_kg: float = DEFAULT_BIKE_MASS_KG,
    cda_m2: float = DEFAULT_CDA_M2,
    crr: float = DEFAULT_CRR,
    distance_step_m: float = DEFAULT_DISTANCE_STEP_M,
    include_gap_samples: bool = True,
) -> dict[str, Any]:
    """Estimate a selected section from already parsed routes."""
    if not tracks:
        raise ValueError("At least one track is required.")

    if reference_index < 0 or reference_index >= len(tracks):
        raise ValueError("reference_index is outside the loaded track range.")

    if sync_mode not in SYNC_MODES:
        raise ValueError(
            f"sync_mode must be one of: {', '.join(sorted(SYNC_MODES))}."
        )

    reference_route = tracks[reference_index].route
    if end_distance_m is None:
        end_distance_m = reference_route.distance_m
    if end_distance_m <= start_distance_m:
        raise ValueError("end_distance_m must be greater than start_distance_m.")

    common_distance_m = min(track.route.distance_m for track in tracks)
    selection_limit_m = (
        common_distance_m if sync_mode == SYNC_MODE_DISTANCE else reference_route.distance_m
    )
    if end_distance_m > selection_limit_m:
        raise ValueError(
            "Selected segment exceeds the available route distance "
            f"({selection_limit_m:.1f} m)."
        )

    reference_stats = segment_stats(reference_route, start_distance_m, end_distance_m)
    reference_start_time = time_at_distance(reference_route, start_distance_m)
    reference_end_time = time_at_distance(reference_route, end_distance_m)
    mappings = segment_mappings_for_tracks(
        tracks,
        reference_index=reference_index,
        start_distance_m=start_distance_m,
        end_distance_m=end_distance_m,
        sync_mode=sync_mode,
    )
    comparison_rows = []
    for index, track in enumerate(tracks):
        mapping = mappings[index]
        stats = segment_stats(
            track.route,
            mapping.start_distance_m,
            mapping.end_distance_m,
        )
        power = estimate_segment_power(
            stats,
            rider_mass_kg=track.rider_mass_kg,
            bike_mass_kg=bike_mass_kg,
            cda_m2=cda_m2,
            crr=crr,
        )
        start_time = time_at_distance(track.route, mapping.start_distance_m)
        end_time = time_at_distance(track.route, mapping.end_distance_m)
        time_gap_s = (
            (start_time - reference_start_time).total_seconds()
            if start_time is not None and reference_start_time is not None
            else None
        )
        finish_gap_s = (
            (end_time - reference_end_time).total_seconds()
            if end_time is not None and reference_end_time is not None
            else None
        )
        elapsed_gap_s = (
            stats.elapsed_s - reference_stats.elapsed_s
            if stats.elapsed_s is not None and reference_stats.elapsed_s is not None
            else None
        )
        comparison_rows.append(
            {
                "index": index,
                "name": track.name,
                "rider_mass_kg": track.rider_mass_kg,
                "color": track.color,
                "start_time": start_time.isoformat() if start_time is not None else None,
                "end_time": end_time.isoformat() if end_time is not None else None,
                "start_gap_s": time_gap_s,
                "finish_gap_s": finish_gap_s,
                "elapsed_gap_s": elapsed_gap_s,
                "segment": segment_stats_payload(stats),
                "mapping": {
                    "start_distance_m": mapping.start_distance_m,
                    "end_distance_m": mapping.end_distance_m,
                    "start_match_delta_m": mapping.start_match_delta_m,
                    "end_match_delta_m": mapping.end_match_delta_m,
                },
                "metrics": power,
            }
        )

    return {
        "sync_mode": sync_mode,
        "segment": {
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
            "distance_m": end_distance_m - start_distance_m,
        },
        "reference_index": reference_index,
        "tracks": comparison_rows,
        "gap_samples": (
            gap_samples(
                tracks,
                start_distance_m,
                end_distance_m,
                reference_index=reference_index,
                step_m=distance_step_m,
                sync_mode=sync_mode,
            )
            if include_gap_samples
            else []
        ),
    }


def segment_stats_payload(stats: SegmentStats) -> dict[str, float | None]:
    return {
        "start_distance_m": stats.start_distance_m,
        "end_distance_m": stats.end_distance_m,
        "distance_m": stats.distance_m,
        "elapsed_s": stats.elapsed_s,
        "ascent_m": stats.ascent_m,
        "descent_m": stats.descent_m,
        "elevation_delta_m": stats.elevation_delta_m,
        "avg_altitude_m": stats.avg_altitude_m,
        "gradient_percent": (
            100.0 * stats.elevation_delta_m / stats.distance_m
            if stats.distance_m > 0
            else None
        ),
        "vam_m_per_h": (
            stats.ascent_m / (stats.elapsed_s / 3600.0)
            if stats.elapsed_s and stats.elapsed_s > 0
            else None
        ),
    }


def segment_stats(
    route: GPXRoute,
    start_distance_m: float,
    end_distance_m: float,
) -> SegmentStats:
    if start_distance_m < 0.0:
        raise ValueError("start_distance_m must be >= 0.")
    if end_distance_m > route.distance_m:
        raise ValueError("end_distance_m exceeds route distance.")
    if end_distance_m <= start_distance_m:
        raise ValueError("end_distance_m must be greater than start_distance_m.")

    sample_distances = [
        start_distance_m,
        *[
            point.distance_m
            for point in route.points
            if start_distance_m < point.distance_m < end_distance_m
        ],
        end_distance_m,
    ]
    samples = [point_at_distance(route, distance_m) for distance_m in sample_distances]

    ascent_m = 0.0
    descent_m = 0.0
    for start, end in zip(samples, samples[1:]):
        if start.elevation_m is None or end.elevation_m is None:
            continue
        delta = end.elevation_m - start.elevation_m
        ascent_m += max(0.0, delta)
        descent_m += abs(min(0.0, delta))

    start_sample = samples[0]
    end_sample = samples[-1]
    elapsed_s = (
        (end_sample.time - start_sample.time).total_seconds()
        if start_sample.time is not None and end_sample.time is not None
        else None
    )
    elevations = [sample.elevation_m for sample in samples if sample.elevation_m is not None]
    avg_altitude_m = sum(elevations) / len(elevations) if elevations else 0.0
    elevation_delta_m = (
        end_sample.elevation_m - start_sample.elevation_m
        if start_sample.elevation_m is not None and end_sample.elevation_m is not None
        else ascent_m
    )

    return SegmentStats(
        start_distance_m=start_distance_m,
        end_distance_m=end_distance_m,
        distance_m=end_distance_m - start_distance_m,
        elapsed_s=elapsed_s,
        ascent_m=ascent_m,
        descent_m=descent_m,
        elevation_delta_m=elevation_delta_m,
        avg_altitude_m=avg_altitude_m,
    )


def estimate_segment_power(
    stats: SegmentStats,
    *,
    rider_mass_kg: float = DEFAULT_RIDER_MASS_KG,
    bike_mass_kg: float = DEFAULT_BIKE_MASS_KG,
    cda_m2: float = DEFAULT_CDA_M2,
    crr: float = DEFAULT_CRR,
    standard_rider_mass_kg: float = DEFAULT_RIDER_MASS_KG,
) -> dict[str, float | None]:
    if stats.elapsed_s is None or stats.elapsed_s <= 0.0:
        return {
            "total_power_w": None,
            "watts_per_kg": None,
            "standard_60kg_power_w": None,
            "standard_60kg_w_per_kg": None,
            "sea_level_equivalent_power_w": None,
            "aslp_w_per_kg": None,
        }

    v_road = stats.distance_m / stats.elapsed_s
    rho = air_density_at_altitude(stats.avg_altitude_m)

    total_power = _power_for_mass(
        rider_mass_kg=rider_mass_kg,
        bike_mass_kg=bike_mass_kg,
        ascent_m=stats.ascent_m,
        distance_m=stats.distance_m,
        elapsed_s=stats.elapsed_s,
        cda_m2=cda_m2,
        crr=crr,
        rho=rho,
        v_road=v_road,
    )
    standard_power = _power_for_mass(
        rider_mass_kg=standard_rider_mass_kg,
        bike_mass_kg=bike_mass_kg,
        ascent_m=stats.ascent_m,
        distance_m=stats.distance_m,
        elapsed_s=stats.elapsed_s,
        cda_m2=cda_m2,
        crr=crr,
        rho=rho,
        v_road=v_road,
    )
    aslp = summarise_aslp(total_power, rider_mass_kg, stats.avg_altitude_m)

    return {
        "total_power_w": total_power,
        "watts_per_kg": total_power / rider_mass_kg,
        "standard_60kg_power_w": standard_power,
        "standard_60kg_w_per_kg": standard_power / standard_rider_mass_kg,
        "sea_level_equivalent_power_w": aslp["sea_level_equivalent_power_w"],
        "aslp_w_per_kg": aslp["aslp_w_per_kg"],
        "air_density_kg_m3": rho,
        "road_speed_m_per_s": v_road,
        "gravity_power_w": (rider_mass_kg + bike_mass_kg) * G * stats.ascent_m / stats.elapsed_s,
        "rolling_power_w": crr * (rider_mass_kg + bike_mass_kg) * G * stats.distance_m / stats.elapsed_s,
        "aero_power_w": 0.5 * rho * cda_m2 * v_road**3,
    }


def _power_for_mass(
    *,
    rider_mass_kg: float,
    bike_mass_kg: float,
    ascent_m: float,
    distance_m: float,
    elapsed_s: float,
    cda_m2: float,
    crr: float,
    rho: float,
    v_road: float,
) -> float:
    total_mass_kg = rider_mass_kg + bike_mass_kg
    gravity_power = total_mass_kg * G * ascent_m / elapsed_s
    rolling_power = crr * total_mass_kg * G * distance_m / elapsed_s
    aero_power = 0.5 * rho * cda_m2 * v_road**3
    return gravity_power + rolling_power + aero_power


def segment_mappings_for_tracks(
    tracks: list[LoadedComparisonTrack],
    *,
    reference_index: int,
    start_distance_m: float,
    end_distance_m: float,
    sync_mode: str = SYNC_MODE_DISTANCE,
) -> list[TrackSegmentMapping]:
    if sync_mode == SYNC_MODE_DISTANCE:
        return [
            TrackSegmentMapping(
                start_distance_m=start_distance_m,
                end_distance_m=end_distance_m,
            )
            for _ in tracks
        ]

    reference_route = tracks[reference_index].route
    mappings = []
    for index, track in enumerate(tracks):
        if index == reference_index:
            mappings.append(
                TrackSegmentMapping(
                    start_distance_m=start_distance_m,
                    end_distance_m=end_distance_m,
                    start_match_delta_m=0.0,
                    end_match_delta_m=0.0,
                )
            )
            continue

        start_match = route_distance_for_reference_location(
            reference_route,
            track.route,
            start_distance_m,
        )
        end_match = route_distance_for_reference_location(
            reference_route,
            track.route,
            end_distance_m,
        )
        if end_match["distance_m"] <= start_match["distance_m"]:
            raise ValueError(
                f"Location sync mapped {track.name} backwards. "
                "Check that all GPX files follow the same route direction."
            )

        mappings.append(
            TrackSegmentMapping(
                start_distance_m=start_match["distance_m"],
                end_distance_m=end_match["distance_m"],
                start_match_delta_m=start_match["match_delta_m"],
                end_match_delta_m=end_match["match_delta_m"],
            )
        )

    return mappings


def route_distance_for_reference_location(
    reference_route: GPXRoute,
    target_route: GPXRoute,
    reference_distance_m: float,
) -> dict[str, float]:
    point = point_at_distance(reference_route, reference_distance_m)
    return closest_route_distance_to_location(
        target_route,
        latitude=point.latitude,
        longitude=point.longitude,
    )


def closest_route_distance_to_location(
    route: GPXRoute,
    *,
    latitude: float,
    longitude: float,
) -> dict[str, float]:
    if not route.segments:
        raise ValueError("Route needs at least one connected segment for location sync.")

    meters_per_lat = 111_320.0
    meters_per_lon = 111_320.0 * math.cos(math.radians(latitude))
    best_distance_m = route.points[0].distance_m
    best_delta_m = float("inf")

    for route_segment in route.segments:
        start = route_segment.start
        end = route_segment.end
        ax = (start.longitude - longitude) * meters_per_lon
        ay = (start.latitude - latitude) * meters_per_lat
        bx = (end.longitude - longitude) * meters_per_lon
        by = (end.latitude - latitude) * meters_per_lat
        abx = bx - ax
        aby = by - ay
        ab2 = abx * abx + aby * aby
        if ab2 <= 0.0:
            fraction = 0.0
        else:
            fraction = max(0.0, min(1.0, -(ax * abx + ay * aby) / ab2))

        px = ax + fraction * abx
        py = ay + fraction * aby
        delta_m = math.hypot(px, py)
        if delta_m < best_delta_m:
            best_delta_m = delta_m
            best_distance_m = start.distance_m + fraction * route_segment.distance_m

    return {
        "distance_m": best_distance_m,
        "match_delta_m": best_delta_m,
    }


def gap_samples(
    tracks: list[LoadedComparisonTrack],
    start_distance_m: float,
    end_distance_m: float,
    *,
    reference_index: int = DEFAULT_REFERENCE_INDEX,
    step_m: float = DEFAULT_DISTANCE_STEP_M,
    sync_mode: str = SYNC_MODE_DISTANCE,
) -> list[dict[str, Any]]:
    reference_route = tracks[reference_index].route
    distances = distance_grid(start_distance_m, end_distance_m, step_m=step_m)
    reference_start = time_at_distance(reference_route, start_distance_m)
    reference_elapsed = {
        distance_m: elapsed_at_distance(reference_route, start_distance_m, distance_m)
        for distance_m in distances
    }

    result = []
    for index, track in enumerate(tracks):
        if sync_mode == SYNC_MODE_LOCATION and index != reference_index:
            start_match = route_distance_for_reference_location(
                reference_route,
                track.route,
                start_distance_m,
            )
            track_start_distance_m = start_match["distance_m"]
        else:
            track_start_distance_m = start_distance_m

        track_start = time_at_distance(track.route, track_start_distance_m)
        samples = []
        for distance_m in distances:
            if sync_mode == SYNC_MODE_LOCATION and index != reference_index:
                target_match = route_distance_for_reference_location(
                    reference_route,
                    track.route,
                    distance_m,
                )
                track_distance_m = target_match["distance_m"]
                match_delta_m = target_match["match_delta_m"]
            else:
                track_distance_m = distance_m
                match_delta_m = 0.0 if sync_mode == SYNC_MODE_LOCATION else None

            elapsed_s = elapsed_at_distance(
                track.route,
                track_start_distance_m,
                track_distance_m,
            )
            ref_elapsed_s = reference_elapsed[distance_m]
            gap_s = (
                elapsed_s - ref_elapsed_s
                if elapsed_s is not None and ref_elapsed_s is not None
                else None
            )
            absolute_gap_s = (
                (track_start - reference_start).total_seconds() + gap_s
                if track_start is not None
                and reference_start is not None
                and gap_s is not None
                else None
            )
            samples.append(
                {
                    "distance_m": distance_m,
                    "track_distance_m": track_distance_m,
                    "match_delta_m": match_delta_m,
                    "gap_s": gap_s,
                    "absolute_gap_s": absolute_gap_s,
                    "elapsed_s": elapsed_s,
                }
            )

        result.append(
            {
                "index": index,
                "name": track.name,
                "color": track.color,
                "samples": samples,
            }
        )

    return result


def distance_grid(start_distance_m: float, end_distance_m: float, *, step_m: float) -> list[float]:
    if step_m <= 0.0:
        raise ValueError("step_m must be > 0.")

    distances = []
    current = start_distance_m
    while current < end_distance_m:
        distances.append(current)
        current += step_m
    if not distances or distances[-1] != end_distance_m:
        distances.append(end_distance_m)
    return distances


def elapsed_at_distance(
    route: GPXRoute,
    start_distance_m: float,
    target_distance_m: float,
) -> float | None:
    start_time = time_at_distance(route, start_distance_m)
    target_time = time_at_distance(route, target_distance_m)
    if start_time is None or target_time is None:
        return None
    return (target_time - start_time).total_seconds()


def time_at_distance(route: GPXRoute, distance_m: float) -> datetime | None:
    return point_at_distance(route, distance_m).time


def point_at_distance(route: GPXRoute, distance_m: float) -> InterpolatedPoint:
    if not route.points:
        raise ValueError("Route has no points.")

    target = max(0.0, min(distance_m, route.distance_m))
    distances = [point.distance_m for point in route.points]
    index = bisect.bisect_left(distances, target)

    if index <= 0:
        return _interpolated_from_track_point(route.points[0], target)
    if index >= len(route.points):
        return _interpolated_from_track_point(route.points[-1], target)

    previous = route.points[index - 1]
    current = route.points[index]
    span = current.distance_m - previous.distance_m
    fraction = 0.0 if span <= 0.0 else (target - previous.distance_m) / span

    return InterpolatedPoint(
        distance_m=target,
        latitude=_lerp(previous.latitude, current.latitude, fraction),
        longitude=_lerp(previous.longitude, current.longitude, fraction),
        elevation_m=_optional_lerp(previous.elevation_m, current.elevation_m, fraction),
        time=_interpolate_time(previous.time, current.time, fraction),
    )


def _interpolated_from_track_point(point: TrackPoint, distance_m: float) -> InterpolatedPoint:
    return InterpolatedPoint(
        distance_m=distance_m,
        latitude=point.latitude,
        longitude=point.longitude,
        elevation_m=point.elevation_m,
        time=point.time,
    )


def _optional_lerp(start: float | None, end: float | None, fraction: float) -> float | None:
    if start is None or end is None:
        return None
    return _lerp(start, end, fraction)


def _interpolate_time(
    start: datetime | None,
    end: datetime | None,
    fraction: float,
) -> datetime | None:
    if start is None or end is None:
        return None
    return start + (end - start) * fraction


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction
