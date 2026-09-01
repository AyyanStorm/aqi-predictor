"""
lstm.py — Day 15: LSTM baseline for the model comparison ladder.

The roadmap's model ladder: persistence → seasonal naive → Ridge →
Random Forest → LightGBM → LSTM. Every model so far treats each row
independently: it sees the engineered features of ONE timestamp and
predicts AQI h hours later. An LSTM is the first model that reads a
SEQUENCE of past timestamps and learns temporal dynamics directly —
which is why RNNs are the classic choice for time series.

Why sequences matter (the Day 15 lesson):
    Air quality is a process, not a collection of independent rows. A
    smog episode builds over hours; a dust storm arrives and departs.
    The engineered features (lags, rolling means) try to hand this to
    the tree models as pre-digested numbers. The LSTM instead learns
    its own representation of "what has the atmosphere been doing" from
    the raw sequence of feature vectors. That is the honest reason to
    build it: not because it will win (it almost certainly will NOT beat
    LightGBM on tabular features — the roadmap says so explicitly), but
    because the comparison is the deliverable. The report gets to say:
    "we tried a sequence model, here is the evidence for why the
    gradient-boosted trees still won."

Windowing:
    A sliding window of `window` consecutive hourly rows, one per city
    (sequences NEVER cross a city boundary — that would teach the LSTM
    impossible transitions between cities). Window k = rows
    [k - window + 1 .. k]; the target is y_h at row k (the LAST row of
    the window), so the model sees only the past when predicting the
    future — the same no-leakage rule as the rest of the project.

Honest comparison (the roadmap's rule for every model):
    lstm_fit_predict() implements the exact fit_predict(train_df,
    valid_df) contract that walk_forward_evaluate() (evaluate.py, Day 9)
    expects, so the LSTM is scored on the SAME walk-forward folds, same
    rows, same metrics as Ridge/RF/LightGBM. Apples-to-apples or it
    doesn't count.

Practical notes:
    - Features are STANDARDISED (StandardScaler) before the LSTM — neural
      nets are NOT scale-invariant like trees; a feature measured in the
      hundreds (surface_pressure) would otherwise dwarf one measured in
      single digits (precipitation). The scaler is fit on TRAINING rows
      only, never on validation rows (no leakage).
    - NaN policy identical to the other models: rows with missing features
      or targets are dropped honestly, never imputed. Windows that would
      cross a gap are discarded.
    - Defaults are deliberately small (window=24h, 32 units, 10 epochs)
      so a full run stays within an evening session on a laptop. The
      LSTM is a baseline for comparison, not the serving model — it is
      therefore NOT wired into --register (the registry serves the
      production model, which is LightGBM unless evidence says otherwise).
    - Keras 3 runs on the torch backend (KERAS_BACKEND=torch), so no
      TensorFlow install is needed.
"""

import os

# Keras 3 is backend-agnostic; torch is already in requirements and is
# far lighter than TensorFlow. Set BEFORE importing keras.
os.environ.setdefault("KERAS_BACKEND", "torch")

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from typing import Tuple

from src.config import FORECAST_HORIZONS
from src.training.train import select_features
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TARGET_PREFIX = "y_"


# =========================================================
# 1. WINDOWING — turn rows into sequences (per city)
# =========================================================

