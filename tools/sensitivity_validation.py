from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climbing_performance.gpx import parse_gpx
from climbing_performance.aslp import cp_remaining_fraction_at_altitude
from climbing_performance.workflow import motorcycle_draft_aero_multiplier


ACTIVE_SCENARIO_PATH = REPO_ROOT / "data" / "cache" / "active_segment_scenario.json"
DEFAULT_GPX_PATH = REPO_ROOT / "data" / "la_redoute.gpx"
LA_REDOUTE_WEATHER_PATH = REPO_ROOT / "data" / "la_redoute_weather.json"
G = 9.81
RHO0 = 1.225
SCALE_HEIGHT_M = 8500.0
STANDARD_TEMP_K = 288.15


@dataclass(frozen=True)
class SensitivityCase:
    name: str
    rider_mass_kg: float
    bike_mass_kg: float
    cda_m2: float
    crr: float
    segment_transform: Callable[[dict], float] | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run sensitivity validation from the active segment GUI assumptions."
    )
    parser.add_argument("--scenario", type=Path, default=ACTIVE_SCENARIO_PATH)
    parser.add_argument("--gpx", type=Path, default=DEFAULT_GPX_PATH)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    rows = run_sensitivity_cases(args.gpx, scenario)

    print_table(rows)
    if args.output_csv:
        write_csv(args.output_csv, rows)
        print(f"\nWrote {args.output_csv}")


def load_scenario(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"No active scenario found at {path}. Start tools/open_segment_gui.py "
            "and let the GUI render once, or pass --scenario."
        )

    return json.loads(path.read_text(encoding="utf-8"))


def run_sensitivity_cases(gpx_path: Path, scenario: dict) -> list[dict]:
    validate_gpx_matches_scenario(gpx_path, scenario)
    assumptions = scenario["assumptions"]
    base_case = SensitivityCase(
        name="active",
        rider_mass_kg=float(assumptions["rider_mass_kg"]),
        bike_mass_kg=float(assumptions["bike_mass_kg"]),
        cda_m2=float(assumptions["cda_m2"]),
        crr=float(assumptions["crr"]),
    )
    cases = build_cases(base_case)
    base_row = None
    rows = []

    for case in cases:
        summary = evaluate_case(gpx_path, scenario, case)
        row = {
            "case": case.name,
            "rider_kg": case.rider_mass_kg,
            "bike_kg": case.bike_mass_kg,
            "cda_m2": case.cda_m2,
            "crr": case.crr,
            "avg_aero_multiplier": weighted_aero_multiplier(scenario, case),
            "total_power_w": summary["total_power_w"],
            "wkg": summary["watts_per_kg"],
            "aslp_wkg": summary["aslp_w_per_kg"],
            "standard60_wkg": summary["standard60_w_per_kg"],
            "aero_power_w": summary["power_aero_w"],
        }
        if base_row is None:
            base_row = row
        row["delta_w"] = row["total_power_w"] - base_row["total_power_w"]
        row["delta_wkg"] = row["wkg"] - base_row["wkg"]
        rows.append(row)

    return rows


def validate_gpx_matches_scenario(gpx_path: Path, scenario: dict) -> None:
    route = parse_gpx(gpx_path)
    scenario_route = scenario.get("route", {})
    scenario_distance = float(scenario_route.get("distance_m", 0.0))
    scenario_duration = scenario_route.get("duration_s")

    if abs(route.distance_m - scenario_distance) > 1.0:
        raise SystemExit(
            f"Scenario route distance is {scenario_distance:.1f} m, but {gpx_path} "
            f"is {route.distance_m:.1f} m. Pass the matching route with --gpx."
        )

    if scenario_duration is not None and route.start_time and route.end_time:
        route_duration = (route.end_time - route.start_time).total_seconds()
        if abs(route_duration - float(scenario_duration)) > 1.0:
            raise SystemExit(
                f"Scenario route duration is {float(scenario_duration):.1f} s, "
                f"but {gpx_path} is {route_duration:.1f} s. Pass the matching route "
                "with --gpx."
            )


