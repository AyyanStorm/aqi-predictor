"""
open_meteo_client.py — the ONLY file in this project that talks to the
Open-Meteo API. Every other file that needs weather or AQI data calls
the functions below instead of making its own HTTP requests.
"""

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Cached (1hr), auto-retrying session — built once, reused by every call
# below. See Day 1 notes: caching avoids re-hitting the API while you
# debug; retrying with backoff avoids hammering a struggling server.
# retries are fail-fast on purpose: with chunked requests (Day 8 fix) a
# single stall costs seconds, not minutes — 8 retries x 0.5 backoff could
# burn ~2 minutes per dead request, which made the backfill crawl.
cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=3, backoff_factor=0.3)
openmeteo = openmeteo_requests.Client(session=retry_session)


def _build_dataframe(hourly, variable_names):
    """
    Turn an Open-Meteo `Hourly()` response object into a DataFrame.

    Open-Meteo guarantees the response variables come back in the SAME
    ORDER they were requested in. Rather than hardcoding that order
    twice (once in the request, once when reading the response — the
    Day 1 bug, where an edit to one list could silently misalign the
    other), this function takes the exact same `variable_names` list
    you requested with, and uses its position to pull out the matching
    response column. One list, one source of truth, for both ends.
    """
    data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left",
        )
    }
    for i, name in enumerate(variable_names):
        data[name] = hourly.Variables(i).ValuesAsNumpy()

    return pd.DataFrame(data)


def fetch_air_quality(latitude, longitude, start_date, end_date, url):
    """
    Fetch hourly AQI + pollutant data for one location.

    Returns a DataFrame with columns:
        date, us_aqi, pm10, pm2_5, carbon_monoxide,
        nitrogen_dioxide, sulphur_dioxide, ozone
    """
    variables = [
        "us_aqi", "pm10", "pm2_5", "carbon_monoxide",
        "nitrogen_dioxide", "sulphur_dioxide", "ozone",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": variables,
        "start_date": start_date,
        "end_date": end_date,
    }

    response = openmeteo.weather_api(url, params=params)[0]
    hourly = response.Hourly()
    df = _build_dataframe(hourly, variables)

    logger.info(f"Fetched air quality data for ({latitude}, {longitude}): {len(df)} rows")
    return df


def fetch_weather(latitude, longitude, start_date, end_date, url, variables):
    """
    Fetch hourly weather data for one location.

    `variables` is a list of Open-Meteo variable names (see
    config.WEATHER_VARIABLES). This function is deliberately generic —
    it doesn't know or care what's inside `variables`, which is what
    lets the SAME function be reused later for forecast weather
    (Day 16) just by pointing it at a different url and date range.

    Returns a DataFrame with a `date` column plus one column per
    requested variable.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": variables,
        "start_date": start_date,
        "end_date": end_date,
    }

    response = openmeteo.weather_api(url, params=params)[0]
    hourly = response.Hourly()
    df = _build_dataframe(hourly, variables)

    logger.info(f"Fetched weather data for ({latitude}, {longitude}): {len(df)} rows")
    return df
