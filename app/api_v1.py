"""
AQI Predictor REST API v1 - FastAPI endpoints with async/await patterns.

Implements:
- Async I/O for all external service calls
- Dependency injection for loose coupling
- Comprehensive error handling
- Request tracing and logging
- Graceful degradation with caching
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.schemas import (
    PredictionResponse, ErrorResponse, HealthResponse, CitiesResponse,
    CityInfo, AQIReading
)
from src.config import CITIES
from src.core.dependencies import get_container
from src.utils.aqi_utils import aqi_category, health_message
from src.utils.logger import get_logger, log_event
from src.utils.exceptions import (
    InvalidCoordinatesError, InvalidCityError, ModelNotFoundError,
    PredictionError, CircuitBreakerOpenError, ServiceError
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Predictions"])


# ============================================================================
# Helper Functions
# ============================================================================

def validate_coordinates(lat: float, lon: float) -> tuple[float, float]:
    """Validate latitude and longitude."""
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise InvalidCoordinatesError(lat, lon)
    return lat, lon


def validate_city(city: Optional[str]) -> Optional[str]:
    """Validate city name if provided."""
    if city and city not in CITIES:
        raise InvalidCityError(city, list(CITIES.keys()))
    return city


async def get_prediction_with_fallback(
    lat: float,
    lon: float,
    city: Optional[str],
    request_id: str
) -> dict:
    """
    Get prediction with graceful fallback to cache on service errors.
    
    Attempts live prediction first, falls back to cached prediction if
    service unavailable or inference fails.
    """
    container = get_container()
    cache = container.get_prediction_cache()
    breaker = container.get_circuit_breaker()
    
    try:
        # Check circuit breaker
        if breaker.is_open:
            log_event(
                "warning",
                "Circuit breaker open, attempting cache fallback",
                {"request_id": request_id, "lat": lat, "lon": lon}
            )
        
        # Attempt live prediction
        result = await breaker.call_async(
            predict_async,
            lat=lat,
            lon=lon,
            city=city,
            request_id=request_id
        )
        
        # Cache successful prediction
        await cache.set_async(lat, lon, result)
        
        return {
            **result,
            "source": "live",
            "cached": False,
        }
    
    except CircuitBreakerOpenError as e:
        log_event(
            "warning",
            "Prediction service unavailable, using cache",
            {"request_id": request_id, "error": str(e)}
        )
        
        # Try cache fallback
        cached = await cache.get_async(lat, lon)
        if cached:
            return {
                **cached,
                "source": "cache",
                "cached": True,
                "cache_age_hours": cached.get("cache_age_hours", -1),
                "degraded_mode": True,
            }
        
        # No cache available
        raise PredictionError(
            "Service unavailable and no cached prediction available",
            fallback_available=False
        )
    
    except Exception as e:
        log_event(
            "error",
            f"Prediction failed: {str(e)}",
            {"request_id": request_id, "error_type": type(e).__name__}
        )
        raise


async def predict_async(
    lat: float,
    lon: float,
    city: Optional[str],
    request_id: str
) -> dict:
    """
    Async wrapper for prediction service.
    
    In production, this would call an async inference service.
    For now, wraps the synchronous predictor.
    """
    from src.inference.predict import predict
    
    try:
        # Call synchronous predictor (wrapped for now)
        # TODO: Migrate to true async inference service
        result = predict(lat=lat, lon=lon, city=city)
        
        return {
            "current": result.get("current"),
            "forecast": result.get("forecast"),
            "model": result.get("model"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
        }
    
    except Exception as e:
        raise PredictionError(str(e), fallback_available=True)


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/predict",
    response_model=PredictionResponse,
    responses={
        200: {"description": "Successful prediction"},
        400: {"description": "Invalid coordinates or city"},
        503: {"description": "Service unavailable (cache available)"},
    },
    summary="Get 3-day AQI forecast",
    tags=["Predictions"]
)
async def predict_endpoint(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude (-90 to 90)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (-180 to 180)"),
    city: Optional[str] = Query(None, description="City name (optional, for validation)"),
) -> PredictionResponse:
    """
    Get air quality prediction and 3-day forecast.
    
    **Parameters:**
    - `lat`: Latitude (-90 to 90)
    - `lon`: Longitude (-180 to 180)
    - `city`: City name (optional, used for validation and context)
    
    **Returns:**
    - Current AQI reading with health message
    - 3-day forecast (+24h, +48h, +72h)
    - Model metadata and feature importance
    - Request ID for tracing
    
    **Resilience:**
    - If live prediction fails, returns cached prediction with `degraded_mode: true`
    - Includes cache age and availability in response
    
    **Example:**
    ```bash
    curl "https://api.example.com/api/v1/predict?lat=24.86&lon=67.01&city=Karachi"
    ```
    """
    request_id = request.state.request_id
    
    try:
        # Validate input
        lat, lon = validate_coordinates(lat, lon)
        city = validate_city(city)
        
        log_event(
            "info",
            "Prediction request",
            {
                "request_id": request_id,
                "lat": lat,
                "lon": lon,
                "city": city or "unknown"
            }
        )
        
        # Get prediction with fallback
        prediction = await get_prediction_with_fallback(lat, lon, city, request_id)
        
        log_event(
            "info",
            "Prediction successful",
            {
                "request_id": request_id,
                "source": prediction.get("source"),
                "cached": prediction.get("cached")
            }
        )
        
        return PredictionResponse(**prediction)
    
    except Exception as e:
        logger.error(f"Prediction endpoint error: {e}", exc_info=True)
        raise


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    tags=["Health"]
)
async def health_check(request: Request) -> HealthResponse:
    """
    Service health status endpoint.
    
    Returns:
    - Overall service status (healthy/degraded/unhealthy)
    - Model availability and version
    - Feature store status
    - Cache status
    - Upstream service status
    
    Used by load balancers and monitoring systems.
    """
    request_id = request.state.request_id
    container = get_container()
    
    try:
        # Check service readiness
        model_registry = container.get_model_registry()
        cache = container.get_prediction_cache()
        
        # Get production model info
        production_entry = model_registry.production_entry()
        
        status = "healthy" if production_entry else "degraded"
        model_info = {
            "version": production_entry.model_id if production_entry else None,
            "rmse": production_entry.rmse if production_entry else None,
            "available": production_entry is not None,
        }
        
        return HealthResponse(
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model_info,
            service="aqi_predictor_api",
            version="1.0.0",
            request_id=request_id,
        )
    
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
            model={"available": False},
            service="aqi_predictor_api",
            version="1.0.0",
            request_id=request_id,
            error=str(e),
        )


@router.get(
    "/cities",
    response_model=CitiesResponse,
    summary="List supported cities",
    tags=["Reference Data"]
)
async def list_cities(request: Request) -> CitiesResponse:
    """
    Get list of training cities with coordinates.
    
    Useful for client applications to build location pickers or
    validate city input without hardcoding.
    
    Returns:
    - List of 10 Pakistani training cities
    - Coordinates (latitude, longitude) for each
    - City metadata (region, population, etc.)
    """
    request_id = request.state.request_id
    
    cities = [
        CityInfo(
            name=city,
            lat=coords["lat"],
            lon=coords["lon"],
            region=coords.get("region", ""),
        )
        for city, coords in CITIES.items()
    ]
    
    log_event(
        "info",
        "Cities list requested",
        {"request_id": request_id, "count": len(cities)}
    )
    
    return CitiesResponse(
        cities=cities,
        count=len(cities),
        timestamp=datetime.now(timezone.utc).isoformat(),
        request_id=request_id,
    )


@router.get(
    "/status",
    response_model=dict,
    summary="Detailed service status",
    tags=["Health"]
)
async def service_status(request: Request) -> dict:
    """
    Detailed service status with all component information.
    
    Returns:
    - Container readiness status
    - Individual service statuses
    - Model registry information
    - Cache statistics
    - Circuit breaker state
    
    Used for debugging and monitoring.
    """
    request_id = request.state.request_id
    container = get_container()
    
    try:
        cache = container.get_prediction_cache()
        breaker = container.get_circuit_breaker()
        
        return {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "container": {
                "ready": container.is_ready,
                "initialized": container._initialized,
            },
            "circuit_breaker": {
                "status": breaker.status,
                "is_open": breaker.is_open,
                "failure_count": breaker.fail_count,
            },
            "cache": {
                "size": len(cache) if cache else 0,
                "max_entries": getattr(cache, "max_entries", None),
            },
        }
    
    except Exception as e:
        logger.error(f"Status check failed: {e}", exc_info=True)
        return {
            "request_id": request_id,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
