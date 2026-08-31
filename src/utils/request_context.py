"""
request_context.py — Request context and tracing utilities.

Provides request ID generation and context variables for tracing
requests through the entire logging stack, enabling correlation
between API requests and server logs.

Issue #39: Missing request IDs and poor error context in API responses.
"""

import uuid
from contextvars import ContextVar
from typing import Optional

# Context variable to store request ID for this request lifetime
_request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_request_path_var: ContextVar[Optional[str]] = ContextVar('request_path', default=None)
_request_method_var: ContextVar[Optional[str]] = ContextVar('request_method', default=None)


def generate_request_id() -> str:
    """Generate a unique 8-character request ID.
    
    Returns:
        str: Unique request ID (8 hex characters)
    """
    return str(uuid.uuid4())[:8]


def get_request_id() -> str:
    """Get current request ID from context.
    
    Returns:
        str: Request ID, or 'unknown' if not set
    """
    request_id = _request_id_var.get()
    return request_id if request_id is not None else 'unknown'


def set_request_id(request_id: str) -> None:
    """Set request ID for current request.
    
    Args:
        request_id: Unique request identifier
    """
    _request_id_var.set(request_id)


def get_request_path() -> str:
    """Get current request path from context.
    
    Returns:
        str: Request path, or 'unknown' if not set
    """
    path = _request_path_var.get()
    return path if path is not None else 'unknown'


def set_request_path(path: str) -> None:
    """Set request path for current request.
    
    Args:
        path: API endpoint path (e.g., '/predict')
    """
    _request_path_var.set(path)


def get_request_method() -> str:
    """Get current request method from context.
    
    Returns:
        str: HTTP method, or 'unknown' if not set
    """
    method = _request_method_var.get()
    return method if method is not None else 'unknown'


def set_request_method(method: str) -> None:
    """Set request method for current request.
    
    Args:
        method: HTTP method (GET, POST, etc.)
    """
    _request_method_var.set(method)


def clear_request_context() -> None:
    """Clear all request context variables.
    
    Useful for cleanup between tests or when reusing threads.
    """
    _request_id_var.set(None)
    _request_path_var.set(None)
    _request_method_var.set(None)


__all__ = [
    'generate_request_id',
    'get_request_id',
    'set_request_id',
    'get_request_path',
    'set_request_path',
    'get_request_method',
    'set_request_method',
    'clear_request_context',
]
