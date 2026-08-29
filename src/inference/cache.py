"""
cache.py — Prediction caching layer with file persistence.

Stores last-known forecasts for fallback when API is unavailable.
Used by predict() to provide graceful degradation.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PredictionCache:
    """
    Cache forecasts with file persistence and TTL.
    
    Enables graceful degradation: when the forecast API fails,
    return cached prediction from last successful request (if available).
    
    Caches are stored as JSON in .prediction_cache.json for persistence
    across application restarts.
    """
    
    def __init__(self, cache_file=None, max_age_hours=24):
        """
        Initialize cache.
        
        Args:
            cache_file: Path to cache file (default: .prediction_cache.json)
            max_age_hours: Max age of cached predictions (default: 24h)
        """
        self.cache_file = Path(cache_file) if cache_file else Path('.prediction_cache.json')
        self.max_age_hours = max_age_hours
    
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
            return None, None
        except json.JSONDecodeError:
            logger.warning(f'Corrupted cache file: {self.cache_file}')
            return None, None
        
        key = f"{lat},{lon}"
        
        if key not in cache:
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
                return cached_entry['data'], age_hours
            else:
                logger.info(
                    f'Cache expired: lat={lat}, lon={lon}, age={age_hours:.1f}h > {self.max_age_hours}h'
                )
                return None, None
        
        except (KeyError, ValueError) as e:
            logger.warning(f'Invalid cache entry for {key}: {e}')
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
        
        # Write back to disk
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache, f)
            logger.info(f'Cached prediction: lat={lat}, lon={lon}')
        except Exception as e:
            logger.error(f'Failed to write cache: {e}')
    
    def clear(self):
        """Clear all cached predictions."""
        try:
            self.cache_file.unlink()
            logger.info('Cache cleared')
        except FileNotFoundError:
            pass
