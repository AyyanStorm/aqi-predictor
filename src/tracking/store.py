"""
store.py — prediction tracking store (Hopsworks + Parquet fallback).

Same adapter pattern as src/features/feature_store.py: OUR OWN
signatures in front, Hopsworks behind a lazy import, and a local
Parquet backend implementing the identical interface so the dashboard
works with zero credentials (and zero hopsworks install — it can't
coexist with keras in one venv anyway).

Schema (one row per generated prediction):
    user_id         str   per-browser anonymous id (Q4: per-browser)
    prediction_id   str   uuid — primary key (upsert-safe)
    city            str   display name
    lat, lon        float
    timezone        str   IANA name (e.g. "Asia/Dubai")
    source          str   quick-pick | search | browser | ip
    created_at      datetime  when the prediction was generated (event time)
    base_ts         datetime  the "now" the forecast was built from (UTC)
    current_aqi     int
    pred_24/48/72   int   predicted AQI at each horizon
    model_name      str
    model_version   int

Horizon timestamps are NOT stored: they are base_ts + 24/48/72h
(absolute elapsed hours), recomputed dynamically — nothing hardcoded.
"""

import uuid
from pathlib import Path

import pandas as pd

from src.config import (
    DATA_DIR,
    EVENT_TIME_COLUMN,  # reused name for the event-time column
    HOPSWORKS_API_KEY,
    HOPSWORKS_HOST,
    HOPSWORKS_PORT,
    HOPSWORKS_PROJECT,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

PREDICTIONS_FG_NAME = "aqi_predictions"
PREDICTIONS_FG_VERSION = 1
PREDICTIONS_PK = "prediction_id"

# Fallback file: data/tracking/predictions.parquet (gitignored).
TRACKING_DIR = DATA_DIR / "tracking"


def _normalize(df):
    """Cast the schema columns to stable types for storage backends."""
    df = df.copy()
    for col in ("created_at", "base_ts"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


class PredictionStore:
    """Interface every backend implements."""

    def save(self, record: dict):
        raise NotImplementedError

    def load(self, user_id=None, city=None):
        """Return a DataFrame of predictions, optionally filtered."""
        raise NotImplementedError


class HopsworksPredictionStore(PredictionStore):
    """Real Hopsworks backend (lazy import; HUDI; auto-create FG)."""

    def __init__(self):
        if not HOPSWORKS_API_KEY:
            raise ValueError("HOPSWORKS_API_KEY is not set — add it to .env")
        self._feature_group = None

    def _connect(self):
        if self._feature_group is not None:
            return self._feature_group

        import hopsworks  # lazy — dashboard envs never import this

        cert_folder = str(Path(__import__("tempfile").gettempdir()) / "hopsworks_certs")
        project = hopsworks.login(
            project=HOPSWORKS_PROJECT,
            host=HOPSWORKS_HOST,
            port=HOPSWORKS_PORT,
            api_key_value=HOPSWORKS_API_KEY,
            cert_folder=cert_folder,
        )
        fs = project.get_feature_store()

        try:
            fg = fs.get_feature_group(
                name=PREDICTIONS_FG_NAME, version=PREDICTIONS_FG_VERSION
            )
        except Exception:
            fg = None
        if fg is None:
            fg = fs.create_feature_group(
                name=PREDICTIONS_FG_NAME,
                version=PREDICTIONS_FG_VERSION,
                primary_key=[PREDICTIONS_PK],
                event_time=EVENT_TIME_COLUMN,
                online_enabled=False,
                time_travel_format="HUDI",  # no client-side delta lib needed
            )
            logger.info(
                f"Created feature group {PREDICTIONS_FG_NAME} v{PREDICTIONS_FG_VERSION}"
            )
        self._feature_group = fg
        return fg

    def save(self, record: dict):
        fg = self._connect()
        df = _normalize(pd.DataFrame([record]))
        fg.insert(df)
        logger.info(f"Saved prediction {record.get('prediction_id')} to Hopsworks")

    def load(self, user_id=None, city=None):
        fg = self._connect()
        df = fg.read()
        if user_id is not None:
            df = df[df["user_id"] == user_id]
        if city is not None:
            df = df[df["city"] == city]
        return _normalize(df)


class ParquetPredictionStore(PredictionStore):
    """Local-disk fallback with the same interface."""

    def __init__(self, root=None):
        self.root = Path(root) if root else TRACKING_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "predictions.parquet"

    def save(self, record: dict):
        new = _normalize(pd.DataFrame([record]))
        old = self.load()
        if not old.empty:
            merged = pd.concat([old, new], ignore_index=True)
            merged = merged.drop_duplicates(subset=[PREDICTIONS_PK], keep="last")
        else:
            merged = new
        merged.to_parquet(self._path, index=False)
        logger.info(f"Saved prediction {record.get('prediction_id')} to Parquet")

    def load(self, user_id=None, city=None):
        if not self._path.exists():
            return pd.DataFrame()
        df = _normalize(pd.read_parquet(self._path))
        if user_id is not None:
            df = df[df["user_id"] == user_id]
        if city is not None:
            df = df[df["city"] == city]
        return df


def get_prediction_store():
    """Factory: Hopsworks when configured AND installed, else Parquet."""
    if HOPSWORKS_API_KEY and HOPSWORKS_PROJECT:
        try:
            import importlib.util

            if importlib.util.find_spec("hopsworks") is not None:
                return HopsworksPredictionStore()
        except (ValueError, ImportError) as exc:
            logger.warning(f"Hopsworks unavailable for predictions: {exc}")
    logger.info("Using Parquet prediction store")
    return ParquetPredictionStore()


def new_prediction_id():
    """Unique prediction id (upsert key)."""
    return str(uuid.uuid4())
