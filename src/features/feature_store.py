"""
feature_store.py — Feature Store interface (backend-agnostic).

The Feature Store is where the training pipeline reads from and the
feature pipeline writes to. The model never talks to the raw API at
training time — only to this store.

This module provides backend-agnostic functions that hide the specific
feature store implementation (Hopsworks, Parquet, S3, BigQuery, etc.).
The rest of the project uses these simple functions and never directly
imports a backend.

Schema (defined in config.py):
    feature group : aqi_features (version 1)
    primary key   : city
    event time    : date (hourly timestamp)

Issue #42: Abstraction layer for feature store backends.
"""

from typing import List, Optional

import pandas as pd

from src.features.backends import feature_store_backend
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Backend-agnostic public API
# These functions delegate to the configured backend instance


def write_features(df: pd.DataFrame) -> None:
    """
    Write features to the feature store (backend-agnostic).

    This function delegates to the configured backend (Hopsworks, Parquet, etc.)
    without exposing backend details to callers.

    Args:
        df: DataFrame with features to write
           (city, date, and feature columns)
    """
    feature_store_backend.write_features(df)


def read_features(
    start: Optional[str] = None,
    end: Optional[str] = None,
    cities: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Read features from the feature store (backend-agnostic).

    This function delegates to the configured backend (Hopsworks, Parquet, etc.)
    without exposing backend details to callers.

    Args:
        start: Optional start date (ISO format or pandas-parseable)
        end: Optional end date (ISO format or pandas-parseable)
        cities: Optional list of cities to filter

    Returns:
        DataFrame with features matching filters
    """
    return feature_store_backend.read_features(start=start, end=end, cities=cities)


def list_cities() -> List[str]:
    """
    List all cities in the feature store (backend-agnostic).

    Returns:
        List of city names
    """
    return feature_store_backend.list_cities()


def get_feature_store():
    """Deprecated: use feature_store_backend from backends.py instead.

    This function is kept for backward compatibility but new code should
    use the module-level write_features(), read_features(), and list_cities()
    functions instead.
    """
    logger.warning(
        "get_feature_store() is deprecated — "
        "use write_features/read_features/list_cities functions instead"
    )
    return feature_store_backend


__all__ = [
    "write_features",
    "read_features",
    "list_cities",
    "get_feature_store",
    "feature_store_backend",
]
