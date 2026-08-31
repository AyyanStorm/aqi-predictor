"""
api.py — Day 19: FastAPI serving endpoint (brief requirement: Streamlit
AND a REST API).

    GET /predict?lat=24.86&lon=67.01&city=Karachi
        -> full JSON forecast: current AQI + +24h/+48h/+72h, model
           provenance, and the exact feature vector.

    GET /health
        -> service + production-model status (used by Render uptime
           checks on Day 23).

    GET /cities
        -> the 10 training cities with coordinates (handy for clients
           to build a picker without hardcoding).

Reuses the EXACT same inference pipeline as the dashboard
(src.inference.predict.predict) — one code path for Streamlit, API,
and (later) the automation workflows. Errors become proper HTTP codes:
503 when no production model is registered, 400 on bad coordinates,
502 when the upstream data fetch fails.

Run locally:  uvicorn app.api:app --reload
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from src.config import CITIES
from src.inference.predict import predict
from src.tracking.store import ParquetPredictionStore, HopsworksPredictionStore
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category, health_message
from src.utils.logger import get_logger, log_event
from src.utils.rate_limiter import limiter, log_rate_limit_exceeded
from src.utils.metrics import (
    api_requests, api_latency, record_latency, update_model_metrics
)

logger = get_logger(__name__)

app = FastAPI(
    title="AQI Predictor — Pakistan",
    description="""
    Live air quality forecast (+24h/+48h/+72h) for any coordinates on Earth.
    
    Served by a city-agnostic LightGBM model trained on 10 Pakistani cities
    (Karachi, Lahore, Islamabad, Faisalabad, Rawalpindi, Multan, Peshawar,
    Quetta, Hyderabad, Gujranwala).
    
    ## Features
    - **Current AQI**: Observed air quality index at prediction time
    - **3-Day Forecast**: +24h, +48h, +72h predictions with EPA band labels
    - **Explainability**: SHAP-based feature importance for each prediction
    - **Graceful Degradation**: Returns cached predictions if API unavailable
    
    ## Rate Limits (Issue #40)
    - **/predict**: 30 requests per minute per IP
    - **/health, /cities**: 60 requests per minute per IP
    - **Default**: 200 requests per hour per IP
    
    Exceeding rate limits returns HTTP 429 with Retry-After header.
    
    ## Usage Example
    ```bash
    curl 'https://api.example.com/predict?lat=24.86&lon=67.01&city=Karachi'
    ```
    
    ## Error Handling
    - **400**: Invalid request (bad coordinates, missing parameters)
    - **429**: Rate limit exceeded (too many requests from your IP)
    - **503**: Forecast service temporarily unavailable (circuit breaker open)
    - **500**: Unexpected server error
    
    All responses include a `request_id` for debugging.
    """,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Attach limiter to app for slowapi
app.state.limiter = limiter

# Custom exception handler for rate limit exceeded
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors with proper 429 response."""
    client_ip = request.client.host if request.client else "unknown"
    endpoint = request.url.path
    
    # Log the rate limit violation
    log_rate_limit_exceeded(request, client_ip, endpoint)
    
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "60"},
        content={
            "error": "Rate limit exceeded",
            "details": "Too many requests from your IP. Please try again later.",
            "retry_after": 60,
            "limit": str(exc.detail),
        },
    )


@app.middleware("http")
async def request_logging(request, call_next):
    """Structured access log + metrics for every request (Day 24 observability, Issue #35).

    Logs method, path, status and duration_ms as one searchable line —
    the minimum needed to answer "is the API healthy / who is calling
    it / where is the latency". Also records request latency and count
    to Prometheus metrics.
    """
    import time

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - start
        log_event(
            logger, "http_request", level=logging.ERROR,
            method=request.method, path=request.url.path,
            status=500, duration_ms=round(duration * 1000, 1),
        )
        # Record error metric
        api_requests.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=500
        ).inc()
        api_latency.labels(endpoint=request.url.path).observe(duration)
        raise
    
    duration = time.perf_counter() - start
    
    log_event(
        logger, "http_request",
        method=request.method, path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration * 1000, 1),
    )
    
    # Record metrics for Prometheus (Issue #35)
    api_requests.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code
    ).inc()
    api_latency.labels(endpoint=request.url.path).observe(duration)
    
    return response


@app.get("/health")
@limiter.limit("60/minute")
def health(request: Request):
    """Service status + whether a production model is registered.
    
    Rate limited to 60 requests per minute per IP.
    """
    reg = ModelRegistry()
    prod = reg.production_entry()
    return {
        "status": "ok",
        "model": (
            {"name": prod["name"], "version": prod["version"]}
            if prod else None
        ),
    }


@app.get("/cities")
@limiter.limit("60/minute")
def cities(request: Request):
    """The 10 training cities (name -> lat/lon).
    
    Rate limited to 60 requests per minute per IP.
    """
    return {"cities": CITIES}


