"""
feature_store.py — Hopsworks Feature Store adapter with Parquet fallback.

Day 7 deliverable. The Feature Store is where the training pipeline reads
from and the feature pipeline writes to (roadmap architecture, Section 4).
The model never talks to the raw API at training time — only to this store.

Why an adapter (roadmap risk R4):
    Hopsworks free tier can throttle, go down, or hit quota at 11pm on
    Day 25. If that happens, you don't want to rewrite the project — you
    want to swap one file. So this module exposes OUR OWN signatures:

        write_features(df)
        read_features(start=None, end=None, cities=None)

    and hides Hopsworks behind them. The ParquetFeatureStore implements
    the same interface on local disk, so the whole system keeps working
    with zero code changes elsewhere. Same interface, one-line switch.

Schema (defined in config.py, used by BOTH implementations so they can
never drift apart):
    feature group : aqi_features (version 1)
    primary key   : city
    event time    : date   (hourly timestamp)
"""

import os
import tempfile

import pandas as pd

from src.config import (
    DATA_DIR_FALLBACK,
    EVENT_TIME_COLUMN,
    FEATURE_GROUP_NAME,
    FEATURE_GROUP_VERSION,
    HOPSWORKS_API_KEY,
    HOPSWORKS_HOST,
    HOPSWORKS_PORT,
    HOPSWORKS_PROJECT,
    PRIMARY_KEY,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FeatureStore:
    """
    Interface every backend implements. The rest of the project only ever
    imports this class and the get_feature_store() factory — never Hopsworks
    or Parquet directly.
    """

    def write_features(self, df):
        """Write (or upsert) an engineered-features DataFrame."""
        raise NotImplementedError

    def read_features(self, start=None, end=None, cities=None):
        """Read features back as a DataFrame. All args optional filters."""
        raise NotImplementedError


class HopsworksFeatureStore(FeatureStore):
    """
    Real Hopsworks backend. The `hopsworks` package is imported lazily
    (inside methods) so the rest of the project imports fine even where
    the client isn't installed — e.g. CI or a machine without the dep.
    """

    def __init__(self):
        if not HOPSWORKS_API_KEY:
            raise ValueError("HOPSWORKS_API_KEY is not set — add it to .env")
        if not HOPSWORKS_PROJECT:
            raise ValueError("HOPSWORKS_PROJECT is not set — add it to .env")
        self._project = None
        self._feature_group = None

    def _connect(self):
        if self._feature_group is not None:
            return self._feature_group

        import hopsworks  # lazy import: only needed for the real backend

        # cert_folder: hopsworks defaults to /tmp (Linux-style), which
        # DOES NOT EXIST on Windows -> FileNotFoundError during login.
        # Use the OS temp dir instead (C:\Users\...\Temp on Windows,
        # /tmp on Linux) so the same code works on both.
        cert_folder = os.path.join(tempfile.gettempdir(), "hopsworks_certs")

        project = hopsworks.login(
            project=HOPSWORKS_PROJECT,
            host=HOPSWORKS_HOST,
            port=HOPSWORKS_PORT,
            api_key_value=HOPSWORKS_API_KEY,
            cert_folder=cert_folder,
        )
        fs = project.get_feature_store()

        try:
            fg = fs.get_feature_group(name=FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION)
        except Exception:
            fg = None  # 5.x can raise on some backends; treat as missing
        if fg is None:
            # First run: the feature group doesn't exist yet. hopsworks 5.x
            # returns None (does NOT raise) when a group is missing, so we
            # must check the return value, not rely on an exception.
            # Create it with the schema from config. primary_key + event_time
            # are the columns Hopsworks uses for upserts and time-travel reads.
            fg = fs.create_feature_group(
                name=FEATURE_GROUP_NAME,
                version=FEATURE_GROUP_VERSION,
                primary_key=[PRIMARY_KEY],
                event_time=EVENT_TIME_COLUMN,
                online_enabled=False,  # offline-only is fine and saves quota
            )
            logger.info(f"Created feature group {FEATURE_GROUP_NAME} v{FEATURE_GROUP_VERSION}")

        self._feature_group = fg
        return fg

    def write_features(self, df):
        fg = self._connect()
        df = df.copy()
        # Hopsworks expects the event-time column as a pandas Timestamp.
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])
        fg.insert(df)
        logger.info(f"Wrote {len(df)} rows to Hopsworks '{FEATURE_GROUP_NAME}'")

    def read_features(self, start=None, end=None, cities=None):
        fg = self._connect()
        df = fg.read()
        if start is not None:
            df = df[df[EVENT_TIME_COLUMN] >= pd.to_datetime(start)]
        if end is not None:
            df = df[df[EVENT_TIME_COLUMN] <= pd.to_datetime(end)]
        if cities is not None:
            df = df[df[PRIMARY_KEY].isin(cities)]
        logger.info(f"Read {len(df)} rows from Hopsworks '{FEATURE_GROUP_NAME}'")
        return df


