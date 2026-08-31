"""
backends.py — Feature store backend abstraction (Strategy pattern).

Defines a clean interface for feature store backends, enabling easy
switching between Hopsworks, Parquet, S3, BigQuery, etc. without
changing code that depends on feature storage.

Issue #42: Abstraction layer for feature store backends.
"""

import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

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


class FeatureStoreBackend(ABC):
    """
    Abstract interface for feature store backends.
    
    All backends implement the same interface, enabling easy swapping
    and testing without coupling to any specific implementation.
    """

    @abstractmethod
    def write_features(self, df: pd.DataFrame) -> None:
        """
        Write or upsert features to the store.
        
        Args:
            df: DataFrame with columns matching feature group schema
               (city, date, and feature columns)
        
        Returns:
            None
        """
        pass

    @abstractmethod
    def read_features(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        cities: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Read features from the store with optional filtering.
        
        Args:
            start: Optional start date (ISO format or pandas-parseable)
            end: Optional end date (ISO format or pandas-parseable)
            cities: Optional list of cities to filter
        
        Returns:
            DataFrame with features matching filters
        """
        pass

    @abstractmethod
    def list_cities(self) -> List[str]:
        """
        List all cities available in the feature store.
        
        Returns:
            List of city names
        """
        pass


class HopsworksBackend(FeatureStoreBackend):
    """
    Hopsworks Feature Store backend.
    
    Stores features in Hopsworks cloud feature store with support for
    time-travel reads, upserts, and online feature serving.
    
    Requires:
    - HOPSWORKS_API_KEY environment variable
    - HOPSWORKS_PROJECT environment variable
    - hopsworks Python package installed
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        project: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """
        Initialize Hopsworks backend.
        
        Args:
            api_key: Hopsworks API key (defaults to HOPSWORKS_API_KEY)
            project: Hopsworks project name (defaults to HOPSWORKS_PROJECT)
            host: Hopsworks host (defaults to HOPSWORKS_HOST)
            port: Hopsworks port (defaults to HOPSWORKS_PORT)
        
        Raises:
            ValueError: If api_key or project is missing
        """
        self.api_key = api_key or HOPSWORKS_API_KEY
        self.project = project or HOPSWORKS_PROJECT
        self.host = host or HOPSWORKS_HOST
        self.port = port or HOPSWORKS_PORT

        if not self.api_key:
            raise ValueError("HOPSWORKS_API_KEY is not set — add it to .env")
        if not self.project:
            raise ValueError("HOPSWORKS_PROJECT is not set — add it to .env")

        self._feature_group = None

    def _connect(self):
        """Connect to Hopsworks and return feature group (lazy initialization)."""
        if self._feature_group is not None:
            return self._feature_group

        import hopsworks  # lazy import: only needed for Hopsworks backend

        # Use OS temp dir for certificates (works on Windows and Linux)
        cert_folder = os.path.join(tempfile.gettempdir(), "hopsworks_certs")

        hopsworks_project = hopsworks.login(
            project=self.project,
            host=self.host,
            port=self.port,
            api_key_value=self.api_key,
            cert_folder=cert_folder,
        )
        fs = hopsworks_project.get_feature_store()

        try:
            fg = fs.get_feature_group(
                name=FEATURE_GROUP_NAME, version=FEATURE_GROUP_VERSION
            )
        except Exception:
            fg = None  # Some backends return None instead of raising

        if fg is None:
            # Create feature group with schema from config
            fg = fs.create_feature_group(
                name=FEATURE_GROUP_NAME,
                version=FEATURE_GROUP_VERSION,
                primary_key=[PRIMARY_KEY],
                event_time=EVENT_TIME_COLUMN,
                online_enabled=False,  # offline-only saves quota
                time_travel_format="HUDI",  # HUDI is portable across platforms
            )
            logger.info(
                f"Created feature group {FEATURE_GROUP_NAME} v{FEATURE_GROUP_VERSION}"
            )

        self._feature_group = fg
        return fg

    def write_features(self, df: pd.DataFrame) -> None:
        """Write features to Hopsworks with upsert semantics."""
        if df is None or df.empty:
            logger.warning(
                "write_features: nothing to write (empty DataFrame) — "
                "skipping Hopsworks insert."
            )
            return

        fg = self._connect()
        df = df.copy()

        # Convert event time to pandas Timestamp
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])

        fg.insert(df)
        logger.info(
            f"Wrote {len(df)} rows to Hopsworks '{FEATURE_GROUP_NAME}'"
        )

    def read_features(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        cities: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read features from Hopsworks with optional filtering."""
        fg = self._connect()
        df = fg.read()

        if start is not None:
            df = df[df[EVENT_TIME_COLUMN] >= pd.to_datetime(start)]
        if end is not None:
            df = df[df[EVENT_TIME_COLUMN] <= pd.to_datetime(end)]
        if cities is not None:
            df = df[df[PRIMARY_KEY].isin(cities)]

        logger.info(
            f"Read {len(df)} rows from Hopsworks '{FEATURE_GROUP_NAME}'"
        )
        return df

    def list_cities(self) -> List[str]:
        """List all cities in Hopsworks feature group."""
        fg = self._connect()
        df = fg.read()
        if df.empty:
            return []
        return df[PRIMARY_KEY].unique().tolist()


class ParquetBackend(FeatureStoreBackend):
    """
    Local Parquet file backend.
    
    Stores features as Parquet files (one per city) on local or remote
    filesystem. Useful for development, testing, and fallback when
    Hopsworks is unavailable.
    
    Features:
    - Upsert semantics (merge on city + date)
    - Supports date filtering
    - No external dependencies (beyond pandas)
    """

    def __init__(self, root: Optional[Path] = None):
        """
        Initialize Parquet backend.
        
        Args:
            root: Root directory for Parquet files
                  (defaults to DATA_DIR_FALLBACK)
        """
        self.root = Path(root) if root else DATA_DIR_FALLBACK
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, city: str) -> Path:
        """Get file path for a city."""
        # Sanitize city name
        safe = str(city).replace(" ", "_").lower()
        return self.root / f"{safe}.parquet"

    def write_features(self, df: pd.DataFrame) -> None:
        """Upsert features to Parquet (merge on city + date)."""
        if df is None or df.empty:
            logger.warning(
                "write_features: nothing to write (empty DataFrame) — "
                "skipping Parquet upsert."
            )
            return

        df = df.copy()

        # Convert event time to pandas Timestamp
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])

        # Write per-city to enable upsert
        for city, group in df.groupby(PRIMARY_KEY):
            path = self._path(city)

            if path.exists():
                # Merge with existing data
                old = pd.read_parquet(path)
                if EVENT_TIME_COLUMN in old.columns:
                    old[EVENT_TIME_COLUMN] = pd.to_datetime(old[EVENT_TIME_COLUMN])

                merged = pd.concat([old, group], ignore_index=True)
                # Keep latest version of each city+date combination
                merged = merged.drop_duplicates(
                    subset=[PRIMARY_KEY, EVENT_TIME_COLUMN], keep="last"
                ).sort_values(EVENT_TIME_COLUMN)
            else:
                merged = group

            merged.to_parquet(path, index=False)

        logger.info(
            f"Upserted {len(df)} rows to Parquet fallback ({self.root})"
        )

    def read_features(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        cities: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read features from Parquet with optional filtering."""
        if cities is None:
            # Read all cities
            files = list(self.root.glob("*.parquet"))
        else:
            # Read specific cities
            files = [self._path(c) for c in cities]

        frames = []
        for path in files:
            if path.exists():
                frames.append(pd.read_parquet(path))

        if not frames:
            logger.warning(f"No Parquet files found in {self.root}")
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        # Apply date filtering
        if EVENT_TIME_COLUMN in df.columns:
            df[EVENT_TIME_COLUMN] = pd.to_datetime(df[EVENT_TIME_COLUMN])
            if start is not None:
                df = df[df[EVENT_TIME_COLUMN] >= pd.to_datetime(start)]
            if end is not None:
                df = df[df[EVENT_TIME_COLUMN] <= pd.to_datetime(end)]

        logger.info(f"Read {len(df)} rows from Parquet fallback")
        return df

    def list_cities(self) -> List[str]:
        """List all cities in Parquet store."""
        files = list(self.root.glob("*.parquet"))
        if not files:
            return []
        # Extract city names from filenames (without .parquet extension)
        return [f.stem for f in files]


def get_feature_store_backend() -> FeatureStoreBackend:
    """
    Factory function: get the best available backend.
    
    Strategy:
    1. If HOPSWORKS_API_KEY and HOPSWORKS_PROJECT are set AND
       hopsworks package is installed: use HopsworksBackend
    2. Otherwise: fall back to ParquetBackend (always available)
    
    This enables graceful degradation when Hopsworks is unavailable
    without requiring any code changes elsewhere.
    
    Returns:
        FeatureStoreBackend instance (either Hopsworks or Parquet)
    """
    if HOPSWORKS_API_KEY and HOPSWORKS_PROJECT:
        try:
            import importlib.util

            if importlib.util.find_spec("hopsworks") is None:
                raise ImportError(
                    "hopsworks package not installed "
                    "(install requirements-feature-store.txt)"
                )
            logger.info("Using Hopsworks feature store backend")
            return HopsworksBackend()
        except (ValueError, ImportError) as exc:
            logger.warning(f"Hopsworks unavailable: {exc}")

    logger.info("Using Parquet fallback feature store backend")
    return ParquetBackend()


# Global singleton instance
feature_store_backend = get_feature_store_backend()


__all__ = [
    "FeatureStoreBackend",
    "HopsworksBackend",
    "ParquetBackend",
    "get_feature_store_backend",
    "feature_store_backend",
]
