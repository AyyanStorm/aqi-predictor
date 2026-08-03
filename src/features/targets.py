"""
targets.py — multi-horizon target construction + leakage audit + walk-forward split.

Day 6 deliverable. Solves the single most important problem in this project
(roadmap Section 2): Open-Meteo's `us_aqi` is *computed* from the pollutant
concentrations at the same timestamp. If you ever train with

    X = [pm2_5, pm10, co, no2, so2, o3] at time t
    y = us_aqi                        at time t

you get R² ≈ 0.999 — not machine learning, just rediscovering the US EPA
breakpoint lookup table. A reviewer spots that in thirty seconds.

The correct framing (what this module implements):

    Given everything observable at time t,
    predict us_aqi at t+24h, t+48h, t+72h.

Rules held here (from the roadmap, keep them in your head all 28 days):
  - Every FEATURE must be answerable with "yes, I would know this value at
    the moment I press Predict." If no -> delete the feature.
  - The TARGET is always the FUTURE. A target row is only legal if it was
    constructed by shifting `us_aqi` BACKWARD by the horizon, per city.
"""

import numpy as np
import pandas as pd

from src.config import FORECAST_HORIZONS
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns that are allowed to be targets. Everything else in the DataFrame
# that isn't metadata is treated as a feature during the audit.
_TARGET_PREFIX = "y_"


