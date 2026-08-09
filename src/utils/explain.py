"""
explain.py — Day 20: SHAP explainability + "talking SHAP".

Turns the model's prediction into an ANSWER for a human:

  - per-prediction SHAP values (TreeExplainer — fast and exact for
    LightGBM) for every horizon: which features pushed AQI up, which
    pushed it down, and by how much;
  - a GLOBAL view aggregated from the same run (mean |SHAP| across the
    three horizons) — the "what matters most" ranking;
  - talking SHAP: a natural-language sentence per horizon built from
    the top contributors, e.g.

      "The +24h AQI of 120 is driven up mostly by wind speed at +24h
       (+14), while yesterday's AQI pulls it down (−6)."

Feature names are technical column names (aqi_lag_24h, ...). The
FEATURE_LABELS map turns them into plain English so the sentences and
charts read like a human wrote them.

Pure Python, no Streamlit — reusable by the dashboard AND the report.
The dashboard rendering lives in app/components/explanation.py.
"""

import numpy as np
import pandas as pd
import shap

from src.config import FORECAST_HORIZONS
from src.training.model_registry import ModelRegistry
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------
# Feature name -> plain-English label (for talking SHAP + charts)
# ---------------------------------------------------------------

_HORIZON_SUFFIXES = ("_24h", "_48h", "_72h")

FEATURE_LABELS = {
    # Family A — AQI history
    "aqi_lag_1h": "AQI one hour ago",
    "aqi_lag_24h": "AQI yesterday (same hour)",
    "aqi_lag_168h": "AQI one week ago",
    "aqi_roll_mean_24h": "24-hour average AQI",
    "aqi_roll_max_24h": "24-hour peak AQI",
    "aqi_roll_mean_168h": "7-day average AQI",
    "aqi_change_rate_24h": "AQI change vs 24h ago",
    # Calendar
    "hour_sin": "Time of day",
    "hour_cos": "Time of day",
    "dow_sin": "Day of week",
    "dow_cos": "Day of week",
    "month_sin": "Season (month)",
    "month_cos": "Season (month)",
    "is_weekend": "Weekend",
    # Family B — future weather (shifted to the target timestamp)
    "temperature_2m": "Temperature",
    "wind_speed_10m": "Wind speed",
    "wind_direction_10m": "Wind direction",
    "relative_humidity_2m": "Humidity",
    "surface_pressure": "Pressure",
    "precipitation": "Precipitation",
    "boundary_layer_height": "Mixing layer height",
}

_TOP_N = 5  # how many contributors to name in a sentence


def feature_label(col):
    """Human-readable label for a technical feature column."""
    base, suffix = col, None
    for s in _HORIZON_SUFFIXES:
        if col.endswith(s):
            base, suffix = col[: -len(s)], s
            break
    label = FEATURE_LABELS.get(base, base.replace("_", " ").title())
    if suffix:
        label += f" at +{suffix[1:]}"
    return label


# ---------------------------------------------------------------
# SHAP computation
# ---------------------------------------------------------------

def _load_production_model():
    """The registry's production model set + its metadata entry."""
    reg = ModelRegistry()
    prod = reg.production_entry()
    if prod is None:
        raise SystemExit(
            "No production model in the registry — train and promote one "
            "first: python -m src.training.train --register"
        )
    models, entry = reg.load(prod["name"], prod["version"])
    logger.info(
        f"Loaded production model {entry['name']}_v{entry['version']} for SHAP"
    )
    return models, entry


def explain(result, name=None, version=None):
    """
    SHAP explanation of an inference result, per horizon + global.

    Parameters
    ----------
    result : dict
        Output of src.inference.predict.predict() — must contain
        'features' (the exact feature vector) and 'model' provenance.
    name, version : str | int | None
        Model to explain. None = the production model (the one that
        actually made the prediction).

    Returns
    -------
    dict
        {
          "global":  [(feature, mean_abs_shap), ...] sorted desc,
          "horizons": {
              "24": {"base": float, "prediction": int,
                     "contributors": [(feature, shap_value), ...] sorted desc},
              "48": {...}, "72": {...}
          },
          "labels": {feature: human_label, ...}
        }
    """
    models, entry = _load_production_model() if name is None else _load(name, version)
    feature_cols = entry["feature_cols"]

    # Rebuild the exact prediction row, in the model's column order.
    features = result["features"]
    X = pd.DataFrame([features])[feature_cols]

    horizons = {}
    all_abs = {}
    for h in FORECAST_HORIZONS:
        model = models[h]
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X)[0]  # single-row prediction
        base = float(np.asarray(explainer.expected_value).reshape(-1)[0])

        contributors = sorted(
            zip(feature_cols, sv.tolist()),
            key=lambda t: abs(t[1]),
            reverse=True,
        )
        horizons[str(h)] = {
            "base": round(base, 2),
            "prediction": result["forecast"][str(h)],
            "contributors": [(f, round(v, 3)) for f, v in contributors],
        }
        for f, v in contributors:
            all_abs[f] = all_abs.get(f, 0.0) + abs(v)

    # Global importance = mean |SHAP| across the three horizons.
    n = len(FORECAST_HORIZONS)
    global_importance = sorted(
        ((f, v / n) for f, v in all_abs.items()),
        key=lambda t: t[1],
        reverse=True,
    )

    logger.info(
        "SHAP done: "
        + "; ".join(
            f"+{h}h top={horizons[h]['contributors'][0][0]} "
            f"({horizons[h]['contributors'][0][1]:+.1f})"
            for h in horizons
        )
    )
    return {
        "global": global_importance,
        "horizons": horizons,
        "labels": {f: feature_label(f) for f in feature_cols},
    }


def _load(name, version):
    """Load a specific registered model set (for testing/CLI)."""
    reg = ModelRegistry()
    return reg.load(name, version)


# ---------------------------------------------------------------
# Talking SHAP — natural language
# ---------------------------------------------------------------

def talking_shap(explanation, horizon):
    """
    One natural-language sentence explaining a horizon's forecast.

    Parameters
    ----------
    explanation : dict
        Output of explain().
    horizon : str
        "24", "48" or "72".

    Returns
    -------
    str : e.g.
        "The +24h AQI of 120 is driven up mostly by Wind speed at +24h
         (+14); AQI yesterday (same hour) pulls it down (−6)."
    """
    h = explanation["horizons"][horizon]
    labels = explanation["labels"]

    up = [(f, v) for f, v in h["contributors"] if v > 0][:_TOP_N]
    down = [(f, v) for f, v in h["contributors"] if v < 0][:_TOP_N]

    def _phrase(items):
        return ", ".join(
            f"{labels.get(f, f)} ({v:+.0f})" for f, v in items
        )

    pred = h["prediction"]
    parts = [f"The +{horizon}h AQI of {pred}"]
    if up:
        parts.append(f"is driven up mostly by {_phrase(up)}")
        if down:
            parts.append(f"while {_phrase(down)} pull{'s' if len(down)==1 else ''} it down")
    elif down:
        parts.append(f"is held down by {_phrase(down)}")
    else:
        parts.append("has no dominant feature — it is close to the model baseline")
    sentence = "; ".join(parts) + "."
    return sentence


def talking_all(explanation):
    """One sentence per horizon, keyed by horizon string."""
    return {
        h: talking_shap(explanation, h)
        for h in explanation["horizons"]
    }
