"""
validation_gates.py — Validation gates for training and ingestion pipelines.

Provides helper functions to validate data before training/inference,
integrated with the DataQualityValidator and metrics collection.

Issue #37: Automated data quality validation in production.
"""

import pandas as pd
from src.data_ingestion.validators import DataQualityValidator
from src.utils.logger import get_logger
from src.config import CITIES

logger = get_logger(__name__)


def validate_before_training(df, raise_on_error=True):
    """
    Validate feature store data before training.
    
    Ensures:
    - Data not stale (max 6 hours old)
    - No duplicate (city, date) rows
    - Null values within limits (5% max, allows boundary_layer_height gap)
    - Timestamps valid (UTC, hourly cadence)
    - AQI and pollutants in valid ranges
    - All training cities present
    
    Args:
        df: Feature store DataFrame to validate
        raise_on_error: If True, raise SystemExit on validation failure
    
    Returns:
        tuple: (passed: bool, validator: DataQualityValidator)
    
    Raises:
        SystemExit: If raise_on_error=True and validation fails
    """
    logger.info("=" * 70)
    logger.info("PRE-TRAINING DATA QUALITY VALIDATION")
    logger.info("=" * 70)
    
    if df.empty:
        msg = "Feature store is empty — cannot proceed with training"
        logger.error(msg)
        if raise_on_error:
            raise SystemExit(msg)
        return False, None
    
    # Expected training cities (10 cities used in training)
    expected_cities = list(CITIES.keys())
    
    # Initialize validator
    validator = DataQualityValidator(df)
    
    # Run validation
    passed, errors, warnings = validator.run_all(
        expected_cities=expected_cities,
        max_age_hours=6,
        max_null_pct=5
    )
    
    # Print summary
    logger.info("=" * 70)
    if passed:
        logger.info("✓✓✓ DATA QUALITY VALIDATION PASSED ✓✓✓")
        logger.info(f"  • {len(df)} rows, {df['city'].nunique()} cities")
        logger.info(f"  • Date range: {df.index.min()} → {df.index.max()}")
        if warnings:
            logger.info(f"  • {len(warnings)} warning(s) (see above)")
    else:
        logger.error("✗✗✗ DATA QUALITY VALIDATION FAILED ✗✗✗")
        logger.error(f"  • {len(errors)} error(s) preventing training")
        for err in errors:
            logger.error(f"    - {err}")
        if raise_on_error:
            raise SystemExit("Data quality validation failed. Aborting training.")
    logger.info("=" * 70)
    
    return passed, validator


def validate_before_inference(df, raise_on_error=False):
    """
    Lightweight validation before inference (predict()).
    
    Inference is more tolerant than training — uses cached data on failure.
    This is an optional check for diagnostic purposes.
    
    Args:
        df: Live inference frame
        raise_on_error: If True, raise on validation failure (default: False)
    
    Returns:
        tuple: (passed: bool, validator: DataQualityValidator)
    """
    if df.empty:
        logger.warning("Inference frame is empty")
        return False, None
    
    validator = DataQualityValidator(df)
    
    # Lighter validation for inference (don't require all cities)
    passed, errors, warnings = validator.run_all(
        expected_cities=None,  # Don't require all cities
        max_age_hours=2,  # Stricter freshness for live predictions
        max_null_pct=10  # Slightly more tolerant
    )
    
    if not passed and raise_on_error:
        logger.error(f"Inference data quality issues: {errors}")
        raise ValueError(f"Inference data validation failed: {errors}")
    
    return passed, validator


def validate_ingested_batch(df, city=None):
    """
    Validate a batch of freshly ingested data.
    
    Called after each hourly data ingestion to ensure freshness.
    
    Args:
        df: Ingested data (single city usually)
        city: Expected city name (if single city ingestion)
    
    Returns:
        dict: Summary with 'valid', 'errors', 'warnings', 'freshness_hours'
    """
    if df.empty:
        return {
            'valid': False,
            'errors': ['Ingested batch is empty'],
            'warnings': [],
            'freshness_hours': None
        }
    
    validator = DataQualityValidator(df)
    
    checks_to_run = [
        ('Freshness', lambda: validator.check_freshness(max_age_hours=1)),  # Strict for fresh data
        ('Duplicates', lambda: validator.check_duplicates()),
        ('Timestamps', lambda: validator.check_timestamps()),
        ('Value Ranges', lambda: validator.check_value_ranges()),
    ]
    
    if city:
        checks_to_run.append(('City Coverage', lambda: validator.check_city_coverage([city])))
    
    all_passed = True
    for check_name, check_fn in checks_to_run:
        try:
            passed = check_fn()
            if not passed:
                all_passed = False
                logger.warning(f"Ingestion check '{check_name}' failed")
        except Exception as e:
            all_passed = False
            validator.errors.append(f"{check_name} check failed: {e}")
            logger.error(f"Ingestion check '{check_name}' exception: {e}")
    
    # Calculate freshness
    freshness_hours = None
    if 'date' in df.columns:
        from datetime import datetime, timezone
        latest = df['date'].max()
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        freshness_hours = (now - latest).total_seconds() / 3600
    
    return {
        'valid': all_passed,
        'errors': validator.errors,
        'warnings': validator.warnings,
        'freshness_hours': freshness_hours
    }


__all__ = [
    'validate_before_training',
    'validate_before_inference',
    'validate_ingested_batch',
]
