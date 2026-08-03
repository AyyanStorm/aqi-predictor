"""
historical_backfill.py — full 10-city backfill: raw fetch → features →
targets → Feature Store, plus a verification summary.

Day 8 version. For every city in CITIES this script:
    1. Fetches ~4 years of hourly AQI + weather (Open-Meteo)
    2. Saves the RAW merged frame to data/raw/ (EDA still reads this)
    3. Engineers features with build_features() (Day 5)
    4. Adds multi-horizon targets with add_targets() (Day 6)
    5. Writes the ENGINEERED frame to the Feature Store (Day 7 adapter —
       Hopsworks when configured, Parquet fallback otherwise)
    6. Reads it back and prints a verification summary: row counts per
       city and nulls per column.

Run it directly (not imported) to execute the backfill:
    python -m src.data_ingestion.historical_backfill
"""

from datetime import date, timedelta
import time

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

END_DATE = date.today().isoformat()

# One giant 4-year request per city is what times out (risk R5). Fetch in
# ~6-month windows instead: each request is small and fast, and a failure
# only loses one chunk, not the whole city.
BACKFILL_CHUNK_DAYS = 180
SLEEP_BETWEEN_CHUNKS_S = 2   # be polite to the free API
SLEEP_BETWEEN_CITIES_S = 3



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
            time.sleep(5)
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

# Columns that must be complete after the backfill — verification FAILs if
# any of these has nulls (plus whatever else is unexpectedly null).
NON_NULL_COLUMNS = [
    "us_aqi",
    EVENT_TIME_COLUMN,
    PRIMARY_KEY,
    "y_24",
    "y_48",
    "y_72",
    "aqi_lag_1h",
    "aqi_lag_24h",
    "aqi_roll_mean_24h",
]


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
    data/raw/, and return the ENGINEERED frame (features + targets) ready
    for the Feature Store.
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
    return engineered


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
        for col, count in nulls.items():
            flag = "  <-- MUST BE FIXED" if col in NON_NULL_COLUMNS else ""
            logger.info(f"  {col:<28} {count:>8,}{flag}")
        ok = bool(set(nulls.index).isdisjoint(NON_NULL_COLUMNS))

    logger.info("=" * 60)
    logger.info(f"Verification result : {'PASS ✓' if ok else 'FAIL ✗'}")
    return ok, stored, nulls


if __name__ == "__main__":
    engineered_frames = []
    raw_total = 0

    for city_name, coords in CITIES.items():
        try:
            df = backfill_city(city_name, coords["lat"], coords["lon"])
            engineered_frames.append(df)
            raw_total += len(pd.read_csv(RAW_DIR / f"{city_name.lower()}_historical.csv"))
        except Exception as e:
            # One city failing (rate limit, bad response, etc.) shouldn't
            # kill the whole 10-city run — log it and keep going.
            logger.error(f"{city_name}: backfill failed - {e}")
        time.sleep(SLEEP_BETWEEN_CITIES_S)  # let the API breathe between cities

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
