from pathlib import Path
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from climbing_performance.api import create_app, performance_payload, route_payload
from climbing_performance.weather import WeatherSample


LA_REDOUTE_GPX = Path(__file__).parents[1] / "data" / "la_redoute.gpx"
REPO_ROOT = Path(__file__).parents[1]


def test_route_payload_contains_profile_data():
    payload = route_payload(LA_REDOUTE_GPX)

    assert payload["id"] == "la-redoute"
    assert payload["name"] == "La Redoute"
    assert payload["distance_m"] > 1000.0
    assert payload["ascent_m"] > 100.0
    assert payload["duration_s"] == pytest.approx(226.0)
    assert len(payload["points"]) > 100
    assert payload["points"][0]["distance_m"] == pytest.approx(0.0)


def test_route_payload_preserves_distance_for_stationary_points(tmp_path):
    gpx_path = tmp_path / "stationary-point.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="60.0000000" lon="22.0000000"><ele>10.0</ele></trkpt>
      <trkpt lat="60.0000000" lon="22.0010000"><ele>11.0</ele></trkpt>
      <trkpt lat="60.0000000" lon="22.0010000"><ele>11.0</ele></trkpt>
      <trkpt lat="60.0000000" lon="22.0020000"><ele>12.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )

    payload = route_payload(gpx_path)
    distances = [point["distance_m"] for point in payload["points"]]

    assert distances[0] == pytest.approx(0.0)
    assert distances[1] > 0.0
    assert distances[2] == pytest.approx(distances[1])
    assert distances[3] > distances[2]


def test_route_payload_uses_gpx_track_name(tmp_path):
    gpx_path = tmp_path / "uploaded-route.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Evening Ride</name>
    <trkseg>
      <trkpt lat="60.0000000" lon="22.0000000"><ele>10.0</ele></trkpt>
      <trkpt lat="60.0000000" lon="22.0010000"><ele>11.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )

    payload = route_payload(gpx_path)

    assert payload["name"] == "Evening Ride"


def test_performance_payload_uses_segment_types():
    route = route_payload(LA_REDOUTE_GPX)
    split = route["distance_m"] - 865.0

    payload = performance_payload(
        {
            "rider": {"mass_kg": 66.0},
            "bike": {
                "mass_kg": 8.0,
                "cda_m2": 0.37,
                "rolling_resistance_coefficient": 0.004,
            },
            "include_weather": False,
            "segments": [
                {
                    "name": "protected-1",
                    "type": "protected",
                    "start_distance_m": 0.0,
                    "end_distance_m": split,
                },
                {
                    "name": "solo-2",
                    "type": "solo",
                    "start_distance_m": split,
                    "end_distance_m": route["distance_m"],
                },
            ],
        },
        LA_REDOUTE_GPX,
    )

    assert payload["summary"]["watts_per_kg"] == pytest.approx(8.68, rel=1e-2)
    assert len(payload["segments"]) == 2
    assert payload["segments"][0]["avg_gradient_percent"] > 0.0


def test_performance_payload_defaults_to_full_route_protected():
    payload = performance_payload(
        {
            "rider": {"mass_kg": 66.0},
            "bike": {
                "mass_kg": 8.0,
                "cda_m2": 0.37,
                "rolling_resistance_coefficient": 0.004,
            },
            "include_weather": False,
        },
        LA_REDOUTE_GPX,
    )

    assert len(payload["segments"]) == 1
    assert payload["segments"][0]["name"] == "drafting"
    assert payload["segments"][0]["distance_m"] == pytest.approx(
        payload["summary"]["route_distance_m"],
    )


def test_performance_payload_accepts_drafting_segment_type():
    route = route_payload(LA_REDOUTE_GPX)

    payload = performance_payload(
        {
            "include_weather": False,
            "segments": [
                {
                    "name": "drafting-1",
                    "type": "drafting",
                    "start_distance_m": 0.0,
                    "end_distance_m": route["distance_m"],
                }
            ],
        },
        LA_REDOUTE_GPX,
    )

    assert payload["segments"][0]["name"] == "drafting-1"
    assert payload["summary"]["total_power_w"] > 0.0


def test_performance_payload_accepts_leader_segment_type():
    route = route_payload(LA_REDOUTE_GPX)

    payload = performance_payload(
        {
            "include_weather": False,
            "segments": [
                {
                    "name": "leader-1",
                    "type": "leader",
                    "start_distance_m": 0.0,
                    "end_distance_m": route["distance_m"],
                }
            ],
        },
        LA_REDOUTE_GPX,
    )

    assert payload["segments"][0]["name"] == "leader-1"
    assert payload["summary"]["total_power_w"] > 0.0


