#!/usr/bin/env python3
"""
model_select.py — model SELECTION on data strictly BEFORE the 60-day holdout.

Q2/Q3 locked rule: walk-forward CV = model-selection tool ONLY, and
"nothing from the holdout may influence model selection". So selection
runs on date < holdout_start; the winner is later evaluated on the
holdout + Sialkot by final_candidate_eval.py (the final verdict).

Compares Ridge vs RandomForest vs LightGBM on the SAME walk-forward
folds (apples-to-apples). RF is optional (--models rf) because 300 trees
x 3 horizons x 4 folds on up to 253k rows is heavy. Output:
logs/model_select.json + console table. Read-only (no registry writes).
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import PROCESSED_DIR
from src.features.targets import walk_forward_split
from src.training.evaluate import (
    compute_metrics, evaluate_baselines,
)
from src.training.train import (
    ridge_fit_predict, rf_fit_predict, lgbm_fit_predict, select_features,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

STORE_DIR = PROCESSED_DIR / "feature_store_parquet"
HOLDOUT_DAYS = 60
TARGET_PREFIX = "y_"

ALL_CANDIDATES = {
    "ridge": (lambda tr, va, fc: ridge_fit_predict(tr, va, feature_cols=fc), {}),
    "rf": (lambda tr, va, fc: rf_fit_predict(tr, va, feature_cols=fc, n_estimators=300), {}),
    "lgbm": (lambda tr, va, fc: lgbm_fit_predict(
        tr, va, feature_cols=fc, n_estimators=500,
        learning_rate=0.05, num_leaves=31, min_child_samples=20), {}),
}


def load_store():
    frames = [pd.read_parquet(f) for f in sorted(STORE_DIR.glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="ridge,lgbm",
                    help="comma-separated subset of ridge,rf,lgbm (default ridge,lgbm — RF is slow)")
    args = ap.parse_args()
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    candidates = {k: v for k, v in ALL_CANDIDATES.items() if k in wanted}
    assert candidates, "no valid models selected"

    store = load_store()
    holdout_start = store["date"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    sel = store[store["date"] < holdout_start].copy()
    sel = sel.set_index("date").sort_index()
    logger.info(f"Selection window: {sel.index.min()} -> {sel.index.max()} "
                f"({len(sel)} rows, strictly before holdout {holdout_start.date()})")

    feature_cols = select_features(sel)
    logger.info(f"Features ({len(feature_cols)})")

    baselines = evaluate_baselines(sel)
    logger.info("Baselines evaluated")

    results = {"selection_window": {"start": str(sel.index.min().date()),
                                    "end": str(sel.index.max().date()),
                                    "rows": int(len(sel))},
               "baselines": {}, "models": {}}

    for name, (fit_predict, _) in candidates.items():
        logger.info(f"Running walk-forward for {name}...")
        res = []
        for train_df, valid_df, cut in walk_forward_split(
                sel, horizons=[24, 48, 72], n_splits=4, gap_hours=72):
            preds = fit_predict(train_df, valid_df, feature_cols)
            preds = preds.rename(columns={h: f"{TARGET_PREFIX}{h}" for h in [24, 48, 72]})
            for h in [24, 48, 72]:
                col = f"{TARGET_PREFIX}{h}"
                mask = valid_df[col].notna() & preds[col].notna()
                m = compute_metrics(valid_df.loc[mask, col], preds.loc[mask, col])
                m["mape"] = float(
                    (abs(valid_df.loc[mask, col] - preds.loc[mask, col])
                     / valid_df.loc[mask, col].abs().clip(lower=1.0)).mean() * 100)
                res.append({"fold_cut": str(cut.date()), "horizon_h": h,
                            "n": int(mask.sum()), **{k: round(v, 3) for k, v in m.items()}})
        df_res = pd.DataFrame(res)
        mean = (df_res.groupby("horizon_h")[["rmse", "mae", "r2"]]
                .mean().round(3).reset_index())
        results["models"][name] = {
            "per_fold": df_res.to_dict("records"),
            "mean_per_horizon": mean.to_dict("records"),
        }
        logger.info(f"{name} done")

    for _, row in baselines.iterrows():
        results["baselines"].setdefault(row["baseline"], {})[int(row["horizon_h"])] = {
            "rmse": round(float(row["rmse"]), 3), "mae": round(float(row["mae"]), 3),
            "r2": round(float(row["r2"]), 3)}

    for name, d in results["models"].items():
        rows = d["mean_per_horizon"]
        d["selection_score_rmse"] = round(
            sum(r["rmse"] for r in rows) / len(rows), 3)
    winner = min(results["models"].items(),
                 key=lambda kv: kv[1]["selection_score_rmse"])[0]
    results["winner"] = winner

    out = Path("logs/model_select.json")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("\n===== MODEL SELECTION (before holdout) =====")
    print(f"Window: {results['selection_window']['start']} -> "
          f"{results['selection_window']['end']} ({results['selection_window']['rows']} rows)")
    for name, d in results["models"].items():
        print(f"\n{name.upper()} — mean walk-forward RMSE: {d['selection_score_rmse']}")
        for r in d["mean_per_horizon"]:
            print(f"  +{r['horizon_h']}h: RMSE {r['rmse']} MAE {r['mae']} R2 {r['r2']}")
    print(f"\nWINNER: {results['winner']}")
    print(f"Baselines (floor): {json.dumps(results['baselines'])}")
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
