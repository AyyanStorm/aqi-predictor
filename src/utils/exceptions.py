"""
Custom exception hierarchy for AQI Predictor.

Provides domain-specific exceptions for better error handling, logging,
and HTTP error mapping.
"""


class AQIException(Exception):
    """Base exception for all AQI Predictor errors."""
    
    http_status_code = 500
    error_code = "INTERNAL_ERROR"
    
    def __init__(self, message: str, details: dict = None, http_status_code: int = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if http_status_code:
            self.http_status_code = http_status_code
    
    def to_dict(self) -> dict:
        """Convert to HTTP response format."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Input Validation Errors (4xx)
# ============================================================================

class ValidationError(AQIException):
    """Request validation failed."""
    http_status_code = 400
    error_code = "VALIDATION_ERROR"


class InvalidCoordinatesError(ValidationError):
    """Geographic coordinates out of valid range."""
    error_code = "INVALID_COORDINATES"
    
    def __init__(self, lat: float, lon: float):
        super().__init__(
            f"Invalid coordinates: lat={lat} (must be -90 to 90), lon={lon} (must be -180 to 180)",
            {"lat": lat, "lon": lon}
        )


class InvalidCityError(ValidationError):
    """City not found or not supported."""
    error_code = "INVALID_CITY"
    
    def __init__(self, city: str, available_cities: list):
        super().__init__(
            f"City '{city}' not found. Available cities: {', '.join(available_cities)}",
            {"city": city, "available": available_cities}
        )


class MissingParameterError(ValidationError):
    """Required parameter missing from request."""
    error_code = "MISSING_PARAMETER"
    
    def __init__(self, param: str, required_params: list):
        super().__init__(
            f"Missing required parameter: {param}. Required: {', '.join(required_params)}",
            {"missing": param, "required": required_params}
        )


# ============================================================================
# Service/Dependency Errors (5xx)
# ============================================================================

class ServiceError(AQIException):
    """Error in external service or dependency."""
    http_status_code = 503
    error_code = "SERVICE_UNAVAILABLE"


class ModelNotFoundError(ServiceError):
    """Production model not available in registry."""
    error_code = "MODEL_NOT_FOUND"
    
    def __init__(self):
        super().__init__(
            "No production model available. Model registry may be initializing.",
            {}
        )


class ModelLoadError(ServiceError):
    """Failed to load model from registry."""
    error_code = "MODEL_LOAD_ERROR"
    
    def __init__(self, model_id: str, reason: str):
        super().__init__(
            f"Failed to load model {model_id}: {reason}",
            {"model_id": model_id, "reason": reason}
        )


class PredictionError(ServiceError):
    """Error during inference."""
    error_code = "PREDICTION_ERROR"
    
    def __init__(self, reason: str, fallback_available: bool = False):
        super().__init__(
            f"Prediction failed: {reason}. Fallback cache available: {fallback_available}",
            {"reason": reason, "fallback": fallback_available}
        )


class DataFetchError(ServiceError):
    """Failed to fetch required data from upstream service."""
    error_code = "DATA_FETCH_ERROR"
    
    def __init__(self, source: str, reason: str):
        super().__init__(
            f"Failed to fetch data from {source}: {reason}",
            {"source": source, "reason": reason}
        )


class FeatureStoreError(ServiceError):
    """Error accessing feature store."""
    error_code = "FEATURE_STORE_ERROR"
    
    def __init__(self, reason: str):
        super().__init__(
            f"Feature store error: {reason}",
            {"reason": reason}
        )


class CacheError(ServiceError):
    """Error accessing cache."""
    error_code = "CACHE_ERROR"
    
    def __init__(self, reason: str, is_retrieval: bool = True):
        op = "reading from" if is_retrieval else "writing to"
        super().__init__(
            f"Error {op} cache: {reason}",
            {"reason": reason, "operation": "read" if is_retrieval else "write"}
        )


class CircuitBreakerOpenError(ServiceError):
    """Circuit breaker is open, service unavailable."""
    http_status_code = 503
    error_code = "CIRCUIT_BREAKER_OPEN"
    
    def __init__(self, service: str, retry_after: int = None):
        details = {"service": service}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            f"Service '{service}' temporarily unavailable due to repeated failures. Retry after {retry_after}s.",
            details
        )


# ============================================================================
# Rate Limiting Errors (429)
# ============================================================================

class RateLimitError(AQIException):
    """Rate limit exceeded."""
    http_status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    
    def __init__(self, limit: str, retry_after: int = None):
        details = {"limit": limit}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            f"Rate limit exceeded: {limit}. Please retry later.",
            details
        )


# ============================================================================
# Configuration/Startup Errors (5xx)
# ============================================================================

class ConfigurationError(AQIException):
    """Configuration is invalid or incomplete."""
    http_status_code = 500
    error_code = "CONFIGURATION_ERROR"
    
    def __init__(self, setting: str, reason: str):
        super().__init__(
            f"Configuration error: {setting} - {reason}",
            {"setting": setting, "reason": reason}
        )


class InitializationError(AQIException):
    """Service initialization failed."""
    http_status_code = 500
    error_code = "INITIALIZATION_ERROR"
    
    def __init__(self, component: str, reason: str):
        super().__init__(
            f"Failed to initialize {component}: {reason}",
            {"component": component, "reason": reason}
        )