def test_performance_payload_reports_crank_and_etalon_power():
    payload = performance_payload(
        {
            "rider": {"mass_kg": 66.0},
            "bike": {"mass_kg": 8.0, "cda_m2": 0.32},
            "include_weather": False,
            "drivetrain_efficiency": 0.975,
            "segments": [],
        },
        LA_REDOUTE_GPX,
    )

    summary = payload["summary"]
    assert summary["drivetrain_efficiency"] == pytest.approx(0.975)
    assert summary["crank_power_w"] > summary["total_power_w"]
    assert summary["crank_watts_per_kg"] == pytest.approx(
        summary["crank_power_w"] / 66.0
    )
    assert summary["etalon_rider_mass_kg"] == pytest.approx(60.0)
    assert summary["etalon_watts_per_kg"] == pytest.approx(
        summary["etalon_crank_power_w"] / 60.0
    )


def test_fastapi_routes_return_json():
    client = TestClient(create_app(REPO_ROOT))

    route_response = client.get("/api/routes/la-redoute")
    assert route_response.status_code == 200
    route = route_response.json()

    performance_response = client.post(
        "/api/performance",
        json={
            "rider": {"mass_kg": 66.0},
            "bike": {
                "mass_kg": 8.0,
                "cda_m2": 0.37,
                "rolling_resistance_coefficient": 0.004,
            },
            "include_weather": False,
            "segments": [
                {
                    "name": "protected",
                    "type": "protected",
                    "start_distance_m": 0.0,
                    "end_distance_m": route["distance_m"],
                }
            ],
        },
    )

    assert performance_response.status_code == 200
    summary = performance_response.json()["summary"]
    assert summary["watts_per_kg"] == pytest.approx(
        8.46,
        rel=1e-2,
    )
    assert summary["road_speed_km_per_h"] == pytest.approx(23.9, rel=1e-2)


def test_fastapi_accepts_uploaded_gpx_text():
    client = TestClient(create_app(REPO_ROOT))
    gpx_text = LA_REDOUTE_GPX.read_text(encoding="utf-8")

    route_response = client.post(
        "/api/routes/parse",
        json={"gpx_text": gpx_text},
    )
    assert route_response.status_code == 200
    route = route_response.json()

    performance_response = client.post(
        "/api/performance",
        json={
            "gpx_text": gpx_text,
            "include_weather": False,
            "segments": [
                {
                    "name": "protected",
                    "type": "protected",
                    "start_distance_m": 0.0,
                    "end_distance_m": route["distance_m"],
                }
            ],
        },
    )

    assert performance_response.status_code == 200
    payload = performance_response.json()
    assert payload["route"]["distance_m"] == pytest.approx(route["distance_m"])
    assert payload["summary"]["route_distance_m"] == pytest.approx(route["distance_m"])


def test_uploaded_gpx_temperature_override_changes_air_density_and_power():
    gpx_text = LA_REDOUTE_GPX.read_text(encoding="utf-8")
    base_payload = {
        "gpx_text": gpx_text,
        "include_weather": False,
        "segments": [],
    }

    cold = performance_payload({**base_payload, "temperature_c": 0.0}, LA_REDOUTE_GPX)
    warm = performance_payload({**base_payload, "temperature_c": 30.0}, LA_REDOUTE_GPX)

    assert cold["summary"]["air_density_kg_m3"] > warm["summary"]["air_density_kg_m3"]
    assert cold["summary"]["power_aero_w"] > warm["summary"]["power_aero_w"]
    assert cold["summary"]["total_power_w"] > warm["summary"]["total_power_w"]


def test_uploaded_gpx_wind_direction_override_changes_power(monkeypatch):
    def fake_weather_fetcher(
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        *,
        source: str = "auto",
    ) -> list[WeatherSample]:
        return [
            WeatherSample(
                time=datetime(2026, 4, 26, 15, 0, tzinfo=timezone.utc),
                temperature_c=15.0,
                relative_humidity_pct=50.0,
                wind_speed_m_s=5.0,
                wind_direction_deg=0.0,
            )
        ]

    monkeypatch.setattr(
        "climbing_performance.workflow.cached_fetch_hourly_weather",
        fake_weather_fetcher,
    )

    gpx_text = LA_REDOUTE_GPX.read_text(encoding="utf-8")
    base_payload = {
        "gpx_text": gpx_text,
        "include_weather": True,
        "segments": [],
    }

    north = performance_payload(
        {**base_payload, "wind_direction_deg": 0.0},
        LA_REDOUTE_GPX,
    )
    south = performance_payload(
        {**base_payload, "wind_direction_deg": 180.0},
        LA_REDOUTE_GPX,
    )

    assert north["summary"]["weather_wind_direction_deg"] == pytest.approx(0.0)
    assert south["summary"]["weather_wind_direction_deg"] == pytest.approx(180.0)
    assert north["summary"]["raw_headwind_m_s"] != pytest.approx(
        south["summary"]["raw_headwind_m_s"]
    )
    assert north["summary"]["total_power_w"] != pytest.approx(
        south["summary"]["total_power_w"]
    )