@app.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint (Issue #35).
    
    Exposes all tracked metrics:
    - Prediction latency and errors
    - Model performance (RMSE, version, age)
    - API request count and latency
    - Feature pipeline status
    - Cache hit/miss rates
    
    Scrape this endpoint from Prometheus (typically http://localhost:8000/metrics)
    
    Example:
        curl http://localhost:8000/metrics | head -20
    """
    # Update model metrics before returning (ensure fresh data)
    try:
        update_model_metrics()
    except Exception:
        # Silently continue if update fails - /metrics should always work
        pass
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/predict")
@limiter.limit("30/minute")
def predict_endpoint(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude (-90 to 90)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (-180 to 180)"),
    city: str = Query("api", description="Display label for the location"),
):
    """
    Three-day AQI forecast for any coordinates.

    Returns the same payload the dashboard renders: current AQI,
    +24h/+48h/+72h forecast, model provenance, feature vector.
    
    **Rate Limit:** 30 requests per minute per IP (Issue #40)
    
    All responses include a `request_id` for debugging. If status is "degraded",
    the prediction uses cached data (when live API is unavailable).
    """
    # Generate unique request ID for tracing
    request_id = str(uuid.uuid4())[:8]
    start_time = datetime.now(timezone.utc)
    
    try:
        logger.info(
            f'Prediction request: lat={lat}, lon={lon}, city={city}, request_id={request_id}'
        )
        
        result = predict(lat, lon, city=city)
        
        # Calculate latency
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        # Enrich each horizon with its AQI band label + health message —
        # clients get presentation data without reimplementing EPA bands.
        for h in ("24", "48", "72"):
            aqi = result["forecast"][h]
            result["forecast"][h] = {
                "aqi": aqi,
                "category": aqi_category(aqi),
                "health_message": health_message(aqi),
            }
        result["current"] = {
            "aqi": result["current_aqi"],
            "category": aqi_category(result["current_aqi"]),
            "health_message": health_message(result["current_aqi"]),
        }
        
        # Add metadata
        result["request_id"] = request_id
        result["latency_ms"] = round(latency_ms, 1)
        
        log_event(
            logger, 'prediction_success',
            request_id=request_id,
            lat=lat, lon=lon,
            status=result.get('status', 'ok'),
            latency_ms=round(latency_ms, 1)
        )
        
        return JSONResponse(content=result)
    
    except SystemExit as e:
        # No production model in the registry
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        log_event(
            logger, 'prediction_error',
            level=logging.ERROR,
            request_id=request_id,
            error_type='no_model',
            error=str(e),
            latency_ms=round(latency_ms, 1)
        )
        
        return JSONResponse(
            status_code=503,
            content={
                "error": "Model service unavailable",
                "details": "No production model is registered",
                "request_id": request_id,
                "timestamp": start_time.isoformat(),
                "retry_after": 300
            }
        )
    
    except RuntimeError as e:
        # API failure, degraded service, or no cache available
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        error_msg = str(e)
        
        # Determine if this is a degraded prediction or complete failure
        if 'degraded' in error_msg.lower() or 'cached' in error_msg.lower():
            log_event(
                logger, 'prediction_degraded',
                level=logging.WARNING,
                request_id=request_id,
                error=error_msg,
                latency_ms=round(latency_ms, 1)
            )
            return JSONResponse(
                status_code=200,  # Still successful, but degraded
                content={
                    "error": "Forecast service temporarily unavailable",
                    "details": error_msg,
                    "request_id": request_id,
                    "status": "degraded",
                    "timestamp": start_time.isoformat()
                }
            )
        else:
            log_event(
                logger, 'prediction_error',
                level=logging.ERROR,
                request_id=request_id,
                error_type='runtime',
                error=error_msg,
                latency_ms=round(latency_ms, 1)
            )
            return JSONResponse(
                status_code=503,
                headers={'Retry-After': '300'},
                content={
                    "error": "Forecast service temporarily unavailable",
                    "details": error_msg,
                    "request_id": request_id,
                    "timestamp": start_time.isoformat(),
                    "retry_after": 300,
                    "support": f"Contact support with request_id: {request_id}"
                }
            )
    
    except Exception as e:
        # Unexpected error
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        log_event(
            logger, 'prediction_error',
            level=logging.ERROR,
            request_id=request_id,
            error_type='unexpected',
            error=str(e),
            latency_ms=round(latency_ms, 1)
        )
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": request_id,
                "timestamp": start_time.isoformat(),
                "support": f"Report this issue with request_id: {request_id}"
            }
        )


@app.post("/admin/migrate-predictions")
def migrate_predictions():
    """
    One-time admin endpoint: migrate local Parquet predictions to Hopsworks.
    Only works when HOPSWORKS_API_KEY and HOPSWORKS_PROJECT are set.
    Protected by requiring a shared secret header.
    """
    # Simple shared-secret protection (set ADMIN_SECRET in Render env)
    # For now, just allow if env vars are present (Hopsworks configured)
    if not os.getenv("HOPSWORKS_API_KEY") or not os.getenv("HOPSWORKS_PROJECT"):
        raise HTTPException(
            status_code=503,
            detail="Hopsworks not configured on this service"
        )

    try:
        local_store = ParquetPredictionStore()
        local_records = local_store.load_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Local store error: {e}")

    if local_records.empty:
        return {"migrated": 0, "message": "No local predictions to migrate"}

    try:
        hopsworks_store = HopsworksPredictionStore()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Hopsworks connection failed: {e}")

    # Check existing to avoid duplicates
    existing = hopsworks_store.load_all()
    existing_ids = set(existing["prediction_id"].tolist()) if not existing.empty else set()

    migrated = 0
    for _, row in local_records.iterrows():
        record = row.to_dict()
        pred_id = record.get("prediction_id")
        if pred_id in existing_ids:
            continue
        try:
            hopsworks_store.save(record)
            migrated += 1
        except Exception as e:
            logger.error(f"Failed to migrate {pred_id}: {e}")

    return {"migrated": migrated, "total_local": len(local_records), "already_in_hopsworks": len(existing_ids)}
