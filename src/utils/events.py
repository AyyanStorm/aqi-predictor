"""
events.py — pollution event detection on historical AQI (unique feature #2).

The 4-year backfill is a flat table of numbers. This module turns it into
a STORY: for every city it finds the moments that mattered, so the
dashboard (Day 19+) can annotate trend charts with them and the report
can quote real events instead of abstract statistics.

Data is REAL by default. `main()` loads it with a cascade:
    1. Feature Store (Hopsworks, or the Parquet fallback)
    2. data/raw/ CSVs written by the Day 8 backfill
    3. a LIVE Open-Meteo fetch (same client as the backfill) —
       so the tool works even on a fresh clone with no local data.
Pass --demo only to run the synthetic smoke test (injected events).

Two detector types, both derived ONLY from the hourly `us_aqi` column
(no extra data, no targets — so it runs straight on a Feature Store
frame or a raw ingestion frame):

    episode  — sustained unhealthy air: the daily mean stays at or above
               the US EPA "Unhealthy" level (150) for N+ consecutive
               days. In Pakistan's smog window (Oct–Feb) these are the
               winter smog episodes that blanket the Punjab belt.
    spike    — a sharp, short peak: hourly AQI crosses "Very Unhealthy"
               (200) AND climbed at least MIN_SPIKE_RISE points within
               the previous 24h — crop-burning and fireworks events.

Output: one tidy DataFrame (city, event_type, start, end, peak_aqi,
duration_h, smog_season) that the dashboard filters by city and the
report aggregates per city.

The US EPA thresholds live in config.py — the same constants the
dashboard's colour bands and health messages will use on Day 19
(single source of truth, roadmap structural rule 1).
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.config import (
    AQI_UNHEALTHY,
    AQI_VERY_UNHEALTHY,
    AIR_QUALITY_URL,
    CITIES,
    HISTORICAL_START_DATE,
    RAW_DIR,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

MIN_EPISODE_DAYS = 2     # at least 2 consecutive days of unhealthy air
MIN_SPIKE_RISE = 100     # AQI points climbed within the spike window
SPIKE_WINDOW_H = 24      # how fast the spike must happen
SMOG_SEASON_MONTHS = {10, 11, 12, 1, 2}  # Oct–Feb: Pakistan's smog window

_EVENT_COLUMNS = [
    "city", "event_type", "start", "end", "peak_aqi", "duration_h", "smog_season",
]


# =========================================================
# 1. EPISODE DETECTION (sustained unhealthy air)
# =========================================================

def detect_episodes(city_series, min_days=MIN_EPISODE_DAYS, threshold=AQI_UNHEALTHY):
    """
    Find runs of consecutive days whose mean AQI >= threshold.

    Parameters
    ----------
    city_series : pd.Series
        Hourly us_aqi for ONE city, DatetimeIndex, ascending.
    min_days : int
        Minimum run length (in days) to count as an episode.
    threshold : float
        Daily-mean AQI level that defines "unhealthy air".

    Returns
    -------
    list[dict] : one dict per episode with start/end (timestamps),
        peak daily mean, duration in days.
    """
    daily = city_series.resample("D").mean().dropna()
    unhealthy = daily >= threshold

    episodes = []
    run_start = None
    for day, is_unhealthy in unhealthy.items():
        if is_unhealthy and run_start is None:
            run_start = day
        elif not is_unhealthy and run_start is not None:
            run_end = day - pd.Timedelta(days=1)
            if (run_end - run_start).days + 1 >= min_days:
                window = daily.loc[run_start:run_end]
                episodes.append({
                    "start": run_start,
                    "end": run_end,
                    "peak_aqi": float(window.max()),
                    "duration_h": int(len(window) * 24),
                })
            run_start = None
    # flush a run that reaches the end of the series
    if run_start is not None:
        window = daily.loc[run_start:]
        if (window.index[-1] - run_start).days + 1 >= min_days:
            episodes.append({
                "start": run_start,
                "end": window.index[-1],
                "peak_aqi": float(window.max()),
                "duration_h": int(len(window) * 24),
            })
    return episodes


# =========================================================
# 2. SPIKE DETECTION (sharp short peaks)
# =========================================================

def detect_spikes(city_series, min_rise=MIN_SPIKE_RISE,
                  threshold=AQI_VERY_UNHEALTHY, window_h=SPIKE_WINDOW_H):
    """
    Find short, sharp peaks: AQI >= threshold AND it rose >= min_rise
    points within the previous `window_h` hours (a 24h window captures
    crop-burning and fireworks events; a slow seasonal climb does NOT
    qualify — it is an episode, not a spike).

    Parameters
    ----------
    city_series : pd.Series
        Hourly us_aqi for ONE city, DatetimeIndex, ascending.
    min_rise : float
        Minimum rise (in AQI points) within the window.
    threshold : float
        Absolute AQI level the peak must reach.
    window_h : int
        Look-back window for the rise.

    Returns
    -------
    list[dict] : one dict per spike event.
    """
    series = city_series.dropna()
    if len(series) < window_h:
        return []

    # rolling min over the window ENDING at each hour (backward-looking —
    # never peeks at the future, consistent with the project's leakage rule)
    rolling_min = series.rolling(window_h, min_periods=1).min()
    spike_mask = (series >= threshold) & (series - rolling_min >= min_rise)

    # cluster consecutive spike hours into single events
    spikes = []
    in_run = False
    for ts, is_spike in spike_mask.items():
        if is_spike and not in_run:
            run_start = ts
            in_run = True
        elif not is_spike and in_run:
            window = series.loc[run_start:ts - pd.Timedelta(hours=1)]
            spikes.append({
                "start": run_start,
                "end": ts - pd.Timedelta(hours=1),
                "peak_aqi": float(window.max()),
                "duration_h": int(len(window)),
            })
            in_run = False
    if in_run:
        window = series.loc[run_start:]
        spikes.append({
            "start": run_start,
            "end": window.index[-1],
            "peak_aqi": float(window.max()),
            "duration_h": int(len(window)),
        })
    return spikes


# =========================================================
# 3. COMBINED PER-CITY DETECTION
# =========================================================

def detect_events(df, cities=None):
    """
    Run both detectors over every city in the frame.

    Parameters
    ----------
    df : pd.DataFrame
        Must have a DatetimeIndex, a 'city' column and a 'us_aqi' column
        (same contract as build_features.py).
    cities : list[str] | None
        Restrict detection to these cities. None = all cities in df.

    Returns
    -------
    pd.DataFrame : one row per event with columns
        city, event_type, start, end, peak_aqi, duration_h, smog_season.
        Sorted by (city, start). Empty DataFrame if nothing is detected.
    """
    required = {"city", "us_aqi"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df must have columns {required}; missing: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex (hourly, ascending)")

    if cities is None:
        cities = df["city"].unique()

    rows = []
    for city in cities:
        series = df.loc[df["city"] == city, "us_aqi"].sort_index()
        for ev in detect_episodes(series):
            rows.append({
                "city": city,
                "event_type": "episode",
                "start": ev["start"],
                "end": ev["end"],
                "peak_aqi": ev["peak_aqi"],
                "duration_h": ev["duration_h"],
                "smog_season": ev["start"].month in SMOG_SEASON_MONTHS,
            })
        for ev in detect_spikes(series):
            rows.append({
                "city": city,
                "event_type": "spike",
                "start": ev["start"],
                "end": ev["end"],
                "peak_aqi": ev["peak_aqi"],
                "duration_h": ev["duration_h"],
                "smog_season": ev["start"].month in SMOG_SEASON_MONTHS,
            })

    events = pd.DataFrame(rows, columns=_EVENT_COLUMNS)
    if not events.empty:
        events = events.sort_values(["city", "start"]).reset_index(drop=True)
    logger.info(f"Detected {len(events)} events across {len(cities)} cities")
    return events


def event_summary(events):
    """
    Per-city roll-up for the report/dashboard: count of episodes and
    spikes, plus the worst peak AQI seen. Takes detect_events() output.
    Sorted by worst_peak_aqi DESCENDING so the most polluted city leads
    (the dashboard's "worst city right now" leaderboard uses the same
    ordering idea on Day 19).
    """
    if events.empty:
        return pd.DataFrame(
            columns=["city", "n_episodes", "n_spikes", "worst_peak_aqi"]
        )
    summary = (
        events.groupby("city")
        .agg(
            n_episodes=("event_type", lambda s: (s == "episode").sum()),
            n_spikes=("event_type", lambda s: (s == "spike").sum()),
            worst_peak_aqi=("peak_aqi", "max"),
        )
        .reset_index()
        .sort_values("worst_peak_aqi", ascending=False)
        .reset_index(drop=True)
    )
    return summary


def worst_city(events):
    """
    Return the city with the single worst peak AQI across all events
    (ties broken by total event count). Returns (city, worst_peak_aqi)
    or (None, None) when there are no events.
    """
    if events.empty:
        return None, None
    summary = event_summary(events)
    top = summary.iloc[0]
    return top["city"], float(top["worst_peak_aqi"])


# =========================================================
# 4. REAL DATA LOADING (Feature Store -> raw CSVs -> live API)
# =========================================================

def _to_detection_frame(df):
    """Normalise any real-data frame to the detect_events() contract:
    DatetimeIndex + 'city' + 'us_aqi' columns. Works for Feature Store
    frames (date column), raw backfill CSVs, and live API responses."""
    if df is None or df.empty:
        return df
    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date")
    df = df.sort_index()
    keep = [c for c in ("city", "us_aqi") if c in df.columns]
    return df[keep]


def load_store_data(cities=None):
    """Read REAL engineered data from the Feature Store (Hopsworks when
    configured, Parquet fallback otherwise). Empty frame -> not available."""
    from src.features.feature_store import get_feature_store

    store = get_feature_store()
    df = store.read_features(cities=cities)
    if df.empty:
        logger.warning("Feature Store is empty (backfill not run?) — falling through")
        return df
    logger.info(f"Loaded {len(df)} rows from Feature Store")
    return _to_detection_frame(df)


def load_raw_csv(cities=None):
    """Read the REAL raw backfill CSVs: data/raw/all_cities_historical.csv
    if present, else every data/raw/<city>_historical.csv."""
    combined = RAW_DIR / "all_cities_historical.csv"
    if combined.exists():
        df = pd.read_csv(combined)
    else:
        files = sorted(RAW_DIR.glob("*_historical.csv"))
        frames = [pd.read_csv(path) for path in files]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        logger.warning("No raw CSVs found — falling through to live API")
        return df
    if cities is not None:
        df = df[df["city"].isin(cities)]
    logger.info(f"Loaded {len(df)} rows from raw CSVs")
    return _to_detection_frame(df)


def load_live_api(cities=None, start_date=None, end_date=None):
    """Fetch REAL data straight from Open-Meteo — the same client and
    chunking the Day 8 backfill uses, so it works on a fresh clone with
    zero local data. Requests are cached 1h by the shared client."""
    from src.data_ingestion.historical_backfill import _fetch_city_chunked
    from src.data_ingestion.open_meteo_client import fetch_air_quality

    if cities is None:
        cities = list(CITIES.keys())
    if start_date is None:
        start_date = HISTORICAL_START_DATE
    if end_date is None:
        end_date = (date.today() - timedelta(days=1)).isoformat()

    frames = []
    for city in cities:
        coords = CITIES[city]
        aqi = _fetch_city_chunked(
            coords["lat"], coords["lon"], start_date, end_date,
            AIR_QUALITY_URL, fetch_air_quality, "aqi",
        )
        aqi["city"] = city
        frames.append(aqi[["date", "city", "us_aqi"]])
    df = pd.concat(frames, ignore_index=True)
    logger.info(f"Fetched {len(df)} rows live from Open-Meteo ({len(cities)} cities)")
    return _to_detection_frame(df)


def load_real_data(cities=None, source="auto", start_date=None, end_date=None):
    """Cascade loader — REAL data only: Feature Store -> raw CSVs ->
    live Open-Meteo. `source` forces one of {'store', 'csv', 'api'}."""
    if source == "store":
        return load_store_data(cities)
    if source == "csv":
        return load_raw_csv(cities)
    if source == "api":
        return load_live_api(cities, start_date, end_date)

    df = load_store_data(cities)
    if not df.empty:
        return df
    df = load_raw_csv(cities)
    if not df.empty:
        return df
    return load_live_api(cities, start_date, end_date)


# =========================================================
# 5. CLI — REAL data by default; --demo for the synthetic smoke test
# =========================================================

def _demo_data(n_days=400, cities=None):
    """
    Synthetic hourly AQI with two KNOWN injected events per city, so the
    detectors can be eyeballed (and tested) without real data:
        - a 5-day smog episode in JANUARY (daily mean ~180 > 150, so the
          smog_season flag must come out True)
        - a 12-hour spike in late October (peak 260 > 200, rise > 100 in 24h)
    """
    if cities is None:
        cities = ["Karachi", "Lahore"]
    rng = np.random.default_rng(0)
    idx = pd.date_range("2023-01-01", periods=n_days * 24, freq="h")

    frames = []
    for city in cities:
        t = np.arange(len(idx))
        base = 80 + 30 * np.sin(2 * np.pi * t / (24 * 7)) + t / len(t) * 40
        aqi = base + rng.normal(0, 10, len(idx))

        # inject smog episode: days 20-24 = Jan 21-25, inside smog season
        ep_start, ep_days = 20 * 24, 5
        aqi[ep_start:ep_start + ep_days * 24] = 180 + rng.normal(0, 5, ep_days * 24)
        # inject spike: 12 hours on day 300 (Oct 28, crop-burning season)
        sp_start = 300 * 24
        aqi[sp_start:sp_start + 12] = 260 + rng.normal(0, 3, 12)

        frames.append(pd.DataFrame({"city": city, "us_aqi": np.clip(aqi, 10, 400)},
                                   index=idx))
    return pd.concat(frames).sort_index()


def main():
    """Detect pollution events on REAL data (default). Source cascade:
    Feature Store -> raw CSVs -> live Open-Meteo fetch. Pass --demo for
    the synthetic smoke test with injected events (detector sanity check
    only — real numbers come from real data)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=["auto", "store", "csv", "api"], default="auto",
        help="data source (default auto: store -> raw CSVs -> live API)",
    )
    parser.add_argument(
        "--cities",
        help="comma-separated subset, e.g. Lahore,Karachi (default: all configured)",
    )
    parser.add_argument("--start", help="start date YYYY-MM-DD (live API only)")
    parser.add_argument("--end", help="end date YYYY-MM-DD (live API only)")
    parser.add_argument(
        "--demo", action="store_true",
        help="synthetic smoke test with injected events (not real data)",
    )
    args = parser.parse_args()

    if args.demo:
        logger.warning("Running on SYNTHETIC demo data (--demo) — not real data")
        df = _demo_data(cities=list(CITIES.keys()))
    else:
        cities = [c.strip() for c in args.cities.split(",")] if args.cities else None
        df = load_real_data(cities, source=args.source,
                            start_date=args.start, end_date=args.end)
        if df.empty:
            raise SystemExit(
                "No data available — run the Day 8 backfill, or use --source api "
                "to fetch live from Open-Meteo."
            )

    events = detect_events(df)
    print(events.to_string(index=False))
    print("\nPer-city summary (worst peak first):")
    print(event_summary(events).to_string(index=False))
    city, peak = worst_city(events)
    print(f"\nWorst city by peak AQI: {city} ({peak:.1f})")


if __name__ == "__main__":
    main()
