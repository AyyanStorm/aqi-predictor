"""Unit tests for src/utils/aqi_utils.py — EPA bands, colours, messages.

Covers every band boundary (the classic off-by-one trap: 50 is Good,
51 is Moderate), the hazardous threshold, and out-of-range clamping.
"""

import pytest

from src.utils.aqi_utils import (
    aqi_category,
    aqi_color,
    health_message,
    is_hazardous,
)


@pytest.mark.parametrize(
    "aqi,expected",
    [
        (0, "Good"),
        (50, "Good"),        # inclusive upper edge
        (51, "Moderate"),    # exclusive edge flips band
        (100, "Moderate"),
        (101, "Unhealthy for Sensitive Groups"),
        (150, "Unhealthy for Sensitive Groups"),
        (151, "Unhealthy"),
        (200, "Unhealthy"),
        (201, "Very Unhealthy"),
        (300, "Very Unhealthy"),
        (301, "Hazardous"),
        (500, "Hazardous"),
    ],
)
def test_aqi_category_band_boundaries(aqi, expected):
    assert aqi_category(aqi) == expected


def test_aqi_color_matches_epa_palette():
    assert aqi_color(25) == "#00E400"    # Good → green
    assert aqi_color(75) == "#FFFF00"    # Moderate → yellow
    assert aqi_color(125) == "#FF7E00"   # Sensitive → orange
    assert aqi_color(175) == "#FF0000"   # Unhealthy → red
    assert aqi_color(250) == "#8F3F97"   # Very Unhealthy → purple
    assert aqi_color(400) == "#7E0023"   # Hazardous → maroon


def test_health_message_is_present_for_every_band():
    for aqi in [10, 60, 110, 160, 210, 310]:
        msg = health_message(aqi)
        assert isinstance(msg, str) and len(msg) > 20


@pytest.mark.parametrize("aqi", [0, 50, 100, 150])
def test_not_hazardous_below_threshold(aqi):
    assert is_hazardous(aqi) is False


@pytest.mark.parametrize("aqi", [151, 200, 300, 500])
def test_hazardous_at_and_above_threshold(aqi):
    assert is_hazardous(aqi) is True


def test_out_of_range_values_clamp_to_nearest_band():
    # Defensive path: values outside 0-500 clamp instead of crashing.
    assert aqi_category(-5) == "Good"
    assert aqi_category(999) == "Hazardous"
    assert aqi_color(-5) == "#00E400"
    assert aqi_color(999) == "#7E0023"