def build_cases(base: SensitivityCase) -> list[SensitivityCase]:
    return [
        base,
        SensitivityCase(
            name="cda -0.02",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=max(0.01, base.cda_m2 - 0.02),
            crr=base.crr,
        ),
        SensitivityCase(
            name="cda +0.02",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2 + 0.02,
            crr=base.crr,
        ),
        SensitivityCase(
            name="rider -1 kg",
            rider_mass_kg=max(1.0, base.rider_mass_kg - 1.0),
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
        ),
        SensitivityCase(
            name="rider +1 kg",
            rider_mass_kg=base.rider_mass_kg + 1.0,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
        ),
        SensitivityCase(
            name="crr -0.0005",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=max(0.0001, base.crr - 0.0005),
        ),
        SensitivityCase(
            name="crr +0.0005",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr + 0.0005,
        ),
        SensitivityCase(
            name="protection -0.04",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
            segment_transform=lambda segment: max(
                0.0,
                float(segment["aero_multiplier"]) - (0.04 if segment["type"] != "solo" else 0.0),
            ),
        ),
        SensitivityCase(
            name="protection +0.04",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
            segment_transform=lambda segment: min(
                1.0,
                float(segment["aero_multiplier"]) + (0.04 if segment["type"] != "solo" else 0.0),
            ),
        ),
        SensitivityCase(
            name="moto 5 m",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
            segment_transform=moto_distance_transform(5.0),
        ),
        SensitivityCase(
            name="moto 10 m",
            rider_mass_kg=base.rider_mass_kg,
            bike_mass_kg=base.bike_mass_kg,
            cda_m2=base.cda_m2,
            crr=base.crr,
            segment_transform=moto_distance_transform(10.0),
        ),
    ]


def moto_distance_transform(distance_m: float) -> Callable[[dict], float]:
    def transform(segment: dict) -> float:
        if str(segment["type"]).startswith("moto"):
            return motorcycle_draft_aero_multiplier(distance_m)
        return float(segment["aero_multiplier"])

    return transform


def evaluate_case(gpx_path: Path, scenario: dict, case: SensitivityCase) -> dict:
    return calculate_gui_equivalent_power(gpx_path, scenario, case)


