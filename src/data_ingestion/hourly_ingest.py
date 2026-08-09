"""
hourly_ingest.py — Day 21: the hourly feature pipeline.

The automation phase's first piece: every hour (via GitHub Actions cron)
this script pulls the last 10 days of AQI + weather for all 10 cities,
rebuilds the engineered features with the SAME build_features() the
training pipeline uses, and writes them to the Feature Store (Hopsworks
when .env/Secrets are configured, Parquet fallback otherwise).

Why 10 days and not 1: the lag/rolling features need history
(aqi_lag_168h = one week, 7-day rolling mean), so each hourly run
re-fetches a window that makes the newest rows feature-complete.
Open-Meteo's response cache (requests-cache, 1h TTL) makes the overlap
cheap.

Idempotent by design: the store upserts on (city, date), so a re-run
over the same window just refreshes rows instead of duplicating them —
the same contract the Day 8 backfill uses.

CLI:  python -m src.data_ingestion.hourly_ingest [--cities Karachi,Lahore]
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from src.config import (
    AIR_QUALITY_URL,
    CITIES,
    FORECAST_URL,
    PRIMARY_KEY,
    WEATHER_VARIABLES,
)
from src.data_ingestion.open_meteo_client import fetch_air_quality, fetch_weather
from src.features.build_features import build_features
from src.features.feature_store import get_feature_store
from src.features.targets import add_targets
from src.utils.logger import get_logger

logger = get_logger(__name__)

# How much history each run fetches so the newest rows have complete
# lag/rolling features (matches the inference pipeline's live frame).
INGEST_WINDOW_DAYS = 10

DEFAULT_WORKERS = 4


def ingest_city(city_name, lat, lon):
    """
    Fetch the trailing window for ONE city, engineer features, and
    return the store-ready frame (with targets; incomplete-tail rows
    dropped, exactly like the backfill).

    Returns
    -------
    pd.DataFrame | None
        Engineered rows for the city, or None if the fetch failed
        (caller logs and continues — one city must not kill the run).
    """
    try:
        now = pd.Timestamp.now(tz="UTC").floor("h")
        start = (now - pd.Timedelta(days=INGEST_WINDOW_DAYS)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        aqi = fetch_air_quality(lat, lon, start, end, AIR_QUALITY_URL)
        weather = fetch_weather(
            lat, lon, start, end, FORECAST_URL, WEATHER_VARIABLES
        )

        df = pd.merge(aqi, weather, on="date", how="outer")
        df = df.set_index("date").sort_index()
        df.index = pd.DatetimeIndex(df.index)
        df["city"] = city_name

        df = build_features(df)
        df = add_targets(df)  # drops the tail rows with incomplete targets

        out = df.reset_index()  # `date` back to a column (store event time)
        logger.info(
            f"{city_name}: {len(out)} engineered rows "
            f"({start} -> {end})"
        )
        return out
    except Exception as e:
        logger.error(f"{city_name}: hourly ingest failed - {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Day 21: hourly feature pipeline — refresh the Feature "
                    "Store with the last 10 days of engineered features."
    )
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

    logger.info(
        f"Hourly ingest starting: {len(cities)} cities, "
        f"{INGEST_WINDOW_DAYS}-day window, {args.workers} workers"
    )

    frames = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(ingest_city, name, coords["lat"], coords["lon"]): name
            for name, coords in cities.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            result = future.result()
            if result is not None and not result.empty:
                frames.append(result)

    if not frames:
        logger.error("No city produced rows — aborting.")
        raise SystemExit(1)

    combined = pd.concat(frames, ignore_index=True)
    store = get_feature_store()
    store.write_features(combined)

    total = len(combined)
    per_city = combined.groupby(PRIMARY_KEY).size()
    logger.info("=" * 60)
    logger.info("HOURLY INGEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total engineered rows written : {total}")
    for city, count in per_city.items():
        logger.info(f"  {city:<14} {count:>8,}")
    logger.info("=" * 60)
    logger.info(f"Hourly ingest complete: {total} rows -> feature store")


if __name__ == "__main__":
    main()
