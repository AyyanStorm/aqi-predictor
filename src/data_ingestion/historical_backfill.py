"""
historical_backfill.py — full 10-city backfill: raw fetch → features →
targets → Feature Store, plus a verification summary.

Day 8 version (speed-tuned). For every city in CITIES this script:
    1. Fetches ~4 years of hourly AQI + weather (Open-Meteo), in ~1-year
       chunks so no single request is big enough to time out (risk R5)
    2. Saves the RAW merged frame to data/raw/<city>_historical.csv
       IMMEDIATELY — the file is refreshed the moment a city completes,
       even if the rest of the run is still going
    3. Engineers features with build_features() (Day 5)
    4. Adds multi-horizon targets with add_targets() (Day 6)
    5. Writes the ENGINEERED frame to the Feature Store (Day 7 adapter —
       Hopsworks when configured, Parquet fallback otherwise)
    6. Reads it back and prints a verification summary: row counts per
       city and nulls per column.

Speed design (fixes "too slow, CSVs not updating"):
    - Cities run CONCURRENTLY (default 3 workers): the work is
      network-bound, so parallelism is a near-linear speedup.
    - Client retries are fail-fast (3 tries, short backoff) — a stalled
      request costs seconds, not minutes.
    - data/raw/all_cities_historical.csv is REWRITTEN after every city
      completes, so the combined file is never stale mid-run.

Run it directly (not imported) to execute the backfill:
    python -m src.data_ingestion.historical_backfill
    python -m src.data_ingestion.historical_backfill --cities Karachi,Lahore
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from src.config import (
    CITIES,
    WEATHER_VARIABLES,
    HISTORICAL_START_DATE,
    AIR_QUALITY_URL,
    ARCHIVE_URL,
    RAW_DIR,
    PROCESSED_DIR,
    PRIMARY_KEY,
    EVENT_TIME_COLUMN,
)
from src.data_ingestion.open_meteo_client import fetch_air_quality, fetch_weather
from src.features.build_features import build_features
from src.features.targets import add_targets
from src.features.feature_store import get_feature_store
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The weather archive API refuses end_date = today (max is yesterday, UTC).
# Using today made the final chunk fail for every city and silently dropped
# the last 12 days of weather per city. Clamp to yesterday.
END_DATE = (date.today() - timedelta(days=1)).isoformat()

# ~1-year windows: small enough to never trigger the read timeout that a
# single 4-year request caused (the original Day 8 bug).
BACKFILL_CHUNK_DAYS = 365
SLEEP_BETWEEN_CHUNKS_S = 1.0   # tiny politeness gap between chunk requests
CHUNK_RETRY_SLEEP_S = 2.0      # wait before a chunk's single retry
DEFAULT_WORKERS = 3            # concurrent cities (network-bound, safe on free tier)

# Columns that MUST be 100% complete — any null here is a real bug.
CRITICAL_COLUMNS = [
    "us_aqi",
    EVENT_TIME_COLUMN,
    PRIMARY_KEY,
    "y_24",
    "y_48",
    "y_72",
]

# Lag/rolling features are EXPECTED to have nulls at the start of each
# city's series (no history before the first row). Max allowed nulls =
# warm-up rows x 10 cities. Nulls beyond this mean real data gaps.
WARMUP_ALLOWANCE = {
    "aqi_lag_1h": 10,            # 1 first row/city
    "aqi_lag_24h": 240,          # first 24h/city
    "aqi_lag_168h": 1680,        # first 168h/city (one week)
    "aqi_change_rate_24h": 240,  # us_aqi - aqi_lag_24h
    "aqi_roll_mean_24h": 230,    # rolling(24).mean() -> 23 NaN rows/city
    "aqi_roll_max_24h": 230,     # rolling(24).max()  -> 23 NaN rows/city
    "aqi_roll_mean_168h": 1670,  # rolling(168).mean() -> 167 NaN rows/city
}


def _date_chunks(start_date, end_date, chunk_days):
    """Yield (start, end) ISO date pairs covering [start_date, end_date]."""
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=chunk_days), end)
        yield current.date().isoformat(), chunk_end.date().isoformat()
        current = chunk_end + timedelta(days=1)


def _fetch_city_chunked(lat, lon, start_date, end_date, url, fetch_fn, what, *extra):
    """Fetch one city's data in small windows, concatenate, with sleeps.

    `extra` is forwarded to fetch_fn (e.g. WEATHER_VARIABLES for
    fetch_weather, which takes more args than fetch_air_quality). Each
    chunk gets one retry; a chunk that still fails is SKIPPED with a
    warning so one bad chunk never kills the whole city. Raises only if
    every chunk fails.
    """
    frames = []
    chunks = list(_date_chunks(start_date, end_date, BACKFILL_CHUNK_DAYS))
    for i, (cs, ce) in enumerate(chunks, 1):
        try:
            frames.append(fetch_fn(lat, lon, cs, ce, url, *extra))
        except Exception as e:
            logger.warning(f"{what} chunk {i}/{len(chunks)} ({cs}..{ce}) failed: {e}; retrying once")
            time.sleep(CHUNK_RETRY_SLEEP_S)
            try:
                frames.append(fetch_fn(lat, lon, cs, ce, url, *extra))
            except Exception as e2:
                logger.error(f"{what} chunk {i}/{len(chunks)} ({cs}..{ce}) failed again: {e2}; skipping chunk")
                time.sleep(SLEEP_BETWEEN_CHUNKS_S)
                continue
        if i < len(chunks):
            time.sleep(SLEEP_BETWEEN_CHUNKS_S)
    if not frames:
        raise RuntimeError(f"{what}: all {len(chunks)} chunks failed")
    return pd.concat(frames, ignore_index=True)


def _engineer(df):
    """
    Turn a raw merged frame (date column, city column) into the training
    frame: datetime index + month column (build_features expects both) →
    features → targets → restore `date` as a column for the store.
    """
    df = df.copy()
    df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN], utc=True)
    df = df.set_index(EVENT_TIME_COLUMN).sort_index()
    df["month"] = df.index.month  # build_features() references df["month"]
    df = build_features(df)
    df = add_targets(df)          # drops tail rows with incomplete targets
    return df.reset_index()       # `date` back to a column (store event time)


def backfill_city(city_name, lat, lon):
    """
    Fetch + merge AQI and weather data for ONE city, save the raw frame to
    data/raw/ IMMEDIATELY, and return (engineered, raw) frames. The raw CSV
    is written before engineering so a failure downstream never leaves the
    city's file stale.
    """
    aqi_df = _fetch_city_chunked(
        lat, lon, HISTORICAL_START_DATE, END_DATE, AIR_QUALITY_URL,
        fetch_air_quality, "aqi",
    )
    weather_df = _fetch_city_chunked(
        lat, lon, HISTORICAL_START_DATE, END_DATE, ARCHIVE_URL,
        fetch_weather, "weather", WEATHER_VARIABLES,
    )

    before = len(aqi_df)
    merged_df = pd.merge(aqi_df, weather_df, on="date", how="inner")
    after = len(merged_df)
    if after < before:
        logger.warning(f"{city_name}: merge dropped {before - after} rows ({before} -> {after})")

    # Tag every row with its source city. This is what lets us later
    # hold out one city entirely (Sialkot) to test whether the model
    # generalizes, without the model ever seeing "city" as a feature.
    merged_df["city"] = city_name

    output_path = RAW_DIR / f"{city_name.lower()}_historical.csv"
    merged_df.to_csv(output_path, index=False)
    logger.info(f"{city_name}: saved {after} raw rows to {output_path}")

    engineered = _engineer(merged_df)
    logger.info(f"{city_name}: engineered {len(engineered)} rows (targets complete)")
    return engineered, merged_df


def write_combined_raw(raw_frames):
    """Rewrite data/raw/all_cities_historical.csv from whatever has
    completed so far — called after EVERY city so the file is never stale."""
    combined = pd.concat(raw_frames, ignore_index=True)
    combined_path = RAW_DIR / "all_cities_historical.csv"
    combined.to_csv(combined_path, index=False)
    logger.info(f"Combined raw CSV refreshed: {len(combined)} rows -> {combined_path}")


def verify_backfill(store, expected_raw_rows=None):
    """
    Read the whole store back and print a verification summary: total rows,
    rows per city, and nulls per column. Returns (ok, report_df, nulls).
    """
    stored = store.read_features()
    if stored.empty:
        logger.error("Verification FAILED: store returned zero rows")
        return False, stored, None

    total = len(stored)
    per_city = stored.groupby(PRIMARY_KEY).size().sort_values(ascending=False)
    nulls = stored.isna().sum()
    nulls = nulls[nulls > 0].sort_values(ascending=False)

    logger.info("=" * 60)
    logger.info("BACKFILL VERIFICATION")
    logger.info("=" * 60)
    logger.info(f"Total rows in store : {total}")
    if expected_raw_rows:
        logger.info(f"Expected ~           : {expected_raw_rows} (raw); engineered is lower "
                    f"by ~72 rows/city dropped for incomplete targets")
    logger.info("Rows per city:")
    for city, count in per_city.items():
        logger.info(f"  {city:<14} {count:>8,}")
    if nulls.empty:
        logger.info("Nulls per column    : NONE ✓")
        ok = True
    else:
        logger.info("Nulls per column (non-zero only):")
        ok = True
        for col, count in nulls.items():
            if col in CRITICAL_COLUMNS:
                flag = "  <-- MUST BE FIXED"
                ok = False
            elif col in WARMUP_ALLOWANCE and count <= WARMUP_ALLOWANCE[col]:
                flag = "  (expected warm-up nulls ✓)"
            else:
                flag = "  <-- UNEXPECTED, check"
                ok = False
            logger.info(f"  {col:<28} {count:>8,}{flag}")

    logger.info("=" * 60)
    logger.info(f"Verification result : {'PASS ✓' if ok else 'FAIL ✗'}")
    return ok, stored, nulls


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="10-city AQI backfill -> Feature Store")
    parser.add_argument(
        "--cities",
        help="comma-separated subset, e.g. Karachi,Lahore (default: all 10)",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"concurrent cities (default: {DEFAULT_WORKERS})",
    )
    args = parser.parse_args()

    if args.cities:
        wanted = {c.strip() for c in args.cities.split(",")}
        cities = {k: v for k, v in CITIES.items() if k in wanted}
    else:
        cities = CITIES

    engineered_frames = []
    raw_frames = []
    raw_total = 0

    logger.info(f"Backfill starting: {len(cities)} cities, {args.workers} workers, "
                f"{HISTORICAL_START_DATE} -> {END_DATE}")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(backfill_city, name, coords["lat"], coords["lon"]): name
            for name, coords in cities.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                engineered, raw = future.result()
                engineered_frames.append(engineered)
                raw_frames.append(raw)
                raw_total += len(raw)
                # Combined CSV stays fresh no matter when the run stops.
                write_combined_raw(raw_frames)
            except Exception as e:
                # One city failing (rate limit, bad response, etc.) shouldn't
                # kill the rest — log it and keep going.
                logger.error(f"{name}: backfill failed - {e}")

    if not engineered_frames:
        logger.error("No cities backfilled successfully — aborting.")
        raise SystemExit(1)

    combined = pd.concat(engineered_frames, ignore_index=True)

    # Engineered combined copy on disk (handy for quick local inspection).
    engineered_path = PROCESSED_DIR / "all_cities_engineered.csv"
    combined.to_csv(engineered_path, index=False)
    logger.info(f"Engineered combined: {len(combined)} rows -> {engineered_path}")

    # Feature Store write (Hopsworks when .env is configured, else Parquet).
    store = get_feature_store()
    store.write_features(combined)

    # Verification summary.
    verify_backfill(store, expected_raw_rows=raw_total)