def calculate_gui_equivalent_power(
    gpx_path: Path,
    scenario: dict,
    case: SensitivityCase,
) -> dict:
    route = scenario["route"]
    route_segments = scenario.get("route_segments") or route_segments_from_gpx(gpx_path)
    weather_samples = weather_samples_from_scenario(scenario, gpx_path)
    duration_s = float(route["duration_s"])
    avg_altitude_m = float(route["avg_altitude_m"])
    total_mass = case.rider_mass_kg + case.bike_mass_kg
    standard_total_mass = 60.0 + case.bike_mass_kg

    gravity_work = 0.0
    rolling_work = 0.0
    aero_work = 0.0
    propulsive_work = 0.0
    standard_propulsive_work = 0.0
    headwind_time_sum = 0.0
    air_density_time_sum = 0.0
    weather_weighted_time_s = 0.0

    for route_segment in route_segments:
        elapsed_s = route_segment.get("elapsed_s")
        if elapsed_s is None or float(elapsed_s) <= 0.0:
            continue

        elapsed_s = float(elapsed_s)
        distance_m = float(route_segment["distance_m"])
        road_speed = distance_m / elapsed_s
        sample = nearest_weather_sample(route_segment, weather_samples)
        temperature_c = (
            float(sample["temperature_c"])
            if sample is not None
            else float(scenario["assumptions"].get("temperature_c", 15.0))
        )
        headwind_m_s = 0.0
        if sample is not None:
            headwind_m_s = wind_to_components(
                wind_speed_m_s=float(sample["wind_speed_m_s"]),
                wind_direction_deg=float(sample["wind_direction_deg"]),
                rider_heading_deg=float(route_segment["bearing_deg"]),
            )[0]

        air_speed = max(0.0, road_speed + headwind_m_s)
        segment_altitude = average(
            [
                route_segment.get("start_elevation_m"),
                route_segment.get("end_elevation_m"),
            ]
        )
        rho = air_density_at_altitude_and_temperature(
            segment_altitude if segment_altitude is not None else avg_altitude_m,
            temperature_c,
        )

        weather_weighted_time_s += elapsed_s
        headwind_time_sum += headwind_m_s * elapsed_s
        air_density_time_sum += rho * elapsed_s

        for slice_ in segment_slices(route_segment, scenario["segments"]):
            fraction = slice_["distance_m"] / distance_m
            time_s = elapsed_s * fraction
            elevation_delta_m = float(route_segment.get("elevation_delta_m") or 0.0)
            elevation_change_m = elevation_delta_m * fraction
            aero_multiplier = aero_multiplier_for_segment(slice_["segment"], case)

            gravity_slice = total_mass * G * elevation_change_m
            rolling_slice = case.crr * total_mass * G * slice_["distance_m"]
            aero_slice = (
                0.5
                * rho
                * case.cda_m2
                * aero_multiplier
                * (air_speed**3)
                * time_s
            )
            net_slice = gravity_slice + rolling_slice + aero_slice
            propulsive_slice = max(0.0, net_slice)

            standard_gravity_slice = standard_total_mass * G * elevation_change_m
            standard_rolling_slice = case.crr * standard_total_mass * G * slice_["distance_m"]
            standard_net_slice = standard_gravity_slice + standard_rolling_slice + aero_slice
            standard_propulsive_slice = max(0.0, standard_net_slice)

            gravity_work += gravity_slice
            rolling_work += rolling_slice
            aero_work += aero_slice
            propulsive_work += propulsive_slice
            standard_propulsive_work += standard_propulsive_slice

    total_power = propulsive_work / duration_s
    cp_fraction = cp_remaining_fraction_at_altitude(avg_altitude_m)
    air_density = (
        air_density_time_sum / weather_weighted_time_s
        if weather_weighted_time_s > 0.0
        else air_density_at_altitude_and_temperature(avg_altitude_m, 15.0)
    )

    return {
        "power_gravity_w": gravity_work / duration_s,
        "power_rolling_w": rolling_work / duration_s,
        "power_aero_w": aero_work / duration_s,
        "total_power_w": total_power,
        "watts_per_kg": total_power / case.rider_mass_kg,
        "aslp_w_per_kg": (total_power / cp_fraction) / case.rider_mass_kg,
        "standard60_w_per_kg": (standard_propulsive_work / duration_s) / 60.0,
        "headwind_m_s": (
            headwind_time_sum / weather_weighted_time_s
            if weather_weighted_time_s > 0.0
            else 0.0
        ),
        "air_density_kg_m3": air_density,
    }


def route_segments_from_gpx(gpx_path: Path) -> list[dict]:
    route = parse_gpx(gpx_path)
    return [
        {
            "start_distance_m": start_distance,
            "end_distance_m": start_distance + segment.distance_m,
            "distance_m": segment.distance_m,
            "elevation_delta_m": segment.elevation_delta_m,
            "elapsed_s": segment.elapsed_s,
            "bearing_deg": segment.bearing_deg,
            "start_time": segment.start.time.isoformat() if segment.start.time else None,
            "end_time": segment.end.time.isoformat() if segment.end.time else None,
            "start_elevation_m": segment.start.elevation_m,
            "end_elevation_m": segment.end.elevation_m,
        }
        for start_distance, segment in cumulative_segments(route)
    ]


def cumulative_segments(route) -> list[tuple[float, object]]:
    cumulative = 0.0
    output = []
    for segment in route.segments:
        output.append((cumulative, segment))
        cumulative += segment.distance_m
    return output


