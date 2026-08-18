#!/usr/bin/env python3
"""
model_audit.py — model accuracy audit on the CLEAN 60-day temporal holdout
+ Sialkot generalization set, wired to the pre-declared Q3 gates.

Gates (LOCKED, from docs/AUDIT_PLAN.md Q3 — hard gates, per horizon):
  1. candidate beats persistence
  2. candidate beats seasonal-naive
  3. candidate beats incumbent v6
  + reporting-only MAE targets: 24h<=20, 48h<=25, 72h<=30
  + Sialkot = separate generalization eval, NOT a gate.

Also reports per-city and per-AQI-band breakdowns (no single overall number
hiding weaknesses). Read-only: never writes to the store or registry.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import FORECAST_HORIZONS, PROCESSED_DIR
from src.training.evaluate import (
    compute_metrics, persistence_predictions, seasonal_naive_predictions,
)
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category
from src.utils.logger import get_logger

logger = get_logger(__name__)

STORE_DIR = PROCESSED_DIR / "feature_store_parquet"
HOLDOUT_DAYS = 60
TARGET_PREFIX = "y_"
SIALKOT_PKL = Path("data/raw/sialkot_engineered.pkl")

# Reporting-only reference targets (Q3, LOCKED)
REFERENCE_MAE = {24: 20, 48: 25, 72: 30}


def load_store():
    frames = [pd.read_parquet(f) for f in sorted(STORE_DIR.glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def mape_safe(y_true, y_pred):
    """MAPE with denominator guard (AQI can be near zero)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.maximum(np.abs(y_true), 1.0)
    return float(np.mean(np.abs(y_true - y_pred) / denom) * 100)


def score_frame(df, preds, horizons=FORECAST_HORIZONS):
    """Per-horizon metrics for one eval frame + its predictions."""
    out = {}
    for h in horizons:
        col = f"{TARGET_PREFIX}{h}"
        mask = df[col].notna() & preds[col].notna()
        y_true = df.loc[mask, col]
        y_pred = preds.loc[mask, col]
        m = compute_metrics(y_true, y_pred)
        m["mape"] = mape_safe(y_true, y_pred)
        m["n"] = int(mask.sum())
        m["mae_target_met"] = m["mae"] <= REFERENCE_MAE[h]
        out[h] = {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()}
    return out


def per_city(df, preds):
    rows = []
    for city, g in df.groupby("city"):
        for h in FORECAST_HORIZONS:
            col = f"{TARGET_PREFIX}{h}"
            mask = g[col].notna() & preds[col].notna()
            if mask.sum() == 0:
                continue
            m = compute_metrics(g.loc[mask, col], preds.loc[mask, col])
            rows.append({"city": city, "horizon_h": h, "n": int(mask.sum()),
                         "mae": round(m["mae"], 2), "rmse": round(m["rmse"], 2)})
    return pd.DataFrame(rows)


def per_band(df, preds):
    rows = []
    for h in FORECAST_HORIZONS:
        col = f"{TARGET_PREFIX}{h}"
        tmp = df[["city", col]].copy()
        tmp["pred"] = preds[col]
        tmp = tmp.dropna()
        tmp["band"] = tmp[col].map(aqi_category)
        for band, g in tmp.groupby("band"):
            m = compute_metrics(g[col], g["pred"])
            rows.append({"horizon_h": h, "band": band, "n": int(len(g)),
                         "mae": round(m["mae"], 2), "rmse": round(m["rmse"], 2)})
    return pd.DataFrame(rows)


def model_predictions(df, model_set, feature_cols):
    """Predictions DataFrame from a registry model set, aligned to df.index."""
    preds = pd.DataFrame(index=df.index)
    for h in FORECAST_HORIZONS:
        model = model_set[h]
        X = df[feature_cols]
        preds[f"{TARGET_PREFIX}{h}"] = model.predict(X)
    return preds


