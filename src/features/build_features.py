"""
build_features.py — turns raw AQI/weather data into model-ready features.

Used by BOTH the training pipeline (on historical data) and the live
inference pipeline (Day 16, on freshly fetched data) — this is the ONE
place feature logic is defined, so training and serving can never drift
apart (the "training-serving skew" risk flagged in the roadmap).

Feature families (roadmap Section 2):

    Family A — history, known at time t:
        - current pollutants + us_aqi
        - lags: 1h / 24h / 168h (one week)
        - rolling: 24h mean/max, 168h mean
        - change rate: us_aqi - aqi_lag_24h (the brief's "AQI change rate")

    Family B — future weather at the TARGET timestamp (t+24/48/72h),
    legitimately known at inference time because weather forecasts exist:
        - every weather variable shifted FORWARD by the horizon, so row t
          carries the value that will be observed at t+h — the exact same
          columns the forecast API supplies on Day 16.
        - calendar features OF THE TARGET timestamp (hour / day-of-week /
          month / is_weekend), also shifted forward by the horizon.
        Wind is the single most important feature in this project:
        pollution is emission minus dispersion, and wind is dispersion.
        The roadmap's implementation note is explicit: if training never
        sees future-weather features, the model learns on half the
        information the roadmap says matters most.

Self-containment rule (roadmap structural rule 2):
    Every time column (local_hour, month, day_of_week, is_weekend) is
    derived from the datetime index INSIDE this function — never passed in
    by the caller. A caller-supplied `month` column is exactly how
    training-serving skew sneaks in.
"""

import numpy as np
import pandas as pd

from src.config import FORECAST_HORIZONS, WEATHER_VARIABLES
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_features(df):
    """
    Takes a raw merged DataFrame (must have a datetime index and a
    'city' column) and returns it with engineered features added.
    """
    df = df.copy()  # never mutate the caller's original DataFrame
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex (hourly, ascending)")

    # --- Timezone fix: Pakistan is a single timezone (PKT, UTC+5, no DST) ---
    df["local_hour"] = (df.index.hour + 5) % 24

    # --- Calendar columns, derived from the index (self-contained) ---
    df["month"] = df.index.month
    df["day_of_week"] = df.index.dayofweek  # 0 = Monday ... 6 = Sunday

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
    # (hour, month, day-of-week all wrap around; raw ints would imply
    #  hour 23 is "far" from hour 0, which is wrong.)
    df["hour_sin"] = np.sin(2 * np.pi * df["local_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["local_hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)  # Sat/Sun

    # --- Family B: values AT THE TARGET TIMESTAMP (t + h), per horizon ---
    # For every horizon h, each of these columns is the value the world
    # will have at t+h, pulled back onto row t with a NEGATIVE shift.
    # At inference time the forecast API hands us those exact future
    # values, so training and serving use identical columns.
    #
    # Weather variables that exist in THIS frame only (a frame fetched
    # before boundary_layer_height was added to config simply lacks it;
    # the code degrades gracefully instead of crashing the pipeline).
    present_weather = [v for v in WEATHER_VARIABLES if v in df.columns]

    # Calendar features of the target timestamp (hour/dow/month/is_weekend).
    # Shifted forward per city exactly like the weather, so row t carries
    # "what day of the week will t+24h be?" — known with certainty at t.
    target_calendar_cols = [
        "hour_sin", "hour_cos", "month_sin", "month_cos",
        "dow_sin", "dow_cos", "is_weekend",
    ]

    for h in FORECAST_HORIZONS:
        for var in present_weather:
            df[f"{var}_{h}h"] = df.groupby("city")[var].shift(-h)
        for col in target_calendar_cols:
            df[f"{col}_{h}h"] = df.groupby("city")[col].shift(-h)

    if not present_weather:
        logger.warning(
            "No weather columns found in frame — Family B weather features "
            "skipped (demo/raw frames without weather). Calendar target "
            "features still built."
        )

    logger.info(f"Built features: {df.shape[0]} rows, {df.shape[1]} columns")
    return df
