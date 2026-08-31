"""
predict.py — Day 16: the inference pipeline.

Turns "any lat/lon on Earth" into a 3-day AQI forecast:

    (lat, lon) -> live fetch: last 10 days of AQI + pollutants,
                              forecast weather for the next 4 days
               -> the SAME build_features() training uses
                  (Family A: lags/rolling/change-rate;
                   Family B: weather + calendar AT the target hour)
               -> load the production model set from the registry
               -> predict us_aqi at +24h, +48h, +72h

The two rules this module is built around (roadmap Sections 2 + 5):

1. NO training-serving skew. Feature construction lives in exactly one
   place — src/features/build_features.py — and this file calls it with
   a frame shaped the same way training frames are shaped. The registry
   entry also stores the exact feature_cols the model was trained on
   (model_registry.py Day 14), and we feed the model ONLY those columns,
   in that order. If the model was trained without a column, inference
   must not invent it. If a stored feature is missing from the live
   frame, we fail loudly instead of silently predicting garbage.

2. Family B is legal at inference time because weather forecasts exist.
   The trick that makes build_features() work on live data: the frame
   we build contains the observed past (us_aqi, pollutants, weather) AND
   the forecast weather rows appended AFTER the "now" row. build_features
   computes Family B with shift(-h) — for the "now" row that shift lands
   on a genuine forecast row, so `temperature_2m_24h` really is the
   forecast temperature at t+24h. Same code path as training, where the
   shift lands on observed history.

Forecast horizon reality check (roadmap R10): skill decays with horizon.
+24h will be noticeably better than +72h. That is a real, correct
finding — the report should present it as one, not hide it.

What this module provides:
    1. fetch_live_frame()  — build the merged live frame (observations +
                             forecast weather appended).
    2. predict()           — lat/lon -> {24h, 48h, 72h} forecast dict,
                             with the current AQI and model metadata.
    3. CLI                 — python -m src.inference.predict
                             (defaults to Karachi; --city Lahore also works;
                             --lat/--lon override for anywhere on Earth)
"""

import argparse
import json
import logging

import pandas as pd

from src.config import (
    AIR_QUALITY_URL,
    CITIES,
    FORECAST_URL,
    FORECAST_HORIZONS,
    WEATHER_VARIABLES,
)
from src.data_ingestion.open_meteo_client import fetch_air_quality, fetch_weather
from src.features.build_features import build_features
from src.inference.cache import PredictionCache
from src.inference.circuit_breaker import CircuitBreaker
from src.training.model_registry import ModelRegistry
from src.utils.logger import get_logger, log_event
from src.utils.metrics import (
    prediction_latency, prediction_errors, predictions_made,
    record_latency
)

logger = get_logger(__name__)

# Initialize circuit breaker for Open-Meteo API
# Opens after 5 consecutive failures, resets after 5 minutes
api_breaker = CircuitBreaker(name='OpenMeteo', fail_max=5, reset_timeout=300)

# Initialize prediction cache with 24-hour TTL
cache = PredictionCache(max_age_hours=24)

# How much history Family A needs: the longest lag is 168h (one week)
# and the longest rolling window is 168h, so we fetch 10 days (240h) —
# comfortably more than the warm-up, leaving the "now" row fully built.
HISTORY_DAYS = 10
# Family B needs weather out to +72h; fetch 4 days so the shift(-72)
# from "now" always lands on a forecast row, with margin.
FORECAST_DAYS = 4


