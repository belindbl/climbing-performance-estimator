from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from climbing_performance.gpx import GPXRoute, extract_climbs
from climbing_performance.gpx_compare import (
    DEFAULT_BIKE_MASS_KG,
    DEFAULT_CDA_M2,
    DEFAULT_CRR,
    LoadedComparisonTrack,
    compare_loaded_segment,
    load_gpx_file,
)
from climbing_performance.metrics import air_density_from_weather
from climbing_performance.weather import WeatherAPIError
from climbing_performance.workflow import fetch_route_weather_context


@dataclass(frozen=True)
class SelectedSection:
    name: str
    start_distance_m: float
    end_distance_m: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cl-perf",
        description="Estimate cycling performance from GPX files.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    estimate = commands.add_parser(
        "estimate",
        help="estimate detected climbs or a selected section from a ride",
    )
    estimate.add_argument("ride", type=Path, help="the primary rider's GPX file")
    estimate.add_argument("--rider", help="rider name (defaults to the GPX filename)")
    estimate.add_argument(
        "--rider-mass-kg",
        type=positive_float,
        required=True,
        help="rider mass in kg",
    )
    estimate.add_argument(
        "--compare",
        type=Path,
        help="optional comparison GPX; matching sections by GPS location",
    )
    estimate.add_argument("--comparison-rider", help="comparison rider name")
    estimate.add_argument(
        "--comparison-rider-mass-kg",
        type=positive_float,
        help="comparison rider mass in kg (defaults to the primary rider's mass)",
    )
    estimate.add_argument(
        "--climb",
        type=positive_int,
        help="estimate one detected climb by its 1-based index",
    )
    estimate.add_argument(
        "--start-km",
        type=nonnegative_float,
        help="start distance in km; use with --end-km for an exact section",
    )
    estimate.add_argument(
        "--end-km",
        type=positive_float,
        help="end distance in km; use with --start-km for an exact section",
    )
    estimate.add_argument(
        "--full-route",
        action="store_true",
        help="estimate the whole route instead of detected climbs",
    )
    estimate.add_argument(
        "--bike-mass-kg",
        type=positive_float,
        default=DEFAULT_BIKE_MASS_KG,
        help=f"bike mass in kg (default: {DEFAULT_BIKE_MASS_KG:g})",
    )
    estimate.add_argument(
        "--cda-m2",
        type=positive_float,
        default=DEFAULT_CDA_M2,
        help=f"drag area in m² (default: {DEFAULT_CDA_M2:g})",
    )
    estimate.add_argument(
        "--crr",
        type=nonnegative_float,
        default=DEFAULT_CRR,
        help=f"rolling resistance coefficient (default: {DEFAULT_CRR:g})",
    )
    estimate.add_argument("--reference-temperature-c", type=float)
    estimate.add_argument("--reference-pressure-hpa", type=positive_float)
    estimate.add_argument("--reference-humidity-pct", type=percent_float)
    estimate.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        report = estimate(args)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        parser.error(str(exc))

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print_report(report)


def estimate(args: argparse.Namespace) -> dict[str, Any]:
    primary_loaded = load_gpx_file(args.ride, rider_mass_kg=args.rider_mass_kg)
    primary_name = args.rider or args.ride.stem
    primary = LoadedComparisonTrack(
        route=primary_loaded.route,
        name=primary_name,
        rider_mass_kg=args.rider_mass_kg,
    )
    tracks = [primary]

    comparison_path: Path | None = args.compare
    if comparison_path is not None:
        comparison_mass = (
            args.comparison_rider_mass_kg
            if args.comparison_rider_mass_kg is not None
            else args.rider_mass_kg
        )
        comparison_loaded = load_gpx_file(
            comparison_path,
            rider_mass_kg=comparison_mass,
        )
        tracks.append(
            LoadedComparisonTrack(
                route=comparison_loaded.route,
                name=args.comparison_rider or comparison_path.stem,
                rider_mass_kg=comparison_mass,
            )
        )

    reference_values = (
        args.reference_temperature_c,
        args.reference_pressure_hpa,
        args.reference_humidity_pct,
    )
    if any(value is not None for value in reference_values) and not all(
        value is not None for value in reference_values
    ):
        raise ValueError(
            "--reference-temperature-c, --reference-pressure-hpa, and "
            "--reference-humidity-pct must be supplied together."
        )
    reference_density = (
        air_density_from_weather(
            temperature_c=args.reference_temperature_c,
            pressure_hpa=args.reference_pressure_hpa,
            relative_humidity_pct=args.reference_humidity_pct,
        )
        if all(value is not None for value in reference_values)
        else None
    )
    air_densities = []
    density_sources = []
    for track in tracks:
        try:
            sample = fetch_route_weather_context(track.route).sample
            if sample.surface_pressure_hpa is None:
                raise WeatherAPIError("API weather sample lacks surface pressure.")
            density = air_density_from_weather(
                temperature_c=sample.temperature_c,
                pressure_hpa=sample.surface_pressure_hpa,
                relative_humidity_pct=sample.relative_humidity_pct,
            )
            density_sources.append("Open-Meteo")
        except (WeatherAPIError, ValueError, OSError):
            if reference_density is None:
                raise ValueError(
                    "API weather unavailable for air density. Supply all three "
                    "--reference-temperature-c, --reference-pressure-hpa, and "
                    "--reference-humidity-pct options."
                )
            density = reference_density
            density_sources.append("reference weather input")
        air_densities.append(density)

    sections = select_sections(primary.route, args)
    results = []
    for section in sections:
        comparison = compare_loaded_segment(
            tracks,
            reference_index=0,
            sync_mode="location" if comparison_path is not None else "distance",
            start_distance_m=section.start_distance_m,
            end_distance_m=section.end_distance_m,
            bike_mass_kg=args.bike_mass_kg,
            cda_m2=args.cda_m2,
            crr=args.crr,
            air_density_kg_m3_by_track=air_densities,
            include_gap_samples=False,
        )
        results.append(
            {
                "name": section.name,
                "start_distance_m": section.start_distance_m,
                "end_distance_m": section.end_distance_m,
                "comparison": comparison,
            }
        )

    return {
        "ride": str(args.ride),
        "rider": {"name": primary.name, "mass_kg": primary.rider_mass_kg},
        "comparison_ride": (
            {
                "path": str(comparison_path),
                "name": tracks[1].name,
                "mass_kg": tracks[1].rider_mass_kg,
            }
            if comparison_path is not None
            else None
        ),
        "assumptions": {
            "bike_mass_kg": args.bike_mass_kg,
            "cda_m2": args.cda_m2,
            "crr": args.crr,
            "weather_adjustment": False,
            "air_density_kg_m3_by_track": air_densities,
            "air_density_source_by_track": density_sources,
        },
        "sections": results,
    }


