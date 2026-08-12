"""
accuracy.py — prediction vs actual evaluation (pure Python, no Streamlit).

Implements the grill-me decisions:
  - Option C formula: per-horizon MAPE-based accuracy
        accuracy = max(0, 100 - |pred - actual| / max(actual, 1) * 100)
    headline "Average Prediction Accuracy", plus ±15 AQI tolerance
    hit-rate and EPA category-match % as supporting stats.
  - Actuals are fetched RETROACTIVELY from Open-Meteo's air-quality API
    (it returns observed hourly us_aqi for past dates) at view time —
    no background collection. Missing data is handled gracefully:
    horizons without an observed value are skipped, never crash.
  - Timestamps: base_ts + 24/48/72h (absolute elapsed hours), converted
    to the city's IANA timezone for display. Nothing hardcoded.
"""

import pandas as pd

from src.config import AIR_QUALITY_URL
from src.data_ingestion.open_meteo_client import fetch_air_quality
from src.utils.aqi_utils import aqi_category
from src.utils.logger import get_logger

logger = get_logger(__name__)

HORIZONS = [24, 48, 72]
# "Close enough" tolerance: EPA bands are ~50 AQI wide, so ±15 means the
# prediction landed in the same ballpark (grill-me option C).
TOLERANCE = 15


# ---------------------------------------------------------------
# Record building (from the live prediction result)
# ---------------------------------------------------------------
def build_record(user_id, loc, result):
    """One prediction record dict for the store."""
    base = pd.Timestamp(result["fetched_at"]).floor("h")
    return {
        "user_id": user_id,
        "prediction_id": result.get("prediction_id"),  # filled by caller
        "city": loc.get("name"),
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "timezone": loc.get("timezone"),
        "source": loc.get("source"),
        "created_at": pd.Timestamp.now(tz="UTC"),
        "base_ts": base,
        "current_aqi": int(result["current_aqi"]),
        "pred_24": int(result["forecast"]["24"]),
        "pred_48": int(result["forecast"]["48"]),
        "pred_72": int(result["forecast"]["72"]),
        "model_name": result["model"]["name"],
        "model_version": result["model"]["version"],
    }


def horizon_values(record):
    """[(hours, timestamp_utc, predicted)] for the 3 forecast horizons."""
    base = pd.Timestamp(record["base_ts"])
    out = []
    for h in HORIZONS:
        pred = record.get(f"pred_{h}")
        if pred is None or pd.isna(pred):
            continue
        out.append((h, base + pd.Timedelta(hours=h), int(pred)))
    return out


# ---------------------------------------------------------------
# Actual AQI (retroactive from Open-Meteo)
# ---------------------------------------------------------------
def fetch_actuals(lat, lon, base_ts, end_ts):
    """
    Observed hourly us_aqi for [base_ts - 1h, end_ts] from Open-Meteo.

    Returns a DataFrame with 'date' (UTC-aware, hourly) and 'us_aqi'.
    Empty DataFrame when nothing is available yet or the fetch fails.
    """
    end_ts = min(pd.Timestamp(end_ts), pd.Timestamp.now(tz="UTC"))
    start = (pd.Timestamp(base_ts) - pd.Timedelta(hours=1))
    if end_ts <= start:
        return pd.DataFrame(columns=["date", "us_aqi"])
    try:
        df = fetch_air_quality(
            lat, lon,
            start.strftime("%Y-%m-%d"),
            end_ts.strftime("%Y-%m-%d"),
            AIR_QUALITY_URL,
        )
    except Exception as e:
        logger.warning(f"fetch_actuals failed for ({lat}, {lon}): {e}")
        return pd.DataFrame(columns=["date", "us_aqi"])
    if df is None or df.empty or "us_aqi" not in df.columns:
        return pd.DataFrame(columns=["date", "us_aqi"])
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "us_aqi": pd.to_numeric(df["us_aqi"], errors="coerce"),
    }).dropna(subset=["us_aqi"])
    if out["date"].dt.tz is None:
        out["date"] = out["date"].dt.tz_localize("UTC")
    return out


def actual_at(df, ts):
    """Observed us_aqi at the exact hour of ts (UTC), or None if missing."""
    if df is None or df.empty:
        return None
    match = df.loc[df["date"] == pd.Timestamp(ts).floor("h"), "us_aqi"]
    if match.empty:
        return None
    return float(match.iloc[0])


# ---------------------------------------------------------------
# Evaluation (Option C)
# ---------------------------------------------------------------
def evaluate_horizon(pred, actual):
    """
    One horizon's metrics. Returns None when actual is missing (handled
    gracefully — the horizon just doesn't count).
    """
    if actual is None or pd.isna(actual):
        return None
    actual = float(actual)
    denom = max(actual, 1.0)
    mape_acc = max(0.0, 100.0 - abs(pred - actual) / denom * 100.0)
    return {
        "predicted": pred,
        "actual": round(actual, 1),
        "accuracy_mape": round(mape_acc, 2),     # headline (Option C)
        "within_tolerance": abs(pred - actual) <= TOLERANCE,
        "category_match": aqi_category(pred) == aqi_category(actual),
    }


def evaluate_record(record, actuals_df):
    """
    Evaluate every horizon of one prediction record against observed
    AQI. Returns (results, horizon_ts):
      results: list of dicts (evaluated horizons only)
      horizon_ts: {h: ts_utc} for charting
    """
    ts = {h: pd.Timestamp(record["base_ts"]) + pd.Timedelta(hours=h)
          for h, _, _ in horizon_values(record)}
    results = []
    for h, ts_utc, pred in horizon_values(record):
        actual = actual_at(actuals_df, ts_utc)
        r = evaluate_horizon(pred, actual)
        if r is not None:
            r["horizon"] = h
            r["ts_utc"] = ts_utc
            results.append(r)
    return results, ts


# ---------------------------------------------------------------
# Aggregation across the user's tracked predictions
# ---------------------------------------------------------------
def summarize(evaluated_rows):
    """
    Aggregate Option-C stats over all evaluated horizon-level rows.

    evaluated_rows: list of dicts from evaluate_horizon + horizon/ts.
    Returns a dict with headline accuracy, hit-rate, category-match and
    supporting counts, or None when there is nothing evaluated yet.
    """
    if not evaluated_rows:
        return None
    n = len(evaluated_rows)
    return {
        "n_horizons": n,
        "avg_accuracy": round(sum(r["accuracy_mape"] for r in evaluated_rows) / n, 2),
        "hit_rate": round(sum(r["within_tolerance"] for r in evaluated_rows) / n * 100, 1),
        "category_rate": round(sum(r["category_match"] for r in evaluated_rows) / n * 100, 1),
        "n_correct": sum(r["within_tolerance"] for r in evaluated_rows),
    }
