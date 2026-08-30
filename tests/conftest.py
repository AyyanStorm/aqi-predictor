"""
conftest.py — Pytest configuration and shared fixtures.

Handles rate limiter reset, test database cleanup, and other fixtures
needed across multiple test modules.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Reset the rate limiter's in-memory storage before/after each test.
    
    This is CRITICAL because slowapi's default in-memory storage maintains
    request counts across test functions. Without resetting, one test that
    exceeds a limit will cause subsequent tests to fail prematurely.
    
    autouse=True means this fixture runs automatically for every test.
    """
    try:
        from src.utils.rate_limiter import limiter
        
        # Clear the storage before the test
        if hasattr(limiter, '_storage') and limiter._storage is not None:
            # slowapi 0.1.9 uses _storage internally
            if isinstance(limiter._storage, dict):
                limiter._storage.clear()
            elif hasattr(limiter._storage, 'storage') and isinstance(limiter._storage.storage, dict):
                limiter._storage.storage.clear()
            elif hasattr(limiter._storage, 'clear'):
                limiter._storage.clear()
        
        # Also try the public storage attribute
        if hasattr(limiter, 'storage') and limiter.storage is not None:
            if isinstance(limiter.storage, dict):
                limiter.storage.clear()
            elif hasattr(limiter.storage, 'clear'):
                limiter.storage.clear()
    except ImportError:
        # slowapi not installed yet (might happen during test collection)
        pass
    
    yield
    
    # Clear again after the test for good measure
    try:
        from src.utils.rate_limiter import limiter
        
        if hasattr(limiter, '_storage') and limiter._storage is not None:
            if isinstance(limiter._storage, dict):
                limiter._storage.clear()
            elif hasattr(limiter._storage, 'storage') and isinstance(limiter._storage.storage, dict):
                limiter._storage.storage.clear()
            elif hasattr(limiter._storage, 'clear'):
                limiter._storage.clear()
        
        if hasattr(limiter, 'storage') and limiter.storage is not None:
            if isinstance(limiter.storage, dict):
                limiter.storage.clear()
            elif hasattr(limiter.storage, 'clear'):
                limiter.storage.clear()
    except ImportError:
        pass


@pytest.fixture
def mock_model_registry():
    """Mock the ModelRegistry for tests that don't need real model data."""
    mock = MagicMock()
    mock.production_entry.return_value = None
    return mock


@pytest.fixture
def sample_prediction():
    """Sample prediction payload for testing API responses."""
    return {
        "aqi": 42.5,
        "status": "ok",
        "current": {"aqi": 42.5, "category": "Good"},
        "forecast": [
            {"time": "2026-08-31T00:00:00Z", "aqi": 45.0, "category": "Good"},
            {"time": "2026-09-01T00:00:00Z", "aqi": 48.0, "category": "Good"},
            {"time": "2026-09-02T00:00:00Z", "aqi": 50.0, "category": "Moderate"},
        ],
        "model": {"name": "lightgbm", "version": "v1.0.0"},
        "request_id": "test-12345",
    }
