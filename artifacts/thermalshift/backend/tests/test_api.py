import csv
import hashlib
import io

import rfc8785
from fastapi.testclient import TestClient
import pytest

import main


client = TestClient(main.app)
CSV_HEADERS = [
    "hour",
    "baseline_kwh",
    "tariff_per_kwh",
    "grid_kgco2_per_kwh",
    "ambient_heat_gain_c",
]


def make_csv(hours=range(24), headers=None, overrides=None, short_row_hour=None):
    headers = headers or CSV_HEADERS
    overrides = overrides or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for hour in hours:
        row = {
            "hour": hour,
            "baseline_kwh": round(0.7 + 0.01 * hour, 3),
            "tariff_per_kwh": round(4 + (hour % 5) * 0.25, 2),
            "grid_kgco2_per_kwh": round(0.4 + (hour % 4) * 0.05, 2),
            "ambient_heat_gain_c": 0.1,
        }
        row.update(overrides.get(hour, {}))
        values = [row.get(header, "") for header in headers]
        if hour == short_row_hour:
            values = values[:-1]
        writer.writerow(values)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("csv_text", "expected_detail"),
    [
        ("", "String should have at least 1 character"),
        (make_csv(headers=CSV_HEADERS[:-1]), "missing required columns"),
        (make_csv(hours=range(23)), "exactly 24 hourly records"),
        (make_csv(hours=[0, 0, *range(2, 24)]), "duplicate hour 0"),
        (
            make_csv(overrides={4: {"tariff_per_kwh": "not-a-number"}}),
            "must be numeric",
        ),
        (
            make_csv(overrides={4: {"grid_kgco2_per_kwh": "Infinity"}}),
            "must be finite",
        ),
        (
            make_csv(overrides={4: {"baseline_kwh": -0.1}}),
            "must be non-negative",
        ),
        (
            make_csv(headers=CSV_HEADERS + ["baseline_kwh"]),
            "duplicate column headers",
        ),
        (
            make_csv(short_row_hour=4),
            "has 4 fields; expected 5",
        ),
    ],
)
def test_malformed_csv_is_rejected(csv_text, expected_detail):
    response = client.post("/api/import-csv", json={"csv_text": csv_text})

    assert response.status_code == 422
    detail = response.json()["detail"]
    detail_text = (
        " ".join(item["msg"] for item in detail)
        if isinstance(detail, list)
        else detail
    )
    assert expected_detail in detail_text


def test_csv_import_sorts_hours_and_preserves_scenario_constraints():
    base_scenario = main.demo_scenario().model_dump()
    base_scenario["min_temp_c"] = 1.5
    base_scenario["max_temp_c"] = 4.5
    response = client.post(
        "/api/import-csv",
        json={
            "csv_text": make_csv(hours=reversed(range(24))),
            "scenario": base_scenario,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["record_count"] == 24
    assert body["scenario"]["baseline_kwh"] == [
        round(0.7 + 0.01 * hour, 3) for hour in range(24)
    ]
    assert body["scenario"]["min_temp_c"] == 1.5
    assert body["scenario"]["max_temp_c"] == 4.5


def test_infeasible_schedule_is_returned_without_claiming_success():
    scenario = main.demo_scenario().model_dump()
    scenario["max_cooling_kwh_per_hour"] = 0.0
    response = client.post("/api/optimize", json={"scenario": scenario})

    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is False
    assert "temperature bounds and cooling capacity" in body["message"]


def test_optimized_temperatures_stay_within_configured_limits_and_energy_budget():
    scenario = main.demo_scenario().model_dump()
    scenario["min_temp_c"] = 2.3
    scenario["max_temp_c"] = 4.0
    response = client.post("/api/optimize", json={"scenario": scenario})

    assert response.status_code == 200
    report = response.json()
    assert report["feasible"] is True
    assert report["temperature_check"]["within_configured_limits"] is True
    assert all(
        2.3 - 1e-6 <= row["optimized_temp_c"] <= 4.0 + 1e-6
        for row in report["hourly"]
    )
    assert report["optimized"]["energy_kwh"] == pytest.approx(
        report["baseline"]["energy_kwh"], abs=1e-5
    )


def test_report_hash_verifies_and_tampering_is_detected():
    optimized = client.post(
        "/api/optimize",
        json={"scenario": main.demo_scenario().model_dump()},
    )
    assert optimized.status_code == 200
    response_report = optimized.json()
    report = {
        key: value
        for key, value in response_report.items()
        if key != "evidence"
    }

    valid = client.post(
        "/api/verify-hash",
        json={
            "report": report,
            "report_hash": response_report["evidence"]["report_hash"],
        },
    )
    assert valid.status_code == 200
    assert valid.json()["valid"] is True

    tampered_report = {**report, "scenario": "modified after hashing"}
    tampered = client.post(
        "/api/verify-hash",
        json={
            "report": tampered_report,
            "report_hash": response_report["evidence"]["report_hash"],
        },
    )
    assert tampered.status_code == 200
    assert tampered.json()["valid"] is False


def test_hash_canonicalization_accepts_javascript_integer_serialization():
    report_hash = hashlib.sha256(rfc8785.dumps({"value": 1.0})).hexdigest()
    response = client.post(
        "/api/verify-hash",
        json={"report": {"value": 1}, "report_hash": report_hash},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
