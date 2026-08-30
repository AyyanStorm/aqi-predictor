"""
cache.py — Prediction caching layer with file persistence.

Stores last-known forecasts for fallback when API is unavailable.
Used by predict() to provide graceful degradation.

Issue #41: Multi-layer caching strategy with Prometheus metrics.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.utils.logger import get_logger
from src.utils.cache_metrics import CacheMetrics

logger = get_logger(__name__)


class PredictionCache:
    """
    Cache forecasts with file persistence and TTL.
    
    Enables graceful degradation: when the forecast API fails,
    return cached prediction from last successful request (if available).
    
    Caches are stored as JSON in .prediction_cache.json for persistence
    across application restarts.
    
    Issue #41: Includes Prometheus metrics (hit/miss, size) and automatic
    disk cleanup when cache grows beyond max_entries.
    """
    
    def __init__(self, cache_file=None, max_age_hours=24, max_entries=1000):
        """
        Initialize cache.
        
        Args:
            cache_file: Path to cache file (default: .prediction_cache.json)
            max_age_hours: Max age of cached predictions (default: 24h)
            max_entries: Max number of cached locations before cleanup (default: 1000)
        """
        self.cache_file = Path(cache_file) if cache_file else Path('.prediction_cache.json')
        self.max_age_hours = max_age_hours
        self.max_entries = max_entries
        self.metrics = CacheMetrics('prediction_cache')
    
    def get(self, lat, lon):
        """
        Retrieve cached prediction if within age limit.
        
        Args:
            lat: Latitude
            lon: Longitude
        
        Returns:
            Tuple[dict, float] or (None, None):
                - (prediction_data, age_hours) if cache hit and fresh
                - (None, None) if cache miss or expired
        """
        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)
        except FileNotFoundError:
            self.metrics.record_miss()
            return None, None
        except json.JSONDecodeError:
            logger.warning(f'Corrupted cache file: {self.cache_file}')
            self.metrics.record_miss()
            return None, None
        
        key = f"{lat},{lon}"
        
        if key not in cache:
            self.metrics.record_miss()
            return None, None
        
        cached_entry = cache[key]
        
        try:
            cached_at = datetime.fromisoformat(cached_entry['timestamp'])
            age_hours = (
                datetime.now(timezone.utc) - cached_at
            ).total_seconds() / 3600
            
            if age_hours < self.max_age_hours:
                logger.info(
                    f'Cache hit: lat={lat}, lon={lon}, age={age_hours:.1f}h'
                )
                self.metrics.record_hit(age_hours)
                self._update_size_metric()
                return cached_entry['data'], age_hours
            else:
                logger.info(
                    f'Cache expired: lat={lat}, lon={lon}, age={age_hours:.1f}h > {self.max_age_hours}h'
                )
                self.metrics.record_miss()
                return None, None
        
        except (KeyError, ValueError) as e:
            logger.warning(f'Invalid cache entry for {key}: {e}')
            self.metrics.record_miss()
            return None, None
    
    def set(self, lat, lon, data):
        """
        Cache prediction data with current timestamp.
        
        Args:
            lat: Latitude
            lon: Longitude
            data: Prediction data (dict)
        """
        cache = {}
        
        # Load existing cache
        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        key = f"{lat},{lon}"
        cache[key] = {
            'data': data,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Cleanup if over max_entries (remove oldest entries)
        if len(cache) > self.max_entries:
            cache = self._cleanup_oldest(cache)
        
        # Write back to disk
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache, f)
            logger.info(f'Cached prediction: lat={lat}, lon={lon}')
            self._update_size_metric()
        except Exception as e:
            logger.error(f'Failed to write cache: {e}')
    
    def clear(self):
        """Clear all cached predictions."""
        try:
            self.cache_file.unlink()
            logger.info('Cache cleared')
            self.metrics.set_size(0, 0)
        except FileNotFoundError:
            pass
    
    def _cleanup_oldest(self, cache: dict) -> dict:
        """
        Remove oldest entries when cache exceeds max_entries.
        
        Keeps the newest max_entries // 2 entries (50% reduction).
        Returns the cleaned cache dict.
        """
        # Sort by timestamp (oldest first)
        sorted_entries = sorted(
            cache.items(),
            key=lambda x: x[1].get('timestamp', '')
        )
        
        # Keep only the newest half
        keep_count = self.max_entries // 2
        cleaned = dict(sorted_entries[-keep_count:])
        
        evicted = len(cache) - len(cleaned)
        logger.info(f'Cache cleanup: evicted {evicted} oldest entries, '  
                   f'{len(cleaned)} remain')
        for _ in range(evicted):
            self.metrics.record_eviction()
        
        return cleaned
    
    def _update_size_metric(self):
        """Update Prometheus cache size and entry count metrics."""
        try:
            if self.cache_file.exists():
                size_bytes = os.path.getsize(self.cache_file)
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    num_entries = len(cache)
                self.metrics.set_size(size_bytes, num_entries)
        except Exception as e:
            logger.warning(f'Failed to update size metric: {e}')
