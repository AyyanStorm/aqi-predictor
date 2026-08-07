"""
train.py — Ridge + Random Forest + LightGBM training pipeline (Days 10-12).

Day 10 added linear models: Ridge regression with the maths, regularisation,
scaling and coefficient interpretation. Day 11 added tree ensembles: Random
Forest via bagging, feature importance and hyperparameters. Day 12 adds
LightGBM: gradient boosting, how it differs from bagging, key hyperparameters.

All models plug into Day 9's walk-forward harness (evaluate.py), so they
are compared apples-to-apples against the persistence and seasonal naive
baselines on the SAME folds — and against each other.

The maths, briefly (roadmap Day 10):
    OLS:          min ||y - Xw||^2            -> closed form (X^T X)^{-1} X^T y
    Ridge (L2):   min ||y - Xw||^2 + a||w||^2 -> closed form (X^T X + aI)^{-1} X^T y
    - a = 0 degenerates to OLS; a > 0 shrinks coefficients toward 0.
    - L2 shrinkage trades a little bias for a large cut in variance —
      exactly the bias/variance trade-off from Day 9. AQI lags are
      heavily correlated, which is precisely where Ridge beats OLS.

Why scaling matters (Day 10 theme, and why tree models do NOT need it):
    The L2 penalty punishes the SIZE of coefficients, so a feature measured
    in big numbers (e.g. surface_pressure ~1000) dominates one measured in
    small numbers (e.g. precipitation ~0-10) for no modelling reason.
    StandardScaler puts every feature on unit variance BEFORE Ridge, so the
    penalty is fair and the coefficients become directly comparable.
    Random Forest AND LightGBM are scale-INVARIANT: trees split on one
    feature at a time, so absolute magnitudes don't matter. No scaler
    needed — a useful contrast that makes the "why scaling" lesson stick.

Day 11 theme — Random Forest via bagging (variance reduction):
    A single deep decision tree overfits: it can split until every leaf
    holds one training point. Bagging (bootstrap AGGregatING) fixes this by
    variance reduction:
      1. Draw B bootstrap samples (sample WITH replacement) from the train set.
      2. Grow a deep tree on each sample.
      3. Average the B trees' predictions.
    E[avg] = E[single tree] (bias unchanged), but Var[avg] ~ Var/tree / B
    (variance shrinks ~linearly with B). Random Forest goes one step further:
    each split only considers a random subset of features (max_features),
    which decorrelates the trees — correlated errors don't average away.

    Feature importance (feature_importances_): each node split reduces
    impurity (here MSE); that reduction is weighted by node size and
    accumulated per feature across all trees, then normalised to sum to 1.
    It answers "which features does the forest actually split on to reduce
    error" — the first non-linear signal of what matters, to be cross-checked
    against SHAP on Day 20.

Day 12 theme — LightGBM / gradient boosting (bias reduction):
    Boosting is the OPPOSITE philosophy to bagging. Instead of averaging
    independent trees, boosting builds trees SEQUENTIALLY, and each new
    tree fits the NEGATIVE GRADIENT of the loss — i.e. the residual errors
    the ensemble has made so far:
      1. Start with a weak constant prediction (the mean).
      2. Fit a SHALLOW tree to the residuals: pred - y.
      3. Add it with a small learning_rate (shrinkage): pred += lr * tree.
      4. Repeat; each tree fixes what the previous ones got wrong.
    Bagging reduces VARIANCE (averaging noisy experts); boosting reduces
    BIAS (each round learns from mistakes). This is why boosting usually
    wins on tabular data: it can chase fine structure that bagging's
    averaging smooths away.

    Why LightGBM specifically (vs plain gradient boosting):
      - Histogram-based splits: bins continuous features, so split finding
        is O(bins) not O(rows) — an order-of-magnitude speedup.
      - Leaf-wise (not level-wise) growth: expands the leaf with the best
        loss reduction, so it fits deeper where it matters.
      - Native NaN handling and categorical support.

    Key hyperparameters:
      n_estimators        — number of boosting rounds (trees).
      learning_rate       — shrinkage per round. Lower = each tree adds less,
                            needs more rounds, less overfitting. lr 0.05-0.1
                            with 300-1000 rounds is the classic combo.
      num_leaves          — max leaves per tree; the LightGBM equivalent of
                            max_depth (a depth-d tree can have 2^d leaves).
                            Bigger = more capacity = more overfitting risk.
      min_child_samples   — min rows per leaf; larger = smoother trees.
      subsample           — row sampling per round (bagging-like, adds
                            variance reduction on top of boosting).
      colsample_bytree    — feature sampling per tree (decorrelates rounds).
      reg_alpha / reg_lambda — L1/L2 regularisation on the leaf weights.
    Day 13 (tomorrow) grid-searches these properly; today we ship the model
    with sensible defaults and get the honest walk-forward numbers.

What this module provides:
    1. select_features()        — the feature list. City is NEVER a feature
                                  (roadmap Section 3: city-agnostic global model).
    2. train_ridge_models()     — one (StandardScaler + Ridge) pipeline per
                                  horizon: y_24, y_48, y_72. Three targets ->
                                  three models, exactly as the roadmap prescribes.
    3. ridge_fit_predict()      — the fit_predict(train_df, valid_df) contract
                                  walk_forward_evaluate() expects.
    4. train_rf_models()        — one RandomForestRegressor per horizon (no
                                  scaler — trees are scale-invariant).
    5. rf_fit_predict()         — same contract as ridge_fit_predict, so the
                                  harness treats both models identically.
    6. train_lgbm_models()      — one LGBMRegressor per horizon (gain-based
                                  feature importance).
    7. lgbm_fit_predict()       — same fit_predict contract.
    8. coefficient_table()      — Ridge: which features push AQI up/down, |coef|.
    9. feature_importance_table()— RF/LGBM: which features reduce error, ranked.
    10. main()                  — CLI: load feature store (or demo data), audit
                                  leakage, walk-forward evaluation vs baselines,
                                  print results + per-model interpretation.
"""

