"""Unit tests for src/features/build_features.py.

These are the project's most important tests: build_features() is the
single shared code path between training and live inference, so a bug
here silently corrupts every prediction. We verify the feature math
(lags, rolling, change rate, cyclical, Family B future shifts) and the
self-containment rule (time columns derived from the index, per-city
grouping so cities never bleed into each other).
"""

import numpy as np
import pandas as pd
import pytest

from src.features.build_features import build_features


def make_frame(n=400, cities=("Karachi", "Lahore")):
    """Synthetic hourly frame: 400 rows x 2 cities, deterministic AQI."""
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    frames = []
    for city in cities:
        base = 50.0 + (25.0 * (ord(city[1]) % 3))  # per-city offset
        aqi = base + 10 * np.sin(np.arange(n) / 12.0) + np.arange(n) % 7
        df = pd.DataFrame(
            {
                "city": city,
                "us_aqi": aqi,
                "pm2_5": aqi * 0.5,
                "temperature_2m": 25 + np.sin(np.arange(n) / 24.0) * 8,
                "wind_speed_10m": 5 + np.random.default_rng(0).random(n) * 10,
            },
            index=idx,
        )
        frames.append(df)
    return pd.concat(frames)


def test_requires_datetime_index():
    df = make_frame().reset_index()  # RangeIndex now
    with pytest.raises(ValueError, match="DatetimeIndex"):
        build_features(df)


def test_does_not_mutate_input():
    df = make_frame()
    original_cols = list(df.columns)
    build_features(df)
    assert list(df.columns) == original_cols


def test_lag_features_are_city_scoped():
    df = make_frame()
    out = build_features(df)
    # Karachi's lag must equal Karachi's own previous row, not Lahore's.
    karachi = out[out["city"] == "Karachi"].sort_index()
    expected = karachi["us_aqi"].shift(1)
    pd.testing.assert_series_equal(
        karachi["aqi_lag_1h"].dropna(), expected.dropna(), check_names=False
    )


def test_lag_24h_and_168h():
    df = make_frame()
    out = build_features(df)
    karachi = out[out["city"] == "Karachi"].sort_index()
    pd.testing.assert_series_equal(
        karachi["aqi_lag_24h"].dropna(),
        karachi["us_aqi"].shift(24).dropna(),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        karachi["aqi_lag_168h"].dropna(),
        karachi["us_aqi"].shift(168).dropna(),
        check_names=False,
    )


def test_rolling_mean_and_max():
    df = make_frame()
    out = build_features(df)
    karachi = out[out["city"] == "Karachi"].sort_index()
    expected_mean = karachi["us_aqi"].rolling(24).mean()
    pd.testing.assert_series_equal(
        karachi["aqi_roll_mean_24h"].dropna(),
        expected_mean.dropna(),
        check_names=False,
    )
    expected_max = karachi["us_aqi"].rolling(24).max()
    pd.testing.assert_series_equal(
        karachi["aqi_roll_max_24h"].dropna(),
        expected_max.dropna(),
        check_names=False,
    )


def test_change_rate_is_difference_from_24h_lag():
    df = make_frame()
    out = build_features(df)
    karachi = out[out["city"] == "Karachi"].sort_index()
    pd.testing.assert_series_equal(
        karachi["aqi_change_rate_24h"].dropna(),
        (karachi["us_aqi"] - karachi["us_aqi"].shift(24)).dropna(),
        check_names=False,
    )


def test_cyclical_encoding_unit_circle():
    df = make_frame(n=48, cities=("Karachi",))
    out = build_features(df)
    # sin^2 + cos^2 == 1 for every row: the encoding preserves the
    # "23:00 is close to 00:00" wrap-around property.
    for col_sin, col_cos in [
        ("hour_sin", "hour_cos"),
        ("month_sin", "month_cos"),
        ("dow_sin", "dow_cos"),
    ]:
        norm = out[col_sin] ** 2 + out[col_cos] ** 2
        assert np.allclose(norm, 1.0, atol=1e-10)


def test_weekend_flag():
    df = make_frame(n=14 * 24, cities=("Karachi",))
    out = build_features(df)
    karachi = out[out["city"] == "Karachi"].sort_index()
    sat = karachi[karachi.index.dayofweek == 5]["is_weekend"]
    sun = karachi[karachi.index.dayofweek == 6]["is_weekend"]
    mon = karachi[karachi.index.dayofweek == 0]["is_weekend"]
    assert (sat == 1).all() and (sun == 1).all() and (mon == 0).all()


def test_family_b_weather_shifted_to_target_timestamp():
    df = make_frame()
    out = build_features(df)
    karachi = out[out["city"] == "Karachi"].sort_index()
    # Row t's temperature_2m_24h must equal the temperature at t+24h.
    pd.testing.assert_series_equal(
        karachi["temperature_2m_24h"].dropna(),
        karachi["temperature_2m"].shift(-24).dropna(),
        check_names=False,
    )


def test_missing_weather_degrades_gracefully():
    # A frame without weather columns: Family B weather is skipped but
    # the function must NOT crash (calendar target features still build).
    df = make_frame()[["city", "us_aqi"]]
    out = build_features(df)
    assert "aqi_lag_1h" in out.columns
    assert not any("temperature" in c for c in out.columns)


def test_feature_names_stable_for_model():
    """The feature set the live frame produces must be a superset of the
    documented core features — a rename here breaks every trained model."""
    df = make_frame()
    out = build_features(df)
    core = [
        "aqi_lag_1h", "aqi_lag_24h", "aqi_lag_168h",
        "aqi_roll_mean_24h", "aqi_roll_max_24h", "aqi_roll_mean_168h",
        "aqi_change_rate_24h",
        "hour_sin", "hour_cos", "month_sin", "month_cos",
        "dow_sin", "dow_cos", "is_weekend",
    ]
    for c in core:
        assert c in out.columns, f"missing core feature {c}"