def _city_windows(city_df: pd.DataFrame, feature_cols: list[str], target_col: str, window: int) -> tuple:
    """
    Build (X, y) sequences for ONE city's sorted rows.

    A window is `window` consecutive feature rows; the target is y_h at
    the LAST row of the window. Rows with NaN features or target are
    dropped FIRST (same honest policy as train.py), then windows are cut
    over the remaining rows — so windows never bridge a missing gap.

    Returns
    -------
    (np.ndarray (n, window, F), np.ndarray (n,), np.ndarray (n,))
        X, y, and the timestamp of each window's LAST row (used to map
        predictions back onto the evaluation frame).
    """
    clean = city_df[[*feature_cols, target_col]].dropna()
    if len(clean) < window:
        return None, None, None

    feats = clean[feature_cols].to_numpy(dtype=float)
    target = clean[target_col].to_numpy(dtype=float)
    times = clean.index.to_numpy()

    n = len(clean) - window + 1
    # Sliding window via stride tricks: window i is rows i..i+window-1.
    X = np.lib.stride_tricks.sliding_window_view(feats, window, axis=0)
    X = np.ascontiguousarray(X.transpose(0, 2, 1))  # (n, window, F)
    y = target[window - 1:]
    t = times[window - 1:]
    return X, y, t


# =========================================================
# 2. TRAINING — one LSTM per horizon
# =========================================================

def train_lstm_models(train_df: pd.DataFrame, feature_cols: list[str] | None = None, window: int = 24, units: int = 32,
                      epochs: int = 10, batch_size: int = 256, learning_rate: float = 1e-3,
                      verbose: int = 0, random_state: int = 42) -> tuple:
    """
    Fit one LSTM per forecast horizon on windowed sequences.

    Parameters (all with sane laptop-friendly defaults):
        window        hours of history per sequence (default 24 = one day)
        units         LSTM hidden size (default 32 — small but enough to
                      beat naive baselines; the point is comparison)
        epochs        training epochs (default 10)
        batch_size    training batch size
        learning_rate Adam learning rate

    Returns
    -------
    (dict[int, model], StandardScaler)
        {horizon: trained Keras model} and the scaler fit on TRAIN rows
        (the predictor must reuse it for validation — never refit).
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)

    # Standardise features on TRAIN rows only. Trees are scale-invariant;
    # neural nets are not — without this, surface_pressure (~1000) would
    # dominate precipitation (~0-10) for no modelling reason.
    scaler = StandardScaler()
    all_feats = train_df[feature_cols].dropna().to_numpy(dtype=float)
    scaler.fit(all_feats)

    models = {}
    for h in FORECAST_HORIZONS:
        target_col = f"{_TARGET_PREFIX}{h}"
        X_h, y_h = [], []
        for city, city_df in train_df.groupby("city"):
            Xc, yc, _ = _city_windows(city_df, feature_cols, target_col, window)
            if Xc is None:
                logger.debug(f"City '{city}': fewer than {window} complete "
                               f"rows for horizon {h}h — skipped")
                continue
            # Scale window features with the TRAIN-fitted scaler.
            X_h.append(scaler.transform(Xc.reshape(-1, len(feature_cols)))
                       .reshape(Xc.shape))
            y_h.append(yc)
        if not X_h:
            raise ValueError(f"No complete windows for horizon {h}h — check "
                             f"data window vs LSTM `window` size.")

        X = np.concatenate(X_h, axis=0)
        y = np.concatenate(y_h, axis=0)

        model = _build_lstm(window, len(feature_cols), units, learning_rate,
                            random_state=random_state)
        model.fit(X, y, epochs=epochs, batch_size=batch_size, verbose=verbose)
        models[h] = model
        logger.info(f"Horizon {h}h: LSTM(window={window}, units={units}, "
                    f"epochs={epochs}) on {len(X)} sequences x "
                    f"{len(feature_cols)} features")

    return models, scaler


def _build_lstm(window: int, n_features: int, units: int, learning_rate: float, random_state: int = 42):
    """A single-layer LSTM with a linear output head (regression)."""
    import keras
    from keras import layers

    keras.utils.set_random_seed(random_state)  # reproducible runs

    model = keras.Sequential(
        [
            layers.Input(shape=(window, n_features)),
            layers.LSTM(units, activation="tanh"),
            layers.Dense(1),  # linear output: regression, not classification
        ]
    )
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="mse",
    )
    return model


# =========================================================
# 3. THE fit_predict CONTRACT (walk_forward_evaluate-compatible)
# =========================================================

def lstm_fit_predict(train_df: pd.DataFrame, valid_df: pd.DataFrame, feature_cols: list[str] | None = None, **lstm_kwargs) -> pd.DataFrame:
    """
    Train on train_df, predict every horizon for valid_df.

    The exact contract walk_forward_evaluate() (evaluate.py) expects from
    any model: returns a DataFrame with one column per horizon
    (y_24, y_48, y_72) aligned to valid_df.index. Rows that cannot be
    predicted (warm-up region, missing features) get NaN and the harness
    drops them before scoring — same treatment as Ridge/RF/LightGBM.

    Prediction windows are built from train_df + valid_df concatenated
    per city, so a valid row's window sees the REAL past (including the
    tail of the training fold) exactly as production would at that
    timestamp. Only the last row of each window is predicted, and only
    for rows belonging to valid_df.

    Mapping predictions back is O(n) via a dict of (city, timestamp):
    timestamps repeat across cities (the frame is 10 cities on the same
    clock), so a plain index lookup would be ambiguous.
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)
    window = lstm_kwargs.get("window", 24)

    models, scaler = train_lstm_models(train_df, feature_cols=feature_cols,
                                       **lstm_kwargs)

    # One prediction per (city, timestamp) for each horizon.
    preds = pd.DataFrame(index=valid_df.index)
    valid_city = valid_df["city"].to_numpy()
    valid_time = valid_df.index.to_numpy()

    combined = pd.concat([train_df, valid_df]).sort_index()

    for h, model in models.items():
        col = f"{_TARGET_PREFIX}{h}"
        lookup = {}

        for city, city_df in combined.groupby("city"):
            # Windows need feature rows only; targets are irrelevant here.
            feats = city_df[feature_cols].dropna()
            if len(feats) < window:
                continue
            X = np.lib.stride_tricks.sliding_window_view(
                feats.to_numpy(dtype=float), window, axis=0
            )
            X = np.ascontiguousarray(X.transpose(0, 2, 1))  # (n, window, F)
            X = scaler.transform(X.reshape(-1, len(feature_cols))).reshape(X.shape)
            last_times = feats.index[window - 1:]
            last_cities = city_df.loc[feats.index[window - 1:], "city"].to_numpy()

            yhat = model.predict(X, verbose=0).ravel()
            for (c, t), p in zip(zip(last_cities, last_times), yhat):
                lookup[(c, t)] = p

        preds[col] = [lookup.get((c, t), np.nan)
                      for c, t in zip(valid_city, valid_time)]

    return preds


