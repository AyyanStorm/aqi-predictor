"""
test_data_quality_integration.py — Integration tests for validation in pipelines.

Tests that DataQualityValidator properly gates data ingestion and training.

Issue #37: Automated data quality validation in production.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from src.data_ingestion.validators import DataQualityValidator
from src.config import CITIES


@pytest.fixture
def valid_feature_store():
    """Create valid feature store mimicking production data."""
    now = datetime.now(timezone.utc)
    data = []
    
    for city_name in list(CITIES.keys())[:3]:  # Use 3 cities for testing
        for i in range(100):
            data.append({
                'city': city_name,
                'date': now - timedelta(hours=i),
                'us_aqi': np.random.randint(10, 200),
                'pm2_5': np.random.uniform(5, 50),
                'pm10': np.random.uniform(10, 100),
                'temperature_2m': np.random.uniform(10, 35),
                'wind_speed_10m': np.random.uniform(0, 20),
                'relative_humidity_2m': np.random.uniform(30, 95),
                'surface_pressure': np.random.uniform(900, 1050),
                'boundary_layer_height': np.random.uniform(400, 2000),
            })
    
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    return df


class TestValidationInPipeline:
    """Test validation as pipeline gate."""
    
    def test_pipeline_accepts_valid_data(self, valid_feature_store):
        """Pipeline should accept valid data."""
        expected_cities = list(CITIES.keys())[:3]
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all(
            expected_cities=expected_cities,
            max_age_hours=6,
            max_null_pct=5
        )
        
        # Valid data should pass all checks
        assert passed == True
        assert len(errors) == 0
    
    def test_pipeline_rejects_stale_data(self, valid_feature_store):
        """Pipeline should reject stale data."""
        # Make data 24 hours old
        valid_feature_store['date'] = valid_feature_store['date'] - timedelta(hours=24)
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all(
            max_age_hours=6
        )
        
        assert passed == False
        assert any('stale' in e.lower() for e in errors)
    
    def test_pipeline_rejects_missing_city(self, valid_feature_store):
        """Pipeline should reject if expected city is missing."""
        # Remove one city
        valid_feature_store = valid_feature_store[valid_feature_store['city'] != list(CITIES.keys())[0]]
        expected_cities = list(CITIES.keys())[:3]
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all(
            expected_cities=expected_cities
        )
        
        assert passed == False
        assert any('missing' in e.lower() for e in errors)
    
    def test_pipeline_rejects_duplicates(self, valid_feature_store):
        """Pipeline should reject duplicate rows."""
        # Duplicate the first row
        dup_row = valid_feature_store.iloc[0].copy()
        valid_feature_store = pd.concat([valid_feature_store, pd.DataFrame([dup_row])], ignore_index=True)
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all()
        
        assert passed == False
        assert any('duplicate' in e.lower() for e in errors)


class TestValidationMetrics:
    """Test that validation produces proper summary for metrics."""
    
    def test_summary_on_valid_data(self, valid_feature_store):
        """Summary should reflect successful validation."""
        expected_cities = list(CITIES.keys())[:3]
        
        validator = DataQualityValidator(valid_feature_store)
        validator.run_all(expected_cities=expected_cities)
        
        summary = validator.get_summary()
        assert summary['passed'] == True
        assert summary['error_count'] == 0
        assert isinstance(summary['warnings'], list)
    
    def test_summary_on_invalid_data(self, valid_feature_store):
        """Summary should reflect failed validation."""
        # Introduce error: negative AQI
        valid_feature_store.loc[0, 'us_aqi'] = -10
        
        validator = DataQualityValidator(valid_feature_store)
        validator.run_all()
        
        summary = validator.get_summary()
        assert summary['passed'] == False
        assert summary['error_count'] > 0


class TestValidationWithRealWorldData:
    """Test validation with realistic edge cases."""
    
    def test_handles_partial_nulls_in_boundary_layer(self, valid_feature_store):
        """Should warn but not fail on boundary_layer_height nulls."""
        # Add realistic nulls to boundary_layer_height (known gap)
        valid_feature_store.loc[::3, 'boundary_layer_height'] = np.nan
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all()
        
        # Should pass despite boundary_layer nulls
        assert passed == True
        assert len(errors) == 0
        # But should have a warning
        assert any('boundary_layer' in w.lower() for w in warnings)
    
    def test_handles_extreme_aqi_spikes(self, valid_feature_store):
        """Should warn on extreme AQI but not fail."""
        # Add extreme AQI value (e.g., wildfires)
        valid_feature_store.loc[0, 'us_aqi'] = 750
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all()
        
        # Should pass but warn
        assert passed == True
        assert any('extreme' in w.lower() for w in warnings)


class TestValidationPreventsBadTraining:
    """Test that validation prevents training on bad data."""
    
    def test_prevents_training_on_duplicates(self, valid_feature_store):
        """Training should fail if data has duplicates."""
        # Add duplicates
        dup_row = valid_feature_store.iloc[0].copy()
        valid_feature_store = pd.concat([valid_feature_store, pd.DataFrame([dup_row])], ignore_index=True)
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all()
        
        # Validation should fail
        assert passed == False
        
        # Training code would check: if not passed: raise ValueError(...)
        if not passed:
            pytest.skip("Would abort training - validation failed as expected")
    
    def test_prevents_training_on_missing_cities(self, valid_feature_store):
        """Training should fail if expected cities missing."""
        # Remove a city
        valid_feature_store = valid_feature_store[valid_feature_store['city'] != list(CITIES.keys())[0]]
        expected_cities = list(CITIES.keys())[:3]
        
        validator = DataQualityValidator(valid_feature_store)
        passed, errors, warnings = validator.run_all(expected_cities=expected_cities)
        
        # Validation should fail
        assert passed == False
        
        if not passed:
            pytest.skip("Would abort training - validation failed as expected")


class TestValidationPerformance:
    """Test validation on large datasets."""
    
    def test_validates_large_dataset_efficiently(self, valid_feature_store):
        """Validation should handle 1000+ row datasets quickly."""
        # Expand dataset by adding NEW data, not duplicating
        # Create additional 1000+ rows with different dates to avoid duplicates
        large_dfs = [valid_feature_store]
        now = datetime.now(timezone.utc)
        
        for batch in range(9):  # Create 9 more batches with different timestamps
            df_batch = valid_feature_store.copy()
            # Shift timestamps forward so no duplicates
            df_batch['date'] = df_batch['date'] + timedelta(hours=(batch + 1) * 100)
            large_dfs.append(df_batch)
        
        large_df = pd.concat(large_dfs, ignore_index=True)
        
        validator = DataQualityValidator(large_df)
        
        import time
        start = time.time()
        passed, errors, warnings = validator.run_all()
        elapsed = time.time() - start
        
        # Should complete in under 1 second even with 1000+ rows
        assert elapsed < 1.0, f"Validation took {elapsed:.2f}s, expected < 1s"
        assert passed == True
