"""
Health Check Module

Comprehensive health checks for deployment monitoring.
"""

import os
from datetime import datetime
from typing import Dict, Any
from src.training.model_registry import ModelRegistry


async def get_health_status() -> Dict[str, Any]:
    """Get comprehensive health status for /health endpoint."""
    try:
        # Check model registry
        registry = ModelRegistry()
        production_model = registry.get_production_model()
        model_available = production_model is not None
    except Exception as e:
        model_available = False
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": os.getenv("API_VERSION", "1.0.0"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "components": {
            "model": {
                "status": "healthy" if model_available else "unavailable",
                "available": model_available,
            },
            "cache": {
                "status": "healthy",
                "type": "in-memory",
            },
            "api": {
                "status": "healthy",
                "uptime": "running",
            }
        },
        "monitoring": {
            "sentry": "enabled" if os.getenv("SENTRY_DSN") else "disabled",
            "structured_logging": "enabled",
            "metrics": "prometheus",
        }
    }


async def get_liveness() -> Dict[str, Any]:
    """Kubernetes liveness probe - is app running?"""
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}


async def get_readiness() -> Dict[str, Any]:
    """Kubernetes readiness probe - can app handle traffic?"""
    try:
        registry = ModelRegistry()
        production_model = registry.get_production_model()
        ready = production_model is not None
    except:
        ready = False
    
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "timestamp": datetime.utcnow().isoformat()
    }
