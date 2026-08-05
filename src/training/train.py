"""
train.py — Ridge regression training pipeline (Day 10 deliverable).

Day 10's theme is linear models: the maths, regularisation, scaling and
coefficient interpretation. This module is the first REAL model in the
project — it plugs into Day 9's walk-forward harness (evaluate.py), so
Ridge is compared apples-to-apples against the persistence and seasonal
naive baselines on the SAME folds.

The maths, briefly (roadmap Day 10):
    OLS:          min ||y - Xw||^2            -> closed form (X^T X)^{-1} X^T y
    Ridge (L2):   min ||y - Xw||^2 + a||w||^2 -> closed form (X^T X + aI)^{-1} X^T y
    - a = 0 degenerates to OLS; a > 0 shrinks coefficients toward 0.
    - L2 shrinkage trades a little bias for a large cut in variance —
      exactly the bias/variance trade-off from Day 9. AQI lags are
      heavily correlated, which is precisely where Ridge beats OLS.

Why scaling matters (Day 10 theme):
    The L2 penalty punishes the SIZE of coefficients, so a feature measured
    in big numbers (e.g. surface_pressure ~1000) dominates one measured in
    small numbers (e.g. precipitation ~0-10) for no modelling reason.
    StandardScaler puts every feature on unit variance BEFORE Ridge, so the
    penalty is fair and the coefficients become directly comparable:
    "effect on AQI per standard deviation of the feature". The scaler is
    fit on the training fold ONLY — never on validation — so no information
    leaks from the future into the scaler (leakage rule, roadmap Section 2).

What this module provides:
    1. select_features()       — the feature list. City is NEVER a feature
                                 (roadmap Section 3: city-agnostic global model).
    2. train_ridge_models()    — one (StandardScaler + Ridge) pipeline per
                                 horizon: y_24, y_48, y_72. Three targets ->
                                 three models, exactly as the roadmap prescribes.
    3. ridge_fit_predict()     — the fit_predict(train_df, valid_df) contract
                                 walk_forward_evaluate() expects.
    4. coefficient_table()     — coefficient interpretation: which features
                                 push AQI up/down, ranked by |coef|.
    5. main()                  — CLI: load the feature store (or demo data),
                                 audit leakage, walk-forward evaluation vs
                                 baselines, print results + top coefficients.
"""

import argparse

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.config import FORECAST_HORIZONS
from src.features.targets import add_targets, audit_leakage
from src.training.evaluate import evaluate_baselines, walk_forward_evaluate
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TARGET_PREFIX = "y_"

# Columns that describe the ROW, not the atmosphere. These are never
# features: city would teach the model "which city" (roadmap Section 3),
# and the raw calendar columns are replaced by their cyclical encodings
# (hour_sin/cos, month_sin/cos, dow_sin/cos) which build_features adds.
METADATA_COLUMNS = {"city", "date", "us_aqi", "local_hour", "month", "day_of_week"}


def select_features(df):
    """
    Return the feature column list for a training DataFrame.

    Everything numeric except metadata and target columns. Because the
    list is derived (not hardcoded), anything build_features() adds is
    picked up automatically and training/serving can never drift apart
    (roadmap structural rule 2 — build_features.py is shared by both).
    """
    target_cols = [c for c in df.columns if c.startswith(_TARGET_PREFIX)]
    excluded = METADATA_COLUMNS | set(target_cols)
    candidates = [c for c in df.columns if c not in excluded]
    feature_cols = df[candidates].select_dtypes(include=[np.number]).columns.tolist()
    if not feature_cols:
        raise ValueError("No numeric feature columns found — run build_features() first.")
    return feature_cols


