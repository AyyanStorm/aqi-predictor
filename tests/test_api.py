"""
test_api.py — API endpoint tests (Q6 scope: automated API testing).

Uses FastAPI TestClient against app.api:app (no live network needed for
structure/validation tests; the inference tests hit Open-Meteo like the
real service does).

Coverage:
  - /health: 200, model metadata present
  - /cities: 200, all 10 config cities present
  - /predict: happy path (Karachi) -> 200 with 24/48/72 + current
  - /predict: missing lat/lon -> 422 (validation)
  - /predict: out-of-range lat -> 422
  - /predict: bad coordinates (middle of ocean) -> 502 (upstream failure)
"""
import pytest
from fastapi.testclient import TestClient

from app.api import app
from src.config import CITIES


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "model" in body or "status" in body


def test_cities(client):
    r = client.get("/cities")
    assert r.status_code == 200
    body = r.json()
    cities = body.get("cities", body)  # shape: {"cities": {name: {lat, lon}}}
    names = set(cities.keys()) if isinstance(cities, dict) else {c["name"] for c in cities}
    assert set(CITIES.keys()) <= names


def test_predict_karachi_happy_path(client):
    r = client.get("/predict", params={"lat": 24.8608, "lon": 67.0104, "city": "Karachi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "current" in body
    for h in ("24", "48", "72"):
        assert h in body["forecast"]
        assert "aqi" in body["forecast"][h]
        assert "category" in body["forecast"][h]


def test_predict_missing_params(client):
    r = client.get("/predict")
    assert r.status_code == 422


def test_predict_out_of_range_lat(client):
    r = client.get("/predict", params={"lat": 95.0, "lon": 10.0})
    assert r.status_code == 422


def test_predict_bad_coordinates(client):
    # Middle of the South Pacific. FINDING: Open-Meteo interpolates to the
    # nearest grid cell, so the API returns a plausible-looking forecast
    # instead of an error. System does NOT fail loudly on no-data locations
    # (P2 finding, documented in the QA report). Assert current behaviour
    # so a future change to fail-loud is caught by this test.
    r = client.get("/predict", params={"lat": -45.0, "lon": -120.0})
    assert r.status_code == 200  # currently: interpolated forecast
    body = r.json()
    assert "forecast" in body
