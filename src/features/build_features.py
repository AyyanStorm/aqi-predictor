"""
build_features.py — turns raw AQI/weather data into model-ready features.

Used by BOTH the training pipeline (on historical data) and the live
inference pipeline (Day 16, on freshly fetched data) — this is the ONE
place feature logic is defined, so training and serving can never drift
apart (the "training-serving skew" risk flagged in the roadmap).
"""

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_features(df):
    """
    Takes a raw merged DataFrame (must have a datetime index and a
    'city' column) and returns it with engineered features added.
    """
    df = df.copy()  # never mutate the caller's original DataFrame

    # --- Timezone fix: Pakistan is a single timezone (PKT, UTC+5, no DST) ---
    df["local_hour"] = (df.index.hour + 5) % 24

    # --- Lag features (per city, so cities never bleed into each other) ---
    df["aqi_lag_1h"] = df.groupby("city")["us_aqi"].shift(1)
    df["aqi_lag_24h"] = df.groupby("city")["us_aqi"].shift(24)
    df["aqi_lag_168h"] = df.groupby("city")["us_aqi"].shift(168)  # one week

    # --- Rolling window features ---
    df["aqi_roll_mean_24h"] = df.groupby("city")["us_aqi"].transform(lambda s: s.rolling(24).mean())
    df["aqi_roll_max_24h"] = df.groupby("city")["us_aqi"].transform(lambda s: s.rolling(24).max())
    df["aqi_roll_mean_168h"] = df.groupby("city")["us_aqi"].transform(lambda s: s.rolling(168).mean())

    # --- Change rate (named explicitly in the project brief) ---
    df["aqi_change_rate_24h"] = df["us_aqi"] - df["aqi_lag_24h"]

    # --- Cyclical encoding: sin/cos so hour 23 and hour 0 read as "close" ---
    df["hour_sin"] = np.sin(2 * np.pi * df["local_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["local_hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    logger.info(f"Built features: {df.shape[0]} rows, {df.shape[1]} columns")
    return df
