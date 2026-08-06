"""
tune.py — Day 13: walk-forward backtesting, hyperparameter tuning, unseen-city holdout.

Day 13 turns Day 9's harness into a proper model-selection workflow. Three
pieces, in order:

    1. WALK-FORWARD BACKTESTING
       walk_forward_evaluate() (evaluate.py, Day 9) already scores ANY
       model on time-ordered folds — never shuffled. Tuning reuses it, so
       every hyperparameter combination is judged by the same honest
       protocol the baselines and models were judged by.

    2. HYPERPARAMETER TUNING (grid search on walk-forward CV)
       Each grid point is scored by the walk-forward harness, and the best
       combo per horizon is picked. Why walk-forward and not random CV:
       random K-fold shuffles time, and lag features then leak the future
       into training (Day 9 lesson). For a forecasting model, walk-forward
       CV is the ONLY honest score — so it is the only score tuning sees.

    3. UNSEEN-CITY HOLDOUT (the "works for any city" proof)
       Roadmap Section 3's claim: a city-agnostic model trained on 10
       cities generalises to a city it has never seen. We train on all 10
       cities and evaluate ONLY on Sialkot (in no training fold), compared
       against the naive baselines computed on Sialkot itself. If the
       global model beats naive on a city it never saw, the claim is
       earned — and that table goes in the README on Day 26.

Model fit_predict contracts (from train.py): ridge_fit_predict,
rf_fit_predict, lgbm_fit_predict all take (train_df, valid_df) and return
a DataFrame with y_24/y_48/y_72 columns aligned to valid_df.index.
"""

import argparse
from itertools import product

import numpy as np
import pandas as pd