import argparse

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
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


def train_rf_models(train_df, feature_cols=None, n_estimators=300,
                    max_depth=None, min_samples_leaf=2, max_features=1.0/3.0,
                    n_jobs=-1, random_state=42):
    """
    Fit one RandomForestRegressor per forecast horizon (Day 11 deliverable).

    Bagging in action (roadmap Day 11): each tree trains on a bootstrap
    sample (sampled WITH replacement) of the training rows, and each split
    only sees a random subset of features (max_features). Averaging the
    trees keeps bias at the single-tree level while slashing variance —
    the exact fix for the overfitting a lone deep decision tree would do.

    Unlike Ridge, NO scaler is needed: trees split one feature at a time
    on absolute values, so they are scale-invariant. That is the teaching
    contrast with Day 10's StandardScaler.

    Returns
    -------
    dict[int, RandomForestRegressor]
        {horizon: fitted forest}. Same NaN-drop policy as Ridge (rows with
        missing feature or target are dropped honestly, never imputed).
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
        clean = train_df[[*feature_cols, target_col]].dropna()
        if len(clean) == 0:
            raise ValueError(f"No complete training rows for horizon {h}h — "
                             f"check data window vs warm-up length.")

        X, y = clean[feature_cols], clean[target_col]
        forest = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            max_features=max_features,
            n_jobs=n_jobs,
            random_state=random_state,
        )
        forest.fit(X, y)
        models[h] = forest
        logger.info(f"Horizon {h}h: RandomForest(n_estimators={n_estimators}, "
                    f"max_depth={max_depth}, min_samples_leaf={min_samples_leaf}) "
                    f"on {len(clean)} rows, {len(feature_cols)} features")
    return models


def rf_fit_predict(train_df, valid_df, feature_cols=None, **rf_kwargs):
    """
    The fit_predict(train_df, valid_df) contract for walk_forward_evaluate().

    Identical shape to ridge_fit_predict(): train one forest per horizon,
    predict every horizon for valid_df, return a DataFrame with one column
    per horizon aligned to valid_df.index. The harness therefore scores
    Ridge and Random Forest on the SAME folds, same rows, same metrics —
    apples-to-apples (roadmap Day 11: compare models, not harnesses).
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)
    models = train_rf_models(train_df, feature_cols=feature_cols, **rf_kwargs)

    preds = pd.DataFrame(index=valid_df.index)
    for h, forest in models.items():
        target_col = f"{_TARGET_PREFIX}{h}"
        X_valid = valid_df[feature_cols]
        complete = X_valid.notna().all(axis=1)
        preds[target_col] = np.nan
        if complete.any():
            preds.loc[complete, target_col] = forest.predict(X_valid.loc[complete])
    return preds


