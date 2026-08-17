#!/usr/bin/env python3
"""
revalidate_artifact.py — Day 28: re-score the REGISTERED candidate artifact
(lgbm_v10_local_candidate.joblib = registry v12) on the 60-day holdout and
Sialkot under the CURRENT environment (numpy was upgraded on Day 27).

Why: logs/model_audit_after.json was produced before the numpy 2.x upgrade;
model predictions must be re-confirmed on the artifact that would actually be
promoted, not on a freshly-trained copy.

Read-only: does NOT train, register, or promote.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import PROCESSED_DIR, MODELS_DIR
from src.training.evaluate import (
    compute_metrics, persistence_predictions, seasonal_naive_predictions,
)
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category

STORE_DIR = PROCESSED_DIR / "feature_store_parquet"
HOLDOUT_DAYS = 60
TARGET_PREFIX = "y_"
SIALKOT_PKL = Path("data/raw/sialkot_engineered.pkl")
REFERENCE_MAE = {24: 20, 48: 25, 72: 30}


def mape_safe(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y_true - y_pred) / np.maximum(np.abs(y_true), 1.0)) * 100)


def metrics_frame(df, preds):
    out = {}
    for h in (24, 48, 72):
        col = f"{TARGET_PREFIX}{h}"
        mask = df[col].notna() & preds[col].notna()
        m = compute_metrics(df.loc[mask, col], preds.loc[mask, col])
        m["mape"] = mape_safe(df.loc[mask, col], preds.loc[mask, col])
        m["n"] = int(mask.sum())
        m["mae_target_met"] = m["mae"] <= REFERENCE_MAE[h]
        out[h] = {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()}
    return out


def predict_artifact(models, df, feature_cols):
    X = df[feature_cols]
    return pd.DataFrame(
        {h: models[h].predict(X) for h in (24, 48, 72)},
        index=df.index,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="logs/model_audit_after_v2.json")
    args = ap.parse_args()

    reg = ModelRegistry()
    # v12 = the Q3 candidate (artifact lgbm_v10_local_candidate.joblib)
    entry = None
    for v in reg.list_versions():
        if v["version"] == 12:
            entry = v
            break
    assert entry is not None, "v12 candidate not found in registry"
    models = reg.load("lgbm", 12)[0]
    feature_cols = entry["feature_cols"]
    print(f"Artifact: {entry['artifact']} (v{entry['version']}, status={entry['status']})")
    print(f"feature_cols: {len(feature_cols)}")

    store = pd.concat(
        [pd.read_parquet(f) for f in sorted(STORE_DIR.glob("*.parquet"))],
        ignore_index=True,
    )
    store["date"] = pd.to_datetime(store["date"], utc=True)
    holdout_start = store["date"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    holdout = store[store["date"] >= holdout_start].reset_index(drop=True)
    print(f"Holdout: {len(holdout)} rows from {holdout_start.date()}")

    preds = predict_artifact(models, holdout, feature_cols)
    preds = preds.rename(columns={h: f"{TARGET_PREFIX}{h}" for h in (24, 48, 72)})
    results = {
        "model": "lgbm",
        "artifact": entry["artifact"],
        "trained_on": "< 2026-06-13 (337910 rows)",
        "revalidated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "holdout": metrics_frame(holdout, preds),
    }

    gates = {}
    for h in (24, 48, 72):
        cand = results["holdout"][h]
        pp = metrics_frame(holdout, persistence_predictions(holdout))[h]
        ss = metrics_frame(holdout, seasonal_naive_predictions(holdout))[h]
        gates[h] = {
            "candidate_rmse": cand["rmse"],
            "persistence_rmse": pp["rmse"],
            "seasonal_rmse": ss["rmse"],
            "beats_persistence": cand["rmse"] < pp["rmse"],
            "beats_seasonal_naive": cand["rmse"] < ss["rmse"],
            "mae_target_met": cand["mae_target_met"],
            "reference_mae": REFERENCE_MAE[h],
        }
    results["gates"] = gates
    results["all_hard_gates_pass"] = all(
        g["beats_persistence"] and g["beats_seasonal_naive"] for g in gates.values())

    if SIALKOT_PKL.exists():
        with open(SIALKOT_PKL, "rb") as f:
            sialkot = pickle.load(f)
        sialkot = sialkot.reset_index(drop=True)
        sialkot["date"] = pd.to_datetime(sialkot["date"], utc=True)
        preds_s = predict_artifact(models, sialkot, feature_cols)
        preds_s = preds_s.rename(columns={h: f"{TARGET_PREFIX}{h}" for h in (24, 48, 72)})
        results["sialkot"] = {
            "rows": int(len(sialkot)),
            "horizons": metrics_frame(sialkot, preds_s),
        }
    else:
        results["sialkot"] = {"error": "no sialkot pickle"}

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n===== ARTIFACT v12 RE-VALIDATION (under numpy {np.__version__}) =====")
    for h in (24, 48, 72):
        c = results["holdout"][h]
        g = gates[h]
        print(f"+{h}h: RMSE {c['rmse']} MAE {c['mae']} R2 {c['r2']} MAPE {c['mape']}% "
              f"| beats_persist={g['beats_persistence']} beats_seasonal={g['beats_seasonal_naive']} "
              f"MAE<={g['reference_mae']}={g['mae_target_met']}")
    print(f"ALL HARD GATES PASS: {results['all_hard_gates_pass']}")
    if "horizons" in results.get("sialkot", {}):
        print("SIALKOT:")
        for h in (24, 48, 72):
            s = results["sialkot"]["horizons"][h]
            print(f"  +{h}h: RMSE {s['rmse']} MAE {s['mae']} R2 {s['r2']} MAPE {s['mape']}%")
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
