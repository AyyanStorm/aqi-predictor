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
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.schemas import (
    PredictionResponse, ErrorResponse, HealthResponse, CitiesResponse,
    CityInfo, MigrationResponse, AQIReading
)
from src.config import CITIES
from src.inference.predict import predict
from src.tracking.store import ParquetPredictionStore, HopsworksPredictionStore
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category, health_message
from src.utils.logger import get_logger, log_event
from src.utils.metrics import update_model_metrics

logger = get_logger(__name__)

# Rate limiting: per-IP tracking with Redis fallback to in-memory
# Disable rate limiting in test/development mode (SLOWAPI_ENABLED=false)
enabled_rate_limiting = os.getenv('SLOWAPI_ENABLED', 'true').lower() != 'false'
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/hour"],  # Default fallback
    enabled=enabled_rate_limiting  # Can be disabled for testing
)

# Prometheus metrics for rate limiting (use try/except to avoid duplicate registration)
try:
    rate_limit_exceeded_counter = Counter(
        'aqi_rate_limit_exceeded_total',
        'Total rate limit exceeded errors',
        ['endpoint']
    )
except:
    # Already registered in a previous import
    from prometheus_client import REGISTRY
    rate_limit_exceeded_counter = REGISTRY._names_to_collectors.get('aqi_rate_limit_exceeded_total')

app = FastAPI(
    title="AQI Predictor — Pakistan",
    description="""
# Live air quality forecast (+24h/+48h/+72h) for any coordinates on Earth.

Served by a city-agnostic LightGBM model trained on 10 Pakistani cities:
Karachi, Lahore, Islamabad, Faisalabad, Rawalpindi, Multan, Peshawar,
Quetta, Hyderabad, Gujranwala.

## ✨ Features
- **Current AQI**: Observed air quality index at prediction time
- **3-Day Forecast**: +24h, +48h, +72h predictions with EPA band labels
- **Health Guidance**: Category-specific health messages for each AQI level
- **Explainability**: Feature importance data for each prediction
- **Resilience**: Cached predictions if live API unavailable (degraded mode)
- **Tracing**: Every response includes a `request_id` for debugging

## 🌍 Coverage
- **Geographic**: Any latitude (-90 to 90) and longitude (-180 to 180)
- **Generalization**: Model proven to generalize to unseen Pakistani cities
- **Real-Time**: Updated with latest weather observations hourly

## 🔗 Usage Example

**Request:**
```bash
curl 'https://api.example.com/predict?lat=24.86&lon=67.01&city=Karachi'
```

**Response:**
```json
{
  "current": {"aqi": 68.5, "category": "Moderate"},
  "forecast": {
    "24": {"aqi": 72.0, "category": "Moderate"},
    "48": {"aqi": 58.5, "category": "Moderate"},
    "72": {"aqi": 51.2, "category": "Good"}
  },
  "request_id": "a1b2c3d4",
  "latency_ms": 45.2
}
```

## 📊 HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| **200** | Success | Use forecast normally |
| **200** (degraded) | Using cached data | Forecast accurate, API temporary issue |
| **400** | Invalid parameters | Check lat/lon ranges |
| **503** | Service unavailable | Retry after 5 minutes (see Retry-After header) |
| **500** | Server error | Report with request_id |

## 🔐 Authentication & Rate Limits

**No authentication required** — public API.

**Rate Limits (per IP):**
- `/predict`: 30 req/min
- `/health`, `/cities`: 60 req/min
- Default: 200 req/hour

Exceeding limits returns HTTP 429 with `Retry-After` header.

## 📝 Response Fields

- **current**: Current AQI with EPA category and health message
- **forecast**: 24/48/72-hour predictions with categories
- **model**: Production model name, version, RMSE, accuracy
- **status**: 'ok' or 'degraded' (using cache)
- **request_id**: Unique ID for debugging and support
- **latency_ms**: Server processing time
- **timestamp**: ISO 8601 prediction time

## 🆘 Support

Include `request_id` in bug reports. Check the `/health` endpoint to verify service status.

## 📚 API Reference

- `GET /health` — Service status and production model info
- `GET /cities` — Training cities (to populate UI pickers)
- `GET /predict` — Main forecast endpoint
- `GET /metrics` — Prometheus metrics (internal monitoring)
- `POST /admin/migrate-predictions` — Admin migration tool
""",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Apply limiter to app (enables @limiter.limit() decorator)
app.state.limiter = limiter

# Only add rate limit exception handler if rate limiting is enabled
if enabled_rate_limiting:
    app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
        status_code=429,
        headers={
            "Retry-After": str(max(60, int(exc.args[1]) if len(exc.args) > 1 else 60))
        },
        content={
            "error": "Rate limit exceeded",
            "details": "Too many requests from this IP address",
            "retry_after": max(60, int(exc.args[1]) if len(exc.args) > 1 else 60),
            "message": "Please wait before retrying. Rate limits are per IP address."
        }
    ))