def fetch_live_frame(latitude, longitude, city="inference"):
    """
    Build the live inference frame for one location.

    Returns
    -------
    (pd.DataFrame, pd.Timestamp)
        - df: DatetimeIndex, hourly, sorted ascending, with a 'city'
          column. Past rows carry us_aqi + pollutants + weather; rows
          after "now" carry forecast weather only (AQI columns NaN).
        - now_ts: the last timestamp with an observed us_aqi — this is
          the row we predict from.
    """
    now = pd.Timestamp.now(tz="UTC").floor("h")
    start = (now - pd.Timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    end_hist = now.strftime("%Y-%m-%d")
    end_fc = (now + pd.Timedelta(days=FORECAST_DAYS)).strftime("%Y-%m-%d")

    # Past AQI + pollutants (current hour included by the API).
    aqi = fetch_air_quality(
        latitude, longitude, start, end_hist, AIR_QUALITY_URL
    )

    # Weather: ONE call to the forecast endpoint covering the past
    # window AND the next 4 days. Open-Meteo accepts start_date in the
    # past (up to 92 days) on the forecast API, so a single fetch gives
    # us observed weather for the lag features AND forecast weather for
    # Family B. One endpoint, one call, no archive lag to worry about.
    weather = fetch_weather(
        latitude, longitude, start, end_fc, FORECAST_URL, WEATHER_VARIABLES
    )

    # Outer join on the hour: past rows get weather + AQI; future rows
    # (forecast) get weather only, AQI NaN — exactly what build_features
    # needs for the Family B negative shifts.
    df = pd.merge(aqi, weather, on="date", how="outer")
    df = df.set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    df["city"] = city

    observed = df["us_aqi"].notna()
    if not observed.any():
        raise RuntimeError(
            f"No observed AQI rows returned for ({latitude}, {longitude}) — "
            f"check the coordinates and the Open-Meteo air-quality API."
        )
    now_ts = df.index[observed][-1]

    logger.info(
        f"Live frame ready: {len(df)} rows, "
        f"{df.index.min()} -> {df.index.max()}, now={now_ts}"
    )
    return df, now_ts


def predict(latitude, longitude, city="inference", name=None, version=None):
    """
    End-to-end inference: lat/lon -> 3-day AQI forecast.
    
    With graceful degradation: if the forecast API fails, returns cached
    prediction from the last successful request (if available and fresh).

    Parameters
    ----------
    latitude, longitude : float
        Any coordinates Open-Meteo covers (global, no API key).
    city : str
        Display label; never a model feature (city-agnostic model).
    name : str | None
        Model family to load (default: the registry's production model).
    version : int | None
        Specific version (default: current production).

    Returns
    -------
    dict
        {
          "location": {"lat": ..., "lon": ..., "city": ...},
          "fetched_at": ISO timestamp,
          "current_aqi": observed us_aqi at the prediction hour,
          "model": {"name", "version", "artifact", "mean_rmse"},
          "forecast": {"24": ..., "48": ..., "72": ...},   # ints
          "features": {...},   # the exact feature vector fed to the model
          "status": "ok" | "degraded",  # New: status of prediction
          "cache_age_hours": float,  # New: if degraded, age of cached data
          "warning": str  # New: if degraded, explanation for user
        }
    """
    
    # Track prediction latency and record errors
    with record_latency(prediction_latency, horizon='all', city=city or 'unknown'):
        try:
            logger.info(f'Attempting live forecast: lat={latitude}, lon={longitude}')
            
            # Protected by circuit breaker
            df, now_ts = api_breaker.call(
                fetch_live_frame, latitude, longitude, city=city
            )
        
        # Build features and run inference
        df = build_features(df)
        
        reg = ModelRegistry()
        if name is None:
            prod = reg.production_entry()
            if prod is None:
                raise SystemExit(
                    "No production model in the registry — train and promote "
                    "one first: python -m src.training.train --register"
                )
            name, version = prod["name"], prod["version"]
            logger.info(f"Using production model {name}_v{version}")
        
        try:
            models, entry = reg.load(name, version)
        except KeyError as e:
            raise SystemExit(
                f"{e}\nNo registered model to serve. Train and promote one first: "
                f"python -m src.training.train --register"
            )
        
        feature_cols = entry["feature_cols"]
        missing = [c for c in feature_cols if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"Model {entry['name']}_v{entry['version']} expects feature(s) "
                f"{missing} that the live frame does not have — training/serving "
                f"skew. Rebuild the model with the current build_features()."
            )
        
        row = df.loc[now_ts, feature_cols]
        if row.isna().any():
            nan_cols = row[row.isna()].index.tolist()
            raise RuntimeError(
                f"Prediction row at {now_ts} has NaN features: {nan_cols}. "
                f"Not enough history for the lag/rolling features — "
                f"increase HISTORY_DAYS."
            )
        
        row = row.astype(float)
        X = row.to_frame().T
        forecast = {}
        for h in FORECAST_HORIZONS:
            raw = float(models[h].predict(X)[0])
            forecast[str(h)] = max(0, round(raw))  # AQI is never negative
        
            result = {
                "location": {"lat": latitude, "lon": longitude, "city": city},
                "fetched_at": pd.Timestamp.now(tz="UTC").isoformat(),
                "current_aqi": int(round(float(df.loc[now_ts, "us_aqi"]))),
                "model": {
                    "name": entry["name"],
                    "version": entry["version"],
                    "artifact": entry["artifact"],
                    "mean_rmse": entry["mean_rmse"],
                },
                "forecast": forecast,
                "features": row.round(4).to_dict(),
                "status": "ok"
            }
            
            # Cache successful prediction
            cache.set(latitude, longitude, result)
            
            # Record success metric
            predictions_made.labels(status='ok', horizon='all').inc()
            
            logger.info(
                f"Forecast for ({latitude}, {longitude}) [{city}]: "
                + ", ".join(f"+{h}h={v}" for h, v in forecast.items())
            )
            
            return result
        
        except RuntimeError as e:
            # API failed or circuit breaker open -> try cache
            logger.warning(
                f'Live forecast failed: {e}. Attempting fallback to cache.',
                extra={'fields': {'lat': latitude, 'lon': longitude}}
            )
            
            cached_data, cache_age_hours = cache.get(latitude, longitude)
            
            if cached_data:
                # Return cached data with degraded status
                predictions_made.labels(status='degraded', horizon='all').inc()
                
                log_event(
                    logger, 'prediction_degraded',
                    level=logging.WARNING,
                    lat=latitude, lon=longitude,
                    cache_age_hours=round(cache_age_hours, 1),
                    reason=str(e)
                )
                
                return {
                    **cached_data,
                    "status": "degraded",
                    "cache_age_hours": round(cache_age_hours, 1),
                    "warning": (
                        f"Using cached prediction from {cache_age_hours:.1f} hours ago. "
                        f"Forecast API is temporarily unavailable. "
                        f"Please try again in a few minutes."
                    )
                }
            else:
                # No cache available -> fail
                predictions_made.labels(status='error', horizon='all').inc()
                error_type = type(e).__name__
                prediction_errors.labels(error_type=error_type, city=city or 'unknown').inc()
                
                log_event(
                    logger, 'prediction_failed',
                    level=logging.ERROR,
                    lat=latitude, lon=longitude,
                    error=str(e)
                )
                
                raise RuntimeError(
                    f"Forecast service unavailable. "
                    f"Error: {e}. "
                    f"No cached prediction available. "
                    f"Please try again in 5 minutes."
                )
        
        except SystemExit as e:
            # No model registered
            predictions_made.labels(status='error', horizon='all').inc()
            prediction_errors.labels(error_type='no_model', city=city or 'unknown').inc()
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Day 16: end-to-end inference — city or lat/lon -> 3-day AQI forecast."
    )
    parser.add_argument("--city", default="Karachi",
                        help="City name from config.CITIES; auto-fills lat/lon "
                             "(default: Karachi, the project's home city)")
    parser.add_argument("--lat", type=float,
                        help="Latitude — overrides --city (with --lon)")
    parser.add_argument("--lon", type=float,
                        help="Longitude — overrides --city (with --lat)")
    parser.add_argument("--name", default=None,
                        help="Model family (default: production model)")
    parser.add_argument("--version", type=int, default=None,
                        help="Model version (default: production)")
    args = parser.parse_args()

    # Explicit lat/lon win if both given; otherwise resolve from --city.
    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
    else:
        if args.city not in CITIES:
            parser.error(
                f"Unknown city '{args.city}' — pass --lat/--lon instead, or use "
                f"one of: {', '.join(sorted(CITIES))}"
            )
        coords = CITIES[args.city]
        lat, lon = coords["lat"], coords["lon"]
        if args.lat is not None or args.lon is not None:
            parser.error("Provide BOTH --lat and --lon, or neither (--city fills them)")

    result = predict(lat, lon, city=args.city,
                     name=args.name, version=args.version)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