def feature_importance_table(models, feature_cols):
    """
    Random Forest feature importances (Day 11 theme).

    Each node split reduces impurity (MSE for regression); the reduction is
    weighted by the number of rows reaching the node and accumulated per
    feature across ALL trees, then normalised to sum to 1. High importance
    = the forest relies on this feature to reduce error. This is the first
    non-linear "what actually matters" signal, to be cross-checked against
    SHAP on Day 20 (SHAP is more trustworthy — importance can favour
    high-cardinality features).

    Returns a DataFrame: one row per (horizon, feature), ranked by
    importance within each horizon.
    """
    rows = []
    for h, forest in models.items():
        importances = np.asarray(forest.feature_importances_).ravel()
        for feat, imp in zip(feature_cols, importances):
            rows.append({"horizon_h": h, "feature": feat, "importance": float(imp)})
    table = (
        pd.DataFrame(rows)
        .sort_values(["horizon_h", "importance"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return table


def train_lgbm_models(train_df, feature_cols=None, n_estimators=500,
                      learning_rate=0.05, num_leaves=31, min_child_samples=20,
                      subsample=0.9, colsample_bytree=0.9, n_jobs=-1,
                      random_state=42, verbosity=-1):
    """
    Fit one LGBMRegressor per forecast horizon (Day 12 deliverable).

    Gradient boosting in action: trees are built SEQUENTIALLY, each one
    fitting the negative gradient (residuals) of the ensemble so far, with
    learning_rate shrinkage per round. Opposite philosophy to bagging —
    bagging averages noisy experts (variance reduction), boosting learns
    from mistakes (bias reduction). See module docstring for the full
    Day 12 write-up.

    LightGBM specifics: histogram-based splits (bins continuous features),
    leaf-wise growth (expands the best-loss leaf, not level-by-level), and
    native NaN handling. No scaler needed — trees are scale-invariant.

    feature_importances_ use importance_type="gain" (the total loss
    reduction attributable to each feature) — more meaningful than raw
    split counts for boosting, and directly comparable across horizons.

    Returns
    -------
    dict[int, LGBMRegressor]
        {horizon: fitted model}. Same NaN-drop policy as Ridge/RF (rows
        with missing feature or target are dropped honestly, never imputed).
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
        clean = train_df[[*feature_cols, target_col]].dropna()
        if len(clean) == 0:
            raise ValueError(f"No complete training rows for horizon {h}h — "
                             f"check data window vs warm-up length.")

        X, y = clean[feature_cols], clean[target_col]
        lgbm = LGBMRegressor(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
            min_child_samples=min_child_samples,
            subsample=subsample,
            subsample_freq=1,          # row sampling every round
            colsample_bytree=colsample_bytree,
            n_jobs=n_jobs,
            random_state=random_state,
            verbosity=verbosity,
            importance_type="gain",
        )
        lgbm.fit(X, y)
        models[h] = lgbm
        logger.info(f"Horizon {h}h: LightGBM(n_estimators={n_estimators}, "
                    f"learning_rate={learning_rate}, num_leaves={num_leaves}, "
                    f"min_child_samples={min_child_samples}) on {len(clean)} rows, "
                    f"{len(feature_cols)} features")
    return models


def lgbm_fit_predict(train_df, valid_df, feature_cols=None, **lgbm_kwargs):
    """
    The fit_predict(train_df, valid_df) contract for walk_forward_evaluate().

    Identical shape to ridge_fit_predict()/rf_fit_predict(): train one model
    per horizon, predict every horizon for valid_df, return a DataFrame with
    one column per horizon aligned to valid_df.index. The harness therefore
    scores Ridge, Random Forest and LightGBM on the SAME folds, same rows,
    same metrics — apples-to-apples (roadmap Day 12).
    """
    if feature_cols is None:
        feature_cols = select_features(train_df)
    models = train_lgbm_models(train_df, feature_cols=feature_cols, **lgbm_kwargs)

    preds = pd.DataFrame(index=valid_df.index)
    for h, lgbm in models.items():
        target_col = f"{_TARGET_PREFIX}{h}"
        X_valid = valid_df[feature_cols]
        complete = X_valid.notna().all(axis=1)
        preds[target_col] = np.nan
        if complete.any():
            preds.loc[complete, target_col] = lgbm.predict(X_valid.loc[complete])
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


def _print_results(baseline_results, model_results, top_k=10, model_name="MODEL",
                   importance_table=None):
    """Pretty-print the comparison table + per-model interpretation.

    model_results: walk-forward results frame (one row per fold_cut).
    importance_table: for RF — feature importances; None for Ridge (which
    prints coefficients instead). Both are derived from a full-data refit.
    """
    print("\n" + "=" * 62)
    print("NAIVE BASELINES (the floor any model must beat) — RMSE")
    print("=" * 62)
    print(baseline_results.pivot(index="horizon_h", columns="baseline",
                                 values="rmse").round(1).to_string())
    print("\n" + "=" * 62)
    print(f"{model_name} — walk-forward evaluation (mean across folds) — RMSE/MAE/R2")
    print("=" * 62)
    mean = model_results[model_results["fold_cut"] == "mean"]
    print(mean[["horizon_h", "rmse", "mae", "r2"]].round(2).to_string(index=False))

    if importance_table is None or "importance" not in importance_table.columns:
        print("\n" + "=" * 62)
        print(f"TOP {top_k} COEFFICIENT DRIVERS PER HORIZON (standardised)")
        print("=" * 62)
        for h in FORECAST_HORIZONS:
            top = importance_table[importance_table["horizon_h"] == h].head(top_k)
            print(f"\n+{h}h:")
            for _, row in top.iterrows():
                sign = "+" if row["coefficient"] >= 0 else "-"
                print(f"  {sign} {abs(row['coefficient']):8.2f}  {row['feature']}")
    else:
        print("\n" + "=" * 62)
        print(f"TOP {top_k} FEATURE IMPORTANCES PER HORIZON (Random Forest)")
        print("=" * 62)
        for h in FORECAST_HORIZONS:
            top = importance_table[importance_table["horizon_h"] == h].head(top_k)
            print(f"\n+{h}h:")
            for _, row in top.iterrows():
                print(f"  {row['importance']:7.3f}  {row['feature']}")


def main():
    parser = argparse.ArgumentParser(
        description="Days 10-11: Ridge + Random Forest training pipeline (walk-forward)."
    )
    parser.add_argument("--alpha", type=float, default=1.0,
                        help="Ridge L2 regularisation strength (default 1.0)")
    parser.add_argument("--model", choices=["ridge", "rf", "lgbm", "both", "all"], default="all",
                        help="Which model(s) to run (default: all, compared on same folds)")
    parser.add_argument("--n-estimators", type=int, default=300,
                        help="Random Forest: number of trees (default 300)")
    parser.add_argument("--max-depth", type=int, default=None,
                        help="Random Forest: max tree depth (default None = full grow, bagging handles variance)")
    parser.add_argument("--min-samples-leaf", type=int, default=2,
                        help="Random Forest: min samples per leaf (default 2)")
    parser.add_argument("--learning-rate", type=float, default=0.05,
                        help="LightGBM: shrinkage per boosting round (default 0.05)")
    parser.add_argument("--num-leaves", type=int, default=31,
                        help="LightGBM: max leaves per tree (default 31)")
    parser.add_argument("--min-child-samples", type=int, default=20,
                        help="LightGBM: min rows per leaf (default 20)")
    parser.add_argument("--n-splits", type=int, default=4,
                        help="Walk-forward folds (default 4)")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Coefficient/importance drivers to print per horizon")
    parser.add_argument("--demo", action="store_true",
                        help="Force synthetic demo data (skip the feature store)")
    parser.add_argument("--register", action="store_true",
                        help="Push the full-data refit models to the Model Registry "
                             "(Day 14) with their walk-forward metrics; auto-promotes "
                             "only if they beat the current production model")
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

    # 4. Baselines + selected models on the SAME walk-forward folds.
    feature_cols = select_features(df)
    logger.info(f"Features ({len(feature_cols)}): {feature_cols}")
    baseline_results = evaluate_baselines(df)

    # What gets registered (--register): full-data refit models + their
    # walk-forward mean metrics. Collected here so every model branch below
    # feeds the same registry call at the end (Day 14).
    registry_candidates = []

    def _walkforward_mean(results):
        mean = results[results["fold_cut"] == "mean"]
        return {
            int(r["horizon_h"]): {"rmse": float(r["rmse"]),
                                   "mae": float(r["mae"]),
                                   "r2": float(r["r2"])}
            for _, r in mean.iterrows()
        }

    def _window(df):
        idx = df.index
        return {"start": str(idx.min().date()), "end": str(idx.max().date())}

    if args.model in ("ridge", "both"):
        ridge_results = walk_forward_evaluate(
            df,
            lambda tr, va: ridge_fit_predict(tr, va, alpha=args.alpha,
                                             feature_cols=feature_cols),
            n_splits=args.n_splits,
        )
        full_ridge = train_ridge_models(df, feature_cols=feature_cols, alpha=args.alpha)
        coefs = coefficient_table(full_ridge, feature_cols)
        _print_results(baseline_results, ridge_results, top_k=args.top_k,
                       model_name="RIDGE", importance_table=coefs)
        if args.register:
            registry_candidates.append(
                ("ridge", full_ridge, _walkforward_mean(ridge_results),
                 {"alpha": args.alpha})
            )

    if args.model in ("rf", "both", "all"):
        rf_results = walk_forward_evaluate(
            df,
            lambda tr, va: rf_fit_predict(
                tr, va, feature_cols=feature_cols,
                n_estimators=args.n_estimators,
                max_depth=args.max_depth,
                min_samples_leaf=args.min_samples_leaf,
            ),
            n_splits=args.n_splits,
        )
        full_rf = train_rf_models(
            df, feature_cols=feature_cols,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            min_samples_leaf=args.min_samples_leaf,
        )
        importances = feature_importance_table(full_rf, feature_cols)
        _print_results(baseline_results, rf_results, top_k=args.top_k,
                       model_name="RANDOM FOREST", importance_table=importances)
        if args.register:
            registry_candidates.append(
                ("rf", full_rf, _walkforward_mean(rf_results),
                 {"n_estimators": args.n_estimators,
                  "max_depth": args.max_depth,
                  "min_samples_leaf": args.min_samples_leaf})
            )

    if args.model in ("lgbm", "both", "all"):
        lgbm_results = walk_forward_evaluate(
            df,
            lambda tr, va: lgbm_fit_predict(
                tr, va, feature_cols=feature_cols,
                n_estimators=args.n_estimators,
                learning_rate=args.learning_rate,
                num_leaves=args.num_leaves,
                min_child_samples=args.min_child_samples,
            ),
            n_splits=args.n_splits,
        )
        full_lgbm = train_lgbm_models(
            df, feature_cols=feature_cols,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            num_leaves=args.num_leaves,
            min_child_samples=args.min_child_samples,
        )
        lgbm_importances = feature_importance_table(full_lgbm, feature_cols)
        _print_results(baseline_results, lgbm_results, top_k=args.top_k,
                       model_name="LIGHTGBM", importance_table=lgbm_importances)
        if args.register:
            registry_candidates.append(
                ("lgbm", full_lgbm, _walkforward_mean(lgbm_results),
                 {"n_estimators": args.n_estimators,
                  "learning_rate": args.learning_rate,
                  "num_leaves": args.num_leaves,
                  "min_child_samples": args.min_child_samples})
            )

    # 5. Model Registry (Day 14): register every trained model with its
    #    honest walk-forward metrics; auto-promote only the winners.
    if args.register and registry_candidates:
        from src.training.model_registry import ModelRegistry

        reg = ModelRegistry()
        for name, models, metrics, params in registry_candidates:
            if models is None:
                continue
            version = reg.register(
                name=name,
                models=models,
                metrics=metrics,
                feature_cols=feature_cols,
                params=params,
                n_train_rows=int(len(df)),
                train_window=_window(df),
                notes="full-data refit, walk-forward metrics from --register run",
            )
            reg.promote_if_better(name, version)
        print("\n" + "=" * 62)
        print("MODEL REGISTRY (Day 14) — current production")
        print("=" * 62)
        print(reg.status())


if __name__ == "__main__":
    main()