def main():
    store = load_store()
    holdout_start = store["date"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train = store[store["date"] < holdout_start]
    holdout = store[store["date"] >= holdout_start]
    logger.info(f"Store {store['date'].min().date()} -> {store['date'].max().date()}; "
                f"holdout from {holdout_start.date()}: train={len(train)}, holdout={len(holdout)}")

    # --- load production model (v6) ---
    registry = ModelRegistry()
    model_set, entry = registry.load("lgbm")  # version=None -> production
    feature_cols = entry["feature_cols"]
    model_name = f"{entry['name']}_v{entry['version']}"
    logger.info(f"Loaded {model_name}, {len(feature_cols)} features, "
                f"trained {entry.get('created_at', '?')}")

    # --- baselines + v6 on holdout ---
    preds_persist = persistence_predictions(holdout)
    preds_seas = seasonal_naive_predictions(holdout)
    preds_v6 = model_predictions(holdout, model_set, feature_cols)

    results = {
        "model": model_name,
        "holdout_days": HOLDOUT_DAYS,
        "holdout_start": str(holdout_start.date()),
        "holdout_rows": int(len(holdout)),
        "train_rows": int(len(train)),
        "horizons": {},
    }
    for h in FORECAST_HORIZONS:
        results["horizons"][h] = {
            "persistence": score_frame(holdout, preds_persist)[h],
            "seasonal_naive": score_frame(holdout, preds_seas)[h],
            "v6": score_frame(holdout, preds_v6)[h],
        }

    # --- GATES (Q3, LOCKED) ---
    gates = {}
    for h in FORECAST_HORIZONS:
        v6 = results["horizons"][h]["v6"]
        p = results["horizons"][h]["persistence"]
        s = results["horizons"][h]["seasonal_naive"]
        gates[h] = {
            "beats_persistence": v6["rmse"] < p["rmse"],
            "beats_seasonal_naive": v6["rmse"] < s["rmse"],
            "mae_target_met": v6["mae_target_met"],
            "reference_mae": REFERENCE_MAE[h],
        }
    results["gates_v6_on_holdout"] = gates
    results["all_hard_gates_pass"] = all(
        g["beats_persistence"] and g["beats_seasonal_naive"] for g in gates.values()
    )

    # --- per-city / per-band breakdowns for v6 ---
    results["per_city_v6"] = per_city(holdout, preds_v6).to_dict("records")
    results["per_band_v6"] = per_band(holdout, preds_v6).to_dict("records")

    # --- Sialkot (separate generalization eval, NOT a gate) ---
    if SIALKOT_PKL.exists():
        with open(SIALKOT_PKL, "rb") as f:
            sialkot = pickle.load(f)
        sialkot = sialkot.reset_index(drop=False)
        sialkot["date"] = pd.to_datetime(sialkot["date"], utc=True)
        # v6 needs the trained feature cols; Sialkot frame has them
        if set(feature_cols).issubset(sialkot.columns):
            preds_s = model_predictions(sialkot, model_set, feature_cols)
            results["sialkot"] = {
                "rows": int(len(sialkot)),
                "horizons": score_frame(sialkot, preds_s),
                "per_band_v6": per_band(sialkot, preds_s).to_dict("records"),
            }
            # baselines for context on Sialkot too
            ps = persistence_predictions(sialkot)
            ss = seasonal_naive_predictions(sialkot)
            results["sialkot"]["baselines"] = {
                h: {"persistence": score_frame(sialkot, ps)[h],
                    "seasonal_naive": score_frame(sialkot, ss)[h]}
                for h in FORECAST_HORIZONS
            }
        else:
            missing = set(feature_cols) - set(sialkot.columns)
            results["sialkot"] = {"error": f"missing feature cols: {sorted(missing)[:10]}"}
    else:
        results["sialkot"] = {"error": f"{SIALKOT_PKL} not found"}

    out_path = Path("logs/model_audit_before.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # --- console summary ---
    print(f"\n===== MODEL AUDIT (before) — {model_name} on {HOLDOUT_DAYS}-day holdout =====")
    print(f"Holdout: {results['holdout_start']} -> {store['date'].max().date()} "
          f"({len(holdout)} rows) | train: {len(train)} rows")
    for h in FORECAST_HORIZONS:
        row = results["horizons"][h]
        print(f"\n+{h}h  persistence: RMSE {row['persistence']['rmse']} | "
              f"seasonal: {row['seasonal_naive']['rmse']} | v6: {row['v6']['rmse']} "
              f"(MAE {row['v6']['mae']}, R2 {row['v6']['r2']}, MAPE {row['v6']['mape']}%, n={row['v6']['n']})")
        g = gates[h]
        print(f"   gates: beats_persistence={g['beats_persistence']} "
              f"beats_seasonal={g['beats_seasonal_naive']} "
              f"MAE<={g['reference_mae']} met={g['mae_target_met']}")
    print(f"\nALL HARD GATES PASS: {results['all_hard_gates_pass']}")
    if "sialkot" in results and "horizons" in results["sialkot"]:
        print("\nSIALKOT (unseen city):")
        for h in FORECAST_HORIZONS:
            s = results["sialkot"]["horizons"][h]
            print(f"  +{h}h v6: RMSE {s['rmse']} MAE {s['mae']} R2 {s['r2']} MAPE {s['mape']}% (n={s['n']})")
    print(f"\nsaved -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
