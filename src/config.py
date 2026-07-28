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
    "Karachi": {"lat": 24.8608, "lon": 67.0104},
}


# =========================================================
# 3. API ENDPOINTS (Open-Meteo — free, no API key required)
# =========================================================
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# =========================================================
# 4. MODELLING CONSTANTS
# =========================================================
HISTORICAL_START_DATE = "2022-08-06"

# How many hours ahead we forecast AQI for. Used by targets.py,
# train.py, and the dashboard — one definition, used everywhere.
FORECAST_HORIZONS = [24, 48, 72]


# =========================================================
# 5. SECRETS
# =========================================================
# load_dotenv() reads the local .env file (which is gitignored, never
# committed) and injects its KEY=value lines into the environment.
# On GitHub Actions there is no .env file — load_dotenv() just does
# nothing, and the same os.getenv() call picks up a value injected
# instead from GitHub Secrets. Same code, works in both places.
load_dotenv()

HOPSWORKS_API_KEY = os.getenv("HOPSWORKS_API_KEY")