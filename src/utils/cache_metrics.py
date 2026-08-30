"""
cache_metrics.py — Prometheus metrics for cache performance monitoring.

Tracks cache hit/miss rates, cache size, and age of cached data.
Uses singleton pattern to avoid metric registration conflicts in tests.

Issue #41: Multi-layer caching strategy with observability.
"""

import logging

logger = logging.getLogger(__name__)

# Try to import prometheus, use fallback if not available
try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Dummy classes for when prometheus is not available
class DummyCounter:
    def __init__(self, *args, **kwargs): pass
    def labels(self, **kwargs): return self
    def inc(self, *args): pass

class DummyGauge:
    def __init__(self, *args, **kwargs): pass
    def labels(self, **kwargs): return self
    def set(self, val): pass

class DummyHistogram:
    def __init__(self, *args, **kwargs): pass
    def labels(self, **kwargs): return self
    def observe(self, val): pass


# Global metrics registry (singleton, created once)
_GLOBAL_METRICS = None

def _get_or_create_metrics():
    """Get or create global metrics (idempotent)."""
    global _GLOBAL_METRICS
    
    if _GLOBAL_METRICS is not None:
        return _GLOBAL_METRICS
    
    # Create new metrics dict
    metrics = {
        'hits': None,
        'misses': None,
        'evictions': None,
        'size_bytes': None,
        'entries': None,
        'age_hours': None,
    }
    
    if not PROMETHEUS_AVAILABLE:
        # Use dummy classes
        metrics['hits'] = DummyCounter()
        metrics['misses'] = DummyCounter()
        metrics['evictions'] = DummyCounter()
        metrics['size_bytes'] = DummyGauge()
        metrics['entries'] = DummyGauge()
        metrics['age_hours'] = DummyHistogram()
        _GLOBAL_METRICS = metrics
        return metrics
    
    # Try to register real Prometheus metrics
    try:
        metrics['hits'] = Counter(
            'cache_hits_total',
            'Total cache hits',
            ['cache_name'],
            registry=REGISTRY
        )
        metrics['misses'] = Counter(
            'cache_misses_total',
            'Total cache misses',
            ['cache_name'],
            registry=REGISTRY
        )
        metrics['evictions'] = Counter(
            'cache_evictions_total',
            'Total cache evictions (overflow cleanup)',
            ['cache_name'],
            registry=REGISTRY
        )
        metrics['size_bytes'] = Gauge(
            'cache_size_bytes',
            'Current cache size in bytes',
            ['cache_name'],
            registry=REGISTRY
        )
        metrics['entries'] = Gauge(
            'cache_entries',
            'Number of entries in cache',
            ['cache_name'],
            registry=REGISTRY
        )
        metrics['age_hours'] = Histogram(
            'cache_age_hours',
            'Age of cached data in hours at retrieval',
            ['cache_name'],
            buckets=(0.1, 0.5, 1.0, 6.0, 24.0, float('inf')),
            registry=REGISTRY
        )
        logger.debug('Prometheus cache metrics initialized')
    
    except Exception as e:
        # Registration failed (e.g., duplicate metric in test) → use dummies
        logger.warning(f'Prometheus metrics registration failed: {e}; using dummy metrics')
        metrics['hits'] = DummyCounter()
        metrics['misses'] = DummyCounter()
        metrics['evictions'] = DummyCounter()
        metrics['size_bytes'] = DummyGauge()
        metrics['entries'] = DummyGauge()
        metrics['age_hours'] = DummyHistogram()
    
    _GLOBAL_METRICS = metrics
    return metrics


class CacheMetrics:
    """Prometheus metrics for cache performance.
    
    Uses global singleton metrics to avoid duplicate registration errors.
    Falls back to dummy metrics if prometheus-client is unavailable.
    """
    
    def __init__(self, cache_name: str):
        """
        Initialize metrics for a cache instance.
        
        Args:
            cache_name: Name of the cache (e.g., 'prediction_cache')
        """
        self.cache_name = cache_name
        
        # Get or create global metrics
        self._metrics = _get_or_create_metrics()
        
        # Reference global metrics
        self.hits = self._metrics['hits']
        self.misses = self._metrics['misses']
        self.evictions = self._metrics['evictions']
        self.size_bytes = self._metrics['size_bytes']
        self.entries = self._metrics['entries']
        self.age_hours = self._metrics['age_hours']
    
    def record_hit(self, age_hours: float = 0):
        """Record a cache hit."""
        try:
            self.hits.labels(cache_name=self.cache_name).inc()
            if age_hours > 0:
                self.age_hours.labels(cache_name=self.cache_name).observe(age_hours)
        except Exception as e:
            logger.debug(f'Failed to record cache hit: {e}')
    
    def record_miss(self):
        """Record a cache miss."""
        try:
            self.misses.labels(cache_name=self.cache_name).inc()
        except Exception as e:
            logger.debug(f'Failed to record cache miss: {e}')
    
    def record_eviction(self):
        """Record a cache eviction (overflow cleanup)."""
        try:
            self.evictions.labels(cache_name=self.cache_name).inc()
        except Exception as e:
            logger.debug(f'Failed to record eviction: {e}')
    
    def set_size(self, size_bytes: int, num_entries: int):
        """Update cache size metrics."""
        try:
            self.size_bytes.labels(cache_name=self.cache_name).set(size_bytes)
            self.entries.labels(cache_name=self.cache_name).set(num_entries)
        except Exception as e:
            logger.debug(f'Failed to set size metrics: {e}')
    
    def hit_rate(self) -> float:
        """Calculate cache hit rate (hits / total requests)."""
        try:
            # Try to get internal counter values for hit rate calculation
            hits_val = getattr(self.hits.labels(cache_name=self.cache_name), '_value', None)
            misses_val = getattr(self.misses.labels(cache_name=self.cache_name), '_value', None)
            
            if hits_val and misses_val:
                hits = hits_val.get() if callable(getattr(hits_val, 'get', None)) else 0
                misses = misses_val.get() if callable(getattr(misses_val, 'get', None)) else 0
                total = hits + misses
                return hits / total if total > 0 else 0.0
        except Exception:
            pass
        return 0.0