def add_targets(df, horizons=None):
    """
    Add one target column per horizon: y_24, y_48, y_72.

    For each city group, the target at row t is `us_aqi` at t + h, created
    with a NEGATIVE shift (future values pulled back onto the current row).
    Rows at the tail of each city series where a target is NaN are dropped,
    because a row without a complete target is useless for supervised training.

    Parameters
    ----------
    df : pd.DataFrame
        Must have a datetime index, a 'city' column, and a 'us_aqi' column.
    horizons : list[int] | None
        Hours ahead to predict. Defaults to config.FORECAST_HORIZONS = [24, 48, 72].

    Returns
    -------
    pd.DataFrame
        Copy of df with y_<h> columns added, tail rows with NaN targets dropped.
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS

    df = df.copy()  # never mutate the caller's DataFrame
    missing = {"city", "us_aqi"} - set(df.columns)
    if missing:
        raise ValueError(f"df must have columns 'city' and 'us_aqi'; missing: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex (hourly, sorted ascending)")

    for h in horizons:
        # shift(-h): the value h rows ahead. Grouped by city so the tail of
        # one city never borrows the head of the next city.
        df[f"{_TARGET_PREFIX}{h}"] = df.groupby("city")["us_aqi"].shift(-h)

    n_before = len(df)
    # Drop rows where ANY horizon target is missing (end-of-series per city).
    target_cols = [f"{_TARGET_PREFIX}{h}" for h in horizons]
    df = df.dropna(subset=target_cols)
    n_dropped = n_before - len(df)

    logger.info(
        f"Added targets {target_cols}: {len(df)} rows kept "
        f"({n_dropped} tail rows dropped for incomplete targets)"
    )
    return df


def audit_leakage(df, feature_cols=None):
    """
    Leakage audit — the Day 6 "explicit audit" the roadmap's risk table demands.

    Checks, in order:
      1. No target column appears in the feature set.
      2. Target rows really are future values: y_<h> at row t must equal
         us_aqi at t+h. Verified per city with a midpoint spot check.
      3. No feature is a deterministic function of the same-timestamp target
         (the R² = 0.999 trap): if any feature has |corr| >= 0.999 with a
         target on the SAME row, it is almost certainly the lookup-table trap
         and must be removed.
      4. Same-timestamp pollutant columns used as features are flagged as a
         reminder: they are legal ONLY because the target is in the future.

    Parameters
    ----------
    df : pd.DataFrame
        Output of add_targets() (has y_<h> columns).
    feature_cols : list[str] | None
        Explicit feature list. If None, every non-target, non-metadata column
        is treated as a feature.

    Returns
    -------
    dict
        Audit report: {'ok': bool, 'issues': [str], 'warnings': [str]}.
    """
    target_cols = [c for c in df.columns if c.startswith(_TARGET_PREFIX)]
    if not target_cols:
        raise ValueError("No target columns found — run add_targets() first.")

    metadata = {"city", "us_aqi"}
    if feature_cols is None:
        feature_cols = [c for c in df.columns if c not in set(target_cols) | metadata]

    issues, warnings = [], []

    # 1. Target columns must not double as features.
    overlap = set(feature_cols) & set(target_cols)
    if overlap:
        issues.append(f"Target columns leaked into features: {sorted(overlap)}")

    # 2. Future-value spot check: y_h(t) == us_aqi(t + h), per city.
    for h in [int(c.split("_")[1]) for c in target_cols]:
        col = f"y_{h}"
        for city, group in df.groupby("city"):
            mid = len(group) // 2  # avoid the (already dropped) tail region
            actual = group[col].iloc[mid]
            expected = group["us_aqi"].shift(-h).iloc[mid]
            if not np.isclose(actual, expected, equal_nan=True):
                issues.append(
                    f"{col} at row {group.index[mid]} ({city}) does not equal "
                    f"us_aqi shifted by -{h}h — target construction is wrong."
                )
                break

    # 3. Same-row lookup-table trap: |corr| >= 0.999 feature vs target.
    numeric_features = df[feature_cols].select_dtypes(include=[np.number]).columns
    for col in target_cols:
        for feat in numeric_features:
            corr = df[[feat, col]].corr().iloc[0, 1]
            if abs(corr) >= 0.999:
                issues.append(
                    f"Feature '{feat}' has |corr|={abs(corr):.4f} with '{col}' on the "
                    f"SAME row — this is the lookup-table trap. Remove the feature."
                )

    # 4. Reminder about same-timestamp pollutants as features.
    pollutants = [f for f in numeric_features if f not in {"us_aqi"} and f in df.columns]
    if pollutants:
        warnings.append(
            "Same-timestamp pollutants are used as features — legal ONLY because "
            "targets are shifted into the future. Never add a same-timestamp "
            "us_aqi-vs-pollutant model, and never shift targets back to 0h."
        )

    ok = not issues
    if ok:
        logger.info(f"Leakage audit passed: {len(target_cols)} targets, {len(feature_cols)} features")
    else:
        logger.error(f"Leakage audit FAILED: {len(issues)} issue(s)")
    return {"ok": ok, "issues": issues, "warnings": warnings}


def walk_forward_split(df, horizons=None, n_splits=4, gap_hours=None):
    """
    Design of the walk-forward (time-based) split — NOT a random shuffle.

    Random CV is wrong for time series: a model trained on 2024 rows would
    get to "see" 2023 validation rows through lag features. Here every fold
    trains only on data strictly BEFORE the fold's cut-off and validates on
    the window after it, so the temporal ordering is preserved exactly.

    Fold k (k = 0..n_splits-1):
        train    = rows with timestamp <  cut_k
        validate = rows with timestamp >= cut_k + gap   (gap excludes the
                   horizon span so training features can never contain values
                   from the validation window)

    Returns
    -------
    list[tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]]
        [(train_df, valid_df, cut_k), ...] oldest -> newest folds.
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    max_h = max(horizons)
    if gap_hours is None:
        gap_hours = max_h  # default gap = longest horizon, the strictest choice

    df = df.sort_index()
    timestamps = df.index.unique()
    if len(timestamps) < n_splits * 2:
        raise ValueError("Not enough distinct timestamps for this many splits")

    # n_splits cut points spread over the middle of the timeline.
    cut_idxs = np.linspace(
        len(timestamps) // n_splits,
        len(timestamps) - len(timestamps) // n_splits - 1,
        n_splits,
        dtype=int,
    )

    folds = []
    for cut_idx in cut_idxs:
        cut = timestamps[cut_idx]
        gap = pd.Timedelta(hours=gap_hours)
        train = df[df.index < cut]
        valid = df[df.index >= cut + gap]
        if len(train) == 0 or len(valid) == 0:
            logger.warning(f"Skipping empty fold at cut={cut}")
            continue
        folds.append((train, valid, cut))
        logger.info(
            f"Fold cut={cut}: train {len(train)} rows, validate {len(valid)} rows"
        )
    return folds
