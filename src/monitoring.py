"""
Monitoring & Observability Module

Production-grade monitoring with Sentry, structured logging, and metrics.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pythonjsonlogger import jsonlogger
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from prometheus_client import Counter, Histogram, Gauge
import time


# ============================================================================
# SENTRY INITIALIZATION
# ============================================================================

def init_sentry() -> None:
    """Initialize Sentry for error tracking."""
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            environment=os.getenv("ENVIRONMENT", "production"),
        )
        logging.info("✅ Sentry initialized for error tracking")
    else:
        logging.info("⚠️  SENTRY_DSN not set - error tracking disabled")


# ============================================================================
# STRUCTURED LOGGING SETUP
# ============================================================================

def setup_structured_logging() -> logging.Logger:
    """Setup JSON-formatted structured logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # JSON formatter for structured logs
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt='%(timestamp)s %(level)s %(name)s %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


logger = setup_structured_logging()


# ============================================================================
# PROMETHEUS METRICS
# ============================================================================

# Request metrics
http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint', 'status'],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# Error metrics
errors_total = Counter(
    'aqi_errors_total',
    'Total errors',
    ['error_type', 'endpoint']
)

predictions_total = Counter(
    'aqi_predictions_total',
    'Total predictions made',
    ['model_version', 'horizon']
)

# Performance metrics
prediction_latency_seconds = Histogram(
    'aqi_prediction_latency_seconds',
    'Prediction latency in seconds',
    ['model_version', 'horizon'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

# Health metrics
cache_hits_total = Counter(
    'aqi_cache_hits_total',
    'Total cache hits',
    ['cache_type']
)

cache_misses_total = Counter(
    'aqi_cache_misses_total',
    'Total cache misses',
    ['cache_type']
)

model_accuracy_gauge = Gauge(
    'aqi_model_accuracy',
    'Current model accuracy (RMSE)',
    ['model_version']
)

uptime_seconds = Gauge(
    'aqi_uptime_seconds',
    'Service uptime in seconds'
)


# ============================================================================
# STRUCTURED LOGGING FUNCTIONS
# ============================================================================

def log_event(
    event_type: str,
    level: str = "INFO",
    **kwargs
) -> None:
    """Log structured event with metadata."""
    log_data = {
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **kwargs
    }
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(json.dumps(log_data))


def log_prediction(
    latitude: float,
    longitude: float,
    model_version: str,
    horizon: str,
    aqi_value: float,
    latency_ms: float,
    cache_hit: bool
) -> None:
    """Log prediction event."""
    log_event(
        "prediction_made",
        level="INFO",
        latitude=latitude,
        longitude=longitude,
        model_version=model_version,
        horizon=horizon,
        aqi_value=aqi_value,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
    )


def log_error(
    error_type: str,
    endpoint: str,
    message: str,
    status_code: int,
    request_id: str
) -> None:
    """Log error event to Sentry & structured logs."""
    log_event(
        "error_occurred",
        level="ERROR",
        error_type=error_type,
        endpoint=endpoint,
        message=message,
        status_code=status_code,
        request_id=request_id,
    )
    
    # Also capture in Sentry
    sentry_sdk.capture_message(
        f"{error_type}: {message}",
        level="error",
        extra={
            "endpoint": endpoint,
            "status_code": status_code,
            "request_id": request_id,
        }
    )


def log_health_check(
    status: str,
    model_loaded: bool,
    cache_healthy: bool,
    api_reachable: bool,
    latency_ms: float
) -> None:
    """Log health check event."""
    log_event(
        "health_check",
        level="INFO",
        status=status,
        model_loaded=model_loaded,
        cache_healthy=cache_healthy,
        api_reachable=api_reachable,
        latency_ms=latency_ms,
    )


# ============================================================================
# REQUEST/RESPONSE LOGGING MIDDLEWARE
# ============================================================================

class MonitoringMiddleware:
    """ASGI middleware for request/response monitoring."""
    
    def __init__(self, app, start_time: datetime):
        self.app = app
        self.start_time = start_time
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request_start = time.time()
        request_id = str(int(time.time() * 1000000))
        
        async def send_with_monitoring(message):
            if message["type"] == "http.response.start":
                status_code = message["status"]
                latency = (time.time() - request_start) * 1000
                
                # Update metrics
                method = scope["method"]
                path = scope["path"]
                http_request_duration_seconds.labels(
                    method=method,
                    endpoint=path,
                    status=status_code
                ).observe(latency / 1000)
                http_requests_total.labels(
                    method=method,
                    endpoint=path,
                    status=status_code
                ).inc()
                
                # Log request
                log_event(
                    "http_request",
                    level="INFO",
                    request_id=request_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    latency_ms=round(latency, 2),
                )
            
            await send(message)
        
        await self.app(scope, receive, send_with_monitoring)


# ============================================================================
# HEALTH CHECK
# ============================================================================

def get_health_status() -> Dict[str, Any]:
    """Get comprehensive health status."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "sentry": "enabled" if os.getenv("SENTRY_DSN") else "disabled",
    }


# ============================================================================
# STARTUP & SHUTDOWN
# ============================================================================

start_time = datetime.utcnow()

def on_startup():
    """Initialize monitoring on app startup."""
    init_sentry()
    uptime_seconds.set(0)
    log_event("app_startup", level="INFO", version="1.0.0")


def on_shutdown():
    """Log app shutdown."""
    log_event("app_shutdown", level="INFO")
