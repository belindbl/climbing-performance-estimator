from __future__ import annotations

import pytest

from climbing_performance.gpx_compare import (
    compare_segment_payload,
    comparison_load_payload,
    distance_grid,
    load_gpx_text,
    segment_stats,
)


def gpx_text(name: str, times: list[str]) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>{name}</name>
    <trkseg>
      <trkpt lat="50.0000" lon="5.0000"><ele>100</ele><time>{times[0]}</time></trkpt>
      <trkpt lat="50.0000" lon="5.0010"><ele>110</ele><time>{times[1]}</time></trkpt>
      <trkpt lat="50.0000" lon="5.0020"><ele>120</ele><time>{times[2]}</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


FAST_GPX = gpx_text(
    "Fast",
    [
        "2026-07-14T10:00:00Z",
        "2026-07-14T10:00:10Z",
        "2026-07-14T10:00:20Z",
    ],
)
SLOW_GPX = gpx_text(
    "Slow",
    [
        "2026-07-14T10:00:00Z",
        "2026-07-14T10:00:12Z",
        "2026-07-14T10:00:24Z",
    ],
)
LEADING_POINT_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>Leading Point</name>
    <trkseg>
      <trkpt lat="50.0000" lon="4.9990"><ele>90</ele><time>2026-07-14T09:59:50Z</time></trkpt>
      <trkpt lat="50.0000" lon="5.0000"><ele>100</ele><time>2026-07-14T10:00:00Z</time></trkpt>
      <trkpt lat="50.0000" lon="5.0010"><ele>110</ele><time>2026-07-14T10:00:08Z</time></trkpt>
      <trkpt lat="50.0000" lon="5.0020"><ele>120</ele><time>2026-07-14T10:00:16Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def test_load_gpx_text_returns_track_with_distance_and_name():
    track = load_gpx_text(FAST_GPX, name="fast-test.gpx", rider_mass_kg=61.5)

    assert track.name == "fast test"
    assert track.rider_mass_kg == pytest.approx(61.5)
    assert track.route.distance_m > 100.0
    assert track.route.ascent_m == pytest.approx(20.0)


def test_segment_stats_interpolates_selected_distance_window():
    track = load_gpx_text(FAST_GPX)
    start = track.route.distance_m * 0.25
    end = track.route.distance_m * 0.75

    stats = segment_stats(track.route, start, end)

    assert stats.distance_m == pytest.approx(track.route.distance_m * 0.5)
    assert stats.elapsed_s == pytest.approx(10.0)
    assert stats.ascent_m == pytest.approx(10.0)
    assert stats.elevation_delta_m == pytest.approx(10.0)


def test_compare_segment_payload_reports_relative_gaps_and_power():
    load_payload = comparison_load_payload(
        {
            "tracks": [
                {"name": "fast.gpx", "gpx_text": FAST_GPX, "rider_mass_kg": 60},
                {"name": "slow.gpx", "gpx_text": SLOW_GPX, "rider_mass_kg": 60},
            ]
        }
    )
    common_distance = load_payload["common_distance_m"]

    result = compare_segment_payload(
        {
            "tracks": [
                {"name": "fast.gpx", "gpx_text": FAST_GPX, "rider_mass_kg": 60},
                {"name": "slow.gpx", "gpx_text": SLOW_GPX, "rider_mass_kg": 60},
            ],
            "reference_index": 0,
            "start_distance_m": 0,
            "end_distance_m": common_distance,
            "distance_step_m": common_distance,
            "assumptions": {
                "bike_mass_kg": 8,
                "cda_m2": 0.33,
                "crr": 0.004,
                "reference_weather": {
                    "temperature_c": 15.0,
                    "surface_pressure_hpa": 1013.25,
                    "relative_humidity_pct": 50.0,
                },
            },
        }
    )

    fast, slow = result["tracks"]
    assert fast["segment"]["elapsed_s"] == pytest.approx(20.0)
    assert slow["segment"]["elapsed_s"] == pytest.approx(24.0)
    assert slow["elapsed_gap_s"] == pytest.approx(4.0)
    assert slow["metrics"]["total_power_w"] > 0.0
    assert slow["metrics"]["standard_60kg_w_per_kg"] > 0.0
    assert result["gap_samples"][1]["samples"][-1]["gap_s"] == pytest.approx(4.0)


def test_location_sync_maps_reference_locations_to_each_track_route():
    load_payload = comparison_load_payload(
        {
            "tracks": [
                {"name": "fast.gpx", "gpx_text": FAST_GPX, "rider_mass_kg": 60},
                {
                    "name": "leading.gpx",
                    "gpx_text": LEADING_POINT_GPX,
                    "rider_mass_kg": 60,
                },
            ]
        }
    )
    common_distance = load_payload["common_distance_m"]

    distance_result = compare_segment_payload(
        {
            "tracks": [
                {"name": "fast.gpx", "gpx_text": FAST_GPX, "rider_mass_kg": 60},
                {
                    "name": "leading.gpx",
                    "gpx_text": LEADING_POINT_GPX,
                    "rider_mass_kg": 60,
                },
            ],
            "reference_index": 0,
            "start_distance_m": 0,
            "end_distance_m": common_distance,
            "sync_mode": "distance",
            "assumptions": {"reference_weather": {
                "temperature_c": 15.0,
                "surface_pressure_hpa": 1013.25,
                "relative_humidity_pct": 50.0,
            }},
        }
    )
    location_result = compare_segment_payload(
        {
            "tracks": [
                {"name": "fast.gpx", "gpx_text": FAST_GPX, "rider_mass_kg": 60},
                {
                    "name": "leading.gpx",
                    "gpx_text": LEADING_POINT_GPX,
                    "rider_mass_kg": 60,
                },
            ],
            "reference_index": 0,
            "start_distance_m": 0,
            "end_distance_m": common_distance,
            "sync_mode": "location",
            "assumptions": {"reference_weather": {
                "temperature_c": 15.0,
                "surface_pressure_hpa": 1013.25,
                "relative_humidity_pct": 50.0,
            }},
        }
    )

    distance_track = distance_result["tracks"][1]
    location_track = location_result["tracks"][1]
    assert location_result["sync_mode"] == "location"
    assert location_track["mapping"]["start_distance_m"] > 50.0
    assert location_track["mapping"]["end_distance_m"] > distance_track["mapping"]["end_distance_m"]
    assert location_track["segment"]["elapsed_s"] == pytest.approx(16.0)
    assert distance_track["segment"]["elapsed_s"] != pytest.approx(
        location_track["segment"]["elapsed_s"]
    )
    assert location_result["gap_samples"][1]["samples"][-1]["track_distance_m"] == pytest.approx(
        location_track["mapping"]["end_distance_m"]
    )


def test_distance_grid_includes_exact_end_distance():
    assert distance_grid(0.0, 12.0, step_m=5.0) == [0.0, 5.0, 10.0, 12.0]
