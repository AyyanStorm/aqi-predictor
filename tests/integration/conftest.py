"""
conftest.py — Shared fixtures for integration tests.

Provides real data sources, test coordinates, and client instances
for end-to-end integration testing.

Issue #43: Integration tests for end-to-end paths.
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

from app.api import app


# Markers for test categorization
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow (may call real APIs)"
    )
    config.addinivalue_line(
        "markers", "requires_model: mark test as requiring production model"
    )
    config.addinivalue_line(
        "markers", "requires_data: mark test as requiring real data"
    )


# ============================================================================
# Test Coordinates
# ============================================================================


@pytest.fixture
def test_coordinates():
    """Test locations across Pakistan.
    
    Returns:
        dict: City names mapped to (lat, lon) tuples
    """
    return {
        "Karachi": (24.8608, 67.0104),
        "Lahore": (31.5497, 74.3436),
        "Islamabad": (33.6844, 73.0479),
        "Peshawar": (34.0151, 71.5787),
        "Quetta": (30.1798, 66.9750),
    }


@pytest.fixture
def karachi_coords():
    """Karachi coordinates."""
    return {"lat": 24.8608, "lon": 67.0104, "city": "Karachi"}


@pytest.fixture
def lahore_coords():
    """Lahore coordinates."""
    return {"lat": 31.5497, "lon": 74.3436, "city": "Lahore"}


# ============================================================================
# API Client
# ============================================================================


@pytest.fixture
def api_client():
    """FastAPI test client for /predict and /health endpoints.
    
    Yields:
        TestClient: Configured test client
    """
    return TestClient(app)


# ============================================================================
# Feature Store Data
# ============================================================================


@pytest.fixture(scope="session")
def real_feature_store():
    """Load real feature store for integration tests.
    
    Skips test if feature store doesn't exist (e.g., in CI without data).
    
    Returns:
        pd.DataFrame: Feature data for all cities
    """
    store_path = Path("data/processed/feature_store_parquet")
    
    if not store_path.exists():
        pytest.skip("Feature store not found (normal in CI)")
    
    try:
        # Try to load all city parquet files
        files = list(store_path.glob("*.parquet"))
        if not files:
            pytest.skip("No feature data available")
        
        frames = []
        for file in files:
            frames.append(pd.read_parquet(file))
        
        if not frames:
            pytest.skip("No feature data available")
        
        df = pd.concat(frames, ignore_index=True)
        return df.sort_values("date").reset_index(drop=True)
    
    except Exception as e:
        pytest.skip(f"Could not load feature store: {e}")


@pytest.fixture
def feature_sample(real_feature_store):
    """Sample of real features for inference tests.
    
    Returns:
        pd.DataFrame: First 100 rows of feature store
    """
    if real_feature_store is None or real_feature_store.empty:
        pytest.skip("No feature data available")
    
    return real_feature_store.head(100).copy()


# ============================================================================
# Sample Data
# ============================================================================


@pytest.fixture
def sample_forecast_data():
    """Create sample forecast data structure.
    
    Returns:
        dict: Forecast response structure
    """
    base_date = datetime.utcnow()
    return {
        "current_aqi": 145,
        "current_pm25": 55,
        "current_pm10": 120,
        "forecast_24h": 150,
        "forecast_48h": 130,
        "forecast_72h": 140,
        "last_updated": base_date.isoformat(),
        "confidence": 0.85,
    }


@pytest.fixture
def sample_features():
    """Create sample engineered features.
    
    Returns:
        pd.DataFrame: Sample features with expected columns
    """
    return pd.DataFrame({
        "city": ["Karachi"] * 10,
        "date": pd.date_range("2026-01-01", periods=10),
        "pm25": range(50, 60),
        "pm10": range(100, 110),
        "temperature": range(25, 35),
        "humidity": range(40, 50),
        "wind_speed": range(5, 15),
        "aqi": range(100, 110),
    })


# ============================================================================
# Model Registry
# ============================================================================


@pytest.fixture
def model_registry_mock():
    """Mock model registry for testing.
    
    Returns:
        MagicMock: Mocked ModelRegistry instance
    """
    mock = MagicMock()
    mock.production_entry.return_value = {
        "model_version": "prod-v1",
        "artifact_path": "/tmp/model.pkl",
        "created_at": datetime.utcnow().isoformat(),
        "features": ["pm25", "pm10", "temperature"],
        "accuracy": 0.75,
    }
    return mock


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def tracking_store_mock():
    """Mock tracking store (predictions log).
    
    Returns:
        MagicMock: Mocked tracking store
    """
    mock = MagicMock()
    mock.log_prediction.return_value = True
    mock.get_latest_predictions.return_value = []
    return mock


@pytest.fixture
def feature_store_mock():
    """Mock feature store.
    
    Returns:
        MagicMock: Mocked feature store backend
    """
    mock = MagicMock()
    mock.read_features.return_value = pd.DataFrame()
    mock.write_features.return_value = True
    mock.list_cities.return_value = ["Karachi", "Lahore"]
    return mock


# ============================================================================
# Markers & Skipping
# ============================================================================


def pytest_collection_modifyitems(config, items):
    """Add markers based on test names and skip slow tests in CI."""
    for item in items:
        # Mark all tests in integration/ as integration
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        
        # Mark slow tests
        if "slow" in item.name or "end_to_end" in item.name:
            item.add_marker(pytest.mark.slow)
        
        # Mark tests requiring model
        if "model" in item.name or "inference" in item.name:
            item.add_marker(pytest.mark.requires_model)
        
        # Mark tests requiring data
        if "feature" in item.name or "real_data" in item.name:
            item.add_marker(pytest.mark.requires_data)


__all__ = [
    "test_coordinates",
    "karachi_coords",
    "lahore_coords",
    "api_client",
    "real_feature_store",
    "feature_sample",
    "sample_forecast_data",
    "sample_features",
    "model_registry_mock",
    "tracking_store_mock",
    "feature_store_mock",
]
