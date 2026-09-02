"""
Core architectural components for AQI Predictor.

Provides:
- Dependency injection (dependencies.py)
- API routing & versioning (api_router.py)
- Lifecycle management (lifespan hooks)
- Centralized error handling
"""

from src.core.dependencies import (
    ServiceContainer,
    get_container,
    set_container,
)
from src.core.api_router import (
    create_app,
    create_v1_router,
    create_v2_router,
    lifespan,
    exception_handler,
)

__all__ = [
    "ServiceContainer",
    "get_container",
    "set_container",
    "create_app",
    "create_v1_router",
    "create_v2_router",
    "lifespan",
    "exception_handler",
]
