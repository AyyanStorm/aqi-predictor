"""
evaluate.py — evaluation harness and naive baselines (Day 9 deliverable).

Day 9's theme is ML fundamentals: bias/variance, overfitting, and why
time-series CV differs from random CV. This module turns those concepts
into code that every later model (Day 10+) plugs into:

    1. Metrics — RMSE, MAE, R². The exact numbers the report quotes.
    2. Naive baselines — persistence and seasonal naive. Any real model
       must beat these or it is not a model, it is a liability.
    3. walk_forward_evaluate() — scores ANY model function on the SAME
       walk-forward folds, so Day 10's Ridge and Day 12's LightGBM are
       compared apples-to-apples (same folds, same metrics, same code).

Why baselines first (roadmap Section 2 + risk R10):
    "Tomorrow = today" (persistence) is a surprisingly strong forecast
    for air quality. If a fancy model cannot beat it on RMSE, the honest
    conclusion is that AQI is not forecastable with the current features.
    Reporting that honestly is worth more than a suspiciously perfect
    number. Baselines are the floor every model has to clear.

Baseline definitions (hourly data, targets y_h = us_aqi at t + h):
    persistence      : predict us_aqi at t for every horizon h.
                       (the value you know at prediction time)
    seasonal_naive   : predict us_aqi at t + h - 168, i.e. the same hour
                       one week before the TARGET timestamp. 168h because
                       AQI has a strong weekly rhythm (weekend effect);
                       t + h - 168 <= t for all h <= 168, so the value is
                       always known at time t — no leakage.
"""

import numpy as np
import pandas as pd

from src.config import FORECAST_HORIZONS
from src.features.targets import walk_forward_split
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns that hold the true target values (matches targets.py naming).
_TARGET_PREFIX = "y_"


# =========================================================
# 1. METRICS
# =========================================================

def rmse(y_true, y_pred):
    """Root mean squared error. Same units as AQI, sensitive to big misses."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mae(y_true, y_pred):
    """Mean absolute error. Same units as AQI, robust to outliers."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y_true - y_pred)))


def r2(y_true, y_pred):
    """R² = 1 - SS_res/SS_tot. 1.0 = perfect, 0 = no better than the mean."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot == 0:
        return float("nan")
    return float(1.0 - ss_res / ss_tot)


def compute_metrics(y_true, y_pred):
    """All headline metrics in one dict. The report and the dashboard
    (Day 20) both read from here so numbers can never disagree."""
    return {
        "rmse": rmse(y_true, y_pred),
        "mae": mae(y_true, y_pred),
        "r2": r2(y_true, y_pred),
    }


# =========================================================
# 2. NAIVE BASELINES
# =========================================================

def persistence_predictions(df, horizons=None):
    """
    Persistence baseline: for every horizon h, predict the AQI known NOW.

    y_h at row t is us_aqi at t + h. Persistence says "it stays the same":
    prediction = us_aqi at t, i.e. shift(0) per city.

    Returns a DataFrame with one column per horizon, named y_<h>, aligned
    to df.index — the same contract walk_forward_evaluate() expects from
    any model function.
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    preds = pd.DataFrame(index=df.index)
    current = df.groupby("city")["us_aqi"].transform(lambda s: s.shift(0))
    for h in horizons:
        preds[f"{_TARGET_PREFIX}{h}"] = current
    return preds


def seasonal_naive_predictions(df, horizons=None, period_hours=168):
    """
    Seasonal naive baseline: predict the value observed one full period
    before the TARGET timestamp (default period = 1 week = 168h).

    For target y_h at row t (us_aqi at t + h) we need us_aqi at
    t + h - period. With period=168 and h <= 168 the lookback lands at or
    before t, so the value is always available at prediction time — the
    same guarantee the roadmap's leakage rule demands of every feature.

    shift(k) with k = h - period < 0 pulls that past value onto row t,
    per city, so cities never bleed into each other.
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    preds = pd.DataFrame(index=df.index)
    for h in horizons:
        shift = h - period_hours  # negative: look back into the past
        preds[f"{_TARGET_PREFIX}{h}"] = df.groupby("city")["us_aqi"].transform(
            lambda s: s.shift(shift)
        )
    return preds


def evaluate_baselines(df, horizons=None):
    """
    Score both naive baselines against the real targets and return a tidy
    results table: one row per (baseline, horizon) with rmse/mae/r2.

    This is the number every future model must beat. Run it once, print
    the table, and keep it in the notebook as the reference floor.
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    target_cols = [f"{_TARGET_PREFIX}{h}" for h in horizons]

    missing = [c for c in target_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing target columns {missing} — run add_targets() first "
            f"(see src/features/targets.py)."
        )

    baselines = {
        "persistence": persistence_predictions(df, horizons),
        "seasonal_naive": seasonal_naive_predictions(df, horizons),
    }

    rows = []
    for name, preds in baselines.items():
        for h in horizons:
            col = f"{_TARGET_PREFIX}{h}"
            # Drop rows where either the target or the prediction is NaN
            # (warm-up rows at the start of each city's series).
            mask = df[col].notna() & preds[col].notna()
            metrics = compute_metrics(df.loc[mask, col], preds.loc[mask, col])
            rows.append(
                {"baseline": name, "horizon_h": h, "n": int(mask.sum()), **metrics}
            )

    results = pd.DataFrame(rows)
    logger.info(f"Evaluated {len(baselines)} baselines x {len(horizons)} horizons")
    return results


