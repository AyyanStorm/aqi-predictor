"""Unit tests for src/inference/predict.py — the serving pipeline.

The network fetch and the model registry are mocked: these tests verify
the CONTRACT of predict() (structure, clamping, error modes), not the
live upstream. The live end-to-end path is covered by the deployment
smoke tests (API /predict on Render).
"""

import numpy as np
import pandas as pd
import pytest

import src.inference.predict as predict_mod
from src.inference.predict import predict


class FakeModel:
    """Minimal stand-in for a fitted sklearn/LightGBM regressor."""

    def __init__(self, value):
        self._value = value

    def predict(self, X):
        return np.array([self._value])


def make_entry(feature_cols):
    return {
        "name": "lgbm",
        "version": 6,
        "artifact": "lgbm_v6.joblib",
        "mean_rmse": 24.07,
        "feature_cols": feature_cols,
    }


def make_live_frame(feature_cols):
    """A frame shaped like fetch_live_frame()'s output: history + future.

    History rows carry us_aqi; future rows carry weather only (AQI NaN)
    so the Family B negative shifts have values at the prediction row.
    """
    n = 300
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "city": "Karachi",
            "us_aqi": 50 + np.arange(n) % 20,
            "temperature_2m": 25 + np.sin(np.arange(n) / 24) * 5,
            "wind_speed_10m": np.full(n, 6.0),
        },
        index=idx,
    )
    # Rows beyond the last observed AQI are forecast-only.
    observed_until = n - 100
    df.loc[idx[observed_until + 1:], "us_aqi"] = np.nan
    return df


@pytest.fixture(autouse=True)
def _mock_network_and_registry(monkeypatch):
    """Route predict()'s two external dependencies to fakes."""
    feature_cols = [
        "us_aqi", "aqi_lag_1h", "temperature_2m_24h", "hour_sin",
    ]
    models = {24: FakeModel(71), 48: FakeModel(73), 72: FakeModel(76)}
    entry = make_entry(feature_cols)

    class FakeRegistry:
        def production_entry(self):
            return {"name": "lgbm", "version": 6}

        def load(self, name, version):
            return models, entry

    def fake_fetch(lat, lon, city="inference"):
        df = make_live_frame(feature_cols)
        from src.features.build_features import build_features

        df = build_features(df)
        observed = df["us_aqi"].notna()
        now_ts = df.index[observed][-1]
        return df, now_ts

    monkeypatch.setattr(predict_mod, "ModelRegistry", FakeRegistry)
    monkeypatch.setattr(predict_mod, "fetch_live_frame", fake_fetch)


def test_predict_returns_full_contract():
    result = predict(24.86, 67.01, city="Karachi")
    assert result["location"] == {"lat": 24.86, "lon": 67.01, "city": "Karachi"}
    assert result["current_aqi"] > 0
    assert result["model"]["name"] == "lgbm"
    assert result["model"]["version"] == 6
    assert set(result["forecast"].keys()) == {"24", "48", "72"}
    assert all(isinstance(v, int) for v in result["forecast"].values())
    assert "features" in result and isinstance(result["features"], dict)


def test_predict_forecast_values_match_models():
    result = predict(24.86, 67.01)
    assert result["forecast"] == {"24": 71, "48": 73, "72": 76}


def test_predict_clamps_negative_aqi_to_zero(monkeypatch):
    """AQI is never negative — a model output of -5 must clamp to 0."""
    entry = make_entry(["us_aqi", "aqi_lag_1h", "temperature_2m_24h", "hour_sin"])

    class ClampRegistry:
        def production_entry(self):
            return {"name": "lgbm", "version": 6}

        def load(self, name, version):
            models = {24: FakeModel(-5), 48: FakeModel(-2), 72: FakeModel(3)}
            return models, entry

    monkeypatch.setattr(predict_mod, "ModelRegistry", ClampRegistry)
    result = predict(24.86, 67.01)
    assert result["forecast"]["24"] == 0
    assert result["forecast"]["48"] == 0
    assert result["forecast"]["72"] == 3


def test_predict_raises_when_no_production_model(monkeypatch):
    class EmptyRegistry:
        def production_entry(self):
            return None

    monkeypatch.setattr(predict_mod, "ModelRegistry", EmptyRegistry)
    with pytest.raises(SystemExit, match="No production model"):
        predict(24.86, 67.01)


def test_predict_raises_on_training_serving_skew(monkeypatch):
    """A model expecting a column the live frame lacks must fail loudly."""
    entry = make_entry(["us_aqi", "totally_missing_feature"])

    class SkewRegistry:
        def production_entry(self):
            return {"name": "lgbm", "version": 6}

        def load(self, name, version):
            return {24: FakeModel(1), 48: FakeModel(1), 72: FakeModel(1)}, entry

    monkeypatch.setattr(predict_mod, "ModelRegistry", SkewRegistry)
    with pytest.raises(RuntimeError, match="skew"):
        predict(24.86, 67.01)
