from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
import math
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class TrackPoint:
    latitude: float
    longitude: float
    elevation_m: float | None = None
    time: datetime | None = None
    segment_index: int = 0


@dataclass(frozen=True)
class RouteSegment:
    start: TrackPoint
    end: TrackPoint
    distance_m: float
    elevation_delta_m: float | None
    grade_percent: float | None
    bearing_deg: float
    elapsed_s: float | None


@dataclass(frozen=True)
class Climb:
    start_point: TrackPoint
    end_point: TrackPoint
    distance_m: float
    ascent_m: float
    net_elevation_gain_m: float
    average_grade_percent: float
    start_time: datetime | None
    end_time: datetime | None


@dataclass(frozen=True)
class WeatherQueryWindow:
    latitude: float
    longitude: float
    start_time: datetime
    end_time: datetime

    @property
    def start_date(self) -> str:
        return self.start_time.date().isoformat()

    @property
    def end_date(self) -> str:
        return self.end_time.date().isoformat()


@dataclass
class GPXRoute:
    points: list[TrackPoint]
    segments: list[RouteSegment]

    @property
    def start_time(self) -> datetime | None:
        times = [p.time for p in self.points if p.time is not None]
        return min(times) if times else None

    @property
    def end_time(self) -> datetime | None:
        times = [p.time for p in self.points if p.time is not None]
        return max(times) if times else None

    @property
    def distance_m(self) -> float:
        return sum(s.distance_m for s in self.segments)

    @property
    def ascent_m(self) -> float:
        return sum(
            max(0.0, s.elevation_delta_m)
            for s in self.segments
            if s.elevation_delta_m is not None
        )

    @property
    def descent_m(self) -> float:
        return sum(
            abs(min(0.0, s.elevation_delta_m))
            for s in self.segments
            if s.elevation_delta_m is not None
        )

    @property
    def min_elevation_m(self) -> float | None:
        elevations = [p.elevation_m for p in self.points if p.elevation_m is not None]
        return min(elevations) if elevations else None

    @property
    def max_elevation_m(self) -> float | None:
        elevations = [p.elevation_m for p in self.points if p.elevation_m is not None]
        return max(elevations) if elevations else None

    @property
    def centroid(self) -> tuple[float, float]:
        if not self.points:
            raise ValueError("Route has no points.")

        lat = sum(p.latitude for p in self.points) / len(self.points)
        lon = sum(p.longitude for p in self.points) / len(self.points)
        return lat, lon

    def point_at_distance_fraction(self, fraction: float = 0.5) -> TrackPoint:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be between 0 and 1.")

        if not self.points:
            raise ValueError("Route has no points.")

        target_distance = self.distance_m * fraction
        cumulative = 0.0

        for segment in self.segments:
            cumulative += segment.distance_m
            if cumulative >= target_distance:
                return segment.end

        return self.points[-1]

    def weather_query_window(
        self,
        *,
        location: str = "midpoint",
        pad: timedelta = timedelta(hours=1),
    ) -> WeatherQueryWindow:
        """
        Create a weather query window for the route.

        location:
            "midpoint" gives the distance midpoint.
            "centroid" gives the mean coordinate.
        """
        if self.start_time is None or self.end_time is None:
            raise ValueError(
                "Route has no timestamps. Use assign_estimated_times() first "
                "or provide a GPX file with time data."
            )

        if location == "midpoint":
            p = self.point_at_distance_fraction(0.5)
            lat, lon = p.latitude, p.longitude
        elif location == "centroid":
            lat, lon = self.centroid
        else:
            raise ValueError("location must be 'midpoint' or 'centroid'.")

        return WeatherQueryWindow(
            latitude=lat,
            longitude=lon,
            start_time=self.start_time - pad,
            end_time=self.end_time + pad,
        )


def parse_gpx(path: str | Path) -> GPXRoute:
    path = Path(path)
    root = ET.parse(path).getroot()

    points = _extract_track_points(root)

    if len(points) < 2:
        raise ValueError("GPX file must contain at least two track points.")

    segments = build_route_segments(points)

    return GPXRoute(points=points, segments=segments)


def build_route_segments(points: list[TrackPoint]) -> list[RouteSegment]:
    segments: list[RouteSegment] = []

    for start, end in zip(points, points[1:]):
        # Do not connect separate GPX track segments with artificial jumps.
        if start.segment_index != end.segment_index:
            continue

        distance_m = haversine_distance_m(
            start.latitude,
            start.longitude,
            end.latitude,
            end.longitude,
        )

        if distance_m <= 0:
            continue

        elevation_delta_m: float | None = None
        grade_percent: float | None = None

        if start.elevation_m is not None and end.elevation_m is not None:
            elevation_delta_m = end.elevation_m - start.elevation_m
            grade_percent = 100.0 * elevation_delta_m / distance_m

        elapsed_s: float | None = None
        if start.time is not None and end.time is not None:
            elapsed_s = (end.time - start.time).total_seconds()

        segments.append(
            RouteSegment(
                start=start,
                end=end,
                distance_m=distance_m,
                elevation_delta_m=elevation_delta_m,
                grade_percent=grade_percent,
                bearing_deg=bearing_deg(
                    start.latitude,
                    start.longitude,
                    end.latitude,
                    end.longitude,
                ),
                elapsed_s=elapsed_s,
            )
        )

    return segments


