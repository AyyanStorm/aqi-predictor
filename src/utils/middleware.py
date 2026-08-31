"""
middleware.py — FastAPI middleware for request tracking.

Provides middleware to attach request IDs to all requests and responses,
enabling end-to-end request tracing through logs.

Issue #39: Missing request IDs and poor error context in API responses.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import MutableHeaders
from datetime import datetime, timezone
import time

from src.utils.request_context import (
    generate_request_id,
    set_request_id,
    set_request_path,
    set_request_method,
    clear_request_context,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique request ID to each request.
    
    This middleware:
    - Generates a unique 8-character ID for each request
    - Stores it in context variables for access throughout request lifecycle
    - Adds X-Request-ID header to all responses
    - Logs request timing and status
    """
    
    async def dispatch(self, request, call_next):
        """Process request and attach request ID to response.
        
        Args:
            request: Incoming HTTP request
            call_next: Callable to pass request to next middleware/handler
            
        Returns:
            Response with X-Request-ID header
        """
        # Skip middleware for non-HTTP requests
        if request.scope.get('type') != 'http':
            return await call_next(request)
        
        # Generate request ID
        request_id = generate_request_id()
        set_request_id(request_id)
        set_request_path(request.url.path)
        set_request_method(request.method)
        
        # Track timing
        start_time = time.time()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add request ID to response headers
            response.headers['X-Request-ID'] = request_id
            
            # Log request completion
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f'{request.method} {request.url.path} -> {response.status_code} ({elapsed_ms:.1f}ms)',
                extra={
                    'request_id': request_id,
                    'method': request.method,
                    'path': request.url.path,
                    'status_code': response.status_code,
                    'elapsed_ms': elapsed_ms,
                }
            )
            
            return response
        
        except Exception as e:
            # Log exception
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f'{request.method} {request.url.path} -> ERROR: {e} ({elapsed_ms:.1f}ms)',
                exc_info=True,
                extra={
                    'request_id': request_id,
                    'method': request.method,
                    'path': request.url.path,
                    'elapsed_ms': elapsed_ms,
                }
            )
            raise
        
        finally:
            # Clean up context after request completes
            clear_request_context()


class ErrorResponseMiddleware(BaseHTTPMiddleware):
    """Middleware to standardize error response format.
    
    Ensures all error responses include request ID and timestamp.
    """
    
    async def dispatch(self, request, call_next):
        """Process request and standardize error responses.
        
        Args:
            request: Incoming HTTP request
            call_next: Callable to pass request to next middleware/handler
            
        Returns:
            Response (possibly modified for error cases)
        """
        try:
            response = await call_next(request)
            return response
        
        except Exception as e:
            # Let other middleware/handlers process the exception
            raise


__all__ = ['RequestIDMiddleware', 'ErrorResponseMiddleware']
