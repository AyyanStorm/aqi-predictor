"""
config.py — single source of truth for the AQI Predictor project.

Any value used in more than one file (paths, coordinates, URLs, dates)
lives here and gets imported everywhere else. Change it once, here,
and every file that imports it picks up the new value automatically.
"""

from pathlib import Path
import os
from dotenv import load_dotenv


# =========================================================
# 1. PATHS
# =========================================================
# __file__ = the path to THIS file (config.py).
# .resolve() turns it into a full absolute path, no matter how the
#   script was launched.
# .parents[1] walks up two folders: config.py -> src/ -> repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Everything else is built FROM the root, using the "/" operator,
# which pathlib overloads to mean "join this onto the path".
# This works correctly on Windows AND on Linux (e.g. GitHub Actions).
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"

# Make sure these folders actually exist on disk. This matters because
# data/ is gitignored — it won't exist at all on a machine that just
# cloned the repo (like a GitHub Actions runner) until this code runs.
for _directory in (DATA_DIR, RAW_DIR, PROCESSED_DIR, MODELS_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


# =========================================================
# 2. CITIES
# =========================================================
# Dict keyed by city name -> {lat, lon}.
# Chosen over a list-of-dicts because both operations we need are cheap:
#   - loop over every city (Day 3 backfill):      for name, coords in CITIES.items()
#   - look up one city by name (Day 18 search):   CITIES["Lahore"]
# A list-of-dicts would need a linear search for the second case.
#
# Only Karachi for now (Day 1). The other 9 Pakistani cities
# (Lahore, Islamabad, Faisalabad, Rawalpindi, Multan, Peshawar,
# Quetta, Hyderabad, Gujranwala) get added on Day 3, plus Sialkot
# held out separately as the unseen-city validation set.
CITIES = {
    "Karachi":     {"lat": 24.8608, "lon": 67.0104},
    "Lahore":      {"lat": 31.5497, "lon": 74.3436},
    "Islamabad":   {"lat": 33.6844, "lon": 73.0479},
    "Faisalabad":  {"lat": 31.4504, "lon": 73.1350},
    "Rawalpindi":  {"lat": 33.5651, "lon": 73.0169},
    "Multan":      {"lat": 30.1575, "lon": 71.5249},
    "Peshawar":    {"lat": 34.0151, "lon": 71.5249},
    "Quetta":      {"lat": 30.1798, "lon": 66.9750},
    "Hyderabad":   {"lat": 25.3960, "lon": 68.3578},
    "Gujranwala":  {"lat": 32.1877, "lon": 74.1945},
}
SIALKOT = {"lat": 32.4945, "lon": 74.5229}

# =========================================================
# 3. API ENDPOINTS (Open-Meteo — free, no API key required)
# =========================================================
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Weather variables pulled from ARCHIVE_URL (history) and, later, FORECAST_URL
# (future). Wind is the single most important driver of AQI after the
# pollutants themselves — it controls how fast pollution disperses.
# boundary_layer_height is the altitude of the atmospheric mixing layer;
# a low (night-time) boundary layer traps pollution, a high one disperses
# it — listed in the roadmap's Family B feature set.
WEATHER_VARIABLES = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "relative_humidity_2m",
    "surface_pressure",
    "precipitation",
    "boundary_layer_height",
]


# =========================================================
# 4. MODELLING CONSTANTS
# =========================================================
HISTORICAL_START_DATE = "2022-08-06"

# How many hours ahead we forecast AQI for. Used by targets.py,
# train.py, and the dashboard — one definition, used everywhere.
FORECAST_HORIZONS = [24, 48, 72]

# US EPA AQI breakpoints (single source of truth). Used by:
#   - src/utils/events.py   (Day 10: smog-episode/spike detection)
#   - src/utils/aqi_utils.py (Day 19: colour bands + health messages)
#   - the dashboard's hazardous-AQI alert (Day 19)
AQI_UNHEALTHY = 150          # >= this = "Unhealthy" (orange)
AQI_VERY_UNHEALTHY = 200     # >= this = "Very Unhealthy" (red)
AQI_HAZARDOUS = 300          # >= this = "Hazardous" (maroon) -> alert


# =========================================================
# 5. SECRETS
# =========================================================
# load_dotenv() reads the local .env file (which is gitignored, never
# committed) and injects its KEY=value lines into the environment.
# On GitHub Actions there is no .env file — load_dotenv() just does
# nothing, and the same os.getenv() call picks up a value injected
# instead from GitHub Secrets. Same code, works in both places.
load_dotenv()

# =========================================================
# 6. HOPSWORKS FEATURE STORE (Day 7+)
# =========================================================
# Real values live in .env (gitignored). On GitHub Actions they come
# from repo Secrets — same os.getenv() call, no code change.
HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")
HOPSWORKS_PROJECT = os.getenv("HOPSWORKS_PROJECT")
HOPSWORKS_HOST = os.getenv("HOPSWORKS_HOST", "eu-west.cloud.hopsworks.ai")
HOPSWORKS_PORT = int(os.getenv("HOPSWORKS_PORT", "443"))

# Feature group schema — one definition, used by both the Hopsworks
# adapter and the Parquet fallback so they can never drift apart.
FEATURE_GROUP_NAME = "aqi_features"
FEATURE_GROUP_VERSION = 1
PRIMARY_KEY = "city"            # which city the row belongs to
EVENT_TIME_COLUMN = "date"      # hourly timestamp (matches ingestion output)
DATA_DIR_FALLBACK = PROCESSED_DIR / "feature_store_parquet"