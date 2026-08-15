"""Tests for the global AQI map data layer (no live network in unit tests)."""

import pandas as pd
import pytest

from app.map_service import (
    GRID_STEP,
    _grid_points,
    nearest_marker,
    haversine_km,
)
from app.components.aqi_map import (
    _band_rgba,
    _heat_color_range,
    _hex_to_rgb,
    _prepare_markers,
)
from src.utils.aqi_utils import AQI_BANDS


# ---------------------------------------------------------------
# Grid geometry
# ---------------------------------------------------------------
def test_grid_points_cover_world():
    pts = _grid_points()
    assert len(pts) > 3000
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    assert min(lats) >= -60 and max(lats) <= 69
    assert min(lons) >= -180 and max(lons) <= 180
    # Spacing matches GRID_STEP.
    assert abs(pts[1][1] - pts[0][1]) == GRID_STEP


def test_haversine():
    # Karachi -> Lahore is roughly 1,000-1,050 km.
    d = haversine_km(24.8608, 67.0104, 31.5497, 74.3436)
    assert 950 < d < 1100


# ---------------------------------------------------------------
# Color mapping (EPA bands -> deck.gl colors)
# ---------------------------------------------------------------
def test_hex_to_rgb():
    assert _hex_to_rgb("#00E400") == [0, 228, 0, 255]
    assert _hex_to_rgb("#FF7E00", alpha=200)[3] == 200


def test_band_rgba_matches_epa():
    for lo, hi, _label, color, _msg in AQI_BANDS:
        sample = lo if lo > 0 else 25
        rgba = _band_rgba(sample)
        assert rgba[:3] == _hex_to_rgb(color)[:3]


def test_heat_color_range_has_six_bands():
    cr = _heat_color_range()
    assert len(cr) == len(AQI_BANDS) == 6
    for stop in cr:
        assert len(stop) == 4


# ---------------------------------------------------------------
# Marker prep
# ---------------------------------------------------------------
def test_prepare_markers_adds_color_and_drops_na():
    df = pd.DataFrame([
        {"name": "A", "lat": 1.0, "lon": 2.0, "aqi": 30},
        {"name": "B", "lat": 3.0, "lon": 4.0, "aqi": None},
    ])
    out = _prepare_markers(df)
    assert len(out) == 1
    assert out.iloc[0]["fill_color"] == _band_rgba(30)


def test_nearest_marker():
    df = pd.DataFrame([
        {"name": "Karachi", "lat": 24.86, "lon": 67.01},
        {"name": "Lahore", "lat": 31.55, "lon": 74.34},
    ])
    near = nearest_marker(24.9, 67.0, df)
    assert near.iloc[0]["name"] == "Karachi"


def test_prepare_markers_empty():
    assert _prepare_markers(None) is None
    assert _prepare_markers(pd.DataFrame()).empty
