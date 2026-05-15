from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from typing import Iterable

import requests


ELEVATION_API_URL = "https://api.open-meteo.com/v1/elevation"
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class SamplePoint:
    bearing_deg: float
    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float
    horizon_angle_deg: float


@dataclass(frozen=True)
class TerrainWindProbe:
    latitude: float
    longitude: float
    wind_from_deg: float
    center_elevation_m: float
    max_horizon_angle_deg: float
    mean_horizon_angle_deg: float
    shelter_index: float
    exposure_factor: float
    classification: str
    sample_count: int
    samples: list[SamplePoint]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Probe DEM-based terrain shelter for one coordinate and meteorological "
            "wind direction."
        )
    )
    parser.add_argument("--lat", type=float, required=True, help="Latitude in WGS84.")
    parser.add_argument("--lon", type=float, required=True, help="Longitude in WGS84.")
    parser.add_argument(
        "--wind-direction-deg",
        type=float,
        required=True,
        help="Meteorological wind direction: degrees wind is coming from.",
    )
    parser.add_argument("--radius-m", type=float, default=900.0)
    parser.add_argument("--step-m", type=float, default=90.0)
    parser.add_argument("--sector-deg", type=float, default=60.0)
    parser.add_argument("--rays", type=int, default=7)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full probe result as JSON.",
    )
    args = parser.parse_args()

    probe = probe_terrain_wind(
        latitude=args.lat,
        longitude=args.lon,
        wind_from_deg=args.wind_direction_deg,
        radius_m=args.radius_m,
        step_m=args.step_m,
        sector_deg=args.sector_deg,
        ray_count=args.rays,
    )

    if args.json:
        print(json.dumps(probe_to_payload(probe), indent=2))
    else:
        print_summary(probe)


def probe_terrain_wind(
    *,
    latitude: float,
    longitude: float,
    wind_from_deg: float,
    radius_m: float = 900.0,
    step_m: float = 90.0,
    sector_deg: float = 60.0,
    ray_count: int = 7,
) -> TerrainWindProbe:
    validate_inputs(latitude, longitude, radius_m, step_m, sector_deg, ray_count)

    sample_locations = [(latitude, longitude)]
    for bearing in wind_sector_bearings(wind_from_deg, sector_deg, ray_count):
        for distance in distances(step_m, radius_m):
            sample_locations.append(destination_point(latitude, longitude, bearing, distance))

    elevations = fetch_elevations(sample_locations)
    center_elevation = elevations[0]
    samples = []
    index = 1
    for bearing in wind_sector_bearings(wind_from_deg, sector_deg, ray_count):
        for distance in distances(step_m, radius_m):
            sample_lat, sample_lon = sample_locations[index]
            sample_elevation = elevations[index]
            horizon_angle = math.degrees(
                math.atan2(sample_elevation - center_elevation, distance)
            )
            samples.append(
                SamplePoint(
                    bearing_deg=normalize_degrees(bearing),
                    distance_m=distance,
                    latitude=sample_lat,
                    longitude=sample_lon,
                    elevation_m=sample_elevation,
                    horizon_angle_deg=horizon_angle,
                )
            )
            index += 1

    max_horizon = max(sample.horizon_angle_deg for sample in samples)
    mean_horizon = sum(sample.horizon_angle_deg for sample in samples) / len(samples)
    shelter_index = max(0.0, max_horizon) + max(0.0, mean_horizon) * 0.5
    exposure_factor = shelter_to_exposure_factor(shelter_index)

    return TerrainWindProbe(
        latitude=latitude,
        longitude=longitude,
        wind_from_deg=normalize_degrees(wind_from_deg),
        center_elevation_m=center_elevation,
        max_horizon_angle_deg=max_horizon,
        mean_horizon_angle_deg=mean_horizon,
        shelter_index=shelter_index,
        exposure_factor=exposure_factor,
        classification=classify_exposure(exposure_factor),
        sample_count=len(samples),
        samples=samples,
    )


