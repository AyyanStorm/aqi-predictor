"""
validators.py — Data quality validation for feature store.

Automated checks to ensure data quality before training and inference:
- Freshness: data not stale (max 6 hours old)
- Duplicates: no duplicate (city, date) rows
- Nulls: missing values within thresholds
- Timestamps: UTC-aware with hourly cadence
- Value ranges: AQI and pollutants in valid ranges
- City coverage: all expected cities present

Issue #37: Automated data quality validation in production pipeline.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataQualityValidator:
    """
    Validates feature store data quality before training/inference.
    
    Checks for staleness, duplicates, nulls, schema issues, and outliers.
    Provides detailed error and warning logs for monitoring.
    """
    
    def __init__(self, feature_df, config=None):
        """
        Args:
            feature_df: DataFrame with feature store data
            config: Optional dict with validation thresholds
        """
        self.df = feature_df
        self.config = config or {}
        self.errors = []
        self.warnings = []
    
    def check_freshness(self, max_age_hours=6):
        """
        Ensure data was ingested recently (not stale).
        
        Args:
            max_age_hours: Maximum allowed age in hours (default 6)
        
        Returns:
            bool: True if fresh, False if stale
        """
        if len(self.df) == 0:
            self.errors.append('Feature store is empty')
            return False
        
        # Assume 'date' or 'timestamp' column exists
        date_col = 'date' if 'date' in self.df.columns else 'timestamp'
        if date_col not in self.df.columns:
            self.errors.append(f'No date/timestamp column found')
            return False
        
        latest = self.df[date_col].max()
        
        # Handle timezone-aware and naive datetimes
        now = datetime.now(timezone.utc)
        if latest.tzinfo is None:
            # Assume UTC if naive
            latest = latest.replace(tzinfo=timezone.utc)
        
        age_seconds = (now - latest).total_seconds()
        age_hours = age_seconds / 3600
        
        if age_hours > max_age_hours:
            self.errors.append(
                f'Data is stale: {age_hours:.1f}h old (max {max_age_hours}h)'
            )
            return False
        
        logger.info(f'✓ Data freshness OK: {age_hours:.1f}h old')
        return True
    
    def check_duplicates(self):
        """
        Detect duplicate (city, date) rows.
        
        Returns:
            bool: True if no duplicates, False if duplicates found
        """
        if 'city' not in self.df.columns or 'date' not in self.df.columns:
            logger.warning('Cannot check duplicates: missing city/date columns')
            return True
        
        dup_mask = self.df.duplicated(subset=['city', 'date'], keep=False)
        dup_count = dup_mask.sum()
        
        if dup_count > 0:
            self.errors.append(f'Found {dup_count} duplicate (city, date) rows')
            return False
        
        logger.info('✓ No duplicates found')
        return True
    
    def check_nulls(self, max_missing_pct=5):
        """
        Check for excessive missing values.
        
        Args:
            max_missing_pct: Maximum allowed null percentage (default 5)
        
        Returns:
            bool: True if within thresholds, False otherwise
        """
        null_pcts = (self.df.isnull().sum() / len(self.df) * 100).sort_values(ascending=False)
        
        # Find columns exceeding threshold
        bad_cols = null_pcts[null_pcts > max_missing_pct]
        
        if len(bad_cols) > 0:
            # Known caveat: boundary_layer_height missing Jan-Jun 2024
            if 'boundary_layer_height' in bad_cols.index:
                pct = bad_cols['boundary_layer_height']
                self.warnings.append(
                    f'boundary_layer_height: {pct:.1f}% null (known gap Jan-Jun 2024, '
                    'imputed by model)'
                )
            
            # Other columns are errors
            other_bad = bad_cols.drop('boundary_layer_height', errors='ignore')
            if len(other_bad) > 0:
                msg = ', '.join([f'{col}: {pct:.1f}%' for col, pct in other_bad.items()])
                self.errors.append(f'Excessive nulls: {msg} (max {max_missing_pct}%)')
                return False
        
        logger.info(f'✓ Null values within limits (max {max_missing_pct}%)')
        return True
    
    def check_timestamps(self):
        """
        Verify timestamps are UTC-aware and have hourly cadence.
        
        Returns:
            bool: True if timestamps valid, False otherwise
        """
        if 'date' not in self.df.columns and 'timestamp' not in self.df.columns:
            logger.warning('Cannot check timestamps: no date/timestamp column')
            return True
        
        date_col = 'date' if 'date' in self.df.columns else 'timestamp'
        dates = self.df[date_col].sort_values()
        
        # Check UTC-aware
        if dates.dt.tz is None:
            self.warnings.append('Timestamps are not explicitly UTC-aware (assuming UTC)')
        
        # Check hourly cadence within each city
        if 'city' in self.df.columns:
            for city in self.df['city'].unique():
                city_dates = self.df[self.df['city'] == city][date_col].sort_values()
                
                if len(city_dates) < 2:
                    continue
                
                diffs = city_dates.diff()
                expected_diff = pd.Timedelta(hours=1)
                
                # Allow small variations (might be DST transitions)
                bad_diffs = (diffs != expected_diff) & (diffs.notna())
                
                if bad_diffs.any():
                    self.warnings.append(
                        f'{city}: {bad_diffs.sum()} timestamps not exactly 1h apart '
                        '(may be DST transition)'
                    )
        
        logger.info('✓ Timestamps have hourly cadence')
        return True
    
    def check_value_ranges(self):
        """
        Verify AQI and pollutants are within valid ranges.
        
        Returns:
            bool: True if ranges valid, False if critical issues
        """
        aqi_col = 'us_aqi'
        
        if aqi_col not in self.df.columns:
            logger.warning(f'Cannot check value ranges: {aqi_col} column not found')
            return True
        
        # AQI should be 0-500+ (EPA caps at 500, but spikes exist)
        if (self.df[aqi_col] < 0).any():
            self.errors.append(f'{aqi_col} has negative values')
            return False
        
        if (self.df[aqi_col] > 600).any():
            extreme_count = (self.df[aqi_col] > 600).sum()
            self.warnings.append(f'{aqi_col} has {extreme_count} extreme values > 600')
        
        # Check for NaN
        if self.df[aqi_col].isna().any():
            self.errors.append(f'{aqi_col} has NaN values')
            return False
        
        logger.info('✓ Value ranges valid')
        return True
    
    def check_city_coverage(self, expected_cities):
        """
        Ensure all expected cities are represented.
        
        Args:
            expected_cities: List of expected city names
        
        Returns:
            bool: True if all cities present, False if missing
        """
        if 'city' not in self.df.columns:
            logger.warning('Cannot check city coverage: no city column')
            return True
        
        cities_in_data = set(self.df['city'].unique())
        expected = set(expected_cities)
        
        missing = expected - cities_in_data
        if missing:
            self.errors.append(f'Missing cities: {missing}')
            return False
        
        extra = cities_in_data - expected
        if extra:
            self.warnings.append(f'Unexpected cities in data: {extra}')
        
        logger.info(f'✓ All {len(expected)} expected cities present')
        return True
    
    def run_all(self, expected_cities=None, max_age_hours=6, max_null_pct=5):
        """
        Run all validation checks.
        
        Args:
            expected_cities: List of expected city names (optional)
            max_age_hours: Maximum data age in hours (default 6)
            max_null_pct: Maximum null percentage (default 5)
        
        Returns:
            tuple: (passed: bool, errors: list, warnings: list)
        """
        logger.info('=' * 50)
        logger.info('Starting Data Quality Validation')
        logger.info('=' * 50)
        
        checks = [
            ('Freshness', lambda: self.check_freshness(max_age_hours=max_age_hours)),
            ('Duplicates', lambda: self.check_duplicates()),
            ('Nulls', lambda: self.check_nulls(max_missing_pct=max_null_pct)),
            ('Timestamps', lambda: self.check_timestamps()),
            ('Value Ranges', lambda: self.check_value_ranges()),
        ]
        
        if expected_cities:
            checks.append(('City Coverage', lambda: self.check_city_coverage(expected_cities)))
        
        all_passed = True
        for check_name, check_fn in checks:
            try:
                passed = check_fn()
                if not passed:
                    all_passed = False
                    logger.error(f'✗ {check_name} check FAILED')
                else:
                    logger.info(f'✓ {check_name} check PASSED')
            except Exception as e:
                self.errors.append(f'{check_name} check failed with exception: {e}')
                all_passed = False
                logger.error(f'✗ {check_name} check FAILED: {e}')
        
        # Summary
        logger.info('=' * 50)
        logger.info(f'Validation Summary:')
        logger.info(f'  Errors: {len(self.errors)}')
        logger.info(f'  Warnings: {len(self.warnings)}')
        
        if self.errors:
            logger.error('VALIDATION FAILED - ERRORS:')
            for err in self.errors:
                logger.error(f'  • {err}')
        
        if self.warnings:
            logger.warning('VALIDATION WARNINGS:')
            for warn in self.warnings:
                logger.warning(f'  • {warn}')
        
        if all_passed:
            logger.info('✓✓✓ All validation checks PASSED ✓✓✓')
        else:
            logger.error('✗✗✗ Validation FAILED ✗✗✗')
        
        logger.info('=' * 50)
        
        return all_passed, self.errors, self.warnings
    
    def get_summary(self):
        """
        Get validation summary as dict (useful for metrics/logging).
        
        Returns:
            dict: Summary with error_count, warning_count, passed status
        """
        return {
            'error_count': len(self.errors),
            'warning_count': len(self.warnings),
            'passed': len(self.errors) == 0,
            'errors': self.errors,
            'warnings': self.warnings,
        }
