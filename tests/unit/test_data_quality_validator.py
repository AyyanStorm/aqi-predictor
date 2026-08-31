"""
test_data_quality_validator.py — Unit tests for DataQualityValidator.

Tests all validation checks:
- Freshness detection
- Duplicate row detection
- Null value thresholds
- Timestamp validation
- Value range checks
- City coverage verification

Issue #37: Automated data quality validation in production.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from src.data_ingestion.validators import DataQualityValidator


@pytest.fixture
def sample_feature_df():
    """Create a valid sample feature store DataFrame."""
    now = datetime.now(timezone.utc)
    
    data = []
    for city in ['Karachi', 'Lahore', 'Islamabad']:
        for i in range(24):
            data.append({
                'city': city,
                'date': now - timedelta(hours=i),
                'us_aqi': np.random.randint(10, 200),
                'pm2_5': np.random.uniform(5, 50),
                'pm10': np.random.uniform(10, 100),
                'temperature_2m': np.random.uniform(10, 35),
                'wind_speed_10m': np.random.uniform(0, 20),
                'boundary_layer_height': np.random.uniform(400, 2000),
            })
    
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    return df


class TestFreshnessCheck:
    """Test freshness validation."""
    
    def test_fresh_data_passes(self, sample_feature_df):
        """Recent data should pass freshness check."""
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_freshness(max_age_hours=6) == True
        assert len(validator.errors) == 0
    
    def test_stale_data_fails(self, sample_feature_df):
        """Data older than threshold should fail."""
        # Make all timestamps 12 hours old
        sample_feature_df['date'] = sample_feature_df['date'] - timedelta(hours=12)
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_freshness(max_age_hours=6) == False
        assert len(validator.errors) == 1
        assert 'stale' in validator.errors[0].lower()
    
    def test_empty_dataframe_fails(self):
        """Empty feature store should fail."""
        df = pd.DataFrame()
        validator = DataQualityValidator(df)
        assert validator.check_freshness() == False
        assert len(validator.errors) == 1


class TestDuplicateDetection:
    """Test duplicate row detection."""
    
    def test_no_duplicates_passes(self, sample_feature_df):
        """DataFrame with no duplicates should pass."""
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_duplicates() == True
        assert len(validator.errors) == 0
    
    def test_detects_duplicate_rows(self, sample_feature_df):
        """Should detect duplicate (city, date) rows."""
        # Add a duplicate row
        first_row = sample_feature_df.iloc[0].copy()
        sample_feature_df = pd.concat([sample_feature_df, pd.DataFrame([first_row])], ignore_index=True)
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_duplicates() == False
        assert len(validator.errors) == 1
        assert 'duplicate' in validator.errors[0].lower()


class TestNullValueCheck:
    """Test null value validation."""
    
    def test_acceptable_nulls_pass(self, sample_feature_df):
        """Low null percentage should pass."""
        # Add a few nulls (< 5%)
        sample_feature_df.loc[0, 'pm2_5'] = np.nan
        sample_feature_df.loc[1, 'pm10'] = np.nan
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_nulls(max_missing_pct=5) == True
    
    def test_excessive_nulls_fail(self, sample_feature_df):
        """High null percentage should fail."""
        # Make 50% of a column null
        sample_feature_df.loc[sample_feature_df.index[::2], 'pm2_5'] = np.nan
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_nulls(max_missing_pct=5) == False
        assert len(validator.errors) == 1
        assert 'excessive nulls' in validator.errors[0].lower()
    
    def test_known_gap_boundary_layer_warning(self, sample_feature_df):
        """Known gap in boundary_layer_height should warn, not error."""
        # Make 30% of boundary_layer_height null (known gap)
        sample_feature_df.loc[sample_feature_df.index[::3], 'boundary_layer_height'] = np.nan
        
        validator = DataQualityValidator(sample_feature_df)
        result = validator.check_nulls(max_missing_pct=5)
        
        # Should pass (not error) but add warning
        assert result == True
        assert len(validator.errors) == 0
        assert len(validator.warnings) > 0
        assert 'boundary_layer' in validator.warnings[0].lower()


class TestTimestampValidation:
    """Test timestamp validation."""
    
    def test_valid_timestamps_pass(self, sample_feature_df):
        """Valid UTC timestamps with hourly cadence should pass."""
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_timestamps() == True
    
    def test_detects_non_hourly_cadence(self, sample_feature_df):
        """Timestamps not exactly 1 hour apart should warn."""
        # Modify one timestamp to break hourly cadence
        sample_feature_df.loc[5, 'date'] = sample_feature_df.loc[5, 'date'] + timedelta(hours=2)
        
        validator = DataQualityValidator(sample_feature_df)
        result = validator.check_timestamps()
        
        # Should still pass but add warning
        assert result == True
        assert len(validator.warnings) > 0


class TestValueRangeCheck:
    """Test value range validation."""
    
    def test_valid_ranges_pass(self, sample_feature_df):
        """AQI and pollutants in valid ranges should pass."""
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_value_ranges() == True
        assert len(validator.errors) == 0
    
    def test_negative_aqi_fails(self, sample_feature_df):
        """Negative AQI values should fail."""
        sample_feature_df.loc[0, 'us_aqi'] = -5
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_value_ranges() == False
        assert len(validator.errors) == 1
        assert 'negative' in validator.errors[0].lower()
    
    def test_nan_aqi_fails(self, sample_feature_df):
        """NaN AQI values should fail."""
        sample_feature_df.loc[0, 'us_aqi'] = np.nan
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_value_ranges() == False
        assert len(validator.errors) == 1
        assert 'nan' in validator.errors[0].lower()
    
    def test_extreme_aqi_warning(self, sample_feature_df):
        """Extreme AQI values should warn but not fail."""
        sample_feature_df.loc[0, 'us_aqi'] = 700
        
        validator = DataQualityValidator(sample_feature_df)
        result = validator.check_value_ranges()
        
        # Should pass but warn
        assert result == True
        assert len(validator.warnings) > 0
        assert 'extreme' in validator.warnings[0].lower()


class TestCityCoverageCheck:
    """Test city coverage validation."""
    
    def test_all_cities_present_pass(self, sample_feature_df):
        """All expected cities present should pass."""
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_city_coverage(expected_cities) == True
    
    def test_missing_city_fails(self, sample_feature_df):
        """Missing expected city should fail."""
        # Remove one city
        sample_feature_df = sample_feature_df[sample_feature_df['city'] != 'Islamabad']
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        assert validator.check_city_coverage(expected_cities) == False
        assert len(validator.errors) == 1
        assert 'missing' in validator.errors[0].lower()
    
    def test_extra_cities_warning(self, sample_feature_df):
        """Unexpected cities should warn."""
        sample_feature_df.loc[0, 'city'] = 'Peshawar'
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        result = validator.check_city_coverage(expected_cities)
        
        # Should pass but warn
        assert result == True
        assert len(validator.warnings) > 0


class TestRunAll:
    """Test comprehensive validation run."""
    
    def test_all_checks_pass_valid_data(self, sample_feature_df):
        """All checks should pass on valid data."""
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        passed, errors, warnings = validator.run_all(
            expected_cities=expected_cities,
            max_age_hours=6,
            max_null_pct=5
        )
        
        assert passed == True
        assert len(errors) == 0
    
    def test_multiple_errors_collected(self, sample_feature_df):
        """Should collect all errors when multiple issues exist."""
        # Introduce multiple problems
        sample_feature_df.loc[0, 'us_aqi'] = -10  # Value range error
        sample_feature_df.loc[1, 'date'] = sample_feature_df.loc[1, 'date'] - timedelta(hours=20)  # Freshness error
        sample_feature_df = sample_feature_df[sample_feature_df['city'] != 'Islamabad']  # City coverage error
        
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        passed, errors, warnings = validator.run_all(expected_cities=expected_cities)
        
        assert passed == False
        assert len(errors) >= 2  # At least 2 errors
    
    def test_get_summary(self, sample_feature_df):
        """Summary should include error count and status."""
        expected_cities = ['Karachi', 'Lahore', 'Islamabad']
        
        validator = DataQualityValidator(sample_feature_df)
        validator.run_all(expected_cities=expected_cities)
        
        summary = validator.get_summary()
        assert isinstance(summary, dict)
        assert 'error_count' in summary
        assert 'warning_count' in summary
        assert 'passed' in summary
        assert summary['passed'] == True


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_missing_date_column(self):
        """Should handle missing date column gracefully."""
        df = pd.DataFrame({
            'city': ['Karachi', 'Lahore'],
            'us_aqi': [50, 60]
        })
        
        validator = DataQualityValidator(df)
        # Should not crash, just return safe values
        result = validator.check_freshness()
        assert result == False
    
    def test_missing_city_column(self):
        """Should handle missing city column gracefully."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'date': [now, now],
            'us_aqi': [50, 60]
        })
        
        validator = DataQualityValidator(df)
        # Should not crash
        result = validator.check_duplicates()
        assert result == True
    
    def test_single_row_dataframe(self):
        """Should handle single-row DataFrame."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'city': ['Karachi'],
            'date': [now],
            'us_aqi': [50],
            'pm2_5': [15]
        })
        
        validator = DataQualityValidator(df)
        passed, errors, warnings = validator.run_all(expected_cities=['Karachi'])
        
        # Single row should pass most checks
        assert len(errors) == 0