def weather_samples_from_scenario(scenario: dict, gpx_path: Path) -> list[dict]:
    samples = scenario.get("weather", {}).get("samples") or []
    if samples:
        return samples

    if gpx_path.resolve() == DEFAULT_GPX_PATH.resolve() and LA_REDOUTE_WEATHER_PATH.exists():
        payload = json.loads(LA_REDOUTE_WEATHER_PATH.read_text(encoding="utf-8"))
        return payload.get("samples", [])

    return []


def nearest_weather_sample(route_segment: dict, samples: list[dict]) -> dict | None:
    if not samples:
        return None

    start_time = parse_time(route_segment.get("start_time"))
    end_time = parse_time(route_segment.get("end_time"))
    if start_time is None or end_time is None:
        return samples[0]

    midpoint = start_time + (end_time - start_time) / 2
    return min(samples, key=lambda sample: abs(parse_time(sample["time"]) - midpoint))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def wind_to_components(
    *,
    wind_speed_m_s: float,
    wind_direction_deg: float,
    rider_heading_deg: float,
) -> tuple[float, float]:
    wind_to_deg = (wind_direction_deg + 180.0) % 360.0
    rel_deg = (wind_to_deg - rider_heading_deg + 360.0) % 360.0
    rel_rad = math.radians(rel_deg)
    along = wind_speed_m_s * math.cos(rel_rad)
    across = wind_speed_m_s * math.sin(rel_rad)
    return -along, abs(across)


def air_density_at_altitude_and_temperature(altitude_m: float, temperature_c: float) -> float:
    altitude_density = RHO0 * math.exp(-max(0.0, altitude_m or 0.0) / SCALE_HEIGHT_M)
    return altitude_density * (STANDARD_TEMP_K / (temperature_c + 273.15))


def segment_slices(route_segment: dict, overlays: list[dict]) -> list[dict]:
    slices = []
    route_start = float(route_segment["start_distance_m"])
    route_end = float(route_segment["end_distance_m"])
    for overlay in overlays:
        start = max(route_start, float(overlay["start_distance_m"]))
        end = min(route_end, float(overlay["end_distance_m"]))
        if end > start:
            slices.append({"distance_m": end - start, "segment": overlay})
    return slices


def aero_multiplier_for_segment(segment: dict, case: SensitivityCase) -> float:
    if case.segment_transform is not None:
        return case.segment_transform(segment)
    return float(segment["aero_multiplier"])


def average(values: list[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def weighted_aero_multiplier(scenario: dict, case: SensitivityCase) -> float:
    weighted_sum = 0.0
    distance_sum = 0.0
    for segment in scenario["segments"]:
        distance = float(segment["end_distance_m"]) - float(segment["start_distance_m"])
        multiplier = (
            case.segment_transform(segment)
            if case.segment_transform is not None
            else float(segment["aero_multiplier"])
        )
        weighted_sum += multiplier * distance
        distance_sum += distance

    return weighted_sum / distance_sum if distance_sum > 0.0 else 0.0


def print_table(rows: list[dict]) -> None:
    columns = [
        ("case", "case", 17),
        ("cda_m2", "CdA", 6),
        ("avg_aero_multiplier", "aero x", 7),
        ("total_power_w", "W", 7),
        ("wkg", "W/kg", 6),
        ("aslp_wkg", "aSLP", 6),
        ("standard60_wkg", "60kg", 6),
        ("aero_power_w", "aero W", 7),
        ("delta_wkg", "dW/kg", 7),
    ]
    header = " ".join(label.ljust(width) for _, label, width in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        values = []
        for key, _, width in columns:
            value = row[key]
            if isinstance(value, str):
                values.append(value[:width].ljust(width))
            else:
                values.append(f"{value:.2f}".rjust(width))
        print(" ".join(values))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
