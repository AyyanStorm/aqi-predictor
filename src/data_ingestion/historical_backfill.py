"""
historical_backfill.py — fetches ~4 years of hourly AQI + weather data
for every city in CITIES, merges them, and saves both per-city and
combined CSVs into data/raw/.

Run this file directly (not imported) to execute the backfill:
    python -m src.data_ingestion.historical_backfill
"""

from datetime import date

import pandas as pd

from src.config import (
    CITIES,
    WEATHER_VARIABLES,
    HISTORICAL_START_DATE,
    AIR_QUALITY_URL,
    ARCHIVE_URL,
    RAW_DIR,
)
from src.data_ingestion.open_meteo_client import fetch_air_quality, fetch_weather
from src.utils.logger import get_logger

logger = get_logger(__name__)

END_DATE = date.today().isoformat()


def backfill_city(city_name, lat, lon):
    """
    Fetch + merge AQI and weather data for ONE city, save it to its own
    CSV in data/raw/, and return the merged DataFrame.
    """
    aqi_df = fetch_air_quality(lat, lon, HISTORICAL_START_DATE, END_DATE, AIR_QUALITY_URL)
    weather_df = fetch_weather(lat, lon, HISTORICAL_START_DATE, END_DATE, ARCHIVE_URL, WEATHER_VARIABLES)

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
    logger.info(f"{city_name}: saved {after} rows to {output_path}")

    return merged_df


if __name__ == "__main__":
    all_cities_df = []

    for city_name, coords in CITIES.items():
        try:
            df = backfill_city(city_name, coords["lat"], coords["lon"])
            all_cities_df.append(df)
        except Exception as e:
            # One city failing (rate limit, bad response, etc.) shouldn't
            # kill the whole 10-city run — log it and keep going.
            logger.error(f"{city_name}: backfill failed - {e}")

    combined = pd.concat(all_cities_df, ignore_index=True)
    combined_path = RAW_DIR / "all_cities_historical.csv"
    combined.to_csv(combined_path, index=False)

    logger.info(
        f"Backfill complete: {len(combined)} total rows "
        f"across {len(all_cities_df)}/{len(CITIES)} cities -> {combined_path}"
    )
