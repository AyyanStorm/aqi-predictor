"""
Centralized API routing with versioning support.

Provides versioned API endpoints, error handling, and lifecycle management.
"""

import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from src.utils.logger import get_logger, log_event
from src.utils.exceptions import AQIException, RateLimitError
from src.core.dependencies import get_container

logger = get_logger(__name__)


# ============================================================================
# Error Handler Middleware
# ============================================================================

async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Centralized exception handler for all exceptions.
    
    Maps domain exceptions to HTTP responses with proper status codes,
    error codes, and tracing information.
    """
    request_id = request.headers.get("X-Request-ID", "unknown")
    
    # Handle custom domain exceptions
    if isinstance(exc, AQIException):
        log_event(
            "error",
            f"{exc.error_code}: {exc.message}",
            {
                "request_id": request_id,
                "error_code": exc.error_code,
                "details": exc.details,
                "path": request.url.path,
            }
        )
        
        return JSONResponse(
            status_code=exc.http_status_code,
            content={
                "request_id": request_id,
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            }
        )
    
    # Handle FastAPI HTTPException
    if isinstance(exc, HTTPException):
        log_event(
            "warning",
            f"HTTP {exc.status_code}: {exc.detail}",
            {"request_id": request_id, "path": request.url.path}
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "request_id": request_id,
                "error_code": "HTTP_ERROR",
                "message": exc.detail,
            }
        )
    
    # Handle unexpected errors
    log_event(
        "error",
        f"Unexpected error: {type(exc).__name__}",
        {
            "request_id": request_id,
            "error": str(exc),
            "path": request.url.path,
        },
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "request_id": request_id,
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred. Please contact support.",
            "support_email": "support@aqi-predictor.dev",
        }
    )


# ============================================================================
# Lifecycle Management
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle: startup and shutdown.
    
    Called automatically by FastAPI at app startup and shutdown.
    """
    # ===== STARTUP =====
    logger.info("🚀 Starting AQI Predictor API...")
    try:
        container = get_container()
        await container.initialize()
        logger.info("✅ API ready to serve requests")
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)
        raise
    
    yield  # App runs here
    
    # ===== SHUTDOWN =====
    logger.info("🛑 Shutting down AQI Predictor API...")
    try:
        container = get_container()
        await container.shutdown()
        logger.info("✅ API shutdown gracefully")
    except Exception as e:
        logger.error(f"❌ Shutdown failed: {e}", exc_info=True)


# ============================================================================
# API Router Setup
# ============================================================================

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application with all middleware,
    routers, and error handlers.
    
    Returns:
        Configured FastAPI app instance
    """
    # Create app with lifecycle management
    app = FastAPI(
        title="AQI Predictor — Pakistan",
        description="""
# Live air quality forecast (+24h/+48h/+72h) for any coordinates.

Served by a city-agnostic LightGBM model trained on 10 Pakistani cities.

## ✨ Features
- **Current AQI**: Observed air quality index
- **3-Day Forecast**: +24h, +48h, +72h predictions
- **Health Guidance**: Category-specific recommendations
- **Explainability**: Feature importance for each prediction
- **Resilience**: Cached predictions if service unavailable
- **Tracing**: Every response includes request_id for debugging

## 📊 Endpoints
- `GET /api/v1/predict` - Get AQI prediction
- `GET /api/v1/health` - Service health status
- `GET /api/v1/cities` - List supported cities
- `GET /metrics` - Prometheus metrics

## 🔗 Documentation
- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`
""",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,  # Enable lifecycle hooks
    )
    
    # ===== Exception Handlers =====
    app.add_exception_handler(AQIException, exception_handler)
    app.add_exception_handler(HTTPException, exception_handler)
    app.add_exception_handler(Exception, exception_handler)
    
    # ===== CORS & Security Headers =====
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific domains
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
    )
    
    # ===== Request ID Middleware =====
    import uuid
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        """Add unique request ID for tracing."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    
    return app


# ============================================================================
# Versioned Router Factory
# ============================================================================

def create_v1_router():
    """Create v1 API router with all endpoints."""
    from fastapi import APIRouter
    router = APIRouter(
        prefix="/api/v1",
        tags=["AQI Prediction v1"],
    )
    return router


def create_v2_router():
    """
    Create v2 API router for future enhancements.
    
    Can be used for backwards-incompatible changes without breaking v1.
    """
    from fastapi import APIRouter
    router = APIRouter(
        prefix="/api/v2",
        tags=["AQI Prediction v2"],
    )
    return router