from src.config import FORECAST_HORIZONS
from src.training.evaluate import evaluate_baselines, walk_forward_evaluate
from src.training.train import (
    lgbm_fit_predict,
    rf_fit_predict,
    ridge_fit_predict,
    select_features,
    train_lgbm_models,
    train_rf_models,
    train_ridge_models,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TARGET_PREFIX = "y_"

# ---------------------------------------------------------
# Default grids. Day 12 taught us the knobs; these are the
# ranges worth trying. Kept small so a full grid search on
# real data stays within one evening session (Day 13 budget).
# ---------------------------------------------------------
GRIDS = {
    "ridge": {"alpha": [0.1, 1.0, 10.0]},
    "rf": {
        "n_estimators": [100, 300],
        "max_depth": [None, 20],
        "min_samples_leaf": [2, 5],
    },
    "lgbm": {
        "n_estimators": [200, 500],
        "learning_rate": [0.05, 0.1],
        "num_leaves": [31, 63],
        "min_child_samples": [10, 20],
    },
}


# =========================================================
# 1. GRID SEARCH ON WALK-FORWARD CV
# =========================================================

def _fit_predict_for(model_name, params, feature_cols):
    """Build the fit_predict callable for one model + param combo.

    Every callable has the (train_df, valid_df) -> predictions contract
    that walk_forward_evaluate() requires, so all combos are scored by
    the identical protocol.
    """
    if model_name == "ridge":
        return lambda tr, va: ridge_fit_predict(
            tr, va, alpha=params.get("alpha", 1.0), feature_cols=feature_cols
        )
    if model_name == "rf":
        return lambda tr, va: rf_fit_predict(
            tr, va, feature_cols=feature_cols, **params
        )
    if model_name == "lgbm":
        return lambda tr, va: lgbm_fit_predict(
            tr, va, feature_cols=feature_cols, **params
        )
    raise ValueError(f"Unknown model '{model_name}' (use ridge|rf|lgbm)")


def run_grid_search(df, model_name, grid=None, n_splits=4, feature_cols=None):
    """
    Score every hyperparameter combination on walk-forward CV.

    Returns
    -------
    pd.DataFrame
        One row per (combo, horizon): combo label, the params that define
        it, and mean walk-forward rmse/mae/r2 for that horizon.
    """
    if grid is None:
        grid = GRIDS[model_name]
    if feature_cols is None:
        feature_cols = select_features(df)

    param_names = list(grid.keys())
    combos = list(product(*grid.values()))
    logger.info(f"Grid search {model_name}: {len(combos)} combos x "
                f"{len(FORECAST_HORIZONS)} horizons x {n_splits} walk-forward folds")

    rows = []
    for combo in combos:
        params = dict(zip(param_names, combo))
        results = walk_forward_evaluate(
            df,
            _fit_predict_for(model_name, params, feature_cols),
            n_splits=n_splits,
        )
        mean = results[results["fold_cut"] == "mean"]
        for _, r in mean.iterrows():
            rows.append(
                {
                    "combo": str(params),
                    **params,
                    "horizon_h": r["horizon_h"],
                    "rmse": r["rmse"],
                    "mae": r["mae"],
                    "r2": r["r2"],
                }
            )
        logger.info(f"  {params}: " + ", ".join(
            f"{h}h rmse={mean.loc[mean.horizon_h == h, 'rmse'].iloc[0]:.2f}"
            for h in FORECAST_HORIZONS
        ))

    return pd.DataFrame(rows)


def _py(value):
    """Convert numpy scalars to plain Python so str() round-trips.

    best_combos() reads values back out of a DataFrame, which returns
    np.float64 etc. str(np.float64(0.1)) is 'np.float64(0.1)' — NOT the
    same string as the combo label built from a plain float ('0.1'), so a
    combo-string lookup would silently match zero rows. Converting here
    keeps the params dicts round-trippable through str().
    """
    if hasattr(value, "item"):
        return value.item()
    return value


def best_combos(grid_results, model_name, grid=None):
    """
    Pick the best hyperparameters from a run_grid_search() result.

    Returns
    -------
    dict
        {'per_horizon': {h: params_dict}, 'overall': params_dict}
    per_horizon: for each horizon, the combo with the lowest mean RMSE
    (each horizon gets its own model — the roadmap's three-target design).
    overall: the combo with the lowest RMSE averaged across horizons.
    """
    if grid is None:
        grid = GRIDS[model_name]
    param_names = list(grid.keys())

    per_horizon = {}
    for h in FORECAST_HORIZONS:
        sub = grid_results[grid_results["horizon_h"] == h]
        best = sub.loc[sub["rmse"].idxmin()]
        per_horizon[h] = {k: _py(best[k]) for k in param_names}

    overall_rmse = grid_results.groupby("combo")["rmse"].mean()
    best_combo = overall_rmse.idxmin()
    overall = {k: _py(grid_results.loc[grid_results.combo == best_combo, k].iloc[0])
               for k in param_names}
    return {"per_horizon": per_horizon, "overall": overall}


# =========================================================
# 2. UNSEEN-CITY HOLDOUT (Sialkot is in no training fold)
# =========================================================

def unseen_city_holdout(df, model_name, holdout_city="Sialkot",
                        feature_cols=None, **model_kwargs):
    """
    Train on every city EXCEPT holdout_city; evaluate only on holdout_city.

    This is the roadmap's proof of the city-agnostic claim: the model has
    never seen Sialkot (it is deliberately absent from config.CITIES), so
    any skill it shows there is general atmospheric dynamics, not
    memorisation of one city.

    Baselines (persistence, seasonal naive) are computed ON the holdout
    city only — the fair comparison is "global model vs naive, both
    strangers to the city".

    Returns
    -------
    pd.DataFrame
        One row per (model, horizon): rmse/mae/r2 on the holdout city.
    """
    if feature_cols is None:
        feature_cols = select_features(df)

    train_df = df[df["city"] != holdout_city]
    test_df = df[df["city"] == holdout_city]
    if len(test_df) == 0:
        raise ValueError(f"No rows for holdout city '{holdout_city}' — "
                         f"is it in the data? (It must NOT be in the training cities.)")

    # Fit per-horizon models on ALL non-holdout rows (full history, 10 cities).
    if model_name == "ridge":
        models = train_ridge_models(train_df, feature_cols=feature_cols,
                                    alpha=model_kwargs.get("alpha", 1.0))
    elif model_name == "rf":
        models = train_rf_models(train_df, feature_cols=feature_cols, **model_kwargs)
    elif model_name == "lgbm":
        models = train_lgbm_models(train_df, feature_cols=feature_cols, **model_kwargs)
    else:
        raise ValueError(f"Unknown model '{model_name}' (use ridge|rf|lgbm)")

    preds = pd.DataFrame(index=test_df.index)
    X_test = test_df[feature_cols]
    complete = X_test.notna().all(axis=1)
    for h, model in models.items():
        col = f"{_TARGET_PREFIX}{h}"
        preds[col] = np.nan
        if complete.any():
            preds.loc[complete, col] = model.predict(X_test.loc[complete])

    # Score the global model on the holdout city.
    rows = []
    for h in FORECAST_HORIZONS:
        col = f"{_TARGET_PREFIX}{h}"
        mask = test_df[col].notna() & preds[col].notna()
        from src.training.evaluate import compute_metrics

        rows.append({"model": f"{model_name} (global)", "horizon_h": h,
                     "n": int(mask.sum()),
                     **compute_metrics(test_df.loc[mask, col], preds.loc[mask, col])})

    # Baselines computed on the holdout city only — fair strangers-vs-strangers.
    baselines = evaluate_baselines(test_df)
    for _, r in baselines.iterrows():
        rows.append({"model": f"baseline: {r['baseline']}", "horizon_h": r["horizon_h"],
                     "n": int(r["n"]), "rmse": r["rmse"], "mae": r["mae"], "r2": r["r2"]})

    return pd.DataFrame(rows)


# =========================================================
# 3. CLI
# =========================================================

def _load_data(args):
    """Feature store first, multi-city demo fallback (with Sialkot)."""
    from src.config import CITIES

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

        # 10 training cities + Sialkot as the unseen holdout, so the demo
        # exercises the exact same protocol as the real backfill.
        cities = list(CITIES) + ["Sialkot"]
        df = _demo_data(n_days=args.demo_days, cities=cities)
        logger.warning(f"Running on DEMO data ({len(cities)} cities) — numbers are "
                       "NOT meaningful; run the Day 8 backfill for real results.")

    # Features + targets if the frame doesn't already carry them.
    if "aqi_lag_1h" not in df.columns:
        from src.features.build_features import build_features

        df = build_features(df)
    target_cols = [c for c in df.columns if c.startswith(_TARGET_PREFIX)]
    if not target_cols:
        from src.features.targets import add_targets

        df = add_targets(df)

    # Day 6 leakage gate, re-run before any model selection.
    from src.features.targets import audit_leakage

    audit = audit_leakage(df)
    if not audit["ok"]:
        logger.error(f"Leakage audit FAILED: {audit['issues']}")
        raise SystemExit(1)
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Day 13: walk-forward backtesting, hyperparameter tuning, "
                    "unseen-city holdout."
    )
    parser.add_argument("--model", choices=list(GRIDS), default="lgbm",
                        help="Model to tune + hold out (default lgbm)")
    parser.add_argument("--skip-tune", action="store_true",
                        help="Skip grid search, only run the holdout (uses grid defaults)")
    parser.add_argument("--holdout-city", default="Sialkot",
                        help="Unseen city for the holdout test (default Sialkot)")
    parser.add_argument("--n-splits", type=int, default=4,
                        help="Walk-forward folds for tuning (default 4)")
    parser.add_argument("--demo", action="store_true",
                        help="Force synthetic demo data (10 cities + Sialkot)")
    parser.add_argument("--demo-days", type=int, default=400,
                        help="Demo series length in days (default 400)")
    args = parser.parse_args()

    df = _load_data(args)
    feature_cols = select_features(df)
    logger.info(f"Features ({len(feature_cols)}): {feature_cols}")

    # ---- 1+2. Backtesting + tuning (walk-forward grid search) ----
    best = None
    if not args.skip_tune:
        print("\n" + "=" * 68)
        print(f"GRID SEARCH: {args.model} on walk-forward CV "
              f"({args.n_splits} folds) — mean RMSE per horizon")
        print("=" * 68)
        grid_results = run_grid_search(df, args.model, n_splits=args.n_splits,
                                       feature_cols=feature_cols)
        best = best_combos(grid_results, args.model)

        print("\nBest combo per horizon:")
        for h, params in best["per_horizon"].items():
            rmse = grid_results[
                (grid_results.horizon_h == h)
                & (grid_results.combo == str(params))
            ]["rmse"].iloc[0]
            print(f"  +{h}h: rmse={rmse:6.2f}  {params}")
        print(f"\nBest overall: {best['overall']}")

    # ---- 3. Unseen-city holdout ----
    holdout_params = {}
    if best is not None:
        # Use the OVERALL best combo for the holdout model (single honest
        # model, no cherry-picking per horizon for the proof).
        holdout_params = best["overall"]
    print("\n" + "=" * 68)
    print(f"UNSEEN-CITY HOLDOUT: train on 10 cities, evaluate on "
          f"'{args.holdout_city}' (never seen)")
    print("=" * 68)
    holdout = unseen_city_holdout(df, args.model, holdout_city=args.holdout_city,
                                  feature_cols=feature_cols, **holdout_params)
    pivot = holdout.pivot(index="horizon_h", columns="model",
                          values="rmse").round(1)
    print("\nRMSE on the holdout city (lower is better):")
    print(pivot.to_string())
    print("\nFull metrics:")
    print(holdout.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