def train_ridge_models(train_df, feature_cols=None, alpha=1.0):
    """
    Fit one (StandardScaler + Ridge) pipeline per forecast horizon.

    Parameters
    ----------
    train_df : pd.DataFrame
        Rows with engineered features AND target columns (y_24/y_48/y_72).
    feature_cols : list[str] | None
        Features to train on. Defaults to select_features(train_df).
    alpha : float
        Ridge regularisation strength (a in the L2 penalty). Larger = more
        shrinkage. Default 1.0; grid-searched properly on Day 13.

    Returns
    -------
    dict[int, Pipeline]
        {horizon: fitted (StandardScaler -> Ridge) pipeline}.

    NaN handling: rows with any missing feature OR target are dropped from
    the training fold (warm-up rows where lags/rolling windows don't exist
    yet). Dropping is honest — imputing a lag with a mean would inject
    fake history into the model. Same policy as the baselines in
    evaluate.py, which also only score rows where target AND prediction
    are non-null.
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)
    missing = [c for c in feature_cols + [f"{_TARGET_PREFIX}{h}" for h in FORECAST_HORIZONS]
               if c not in train_df.columns]
    if missing:
        raise ValueError(
            f"train_df is missing columns {missing} — run build_features() and "
            f"add_targets() first (see src/features/)."
        )

    models = {}
    for h in FORECAST_HORIZONS:
        target_col = f"{_TARGET_PREFIX}{h}"
        # Drop NaN rows for THIS horizon's target (a row may have y_24 but
        # not y_72 if it sits near the tail — add_targets drops those, but
        # be defensive for hand-built frames).
        clean = train_df[[*feature_cols, target_col]].dropna()
        if len(clean) == 0:
            raise ValueError(f"No complete training rows for horizon {h}h — "
                             f"check data window vs warm-up length.")

        X, y = clean[feature_cols], clean[target_col]
        pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),  # fit on TRAIN rows only
                ("ridge", Ridge(alpha=alpha)),
            ]
        )
        pipeline.fit(X, y)
        models[h] = pipeline
        logger.info(f"Horizon {h}h: Ridge(alpha={alpha}) on {len(clean)} rows, "
                    f"{len(feature_cols)} features")
    return models


def ridge_fit_predict(train_df, valid_df, alpha=1.0, feature_cols=None):
    """
    The fit_predict(train_df, valid_df) contract for walk_forward_evaluate().

    Trains one Ridge per horizon on train_df, predicts every horizon for
    valid_df, and returns a DataFrame with one column per horizon
    (y_24, y_48, y_72) aligned to valid_df.index — the exact contract
    walk_forward_evaluate() in evaluate.py expects from any model.

    Rows in valid_df with missing features (warm-up region) get NaN
    predictions; the harness drops them before scoring, same as it does
    for the baselines, so all models are compared on identical rows.
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)
    models = train_ridge_models(train_df, feature_cols=feature_cols, alpha=alpha)

    preds = pd.DataFrame(index=valid_df.index)
    for h, pipeline in models.items():
        target_col = f"{_TARGET_PREFIX}{h}"
        X_valid = valid_df[feature_cols]
        complete = X_valid.notna().all(axis=1)
        preds[target_col] = np.nan
        if complete.any():
            preds.loc[complete, target_col] = pipeline.predict(X_valid.loc[complete])
    return preds