def extract_climbs(
    route: GPXRoute,
    *,
    min_distance_m: float = 500.0,
    min_ascent_m: float = 50.0,
    min_average_grade_percent: float = 3.0,
    max_descent_gap_m: float = 10.0,
) -> list[Climb]:
    """
    Extract likely climbs from the route.

    This is deliberately simple:
    - positive elevation segments are accumulated;
    - small descents are tolerated;
    - only sustained climbs above thresholds are returned.
    """
    climbs: list[Climb] = []
    current: list[RouteSegment] = []
    tolerated_descent = 0.0

    def flush_current() -> None:
        nonlocal current, tolerated_descent

        if not current:
            return

        distance_m = sum(s.distance_m for s in current)
        ascent_m = sum(
            max(0.0, s.elevation_delta_m or 0.0)
            for s in current
        )

        start_point = current[0].start
        end_point = current[-1].end

        if (
            start_point.elevation_m is not None
            and end_point.elevation_m is not None
        ):
            net_gain = end_point.elevation_m - start_point.elevation_m
        else:
            net_gain = ascent_m

        average_grade = 100.0 * net_gain / distance_m if distance_m > 0 else 0.0

        if (
            distance_m >= min_distance_m
            and ascent_m >= min_ascent_m
            and average_grade >= min_average_grade_percent
        ):
            climbs.append(
                Climb(
                    start_point=start_point,
                    end_point=end_point,
                    distance_m=distance_m,
                    ascent_m=ascent_m,
                    net_elevation_gain_m=net_gain,
                    average_grade_percent=average_grade,
                    start_time=start_point.time,
                    end_time=end_point.time,
                )
            )

        current = []
        tolerated_descent = 0.0

    for segment in route.segments:
        elevation_delta = segment.elevation_delta_m

        if elevation_delta is None:
            continue

        if elevation_delta > 0:
            current.append(segment)
            tolerated_descent = 0.0
        elif current and abs(elevation_delta) <= max_descent_gap_m:
            current.append(segment)
            tolerated_descent += abs(elevation_delta)

            if tolerated_descent > max_descent_gap_m:
                flush_current()
        else:
            flush_current()

    flush_current()
    return climbs


def assign_estimated_times(
    route: GPXRoute,
    *,
    start_time: datetime,
    duration: timedelta,
) -> GPXRoute:
    """
    Assign estimated timestamps to a GPX route that has no time data.

    Timing is distributed proportionally by distance. This is suitable for
    planned race simulations when the GPX file only contains geometry.
    """
    if not route.points:
        raise ValueError("Route has no points.")

    total_distance = route.distance_m
    if total_distance <= 0:
        raise ValueError("Route distance must be positive.")

    cumulative_by_point_id: dict[int, float] = {id(route.points[0]): 0.0}

    cumulative = 0.0
    for segment in route.segments:
        cumulative += segment.distance_m
        cumulative_by_point_id[id(segment.end)] = cumulative

    new_points: list[TrackPoint] = []

    for point in route.points:
        point_distance = cumulative_by_point_id.get(id(point), 0.0)
        fraction = point_distance / total_distance
        estimated_time = start_time + duration * fraction

        new_points.append(
            TrackPoint(
                latitude=point.latitude,
                longitude=point.longitude,
                elevation_m=point.elevation_m,
                time=estimated_time,
                segment_index=point.segment_index,
            )
        )

    return GPXRoute(
        points=new_points,
        segments=build_route_segments(new_points),
    )


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    earth_radius_m = 6_371_000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2.0) ** 2
    )

    return 2.0 * earth_radius_m * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def bearing_deg(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)

    x = math.sin(d_lambda) * math.cos(phi2)
    y = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    )

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360.0) % 360.0


def _extract_track_points(root: ET.Element) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    segment_index = 0

    track_segments = [
        elem for elem in root.iter()
        if _local_name(elem.tag) == "trkseg"
    ]

    if track_segments:
        for trkseg in track_segments:
            for trkpt in trkseg:
                if _local_name(trkpt.tag) == "trkpt":
                    points.append(_parse_point(trkpt, segment_index))
            segment_index += 1
    else:
        # Fallback for route-style GPX files using <rtept>.
        route_points = [
            elem for elem in root.iter()
            if _local_name(elem.tag) == "rtept"
        ]

        for rtept in route_points:
            points.append(_parse_point(rtept, segment_index))

    return points


def _parse_point(elem: ET.Element, segment_index: int) -> TrackPoint:
    lat = float(elem.attrib["lat"])
    lon = float(elem.attrib["lon"])

    elevation_m: float | None = None
    time: datetime | None = None

    for child in elem:
        name = _local_name(child.tag)

        if name == "ele" and child.text is not None:
            elevation_m = float(child.text)

        elif name == "time" and child.text is not None:
            time = _parse_gpx_time(child.text)

    return TrackPoint(
        latitude=lat,
        longitude=lon,
        elevation_m=elevation_m,
        time=time,
        segment_index=segment_index,
    )


def _parse_gpx_time(value: str) -> datetime:
    # GPX commonly uses UTC timestamps ending with Z.
    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    return datetime.fromisoformat(value)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag