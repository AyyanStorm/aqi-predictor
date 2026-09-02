"""
conftest_improvements.py — Enhanced pytest fixtures for AQI Predictor tests

This file shows BEST PRACTICES for fixtures to improve test quality from 5.3/10 → 10/10.
Copy these fixtures to tests/conftest.py to improve fixture usage.

Key Improvements:
✅ Shared model fixtures (no duplication)
✅ Mock API responses
✅ Sample data fixtures
✅ Database fixtures
✅ API client fixtures
✅ Feature store fixtures
"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# ============================================================================
# 1. MODEL FIXTURES (eliminate duplication across test files)
# ============================================================================

@pytest.fixture
def mock_lgbm_model():
    """Fixture: Mock LightGBM model for testing.
    
    Provides a mock LGBMRegressor with realistic behavior:
    - Returns predictions for 3 horizons (24h, 48h, 72h)
    - Has feature names
    - Has mock SHAP explainer
    
    Returns
    -------
    MagicMock
        Mock model with predict() and other methods
        
    Example
    -------
    >>> def test_predict(mock_lgbm_model):
    ...     result = mock_lgbm_model.predict([[25, 8.2, 70]])
    ...     assert result.shape == (1, 3)  # 3 horizons
    """
    model = MagicMock()
    
    # Mock predictions (3 horizons)
    model.predict.return_value = [[68.5, 72.1, 75.3]]
    model.predict_proba = MagicMock(return_value=None)  # Not used for regression
    
    # Mock feature names
    model.feature_names_ = [
        'temperature_2m', 'wind_speed_10m', 'relative_humidity_2m',
        'aqi_lag_1h', 'aqi_lag_24h', 'aqi_lag_168h', 'aqi_roll_mean_24h'
    ]
    
    # Mock SHAP explainer
    model.get_booster.return_value = MagicMock()
    
    return model


@pytest.fixture
def model_registry(mock_lgbm_model):
    """Fixture: ModelRegistry with mocked production model.
    
    Provides a pre-loaded ModelRegistry for testing model management.
    
    Returns
    -------
    ModelRegistry
        Registry with mock production model
        
    Example
    -------
    >>> def test_registry(model_registry):
    ...     model = model_registry.get_production()
    ...     assert model is not None
    """
    from src.training.model_registry import ModelRegistry
    
    registry = ModelRegistry()
    registry._model = mock_lgbm_model
    registry._version = "1.0.0"
    registry._timestamp = datetime.now()
    
    return registry


@pytest.fixture
def predictor(model_registry):
    """Fixture: Predictor with mocked model registry.
    
    Provides a Predictor instance for end-to-end prediction testing.
    
    Returns
    -------
    Predictor
        Predictor with mocked model registry
    """
    from src.inference.predict import Predictor
    
    return Predictor(model_registry)


# ============================================================================
# 2. FEATURE FIXTURES (sample data for consistent testing)
# ============================================================================

@pytest.fixture
def sample_features_df():
    """Fixture: Sample feature DataFrame for testing.
    
    Provides realistic feature data with 3 rows (representing 3 time steps).
    Uses values typical for Karachi, Pakistan.
    
    Returns
    -------
    pd.DataFrame
        Features ready for model prediction
        
    Columns
    -------
    temperature_2m : float
        Temperature in celsius
    wind_speed_10m : float
        Wind speed in km/h
    relative_humidity_2m : float
        Humidity percentage (0-100)
    aqi_lag_1h : float
        AQI from 1 hour ago
    aqi_lag_24h : float
        AQI from 24 hours ago
    """
    return pd.DataFrame({
        'temperature_2m': [25.5, 24.8, 26.1],
        'wind_speed_10m': [8.2, 7.5, 9.1],
        'relative_humidity_2m': [65, 72, 58],
        'aqi_lag_1h': [65, 68, 70],
        'aqi_lag_24h': [70, 72, 68],
        'aqi_lag_168h': [72, 70, 75],
        'aqi_roll_mean_24h': [68, 70, 69],
    })


@pytest.fixture
def sample_prediction_input():
    """Fixture: Single prediction input (one location, one time).
    
    Returns
    -------
    pd.DataFrame
        Single row for prediction
    """
    return pd.DataFrame({
        'temperature_2m': [25.5],
        'wind_speed_10m': [8.2],
        'relative_humidity_2m': [65],
        'aqi_lag_1h': [65],
        'aqi_lag_24h': [70],
        'aqi_lag_168h': [72],
        'aqi_roll_mean_24h': [68],
    })


@pytest.fixture
def parametrize_aqi_levels():
    """Fixture: Multiple AQI levels for parametrized testing.
    
    Returns
    -------
    list[tuple]
        [(aqi_value, category, color, health_msg), ...]
    """
    return [
        (25, "Good", "#00E400", "satisfactory"),
        (75, "Moderate", "#FFFF00", "acceptable"),
        (125, "Unhealthy for Sensitive Groups", "#FF7E00", "sensitive"),
        (175, "Unhealthy", "#FF0000", "general public"),
        (250, "Very Unhealthy", "#8F3F97", "increased for everyone"),
        (350, "Hazardous", "#7E0023", "emergency conditions"),
    ]


# ============================================================================
# 3. LOCATION FIXTURES
# ============================================================================

@pytest.fixture
def sample_location_karachi():
    """Fixture: Karachi location data."""
    return {
        'lat': 24.8607,
        'lon': 67.0011,
        'name': 'Karachi',
        'country': 'Pakistan',
        'timezone': 'Asia/Karachi',
        'population': 14910352,
    }


@pytest.fixture
def sample_location_london():
    """Fixture: London location data."""
    return {
        'lat': 51.5074,
        'lon': -0.1278,
        'name': 'London',
        'country': 'United Kingdom',
        'timezone': 'Europe/London',
        'population': 9002488,
    }


@pytest.fixture
def sample_location_newyork():
    """Fixture: New York location data."""
    return {
        'lat': 40.7128,
        'lon': -74.0060,
        'name': 'New York',
        'country': 'United States',
        'timezone': 'America/New_York',
        'population': 8398748,
    }


@pytest.fixture
def parametrize_locations():
    """Fixture: Multiple locations for parametrized testing."""
    return [
        (24.8607, 67.0011, "Karachi"),
        (51.5074, -0.1278, "London"),
        (40.7128, -74.0060, "New York"),
        (35.6762, 139.6503, "Tokyo"),
        (33.9716, 18.4194, "Cape Town"),
    ]


# ============================================================================
# 4. API FIXTURES
# ============================================================================

@pytest.fixture
def api_client():
    """Fixture: FastAPI test client.
    
    Provides a TestClient for testing API endpoints without starting
    the actual server.
    
    Returns
    -------
    TestClient
        Client for making test requests
        
    Example
    -------
    >>> def test_predict_endpoint(api_client):
    ...     response = api_client.get("/api/v1/predict?lat=24.86&lon=67.01")
    ...     assert response.status_code == 200
    """
    from fastapi.testclient import TestClient
    from app.api import app
    
    return TestClient(app)


@pytest.fixture
def mock_api_response():
    """Fixture: Mock Open-Meteo API response.
    
    Provides a realistic API response for testing feature extraction.
    """
    return {
        'temperature_2m': 25.5,
        'wind_speed_10m': 8.2,
        'relative_humidity_2m': 65,
        'weather_code': 0,
        'is_day': 1,
        'time': '2026-09-02T12:00',
    }


# ============================================================================
# 5. MOCK EXTERNAL SERVICES
# ============================================================================

@pytest.fixture
def mock_open_meteo_client():
    """Fixture: Mocked Open-Meteo API client.
    
    Returns
    -------
    MagicMock
        Mock client for Open-Meteo API
    """
    mock = MagicMock()
    mock.get_forecast.return_value = {
        'us_aqi': [68, 72, 75],
        'temperature_2m': [25.5, 24.8, 26.1],
        'wind_speed_10m': [8.2, 7.5, 9.1],
    }
    return mock


@pytest.fixture
def mock_nominatim_client():
    """Fixture: Mocked Nominatim reverse geocoding client.
    
    Returns
    -------
    MagicMock
        Mock client for Nominatim API
    """
    mock = MagicMock()
    mock.reverse_geocode.return_value = {
        'address': 'Karachi, Pakistan',
        'country': 'Pakistan',
        'city': 'Karachi',
    }
    return mock


# ============================================================================
# 6. DATABASE FIXTURES
# ============================================================================

@pytest.fixture
def temp_sqlite_db(tmp_path):
    """Fixture: Temporary SQLite database for testing.
    
    Creates a temporary database file that's automatically cleaned up
    after the test completes.
    
    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest's temporary directory fixture
        
    Returns
    -------
    pathlib.Path
        Path to temporary database file
        
    Example
    -------
    >>> def test_store(temp_sqlite_db):
    ...     store = TrackingStore(db_path=str(temp_sqlite_db))
    ...     store.insert_prediction(...)
    ...     # Database automatically cleaned up after test
    """
    db_path = tmp_path / "test.db"
    # Could initialize schema here if needed
    return db_path


@pytest.fixture
def mock_tracking_store():
    """Fixture: Mocked tracking store for drift detection tests.
    
    Returns
    -------
    MagicMock
        Mock TrackingStore
    """
    mock = MagicMock()
    mock.get_predictions.return_value = pd.DataFrame({
        'timestamp': pd.date_range('2026-09-01', periods=100, freq='H'),
        'aqi_predicted': [68, 72, 75, 70, 69] * 20,
        'aqi_actual': [70, 73, 74, 71, 70] * 20,
    })
    return mock


# ============================================================================
# 7. PARAMETRIZATION FIXTURES (data-driven testing)
# ============================================================================

@pytest.fixture
def parametrize_aqi_categories():
    """Fixture: AQI values and expected categories for parametrized testing.
    
    Yields
    ------
    tuple
        (aqi_value, expected_category) pairs
    """
    return [
        (25, "Good"),
        (75, "Moderate"),
        (125, "Unhealthy for Sensitive Groups"),
        (175, "Unhealthy"),
        (250, "Very Unhealthy"),
        (350, "Hazardous"),
        (0, "Good"),  # Edge case: min
        (500, "Hazardous"),  # Edge case: max
    ]


@pytest.fixture
def parametrize_invalid_coordinates():
    """Fixture: Invalid coordinate pairs for error testing.
    
    Yields
    ------
    tuple
        (lat, lon, expected_error) pairs
    """
    return [
        (100, 0, ValueError),  # Latitude out of range
        (0, 200, ValueError),  # Longitude out of range
        (-100, 0, ValueError),  # Latitude too negative
        (45, "invalid", TypeError),  # Non-numeric longitude
    ]


# ============================================================================
# 8. CACHE & PERFORMANCE FIXTURES
# ============================================================================

@pytest.fixture
def clear_cache_before_test():
    """Fixture: Clear all caches before test runs.
    
    This ensures each test starts with a clean state.
    
    Yields
    ------
    None
    """
    # Cleanup before test
    import glob
    for cache_file in glob.glob('.cache*'):
        try:
            Path(cache_file).unlink()
        except:
            pass
    
    yield
    
    # Cleanup after test
    for cache_file in glob.glob('.cache*'):
        try:
            Path(cache_file).unlink()
        except:
            pass


@pytest.fixture
def benchmark_timer():
    """Fixture: Simple benchmark timer for performance testing.
    
    Returns
    -------
    dict
        Dict with start_time, elapsed methods
        
    Example
    -------
    >>> def test_performance(benchmark_timer):
    ...     with benchmark_timer.start():
    ...         result = predict(24.86, 67.01)
    ...     assert benchmark_timer.elapsed < 0.5  # < 500ms
    """
    import time
    from contextlib import contextmanager
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        @contextmanager
        def start(self):
            self.start_time = time.time()
            try:
                yield
            finally:
                self.end_time = time.time()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return Timer()


# ============================================================================
# 9. MARKERS & CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "smoke: mark test as smoke test"
    )
    config.addinivalue_line(
        "markers", "requires_model: mark test as requiring ML model"
    )


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
BEFORE (Old Style - Repetitive):
────────────────────────────────

def test_predict_1():
    model = MagicMock()
    model.predict.return_value = [[68.5, 72.1, 75.3]]
    predictor = Predictor(model)
    result = predictor.predict([[25, 8.2, 70]])
    assert result is not None

def test_predict_2():
    model = MagicMock()
    model.predict.return_value = [[68.5, 72.1, 75.3]]
    predictor = Predictor(model)
    result = predictor.predict([[26, 7.5, 72]])
    assert result is not None

# ... repeated 10+ times with different inputs


AFTER (New Style - DRY & Parametrized):
──────────────────────────────────────

@pytest.mark.parametrize("features,expected_count", [
    ([[25, 8.2, 70]], 1),
    ([[26, 7.5, 72], [24, 8.9, 65]], 2),
    ([[25, 8.2, 70]] * 5, 5),  # Batch of 5
])
def test_predict_batch(predictor, features, expected_count):
    # ✅ One test, multiple cases
    # ✅ Uses fixture (no model setup)
    # ✅ Cleaner, more maintainable
    result = predictor.predict(features)
    assert len(result) == expected_count


FIXTURE USAGE EXAMPLES:
──────────────────────

def test_with_model(mock_lgbm_model):
    # ✅ Uses fixture instead of setup
    result = mock_lgbm_model.predict([[25, 8.2, 70]])
    assert result is not None

def test_with_features(sample_features_df):
    # ✅ Uses fixture for consistent test data
    assert len(sample_features_df) == 3

def test_with_api(api_client):
    # ✅ Uses fixture for test client
    response = api_client.get("/api/v1/predict?lat=24.86&lon=67.01")
    assert response.status_code == 200

def test_with_locations(parametrize_locations):
    # ✅ Uses fixture for multiple test cases
    for lat, lon, name in parametrize_locations:
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180
"""
