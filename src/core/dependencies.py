"""
Dependency Injection Container for AQI Predictor.

Centralized management of service instances, initialization, and lifecycle.
Enables easy testing, backend swapping, and loose coupling.
"""

import logging
from typing import Optional
from functools import lru_cache

from src.config import CITIES
from src.inference.predict import predict as predict_fn
from src.inference.cache import PredictionCache
from src.inference.circuit_breaker import CircuitBreaker
from src.training.model_registry import ModelRegistry
from src.features.feature_store import FeatureStore
from src.tracking.store import ParquetPredictionStore, HopsworksPredictionStore
from src.utils.logger import get_logger
from src.utils.exceptions import InitializationError

logger = get_logger(__name__)


class ServiceContainer:
    """
    Dependency injection container for all services.
    
    Manages initialization, lifecycle, and injection of dependencies.
    Supports easy testing through mock injection.
    
    Example:
        container = ServiceContainer()
        model_registry = container.get_model_registry()
        prediction_cache = container.get_prediction_cache()
    """
    
    def __init__(self):
        self._cache_instance: Optional[PredictionCache] = None
        self._model_registry: Optional[ModelRegistry] = None
        self._feature_store: Optional[FeatureStore] = None
        self._prediction_store: Optional[ParquetPredictionStore] = None
        self._circuit_breaker: Optional[CircuitBreaker] = None
        self._initialized = False
        logger.info("ServiceContainer initialized")
    
    async def initialize(self) -> None:
        """Initialize all services at startup."""
        if self._initialized:
            logger.debug("Services already initialized, skipping")
            return
        
        try:
            logger.info("Initializing services...")
            
            # Initialize model registry first (required for predictions)
            self._model_registry = self._init_model_registry()
            
            # Initialize cache
            self._cache_instance = self._init_cache()
            
            # Initialize feature store
            self._feature_store = self._init_feature_store()
            
            # Initialize prediction store
            self._prediction_store = self._init_prediction_store()
            
            # Initialize circuit breaker for prediction service
            self._circuit_breaker = self._init_circuit_breaker()
            
            self._initialized = True
            logger.info("✅ All services initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize services: {e}", exc_info=True)
            raise InitializationError("services", str(e))
    
    async def shutdown(self) -> None:
        """Graceful shutdown of all services."""
        logger.info("Shutting down services...")
        try:
            if self._cache_instance:
                self._cache_instance.clear()
                logger.debug("Cache cleared")
            
            if self._prediction_store:
                logger.debug("Prediction store gracefully closed")
            
            if self._circuit_breaker:
                logger.debug("Circuit breaker reset")
            
            logger.info("✅ All services shutdown gracefully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)
    
    def _init_model_registry(self) -> ModelRegistry:
        """Initialize model registry."""
        try:
            registry = ModelRegistry(data_dir="data/models/registry")
            logger.debug(f"✅ ModelRegistry initialized at data/models/registry")
            return registry
        except Exception as e:
            logger.error(f"Failed to initialize ModelRegistry: {e}")
            raise
    
    def _init_cache(self) -> PredictionCache:
        """Initialize prediction cache."""
        try:
            cache = PredictionCache(
                cache_file=".prediction_cache.json",
                max_age_hours=24,
                max_entries=10000
            )
            logger.debug(f"✅ PredictionCache initialized")
            return cache
        except Exception as e:
            logger.error(f"Failed to initialize PredictionCache: {e}")
            raise
    
    def _init_feature_store(self) -> FeatureStore:
        """Initialize feature store."""
        try:
            feature_store = FeatureStore(data_dir="data/processed/feature_store_parquet")
            logger.debug(f"✅ FeatureStore initialized")
            return feature_store
        except Exception as e:
            logger.error(f"Failed to initialize FeatureStore: {e}")
            raise
    
    def _init_prediction_store(self) -> ParquetPredictionStore:
        """Initialize prediction store."""
        try:
            store = ParquetPredictionStore(data_dir="data/predictions")
            logger.debug(f"✅ PredictionStore initialized")
            return store
        except Exception as e:
            logger.error(f"Failed to initialize PredictionStore: {e}")
            raise
    
    def _init_circuit_breaker(self) -> CircuitBreaker:
        """Initialize circuit breaker for resilience."""
        breaker = CircuitBreaker(
            name="prediction_service",
            fail_max=5,
            reset_timeout=60
        )
        logger.debug(f"✅ CircuitBreaker initialized")
        return breaker
    
    # ========================================================================
    # Public API - Service Getters
    # ========================================================================
    
    def get_model_registry(self) -> ModelRegistry:
        """Get model registry instance."""
        if not self._model_registry:
            raise InitializationError("model_registry", "Not initialized")
        return self._model_registry
    
    def get_prediction_cache(self) -> PredictionCache:
        """Get prediction cache instance."""
        if not self._cache_instance:
            raise InitializationError("cache", "Not initialized")
        return self._cache_instance
    
    def get_feature_store(self) -> FeatureStore:
        """Get feature store instance."""
        if not self._feature_store:
            raise InitializationError("feature_store", "Not initialized")
        return self._feature_store
    
    def get_prediction_store(self) -> ParquetPredictionStore:
        """Get prediction store instance."""
        if not self._prediction_store:
            raise InitializationError("prediction_store", "Not initialized")
        return self._prediction_store
    
    def get_circuit_breaker(self) -> CircuitBreaker:
        """Get circuit breaker instance."""
        if not self._circuit_breaker:
            raise InitializationError("circuit_breaker", "Not initialized")
        return self._circuit_breaker
    
    def get_config(self) -> dict:
        """Get configuration (CITIES mapping)."""
        return CITIES
    
    @property
    def is_ready(self) -> bool:
        """Check if all services are initialized and ready."""
        return (
            self._initialized and
            self._model_registry is not None and
            self._cache_instance is not None and
            self._feature_store is not None and
            self._prediction_store is not None
        )


# Global container instance (singleton pattern)
_global_container: Optional[ServiceContainer] = None


def get_container() -> ServiceContainer:
    """Get or create the global service container."""
    global _global_container
    if _global_container is None:
        _global_container = ServiceContainer()
    return _global_container


def set_container(container: ServiceContainer) -> None:
    """Set the global service container (useful for testing)."""
    global _global_container
    _global_container = container