# =========================================================
# 4. CLI — quick smoke test on demo data
# =========================================================

def main() -> None:
    """Smoke test: LSTM on tiny synthetic data vs naive baselines."""
    import argparse

    parser = argparse.ArgumentParser(description="Day 15 LSTM smoke test")
    parser.add_argument("--window", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--demo-days", type=int, default=200)
    args = parser.parse_args()

    from src.features.build_features import build_features
    from src.features.targets import add_targets
    from src.training.evaluate import _demo_data, evaluate_baselines, walk_forward_evaluate

    df = _demo_data(n_days=args.demo_days)
    df = build_features(df)   # raw demo rows -> engineered features
    df = add_targets(df)
    feature_cols = select_features(df)

    baselines = evaluate_baselines(df)
    logger.info(str(baselines.pivot(index="horizon_h", columns="baseline",
                          values="rmse").round(1)))

    results = walk_forward_evaluate(
        df,
        lambda tr, va: lstm_fit_predict(
            tr, va, feature_cols=feature_cols,
            window=args.window, epochs=args.epochs,
        ),
        n_splits=2,
    )
    logger.info("LSTM walk-forward (mean across folds):")
    logger.info(str(results[results["fold_cut"] == "mean"]
          [["horizon_h", "rmse", "mae", "r2"]].round(2).to_string(index=False)))


if __name__ == "__main__":
    main()
