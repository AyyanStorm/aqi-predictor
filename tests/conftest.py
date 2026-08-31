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
    
    This is CRITICAL because slowapi's default in-memory storage (MemoryStorage)
    maintains request counts across test functions. Without resetting, one test
    that exceeds a limit will cause subsequent tests to fail prematurely.
    
    slowapi.Limiter uses limiter._storage (MemoryStorage object).
    MemoryStorage internally uses .storage (Counter object from collections).
    We must clear this Counter before each test.
    
    autouse=True means this fixture runs automatically for every test.
    """
    _clear_test_rate_limiter_storage()
    yield
    _clear_test_rate_limiter_storage()


def _clear_test_rate_limiter_storage():
    """Helper to clear the rate limiter storage.
    
    Handles both dict and Counter objects properly.
    Clears the limiter's in-memory Counter to prevent test pollution.
    """
    try:
        from src.utils.rate_limiter import limiter
        
        if hasattr(limiter, '_storage') and limiter._storage is not None:
            memory_storage = limiter._storage
            # MemoryStorage has a .storage attribute (usually a Counter)
            if hasattr(memory_storage, 'storage'):
                storage_obj = memory_storage.storage
                # Completely clear it
                if hasattr(storage_obj, 'clear'):
                    storage_obj.clear()
                elif hasattr(storage_obj, 'popitem'):
                    # Counter/dict fallback
                    try:
                        while storage_obj:
                            storage_obj.popitem()
                    except (KeyError, TypeError):
                        pass
                else:
                    # Last resort: iterate and delete
                    try:
                        for key in list(storage_obj.keys()):
                            del storage_obj[key]
                    except (AttributeError, TypeError):
                        pass
    except ImportError:
        # slowapi not installed yet (might happen during test collection)
        pass
    except Exception as e:
        # Silently ignore any clearing errors but log them
        import sys
        print(f"Warning: Failed to clear rate limiter storage: {e}", file=sys.stderr)


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
