"""
cache_metrics.py — Prometheus metrics for cache performance monitoring.

Tracks cache hit/miss rates, cache size, and age of cached data.
Used by PredictionCache and Streamlit st.cache_data decorators.

Issue #41: Multi-layer caching strategy with observability.
"""

import logging

try:
    from prometheus_client import Counter, Gauge, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Fallback: create dummy classes
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


class CacheMetrics:
    """Prometheus metrics for cache performance."""
    
    def __init__(self, cache_name: str):
        """
        Initialize metrics for a cache instance.
        
        Args:
            cache_name: Name of the cache (e.g., 'prediction_cache', 'forecast_cache')
        """
        self.cache_name = cache_name
        
        # Cache hit/miss counters
        self.hits = Counter(
            'cache_hits_total',
            'Total cache hits',
            ['cache_name']
        )
        
        self.misses = Counter(
            'cache_misses_total',
            'Total cache misses',
            ['cache_name']
        )
        
        self.evictions = Counter(
            'cache_evictions_total',
            'Total cache evictions (overflow cleanup)',
            ['cache_name']
        )
        
        # Cache size gauge
        self.size_bytes = Gauge(
            'cache_size_bytes',
            'Current cache size in bytes',
            ['cache_name']
        )
        
        self.entries = Gauge(
            'cache_entries',
            'Number of entries in cache',
            ['cache_name']
        )
        
        # Cache age histogram (age of data in cache at retrieval)
        self.age_hours = Histogram(
            'cache_age_hours',
            'Age of cached data in hours at retrieval',
            ['cache_name'],
            buckets=(0.1, 0.5, 1.0, 6.0, 24.0, float('inf'))
        )
    
    def record_hit(self, age_hours: float = 0):
        """Record a cache hit."""
        self.hits.labels(cache_name=self.cache_name).inc()
        if age_hours > 0:
            self.age_hours.labels(cache_name=self.cache_name).observe(age_hours)
    
    def record_miss(self):
        """Record a cache miss."""
        self.misses.labels(cache_name=self.cache_name).inc()
    
    def record_eviction(self):
        """Record a cache eviction (overflow cleanup)."""
        self.evictions.labels(cache_name=self.cache_name).inc()
    
    def set_size(self, size_bytes: int, num_entries: int):
        """Update cache size metrics."""
        self.size_bytes.labels(cache_name=self.cache_name).set(size_bytes)
        self.entries.labels(cache_name=self.cache_name).set(num_entries)
    
    def hit_rate(self) -> float:
        """Calculate cache hit rate (hits / total requests)."""
        total = (
            self.hits.labels(cache_name=self.cache_name)._value.get() +
            self.misses.labels(cache_name=self.cache_name)._value.get()
        )
        if total == 0:
            return 0.0
        hits = self.hits.labels(cache_name=self.cache_name)._value.get()
        return hits / total