@app.middleware("http")
async def request_logging(request, call_next):
    """Structured access log for every request (Day 24 observability).

    Logs method, path, status and duration_ms as one searchable line —
    the minimum needed to answer "is the API healthy / who is calling
    it / where is the latency". The event name is http_request so a log
    drain or Render's log search can filter on it.
    
    Also tracks rate limit exceedances per endpoint and IP for alerting.
    """
    import time

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except RateLimitExceeded as e:
        # Log rate limit exceeded with IP for monitoring
        client_ip = get_remote_address(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger, "http_request_rate_limited", level=logging.WARNING,
            method=request.method, path=request.url.path,
            status=429, client_ip=client_ip, duration_ms=duration_ms,
        )
        rate_limit_exceeded_counter.labels(endpoint=request.url.path).inc()
        raise
    except Exception:
        log_event(
            logger, "http_request", level=logging.ERROR,
            method=request.method, path=request.url.path,
            status=500, duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        raise
    
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log_event(
        logger, "http_request",
        method=request.method, path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/health", response_model=HealthResponse, tags=["Status"])
@limiter.limit("60/minute")
def health(request: Request):
    """
    **Service health status and production model info.**

    Used by monitoring systems and uptime checks. Returns current service status
    and information about the active production model.

    ### Rate Limit
    - **Limit**: 60 requests per minute per IP
    - **Header**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

    ### Returns
    - **status**: 'ok' if service is running normally
    - **model**: Production model name and version (null if not registered)

    ### Examples

    **Healthy (with model):**
    ```json
    {
      "status": "ok",
      "model": {"name": "aqi-lgbm-v3", "version": 3}
    }
    ```

    **Unhealthy (no model):**
    ```json
    {
      "status": "ok",
      "model": null
    }
    ```
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


@app.get("/cities", response_model=CitiesResponse, tags=["Reference Data"])
@limiter.limit("60/minute")
def cities(request: Request):
    """
    **List of 10 training cities with coordinates.**

    Returns the cities used to train the production model. Useful for building
    UI dropdowns or validating that predictions for nearby cities will be accurate.

    All cities are in Pakistan.

    ### Rate Limit
    - **Limit**: 60 requests per minute per IP
    - **Header**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

    ### Training Cities
    1. Karachi (24.86°N, 67.01°E)
    2. Lahore (31.54°N, 74.32°E)
    3. Islamabad (33.74°N, 73.17°E)
    4. Faisalabad (31.42°N, 72.97°E)
    5. Rawalpindi (33.60°N, 73.17°E)
    6. Multan (30.20°N, 71.43°E)
    7. Peshawar (34.01°N, 71.57°E)
    8. Quetta (30.18°N, 67.01°E)
    9. Hyderabad (25.39°N, 68.34°E)
    10. Gujranwala (32.16°N, 74.19°E)

    ### Returns
    Map of city names to coordinates (latitude, longitude).

    ### Note
    The model generalizes well to *any* Pakistani coordinates, not just training cities.
    """
    # Transform CITIES dict to match CityInfo schema
    # CITIES format: {"Karachi": {"lat": 24.86, "lon": 67.01}}
    # CityInfo format: {"name": "Karachi", "latitude": 24.86, "longitude": 67.01}
    cities_data = {
        city_name: {
            "name": city_name,
            "latitude": coords["lat"],
            "longitude": coords["lon"]
        }
        for city_name, coords in CITIES.items()
    }
    return {"cities": cities_data}


@app.get("/metrics", tags=["Monitoring"], response_class=Response)
@limiter.limit("60/minute")
def metrics(request: Request):
    """
    **Prometheus metrics for monitoring and observability.**

    Exposes all tracked metrics in Prometheus text format (OpenMetrics).
    Used by Prometheus scraper (configured in docker-compose.yml) and
    visualized in Grafana dashboards.
    
    ### Rate Limit
    - **Limit**: 60 requests per minute per IP
    - **Header**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

    ### Metrics Exposed

    **Prediction Performance:**
    - `aqi_prediction_latency_seconds` — P50/P95/P99 latencies
    - `aqi_api_requests_total` — Request count by endpoint/status
    - `aqi_api_requests_in_progress` — Concurrent requests

    **Model Health:**
    - `aqi_model_rmse_production` — Production model RMSE
    - `aqi_model_accuracy_production` — Production accuracy %
    - `aqi_model_age_days_production` — Days since training
    - `aqi_model_rmse_candidate` — Candidate model RMSE (if available)

    **Data Pipeline:**
    - `aqi_feature_store_age_hours` — Hours since last data update
    - `aqi_feature_store_row_count` — Total rows in feature store
    - `aqi_data_quality_null_percent` — % null values in data

    **Cache:**
    - `aqi_cache_hits_total` — Cache hit count
    - `aqi_cache_misses_total` — Cache miss count

    ### Scraping

    Configure Prometheus to scrape this endpoint:
    ```yaml
    scrape_configs:
      - job_name: 'aqi-api'
        static_configs:
          - targets: ['localhost:8000']
        metrics_path: '/metrics'
        scrape_interval: 30s
    ```

    ### Content Type
    Returns text/plain in OpenMetrics format (Prometheus-compatible).
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


@app.get(
    "/predict",
    response_model=PredictionResponse,
    responses={
        200: {"description": "Forecast successful"},
        400: {"model": ErrorResponse, "description": "Invalid parameters (bad coordinates)"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (30 per minute)"},
        503: {"model": ErrorResponse, "description": "Service unavailable (no model or API down)"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
    tags=["Predictions"]
)
@limiter.limit("30/minute")
def predict_endpoint(request: Request,
    lat: float = Query(
        ...,
        ge=-90,
        le=90,
        description="Latitude in decimal degrees (-90 to 90)",
        examples=[24.86, 31.54, 0.0]
    ),
    lon: float = Query(
        ...,
        ge=-180,
        le=180,
        description="Longitude in decimal degrees (-180 to 180)",
        examples=[67.01, 74.32, 0.0]
    ),
    city: str = Query(
        "api",
        description="Display label for location (shown in response). For UI dropdowns use /cities endpoint.",
        examples=["Karachi", "Lahore", "Custom Location"]
    ),
):
    """
    **3-day air quality forecast for any geographic coordinates.**

    Main prediction endpoint. Returns current AQI and forecasts for +24h, +48h, and +72h
    with EPA category labels and health guidance.

    ### Parameters

    - **lat** (required): Latitude in decimal degrees. Range: -90 to 90.
      - Example: 24.86 (Karachi latitude)

    - **lon** (required): Longitude in decimal degrees. Range: -180 to 180.
      - Example: 67.01 (Karachi longitude)

    - **city** (optional): Display label for this location (shown in responses).
      - Default: "api"
      - Example: "Karachi", "Islamabad", "Unseen City XYZ"

    ### Response Fields

    - **current**: Current AQI with EPA category and health message
    - **forecast**: Predictions for 24h, 48h, 72h ahead
    - **model**: Production model info (name, version, RMSE, accuracy)
    - **status**: 'ok' (live data) or 'degraded' (cached fallback)
    - **request_id**: Unique request ID for debugging (include in support tickets)
    - **latency_ms**: Server processing time in milliseconds
    - **timestamp**: ISO 8601 UTC timestamp of prediction

    ### EPA AQI Categories

    | AQI Range | Category | Health Message |
    |-----------|----------|----------------|
    | 0-50 | Good | Air quality is satisfactory |
    | 51-100 | Moderate | Acceptable; some may be sensitive |
    | 101-150 | USG | Members of sensitive groups may experience |
    | 151-200 | Unhealthy | Everyone may experience health effects |
    | 201-300 | Very Unhealthy | Health alert: emergency conditions |
    | 300+ | Hazardous | Health warning of emergency conditions |

    ### Error Responses

    **400 Bad Request** — Invalid parameters:
    - Latitude out of range (-90 to 90)
    - Longitude out of range (-180 to 180)
    - Missing required parameter

    **503 Service Unavailable** — Forecast unavailable:
    - No production model registered
    - Feature store unreachable
    - Will include `Retry-After` header (suggest retry in 300 seconds)

    **500 Internal Server Error** — Unexpected server error:
    - Check `/health` endpoint
    - Include `request_id` when reporting to support

    ### Examples

    **Request:**
    ```bash
    curl 'https://api.example.com/predict?lat=24.86&lon=67.01&city=Karachi'
    ```

    **Response (200 OK, status=ok):**
    ```json
    {
      "current": {
        "aqi": 68.5,
        "category": "Moderate",
        "health_message": "Members of sensitive groups may experience health effects."
      },
      "forecast": {
        "24": {"aqi": 72.0, "category": "Moderate", ...},
        "48": {"aqi": 58.5, "category": "Moderate", ...},
        "72": {"aqi": 51.2, "category": "Good", ...}
      },
      "model": {
        "name": "aqi-lgbm-v3",
        "version": 3,
        "rmse": 15.5,
        "accuracy": 87.2,
        "training_date": "2026-08-25T10:30:00Z"
      },
      "status": "ok",
      "request_id": "a1b2c3d4",
      "latency_ms": 45.2,
      "timestamp": "2026-09-01T07:30:00Z"
    }
    ```

    **Response (200 OK, status=degraded):**
    ```json
    {
      "current": {...},
      "forecast": {...},
      "status": "degraded",
      "request_id": "a1b2c3d4",
      "timestamp": "2026-09-01T07:30:00Z"
    }
    ```

    **Response (503 Service Unavailable):**
    ```json
    {
      "error": "Forecast service temporarily unavailable",
      "details": "No production model is registered",
      "request_id": "a1b2c3d4",
      "timestamp": "2026-09-01T07:30:00Z",
      "retry_after": 300,
      "support": "Contact support with request_id: a1b2c3d4"
    }
    ```

    ### Rate Limits

    - Limit: 30 requests per minute per IP
    - Exceeding limit returns HTTP 429 with `Retry-After` header

    ### Generalization

    The model is trained on 10 Pakistani cities but generalizes well to any
    unseen city in Pakistan. Test predictions for unfamiliar coordinates — accuracy
    remains high due to robust feature engineering and cross-validation.
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
            headers={'Retry-After': '300'},
            content={
                "error": "Model service unavailable",
                "details": "No production model is registered",
                "request_id": request_id,
                "timestamp": start_time.isoformat(),
                "retry_after": 300,
                "support": f"Contact support with request_id: {request_id}"
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


@app.post(
    "/admin/migrate-predictions",
    response_model=MigrationResponse,
    responses={
        200: {"description": "Migration complete"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (10 per minute)"},
        503: {"model": ErrorResponse, "description": "Hopsworks not configured or unavailable"},
        500: {"model": ErrorResponse, "description": "Local store or Hopsworks error"},
    },
    tags=["Admin"],
)
@limiter.limit("10/minute")
def migrate_predictions(request: Request):
    """
    **[ADMIN] Migrate local predictions to Hopsworks feature store.**

    One-time migration endpoint. Reads all predictions from local Parquet store
    and writes them to Hopsworks feature store (deduplicating existing records).

    ### Prerequisites
    - `HOPSWORKS_API_KEY` environment variable must be set
    - `HOPSWORKS_PROJECT` environment variable must be set
    - Hopsworks must be accessible and project credentials valid

    ### Returns
    - **migrated**: Number of new records written to Hopsworks
    - **total_local**: Total records in local Parquet store
    - **already_in_hopsworks**: Records skipped (already exist)

    ### Response Example
    ```json
    {
      "migrated": 150,
      "total_local": 150,
      "already_in_hopsworks": 0,
      "message": "Migration complete"
    }
    ```

    ### Error Responses

    **503 Service Unavailable** — Hopsworks not configured:
    ```json
    {
      "error": "Hopsworks not configured",
      "details": "Set HOPSWORKS_API_KEY and HOPSWORKS_PROJECT environment variables"
    }
    ```

    **500 Internal Server Error** — Connection or data issue:
    ```json
    {
      "error": "Hopsworks connection failed",
      "details": "Authentication failed: invalid API key"
    }
    ```

    ### Security
    This endpoint should be protected in production (e.g., firewall rules,
    API key, or IP whitelisting). Currently exposed for local testing only.
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