def coefficient_table(models, feature_cols):
    """
    Coefficient interpretation (Day 10 theme).

    Every coefficient is on STANDARDISED features, so they are directly
    comparable: "expected change in AQI per 1 standard deviation of the
    feature, holding everything else fixed". Positive pulls AQI up,
    negative pulls it down. Ranked by |coef| so the biggest drivers lead.

    Returns a DataFrame: one row per (horizon, feature).
    """
    rows = []
    for h, pipeline in models.items():
        ridge = pipeline.named_steps["ridge"]
        coefs = np.asarray(ridge.coef_).ravel()
        for feat, coef in zip(feature_cols, coefs):
            rows.append(
                {
                    "horizon_h": h,
                    "feature": feat,
                    "coefficient": float(coef),
                    "abs_coefficient": abs(float(coef)),
                }
            )
    table = (
        pd.DataFrame(rows)
        .sort_values(["horizon_h", "abs_coefficient"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return table


def _print_results(baseline_results, ridge_results, coefs, top_k=10):
    """Pretty-print the comparison table + top coefficient drivers."""
    print("\n" + "=" * 62)
    print("NAIVE BASELINES (the floor any model must beat) — RMSE")
    print("=" * 62)
    print(baseline_results.pivot(index="horizon_h", columns="baseline",
                                 values="rmse").round(1).to_string())
    print("\n" + "=" * 62)
    print("RIDGE — walk-forward evaluation (mean across folds) — RMSE/MAE/R2")
    print("=" * 62)
    mean = ridge_results[ridge_results["fold_cut"] == "mean"]
    print(mean[["horizon_h", "rmse", "mae", "r2"]].round(2).to_string(index=False))

    print("\n" + "=" * 62)
    print(f"TOP {top_k} COEFFICIENT DRIVERS PER HORIZON (standardised)")
    print("=" * 62)
    for h in FORECAST_HORIZONS:
        top = coefs[coefs["horizon_h"] == h].head(top_k)
        print(f"\n+{h}h:")
        for _, row in top.iterrows():
            sign = "+" if row["coefficient"] >= 0 else "-"
            print(f"  {sign} {abs(row['coefficient']):8.2f}  {row['feature']}")


def main():
    parser = argparse.ArgumentParser(
        description="Day 10: Ridge regression training pipeline (walk-forward)."
    )
    parser.add_argument("--alpha", type=float, default=1.0,
                        help="Ridge L2 regularisation strength (default 1.0)")
    parser.add_argument("--n-splits", type=int, default=4,
                        help="Walk-forward folds (default 4)")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Coefficient drivers to print per horizon")
    parser.add_argument("--demo", action="store_true",
                        help="Force synthetic demo data (skip the feature store)")
    args = parser.parse_args()

    # 1. Load data: feature store first, demo fallback (same as the notebook).
    df = None
    if not args.demo:
        from src.features.feature_store import get_feature_store

        store = get_feature_store()
        df = store.read_features()
        if df.empty:
            logger.warning("Feature store empty — falling back to synthetic demo data.")
            df = None
        else:
            df = df.set_index("date").sort_index()
            df["us_aqi"] = df["us_aqi"].astype(float)
            logger.info(f"Loaded {len(df)} rows from feature store "
                        f"({df['city'].nunique()} cities).")

    if df is None:
        from src.training.evaluate import _demo_data

        df = _demo_data()
        logger.warning("Running on DEMO data — numbers are NOT meaningful; "
                       "run the Day 8 backfill for real results.")

    # 2. Features + targets if the frame doesn't already carry them
    #    (store rows are engineered by the backfill; demo rows are raw).
    if "aqi_lag_1h" not in df.columns:
        from src.features.build_features import build_features

        df = build_features(df)
    target_cols = [c for c in df.columns if c.startswith(_TARGET_PREFIX)]
    if not target_cols:
        df = add_targets(df)

    # 3. Leakage audit — the Day 6 gate, re-run before every training run.
    audit = audit_leakage(df)
    if not audit["ok"]:
        logger.error(f"Leakage audit FAILED: {audit['issues']}")
        raise SystemExit(1)
    for warning in audit["warnings"]:
        logger.warning(warning)

    # 4. Baselines + Ridge on the SAME walk-forward folds.
    feature_cols = select_features(df)
    logger.info(f"Features ({len(feature_cols)}): {feature_cols}")
    baseline_results = evaluate_baselines(df)
    ridge_results = walk_forward_evaluate(
        df,
        lambda tr, va: ridge_fit_predict(tr, va, alpha=args.alpha,
                                         feature_cols=feature_cols),
        n_splits=args.n_splits,
    )

    # 5. Refit on ALL data for the coefficient story (interpretation only —
    #    the honest numbers are the walk-forward ones above).
    full_models = train_ridge_models(df, feature_cols=feature_cols, alpha=args.alpha)
    coefs = coefficient_table(full_models, feature_cols)

    _print_results(baseline_results, ridge_results, coefs, top_k=args.top_k)


if __name__ == "__main__":
    main()