def validate_inputs(
    latitude: float,
    longitude: float,
    radius_m: float,
    step_m: float,
    sector_deg: float,
    ray_count: int,
) -> None:
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("--lat must be between -90 and 90.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("--lon must be between -180 and 180.")
    if radius_m <= 0.0:
        raise ValueError("--radius-m must be positive.")
    if step_m <= 0.0:
        raise ValueError("--step-m must be positive.")
    if radius_m < step_m:
        raise ValueError("--radius-m must be greater than or equal to --step-m.")
    if not 0.0 <= sector_deg <= 180.0:
        raise ValueError("--sector-deg must be between 0 and 180.")
    if ray_count < 1:
        raise ValueError("--rays must be at least 1.")


def wind_sector_bearings(
    wind_from_deg: float,
    sector_deg: float,
    ray_count: int,
) -> list[float]:
    if ray_count == 1:
        return [normalize_degrees(wind_from_deg)]

    start = wind_from_deg - sector_deg / 2.0
    step = sector_deg / (ray_count - 1)
    return [normalize_degrees(start + step * index) for index in range(ray_count)]


def distances(step_m: float, radius_m: float) -> list[float]:
    count = int(math.floor(radius_m / step_m))
    output = [step_m * index for index in range(1, count + 1)]
    if output[-1] < radius_m:
        output.append(radius_m)
    return output


def destination_point(
    latitude: float,
    longitude: float,
    bearing_deg: float,
    distance_m: float,
) -> tuple[float, float]:
    angular_distance = distance_m / EARTH_RADIUS_M
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )

    return math.degrees(lat2), normalize_longitude(math.degrees(lon2))


def fetch_elevations(locations: list[tuple[float, float]]) -> list[float]:
    elevations = []
    for batch in batched(locations, 100):
        params = {
            "latitude": ",".join(f"{lat:.6f}" for lat, _ in batch),
            "longitude": ",".join(f"{lon:.6f}" for _, lon in batch),
        }
        response = requests.get(ELEVATION_API_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if "elevation" not in payload:
            raise RuntimeError(f"Elevation API response missing elevation: {payload}")
        elevations.extend(float(value) for value in payload["elevation"])

    if len(elevations) != len(locations):
        raise RuntimeError(
            f"Elevation API returned {len(elevations)} values for {len(locations)} points."
        )
    return elevations


def batched(
    values: list[tuple[float, float]],
    size: int,
) -> Iterable[list[tuple[float, float]]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def shelter_to_exposure_factor(shelter_index: float) -> float:
    return max(0.2, min(1.0, 1.0 - shelter_index / 18.0))


def classify_exposure(exposure_factor: float) -> str:
    if exposure_factor >= 0.8:
        return "exposed"
    if exposure_factor >= 0.55:
        return "partly sheltered"
    return "sheltered"


def normalize_degrees(value: float) -> float:
    return value % 360.0


def normalize_longitude(value: float) -> float:
    return ((value + 180.0) % 360.0) - 180.0


def probe_to_payload(probe: TerrainWindProbe) -> dict:
    payload = asdict(probe)
    payload["data_source"] = "Open-Meteo Elevation API, Copernicus DEM GLO-90"
    payload["interpretation"] = (
        "Experimental directional terrain shelter probe. Exposure factor is a "
        "screening value, not a calibrated wind-speed prediction."
    )
    return payload


def print_summary(probe: TerrainWindProbe) -> None:
    print("Terrain wind probe")
    print(f"Coordinate: {probe.latitude:.6f}, {probe.longitude:.6f}")
    print(f"Wind from: {probe.wind_from_deg:.0f} deg")
    print(f"Center elevation: {probe.center_elevation_m:.1f} m")
    print(f"Max upwind horizon: {probe.max_horizon_angle_deg:.2f} deg")
    print(f"Mean upwind horizon: {probe.mean_horizon_angle_deg:.2f} deg")
    print(f"Shelter index: {probe.shelter_index:.2f}")
    print(f"Exposure factor: {probe.exposure_factor:.2f}")
    print(f"Classification: {probe.classification}")
    print(f"Samples: {probe.sample_count}")
    print()
    print("Interpretation: lower exposure means the sampled upwind terrain rises enough")
    print("to plausibly shelter the coordinate from some ambient wind. Treat this as")
    print("a first-pass screening metric, not a calibrated local wind model.")


if __name__ == "__main__":
    main()
