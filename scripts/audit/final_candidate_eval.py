#!/usr/bin/env python3
"""
final_candidate_eval.py — train the SELECTED model on all data strictly
before the 60-day holdout, then evaluate it on:
  1. the holdout itself (Q3 hard gates + reference MAE targets)
  2. Sialkot (generalization proof, NOT a gate)

Usage: python3 scripts/audit/final_candidate_eval.py --model lgbm [--out logs/model_audit_after.json]

The winner name comes from model_select.json by default. Read-only w.r.t.
the registry — does NOT register or promote (that's a manual, gated step).
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import PROCESSED_DIR
from src.training.evaluate import (
    compute_metrics, persistence_predictions, seasonal_naive_predictions,
)
from src.training.train import (
    ridge_fit_predict, rf_fit_predict, lgbm_fit_predict, select_features,
)
from src.utils.aqi_utils import aqi_category
from src.utils.logger import get_logger

logger = get_logger(__name__)

STORE_DIR = PROCESSED_DIR / "feature_store_parquet"
HOLDOUT_DAYS = 60
TARGET_PREFIX = "y_"
SIALKOT_PKL = Path("data/raw/sialkot_engineered.pkl")
REFERENCE_MAE = {24: 20, 48: 25, 72: 30}

FITTERS = {
    "ridge": (lambda tr, va, fc: ridge_fit_predict(tr, va, feature_cols=fc)),
    "rf": (lambda tr, va, fc: rf_fit_predict(tr, va, feature_cols=fc, n_estimators=300)),
    "lgbm": (lambda tr, va, fc: lgbm_fit_predict(
        tr, va, feature_cols=fc, n_estimators=500,
        learning_rate=0.05, num_leaves=31, min_child_samples=20)),
}


def load_store():
    frames = [pd.read_parquet(f) for f in sorted(STORE_DIR.glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


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


def per_city(df, preds):
    rows = []
    for city, g in df.groupby("city"):
        for h in (24, 48, 72):
            col = f"{TARGET_PREFIX}{h}"
            mask = g[col].notna() & preds[col].notna()
            if mask.sum() == 0:
                continue
            m = compute_metrics(g.loc[mask, col], preds.loc[mask, col])
            rows.append({"city": city, "horizon_h": h, "n": int(mask.sum()),
                         "mae": round(m["mae"], 2), "rmse": round(m["rmse"], 2)})
    return pd.DataFrame(rows).to_dict("records")


def per_band(df, preds):
    rows = []
    for h in (24, 48, 72):
        col = f"{TARGET_PREFIX}{h}"
        tmp = df[["city", col]].copy()
        tmp["pred"] = preds[col]
        tmp = tmp.dropna()
        tmp["band"] = tmp[col].map(aqi_category)
        for band, g in tmp.groupby("band"):
            m = compute_metrics(g[col], g["pred"])
            rows.append({"horizon_h": h, "band": band, "n": int(len(g)),
                         "mae": round(m["mae"], 2), "rmse": round(m["rmse"], 2)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="ridge|rf|lgbm (default: winner from model_select.json)")
    ap.add_argument("--out", default="logs/model_audit_after.json")
    args = ap.parse_args()

    if args.model is None:
        sel = json.load(open("logs/model_select.json"))
        args.model = sel["winner"]
    assert args.model in FITTERS, f"unknown model {args.model}"
    fit_predict = FITTERS[args.model]

    store = load_store()
    holdout_start = store["date"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train = store[store["date"] < holdout_start]
    holdout = store[store["date"] >= holdout_start]
    feature_cols = select_features(train)
    logger.info(f"Training {args.model} on {len(train)} rows (strictly before "
                f"{holdout_start.date()}); holdout={len(holdout)} rows")

    # Train on ALL pre-holdout data (single fit), then predict holdout.
    # NOTE: keep the unique RangeIndex (NO set_index("date")) — the store
    # has duplicate timestamps across 10 cities, and boolean .loc on a
    # non-unique DatetimeIndex raises IndexError in per_city().
    preds = fit_predict(train, holdout, feature_cols)
    preds = preds.rename(columns={h: f"{TARGET_PREFIX}{h}" for h in (24, 48, 72)})

    results = {
        "model": args.model,
        "trained_on": f"< {holdout_start.date()} ({len(train)} rows)",
        "holdout": metrics_frame(holdout, preds),
        "per_city": per_city(holdout, preds),
        "per_band": per_band(holdout, preds),
    }

    # baselines + gates
    gates = {}
    for h in (24, 48, 72):
        cand = results["holdout"][h]
        pp = persistence_predictions(holdout)
        ss = seasonal_naive_predictions(holdout)
        p = metrics_frame(holdout, pp)[h]
        s = metrics_frame(holdout, ss)[h]
        gates[h] = {
            "candidate_rmse": cand["rmse"],
            "persistence_rmse": p["rmse"],
            "seasonal_rmse": s["rmse"],
            "beats_persistence": cand["rmse"] < p["rmse"],
            "beats_seasonal_naive": cand["rmse"] < s["rmse"],
            "mae_target_met": cand["mae_target_met"],
            "reference_mae": REFERENCE_MAE[h],
        }
    results["gates"] = gates
    results["all_hard_gates_pass"] = all(
        g["beats_persistence"] and g["beats_seasonal_naive"] for g in gates.values())

    # Sialkot (non-gate)
    if SIALKOT_PKL.exists():
        with open(SIALKOT_PKL, "rb") as f:
            sialkot = pickle.load(f)
        sialkot = sialkot.reset_index(drop=False)  # unique RangeIndex, like train/holdout
        sialkot["date"] = pd.to_datetime(sialkot["date"], utc=True)
        preds_s = fit_predict(train, sialkot, feature_cols)
        preds_s = preds_s.rename(columns={h: f"{TARGET_PREFIX}{h}" for h in (24, 48, 72)})
        results["sialkot"] = {
            "rows": int(len(sialkot)),
            "horizons": metrics_frame(sialkot, preds_s),
            "per_band": per_band(sialkot, preds_s),
        }
    else:
        results["sialkot"] = {"error": "no sialkot pickle"}

    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n===== FINAL CANDIDATE ({args.model}) on holdout =====")
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
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