class ParquetFeatureStore(FeatureStore):
    """
    Local-disk fallback with the SAME interface. Writes one Parquet file
    per city under data/processed/feature_store_parquet/. Swapping backends
    is one line in get_feature_store() — nothing else in the project changes.
    """

    def __init__(self, root=None):
        self.root = DATA_DIR_FALLBACK if root is None else root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, city):
        # Sanitise: city names are safe slugs already, but be defensive.
        safe = str(city).replace(" ", "_").lower()
        return self.root / f"{safe}.parquet"

    def write_features(self, df):
        """Upsert (merge on city+date) so history accumulates across runs.

        Plan B (no Hopsworks): the Parquet store is the persistent store,
        so an hourly refresh must MERGE into the existing files, not
        overwrite them — otherwise the store only ever holds the trailing
        ingest window and there is no history to train on. Matches the
        documented upsert contract of the Hopsworks adapter.
        """
        df = df.copy()
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])
        for city, group in df.groupby(PRIMARY_KEY):
            path = self._path(city)
            if path.exists():
                old = pd.read_parquet(path)
                if EVENT_TIME_COLUMN in old.columns:
                    old[EVENT_TIME_COLUMN] = pd.to_datetime(old[EVENT_TIME_COLUMN])
                merged = pd.concat([old, group], ignore_index=True)
                merged = merged.drop_duplicates(
                    subset=[PRIMARY_KEY, EVENT_TIME_COLUMN], keep="last"
                ).sort_values(EVENT_TIME_COLUMN)
            else:
                merged = group
            merged.to_parquet(path, index=False)
        logger.info(f"Upserted {len(df)} rows to Parquet fallback ({self.root})")

    def read_features(self, start=None, end=None, cities=None):
        if cities is None:
            files = list(self.root.glob("*.parquet"))
        else:
            files = [self._path(c) for c in cities]
        frames = []
        for path in files:
            if path.exists():
                frames.append(pd.read_parquet(path))
        if not frames:
            logger.warning(f"No Parquet files found in {self.root}")
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])
            if start is not None:
                df = df[df[EVENT_TIME_COLUMN] >= pd.to_datetime(start)]
            if end is not None:
                df = df[df[EVENT_TIME_COLUMN] <= pd.to_datetime(end)]
        logger.info(f"Read {len(df)} rows from Parquet fallback")
        return df


def get_feature_store():
    """
    Factory: return the best available backend. Prefer Hopsworks when the
    credentials exist AND the client is installed; otherwise degrade
    gracefully to Parquet so nothing downstream ever breaks.

    The hopsworks import check matters: hopsworks pins protobuf<5.0.0 +
    pandas<2.4.0, which HARD-CONFLICT with keras (protobuf>=5.26.1) and
    pandas 3.x, so it lives in its own venv (requirements-feature-store.txt).
    Envs that only install requirements.txt (dashboard, training pipeline)
    must NOT crash when secrets are set — they just fall back to Parquet.
    """
    if HOPSWORKS_API_KEY and HOPSWORKS_PROJECT:
        try:
            import importlib.util

            if importlib.util.find_spec("hopsworks") is None:
                raise ImportError("hopsworks package not installed "
                                  "(install requirements-feature-store.txt)")
            return HopsworksFeatureStore()
        except (ValueError, ImportError) as exc:
            logger.warning(f"Hopsworks unavailable: {exc}")
    logger.info("Using Parquet fallback feature store")
    return ParquetFeatureStore()
