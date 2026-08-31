"""
metrics.py — Prometheus metrics for observability (Issue #35).

Tracks:
- Prediction latency and errors
- Model performance (RMSE, version, age)
- API request latency and errors
- Feature pipeline runtime and errors
- Data quality metrics
- Cache hit/miss rates

All metrics are exposed at GET /metrics in Prometheus format.
"""

import time
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Use default registry (auto-registered with prometheus_client's default)
# This works with FastAPI + prometheus_client.generate_latest()

# ============================================================================
# PREDICTION METRICS
# ============================================================================

prediction_latency = Histogram(
    'aqi_prediction_latency_seconds',
    'Time to generate AQI prediction (including API calls, feature engineering, inference)',
    buckets=(0.1, 0.5, 1.0, 1.5, 2.0, 5.0),
    labelnames=['horizon', 'city']
)

prediction_errors = Counter(
    'aqi_prediction_errors_total',
    'Total prediction errors',
    labelnames=['error_type', 'city']  # error_type: timeout, validation, no_model, unknown
)

predictions_made = Counter(
    'aqi_predictions_total',
    'Total predictions served',
    labelnames=['status', 'horizon']  # status: ok, degraded (cached), error
)

# ============================================================================
# MODEL METRICS
# ============================================================================

model_accuracy = Gauge(
    'aqi_model_rmse_production',
    'RMSE of production model on validation set (lower is better)',
    labelnames=['horizon']  # horizon: 24h, 48h, 72h, all
)

model_version = Gauge(
    'aqi_model_version_current',
    'Version number of production model (e.g., 12 for lgbm_v12)'
)

model_age_days = Gauge(
    'aqi_model_age_days',
    'Days since production model was trained'
)

# ============================================================================
# API METRICS
# ============================================================================

api_requests = Counter(
    'aqi_api_requests_total',
    'Total HTTP requests to API endpoints',
    labelnames=['method', 'endpoint', 'status_code']
)

api_latency = Histogram(
    'aqi_api_latency_seconds',
    'HTTP endpoint latency (request -> response)',
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0),
    labelnames=['endpoint']
)

# ============================================================================
# DATA PIPELINE METRICS
# ============================================================================

feature_store_age_hours = Gauge(
    'aqi_feature_store_age_hours',
    'Hours since feature store was last updated (lower is fresher)'
)

feature_pipeline_runtime = Histogram(
    'aqi_feature_pipeline_runtime_seconds',
    'Time to run hourly feature pipeline (data fetch + feature engineering)',
    buckets=(5, 10, 30, 60, 120, 300),
    labelnames=['pipeline_step']  # step: fetch, engineer, ingest, etc.
)

feature_pipeline_errors = Counter(
    'aqi_feature_pipeline_errors_total',
    'Total feature pipeline errors',
    labelnames=['error_type', 'city']  # API timeout, parse error, DB error, etc.
)

training_pipeline_runtime = Histogram(
    'aqi_training_pipeline_runtime_seconds',
    'Time to run daily training pipeline (data preparation + model training)',
    buckets=(60, 300, 900, 1800, 3600, 7200),
    labelnames=['pipeline_step']  # step: prepare, train, validate, etc.
)

training_pipeline_errors = Counter(
    'aqi_training_pipeline_errors_total',
    'Total training pipeline errors',
    labelnames=['error_type']  # data_quality, training_failed, validation_failed
)

# ============================================================================
# DATA QUALITY METRICS
# ============================================================================

feature_store_rows = Gauge(
    'aqi_feature_store_rows_total',
    'Total rows in feature store',
    labelnames=['city']
)

feature_nulls_percent = Gauge(
    'aqi_feature_nulls_percent',
    'Percentage of null values per feature (higher = worse)',
    labelnames=['feature', 'city']
)

# ============================================================================
# CACHE METRICS
# ============================================================================

cache_hits = Counter(
    'aqi_cache_hits_total',
    'Cache hits when prediction succeeded using cached data',
    labelnames=['cache_type']  # prediction, model, etc.
)

cache_misses = Counter(
    'aqi_cache_misses_total',
    'Cache misses (no fallback available)',
    labelnames=['cache_type']
)

cache_size_bytes = Gauge(
    'aqi_cache_size_bytes',
    'Current cache size in bytes',
    labelnames=['cache_type']
)

# ============================================================================
# HELPER: Context Manager for Timing
# ============================================================================

class record_latency:
    """Context manager to record function execution time to a Histogram.
    
    Example:
        with record_latency(prediction_latency, horizon='24h', city='Karachi'):
            result = predict(lat, lon)
    """
    
    def __init__(self, histogram, **labels):
        """
        Args:
            histogram: Prometheus Histogram metric object
            **labels: Label key-value pairs (must match histogram's labelnames)
        """
        self.histogram = histogram
        self.labels = labels
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        duration = time.perf_counter() - self.start_time
        self.histogram.labels(**self.labels).observe(duration)


# ============================================================================
# HELPER: Update metrics from model registry
# ============================================================================

def update_model_metrics():
    """Update model-related metrics from the model registry.
    
    Call this periodically (e.g., after model promotion) to update:
    - model_version (version number)
    - model_age_days (days since training)
    - model_accuracy (RMSE on validation set)
    
    This is typically called by the training pipeline after promotion.
    """
    try:
        from src.training.model_registry import ModelRegistry
        from datetime import datetime, timezone
        
        registry = ModelRegistry()
        prod_entry = registry.production_entry()
        
        if not prod_entry:
            # No production model registered
            return
        
        # Extract version number from name (e.g., "lgbm_v12" -> 12)
        version_str = prod_entry.get('name', '').split('_v')[-1]
        try:
            version_num = int(version_str)
            model_version.set(version_num)
        except (ValueError, IndexError):
            pass
        
        # Calculate model age
        trained_at = prod_entry.get('trained_at')
        if trained_at:
            if isinstance(trained_at, str):
                trained_at = datetime.fromisoformat(trained_at)
            elif not isinstance(trained_at, datetime):
                trained_at = datetime.fromtimestamp(trained_at)
            
            age = (datetime.now(timezone.utc) - trained_at).total_seconds() / 86400
            model_age_days.set(age)
        
        # Update accuracy metrics
        for horizon in ['24h', '48h', '72h']:
            rmse_key = f'rmse_{horizon}'
            if rmse_key in prod_entry:
                model_accuracy.labels(horizon=horizon).set(prod_entry[rmse_key])
    
    except Exception as e:
        # Silently fail - metrics update should not break the app
        import logging
        logging.getLogger(__name__).warning(f"Failed to update model metrics: {e}")


__all__ = [
    'prediction_latency',
    'prediction_errors',
    'predictions_made',
    'model_accuracy',
    'model_version',
    'model_age_days',
    'api_requests',
    'api_latency',
    'feature_store_age_hours',
    'feature_pipeline_runtime',
    'feature_pipeline_errors',
    'training_pipeline_runtime',
    'training_pipeline_errors',
    'feature_store_rows',
    'feature_nulls_percent',
    'cache_hits',
    'cache_misses',
    'cache_size_bytes',
    'record_latency',
    'update_model_metrics',
]
