"""
cache_metrics.py — Prometheus metrics for cache performance monitoring.

Tracks cache hit/miss rates, cache size, and age of cached data.
Used by PredictionCache and Streamlit st.cache_data decorators.

Issue #41: Multi-layer caching strategy with observability.
"""

import logging

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Fallback: create dummy classes (no-op when prometheus not installed)
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def inc(self, *args): pass
    
    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def set(self, val): pass
    
    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def observe(self, val): pass

logger = logging.getLogger(__name__)


# Global metrics (registered once, reused by all cache instances)
_METRICS_INITIALIZED = False
_HITS = None
_MISSES = None
_EVICTIONS = None
_SIZE_BYTES = None
_ENTRIES = None
_AGE_HOURS = None


def _init_metrics():
    """Initialize global metrics (idempotent, called once)."""
    global _METRICS_INITIALIZED, _HITS, _MISSES, _EVICTIONS, _SIZE_BYTES, _ENTRIES, _AGE_HOURS
    
    if _METRICS_INITIALIZED:
        return
    
    if not PROMETHEUS_AVAILABLE:
        _METRICS_INITIALIZED = True
        return
    
    try:
        # Check if metrics already registered (e.g., in pytest fixtures)
        _HITS = Counter(
            'cache_hits_total',
            'Total cache hits',
            ['cache_name'],
            registry=REGISTRY
        )
        
        _MISSES = Counter(
            'cache_misses_total',
            'Total cache misses',
            ['cache_name'],
            registry=REGISTRY
        )
        
        _EVICTIONS = Counter(
            'cache_evictions_total',
            'Total cache evictions (overflow cleanup)',
            ['cache_name'],
            registry=REGISTRY
        )
        
        _SIZE_BYTES = Gauge(
            'cache_size_bytes',
            'Current cache size in bytes',
            ['cache_name'],
            registry=REGISTRY
        )
        
        _ENTRIES = Gauge(
            'cache_entries',
            'Number of entries in cache',
            ['cache_name'],
            registry=REGISTRY
        )
        
        _AGE_HOURS = Histogram(
            'cache_age_hours',
            'Age of cached data in hours at retrieval',
            ['cache_name'],
            buckets=(0.1, 0.5, 1.0, 6.0, 24.0, float('inf')),
            registry=REGISTRY
        )
        
        _METRICS_INITIALIZED = True
        logger.debug('Prometheus cache metrics initialized')
    
    except Exception as e:
        # If registration fails (e.g., duplicate metric), just log it
        # and mark as initialized so we don't crash the cache
        logger.warning(f'Failed to initialize Prometheus metrics: {e}')
        _METRICS_INITIALIZED = True


class CacheMetrics:
    """Prometheus metrics for cache performance.
    
    Uses global metric instances (registered once) to avoid
    DuplicateTimeseries errors in tests.
    """
    
    def __init__(self, cache_name: str):
        """
        Initialize metrics for a cache instance.
        
        Args:
            cache_name: Name of the cache (e.g., 'prediction_cache', 'forecast_cache')
        """
        _init_metrics()
        self.cache_name = cache_name
        
        # Reference global metrics
        self.hits = _HITS
        self.misses = _MISSES
        self.evictions = _EVICTIONS
        self.size_bytes = _SIZE_BYTES
        self.entries = _ENTRIES
        self.age_hours = _AGE_HOURS
    
    def record_hit(self, age_hours: float = 0):
        """Record a cache hit."""
        if self.hits is None:
            return  # prometheus-client not available
        try:
            self.hits.labels(cache_name=self.cache_name).inc()
            if age_hours > 0:
                self.age_hours.labels(cache_name=self.cache_name).observe(age_hours)
        except Exception as e:
            logger.debug(f'Failed to record cache hit: {e}')
    
    def record_miss(self):
        """Record a cache miss."""
        if self.misses is None:
            return  # prometheus-client not available
        try:
            self.misses.labels(cache_name=self.cache_name).inc()
        except Exception as e:
            logger.debug(f'Failed to record cache miss: {e}')
    
    def record_eviction(self):
        """Record a cache eviction (overflow cleanup)."""
        if self.evictions is None:
            return  # prometheus-client not available
        try:
            self.evictions.labels(cache_name=self.cache_name).inc()
        except Exception as e:
            logger.debug(f'Failed to record eviction: {e}')
    
    def set_size(self, size_bytes: int, num_entries: int):
        """Update cache size metrics."""
        if self.size_bytes is None:
            return  # prometheus-client not available
        try:
            self.size_bytes.labels(cache_name=self.cache_name).set(size_bytes)
            self.entries.labels(cache_name=self.cache_name).set(num_entries)
        except Exception as e:
            logger.debug(f'Failed to set size metrics: {e}')
    
    def hit_rate(self) -> float:
        """Calculate cache hit rate (hits / total requests)."""
        if self.hits is None:
            return 0.0  # prometheus-client not available
        try:
            # Try to get internal counter values
            hits_val = getattr(self.hits.labels(cache_name=self.cache_name), '_value', None)
            misses_val = getattr(self.misses.labels(cache_name=self.cache_name), '_value', None)
            
            if hits_val and misses_val:
                hits = hits_val.get()
                misses = misses_val.get()
                total = hits + misses
                return hits / total if total > 0 else 0.0
        except Exception:
            pass
        return 0.0
