"""
rate_limiter.py — API rate limiting with slowapi.

Implements per-endpoint rate limits to prevent DoS attacks:
- /predict: 30 requests per minute per IP
- /health, /cities: 60 requests per minute per IP
- Default: 200 requests per hour per IP

Issue #40: Protect against DoS attacks with rate limiting.
"""

import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)


def get_remote_address_with_forwarded(request):
    """
    Enhanced IP extraction that checks X-Forwarded-For header.
    
    This allows rate limiting to work correctly when behind a proxy
    (like Render, Cloudflare, or load balancers) and in testing with
    the X-Forwarded-For header.
    
    Args:
        request: FastAPI Request object
    
    Returns:
        Client IP address (string)
    """
    # Check for X-Forwarded-For header first (proxies, load balancers, tests)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        # Take the first IP if there are multiple
        return forwarded.split(',')[0].strip()
    
    # Fall back to direct connection IP
    return get_remote_address(request)


# Initialize limiter with IP-based rate limiting
limiter = Limiter(
    key_func=get_remote_address_with_forwarded,
    default_limits=["200 per hour"],
    storage_uri=None  # Use in-memory storage (good for single-instance apps)
)

# Per-endpoint rate limits
RATE_LIMITS = {
    "/predict": "30/minute",      # 30 predictions per IP per minute
    "/health": "60/minute",        # Health checks (less restrictive)
    "/cities": "60/minute",        # City list (less restrictive)
}


def get_rate_limit(path: str) -> str:
    """
    Get rate limit string for an endpoint path.
    
    Args:
        path: Request path (e.g., '/predict')
    
    Returns:
        Rate limit string (e.g., '30/minute')
    """
    return RATE_LIMITS.get(path, "200/hour")


def log_rate_limit_exceeded(request, client_ip: str, endpoint: str):
    """
    Log rate limit violation for monitoring.
    
    Args:
        request: FastAPI Request object
        client_ip: Client IP address
        endpoint: Endpoint path (e.g., '/predict')
    """
    logger.warning(
        "Rate limit exceeded",
        extra={
            "fields": {
                "ip": client_ip,
                "endpoint": endpoint,
                "event": "rate_limit_exceeded"
            }
        }
    )