# =========================================================
# 3. WALK-FORWARD HARNESS (for real models, Day 10+)
# =========================================================

def walk_forward_evaluate(df, fit_predict, horizons=None, n_splits=4, gap_hours=None):
    """
    Score ANY model on time-ordered walk-forward folds — never shuffled.

    fit_predict(train_df, valid_df) -> predictions DataFrame
        Train on train_df, predict for valid_df, return a DataFrame with
        one column per horizon (y_24, y_48, y_72) aligned to valid_df.index.
        The harness then compares those predictions to the real targets.

    Why walk-forward and not random K-fold (roadmap Day 9 theme):
        Random CV shuffles the timeline, so a model trained on 2024 rows
        gets to "see" 2023 validation rows through lag features — the
        scores look unrealistically good. Walk-forward trains only on the
        past and validates on the future, exactly like production.

    Returns a DataFrame: one row per (fold, horizon) with rmse/mae/r2 and
    a final 'mean' row per horizon (aggregated across folds).
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    target_cols = [f"{_TARGET_PREFIX}{h}" for h in horizons]

    folds = walk_forward_split(df, horizons=horizons, n_splits=n_splits, gap_hours=gap_hours)
    if not folds:
        raise ValueError("No folds produced — check the data window vs n_splits/gap.")

    rows = []
    for train_df, valid_df, cut in folds:
        preds = fit_predict(train_df, valid_df)
        # Defensive: allow either our y_<h> names or plain horizon ints.
        preds = preds.rename(columns={h: f"{_TARGET_PREFIX}{h}" for h in horizons})
        for h in horizons:
            col = f"{_TARGET_PREFIX}{h}"
            if col not in preds.columns:
                raise ValueError(
                    f"fit_predict() must return a '{col}' column; got {list(preds.columns)}"
                )
            mask = valid_df[col].notna() & preds[col].notna()
            metrics = compute_metrics(valid_df.loc[mask, col], preds.loc[mask, col])
            rows.append(
                {
                    "fold_cut": cut,
                    "horizon_h": h,
                    "n": int(mask.sum()),
                    **metrics,
                }
            )

    results = pd.DataFrame(rows)
    # Aggregate: mean metrics per horizon across folds (the headline number).
    agg = (
        results.groupby("horizon_h")[["rmse", "mae", "r2"]]
        .mean()
        .reset_index()
        .assign(fold_cut="mean")
        .reindex(columns=results.columns)
    )
    out = pd.concat([results, agg], ignore_index=True)
    logger.info(f"Walk-forward evaluation: {len(folds)} folds, {len(horizons)} horizons")
    return out


# =========================================================
# 4. CLI — quick sanity run (python -m src.training.evaluate)
# =========================================================

def _demo_data(n_days=400, cities=None):
    """
    Tiny synthetic hourly AQI series so the harness can be smoke-tested
    anywhere, even without the Feature Store. NOT for real conclusions —
    it exists so `python -m src.training.evaluate` runs on a fresh clone.
    """
    if cities is None:
        cities = ["Karachi", "Lahore"]
    rng = np.random.default_rng(42)
    idx = pd.date_range("2023-01-01", periods=n_days * 24, freq="h")
    frames = []
    for city in cities:
        # weekly seasonality + slow drift + noise, scaled per city
        t = np.arange(len(idx))
        base = 80 + 30 * np.sin(2 * np.pi * t / (24 * 7)) + t / len(t) * 40
        aqi = base + rng.normal(0, 12, len(idx))
        frames.append(
            pd.DataFrame(
                {"city": city, "us_aqi": np.clip(aqi, 10, 400)},
                index=idx,
            )
        )
    return pd.concat(frames).sort_index()


def main():
    """Smoke test: build demo data, add targets, print baseline scores."""
    from src.features.targets import add_targets

    df = _demo_data()
    df = add_targets(df)
    results = evaluate_baselines(df)
    print(results.to_string(index=False))
    print("\n(Run on demo data — load the Feature Store for real numbers.)")


if __name__ == "__main__":
    main()