def select_sections(route: GPXRoute, args: argparse.Namespace) -> list[SelectedSection]:
    explicit_range = args.start_km is not None or args.end_km is not None
    if explicit_range and (args.start_km is None or args.end_km is None):
        raise ValueError("--start-km and --end-km must be used together.")

    if sum((args.climb is not None, explicit_range, args.full_route)) > 1:
        raise ValueError("Choose only one of --climb, a distance range, or --full-route.")

    if explicit_range:
        return [
            SelectedSection(
                name="Selected section",
                start_distance_m=args.start_km * 1000.0,
                end_distance_m=args.end_km * 1000.0,
            )
        ]

    if args.full_route:
        return [SelectedSection("Full route", 0.0, route.distance_m)]

    climbs = extract_climbs(route)
    if args.climb is not None:
        if args.climb > len(climbs):
            raise ValueError(
                f"Climb {args.climb} does not exist; this route has {len(climbs)} detected climbs."
            )
        climb = climbs[args.climb - 1]
        return [
            SelectedSection(
                name=f"Climb {args.climb}",
                start_distance_m=climb.start_point.distance_m,
                end_distance_m=climb.end_point.distance_m,
            )
        ]

    if climbs:
        return [
            SelectedSection(
                name=f"Climb {index}",
                start_distance_m=climb.start_point.distance_m,
                end_distance_m=climb.end_point.distance_m,
            )
            for index, climb in enumerate(climbs, start=1)
        ]

    return [SelectedSection("Full route", 0.0, route.distance_m)]


def print_report(report: dict[str, Any]) -> None:
    rider = report["rider"]
    print(f"Ride: {report['ride']}")
    print(f"Rider: {rider['name']} ({rider['mass_kg']:.1f} kg)")
    assumptions = report["assumptions"]
    print(
        "Model: "
        f"bike {assumptions['bike_mass_kg']:.1f} kg, "
        f"CdA {assumptions['cda_m2']:.2f} m², "
        f"Crr {assumptions['crr']:.4f}; wind adjustment not included; "
        "air density uses API or reference weather"
    )
    if report["comparison_ride"] is not None:
        comparison = report["comparison_ride"]
        print(
            f"Compared with: {comparison['name']} "
            f"({comparison['mass_kg']:.1f} kg; matched by GPS location)"
        )

    for section in report["sections"]:
        start_km = section["start_distance_m"] / 1000.0
        end_km = section["end_distance_m"] / 1000.0
        print(f"\n{section['name']} ({start_km:.2f}–{end_km:.2f} km)")
        for row in section["comparison"]["tracks"]:
            segment = row["segment"]
            metrics = row["metrics"]
            elapsed = format_duration(segment["elapsed_s"])
            power = format_number(metrics["total_power_w"], " W", digits=0)
            wkg = format_number(metrics["watts_per_kg"], " W/kg", digits=2)
            vam = format_number(segment["vam_m_per_h"], " m/h", digits=0)
            line = (
                f"  {row['name']}: {elapsed}, avg {power}, {wkg}, "
                f"VAM {vam}, {segment['distance_m'] / 1000:.2f} km, "
                f"{segment['ascent_m']:.0f} m ascent"
            )
            if row["index"] > 0:
                line += f", gap {format_delta(row['elapsed_gap_s'])}"
                match_distances = (
                    row["mapping"]["start_match_delta_m"],
                    row["mapping"]["end_match_delta_m"],
                )
                if all(distance is not None for distance in match_distances):
                    line += (
                        ", GPS offset "
                        f"{max(match_distances):.0f} m"
                    )
            print(line)

        if any(
            row["segment"]["elapsed_s"] is None
            for row in section["comparison"]["tracks"]
        ):
            print("  Power estimates require timestamps across the selected section.")


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "no timestamps"
    rounded = round(seconds)
    sign = "-" if rounded < 0 else ""
    minutes, remainder = divmod(abs(rounded), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{sign}{hours:d}:{minutes:02d}:{remainder:02d}"
    return f"{sign}{minutes:d}:{remainder:02d}"


def format_delta(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    if abs(seconds) < 0.5:
        return "0s"
    return f"{seconds:+.0f}s"


def format_number(value: float | None, suffix: str, *, digits: int) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def percent_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return number


if __name__ == "__main__":
    main()
