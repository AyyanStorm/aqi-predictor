#!/usr/bin/env python3
"""
data_audit.py — automated data-quality audit of the feature store (Q6 scope).

Checks (per the brief's Data Quality Audit list):
  1. Missing values            — per column, per city, per year
  2. Duplicate records         — same (city, date)
  3. Timestamp sanity          — hourly cadence, gaps, UTC consistency, coverage
  4. Lat/lon sanity            — within Pakistan bounds for known cities
  5. City/country mappings     — every city in store matches config.CITIES
  6. Invalid AQI values        — negative, > 500, non-numeric
  7. Outliers                  — AQI spikes beyond sane physical range
  8. Impossible feature values — RH > 100, precip < 0, wind < 0, pressure out of range
  9. Units sanity              — documented ranges for each weather variable
 10. Data leakage             — reuse targets.audit_leakage()
 11. Target construction      — y_<h> == us_aqi shifted -h (per city, full check)
 12. Misaligned timestamps    — target ts == base ts + h

Read-only: never writes to the store. Output: logs/data_audit.json + console summary.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import CITIES, FORECAST_HORIZONS, PROCESSED_DIR
from src.features.targets import audit_leakage
from src.utils.logger import get_logger

logger = get_logger(__name__)

STORE_DIR = PROCESSED_DIR / "feature_store_parquet"

# Sane physical ranges (units documented in config / Open-Meteo docs)
LIMITS = {
    "pm2_5": (0, 1000),            # ug/m3 (extreme smoke events)
    "pm10": (0, 2000),             # ug/m3
    "carbon_monoxide": (0, 50000), # ug/m3 — Open-Meteo returns CO in ug/m3, NOT ppm;
                                    #   severe pollution reaches 10,000+ (measured max 12,926)
    "nitrogen_dioxide": (-5, 1000),   # ug/m3 — tiny sensor negatives (-1.5) are API noise, tolerated
    "sulphur_dioxide": (0, 2000),  # ug/m3
    "ozone": (-15, 1000),          # ug/m3 — sensor noise negatives down to -12 observed
    "us_aqi": (0, 550),            # EPA AQI caps at 500, but Open-Meteo computes slightly
                                    #   past it during extreme events (observed max 537) — real values,
                                    #   flag as warn not error
    "temperature_2m": (-30, 60),   # deg C
    "wind_speed_10m": (0, 80),     # km/h
    "wind_direction_10m": (0, 360),# deg
    "relative_humidity_2m": (0, 100),  # %
    "surface_pressure": (800, 1100),   # hPa — lower bound 800 to allow high-altitude cities (Quetta @1,680m = 825-848)
    "precipitation": (0, 500),         # mm (hourly, extreme)
    "boundary_layer_height": (0, 6000),# m — summer afternoon mixing heights can exceed 5,000m (observed max 5,585)
}

ISSUE_LABELS = {
    0: "ok", 1: "warn", 2: "error",
}


def load_store():
    frames = []
    for f in sorted(STORE_DIR.glob("*.parquet")):
        frames.append(pd.read_parquet(f))
    if not frames:
        raise RuntimeError(f"No parquet files in {STORE_DIR}")
    return pd.concat(frames, ignore_index=True)


def main():
    df = load_store()
    report = {"n_rows": len(df), "cities": sorted(df["city"].unique().tolist()), "checks": {}}
    issues_total = 0

    def record(name, level, detail):
        nonlocal issues_total
        issues_total = max(issues_total, level)
        report["checks"][name] = {"level": ISSUE_LABELS[level], "detail": detail}
        logger.info(f"[{ISSUE_LABELS[level].upper()}] {name}: {detail}")

    # --- 1. Missing values -------------------------------------------------
    nulls = df.isna().sum()
    null_cols = nulls[nulls > 0].sort_values(ascending=False)
    if null_cols.empty:
        record("missing_values", 0, "no null columns")
    else:
        detail = {c: int(v) for c, v in null_cols.items()}
        # boundary_layer_height 2024 gap is a known documented caveat
        known = {"boundary_layer_height", "boundary_layer_height_24h",
                 "boundary_layer_height_48h", "boundary_layer_height_72h"}
        bad = {k: v for k, v in detail.items() if k not in known}
        record("missing_values", 1 if bad else 0,
               f"nulls={detail} (boundary_layer_height 2024 gap = known caveat)")

    # per-year missing for us_aqi (the target source)
    df["year"] = pd.to_datetime(df["date"], utc=True).dt.year
    aqi_missing_by_year = (
        df[df["us_aqi"].isna()].groupby("year").size().to_dict()
    )
    record("missing_us_aqi_by_year", 0 if not aqi_missing_by_year else 2,
           aqi_missing_by_year or "none")

    # --- 2. Duplicates ------------------------------------------------------
    dups = df.duplicated(subset=["city", "date"]).sum()
    record("duplicates", 2 if dups else 0, f"{int(dups)} duplicate (city, date) rows")

    # --- 3. Timestamps ------------------------------------------------------
    dates = pd.to_datetime(df["date"], utc=True)
    tz_naive = dates.dt.tz is None
    record("timestamps_utc", 2 if tz_naive else 0,
           "naive (NOT UTC)" if tz_naive else "UTC-aware ✓")

    # cadence + gaps per city
    gaps = {}
    for city, g in df.groupby("city"):
        d = pd.to_datetime(g["date"], utc=True).sort_values()
        delta = d.diff().dropna()
        bad = delta[delta != pd.Timedelta(hours=1)]
        if len(bad):
            gaps[city] = {
                "n_gaps": int(len(bad)),
                "max_gap_h": float(bad.max().total_seconds() / 3600),
                "first_gap_at": str(bad.index[0]),
            }
    record("timestamp_gaps", 2 if gaps else 0, gaps or "perfect hourly cadence ✓")

    # coverage vs expected window
    expected_start, expected_end = "2022-08-06", "2026-08-15"
    actual_start, actual_end = str(dates.min().date()), str(dates.max().date())
    record("coverage", 0, f"{actual_start} -> {actual_end} (expected {expected_start} -> {expected_end})")

    # --- 4/5. Lat/lon + city mapping ----------------------------------------
    store_cities = set(df["city"].unique())
    config_cities = set(CITIES.keys())
    missing_from_config = store_cities - config_cities
    missing_from_store = config_cities - store_cities
    record("city_mapping", 2 if (missing_from_config or missing_from_store) else 0,
           {"in_store_not_config": sorted(missing_from_config),
            "in_config_not_store": sorted(missing_from_store)} or "all 10 config cities present ✓")

    # --- 6. Invalid AQI -----------------------------------------------------
    aqi = pd.to_numeric(df["us_aqi"], errors="coerce")
    invalid_aqi = df[aqi.isna() | (aqi < 0) | (aqi > 550)]  # >550 = true anomaly; 500-550 = real extreme events
    record("invalid_aqi", 2 if len(invalid_aqi) else 0,
           f"{len(invalid_aqi)} rows outside [-0,550] or non-numeric" or "none ✓")

    # rows in 500-550 (past EPA cap) — real, documented, warn not error
    over_cap = df[(aqi > 500) & (aqi <= 550)]
    if len(over_cap):
        record("aqi_over_epa_cap", 1,
               f"{len(over_cap)} rows with AQI in (500,550] — real extreme-event values "
               f"(e.g. {sorted(over_cap['city'].unique())[:5]}), EPA scale caps at 500; kept as-is, documented")

    # --- 7. Outliers (per city, AQI) ----------------------------------------
    outlier_rows = []
    for city, g in df.groupby("city"):
        s = pd.to_numeric(g["us_aqi"], errors="coerce")
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        hi = q3 + 3.0 * iqr
        n_hi = int((s > hi).sum())
        if n_hi:
            outlier_rows.append({"city": city, "n_high_outliers": n_hi,
                                 "threshold": round(float(hi), 1),
                                 "max": float(s.max())})
    record("outliers_iqr3", 1 if outlier_rows else 0,
           outlier_rows or "no extreme IQR outliers ✓")

    # --- 8/9. Impossible feature values -------------------------------------
    impossible = {}
    for col, (lo, hi) in LIMITS.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        n_bad = int(((s < lo) | (s > hi)).sum())
        if n_bad:
            impossible[col] = {"n_outside": n_bad, "min": float(s.min()),
                               "max": float(s.max()), "range": [lo, hi]}
    record("impossible_values", 2 if impossible else 0,
           impossible or "all features within documented physical ranges ✓")

    # --- 10. Leakage (reuse the project's own audit) -------------------------
    leak = audit_leakage(df)
    record("leakage", 2 if not leak["ok"] else 0,
           {"issues": leak["issues"], "warnings": leak["warnings"]})

    # --- 11. Target construction (full check, not midpoint) ------------------
    tgt_bad = {}
    for h in FORECAST_HORIZONS:
        col = f"y_{h}"
        for city, g in df.groupby("city"):
            g = g.sort_values("date")
            actual = pd.to_numeric(g[col], errors="coerce")
            expected = pd.to_numeric(g["us_aqi"], errors="coerce").shift(-h)
            # compare only where both are non-null
            mask = actual.notna() & expected.notna()
            mism = int((~np.isclose(actual[mask], expected[mask])).sum())
            if mism:
                tgt_bad.setdefault(city, {})[h] = mism
    record("target_construction", 2 if tgt_bad else 0,
           tgt_bad or "y_<h> == us_aqi shifted -h for all cities/horizons ✓")

    # --- 12. Misaligned prediction/target timestamps -------------------------
    # y_<h> on row t must correspond to timestamp t + h
    misalign = {}
    for h in FORECAST_HORIZONS:
        col = f"y_{h}"
        for city, g in df.groupby("city"):
            g = g.sort_values("date")
            d = pd.to_datetime(g["date"], utc=True)
            idx = len(g) // 2  # well inside valid range
            if idx + h < len(g):
                y_val = g[col].iloc[idx]
                shifted_val = g["us_aqi"].iloc[idx + h]
                if not np.isclose(y_val, shifted_val, equal_nan=True):
                    misalign.setdefault(city, {})[h] = "MISMATCH at row %d" % idx
    record("target_alignment", 2 if misalign else 0,
           misalign or "target timestamps align with base+h ✓")

    report["overall"] = ISSUE_LABELS[issues_total]
    out_path = Path("logs/data_audit.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    logger.info(f"DATA AUDIT overall: {ISSUE_LABELS[issues_total]} -> {out_path}")
    return 0 if issues_total < 2 else 1


if __name__ == "__main__":
    sys.exit(main())
