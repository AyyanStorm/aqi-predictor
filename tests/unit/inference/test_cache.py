"""
test_cache.py — Unit tests for prediction caching layer.
"""

import pytest
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.inference.cache import PredictionCache


class TestPredictionCache:
    """Test suite for PredictionCache."""
    
    @pytest.fixture
    def cache(self, tmp_path):
        """Create isolated cache for testing."""
        cache_file = tmp_path / 'test_cache.json'
        return PredictionCache(cache_file=cache_file, max_age_hours=1)
    
    def test_cache_miss_on_empty_store(self, cache):
        """Cache returns None when no data stored."""
        data, age = cache.get(24.86, 67.01)
        assert data is None
        assert age is None
    
    def test_cache_hit_returns_data_and_age(self, cache):
        """Successful cache lookup returns data and age."""
        test_data = {'aqi': 150, 'forecast': {'24': 140}}
        cache.set(24.86, 67.01, test_data)
        
        data, age = cache.get(24.86, 67.01)
        
        assert data == test_data
        assert age is not None
        assert age < 1  # Should be very recent
    
    def test_cache_expires_after_ttl(self, cache):
        """Cache returns None when data expires."""
        test_data = {'aqi': 150}
        cache.set(24.86, 67.01, test_data)
        
        # Immediately should hit
        data, age = cache.get(24.86, 67.01)
        assert data is not None
        
        # Create new cache with 0s TTL
        short_ttl_cache = PredictionCache(
            cache_file=cache.cache_file,
            max_age_hours=0.0001  # ~0.36 seconds
        )
        
        # Wait for expiry
        time.sleep(0.5)
        
        # Should miss now
        data, age = short_ttl_cache.get(24.86, 67.01)
        assert data is None
    
    def test_cache_persists_to_disk(self, cache, tmp_path):
        """Cache data is written to disk."""
        test_data = {'aqi': 150}
        cache.set(24.86, 67.01, test_data)
        
        # Verify file exists and contains data
        assert cache.cache_file.exists()
        
        with open(cache.cache_file) as f:
            cached = json.load(f)
        
        assert '24.86,67.01' in cached
        assert cached['24.86,67.01']['data'] == test_data
    
    def test_cache_loads_from_disk(self, cache):
        """Cache loads existing data from disk."""
        test_data = {'aqi': 150}
        cache.set(24.86, 67.01, test_data)
        
        # Create new cache instance pointing to same file
        new_cache = PredictionCache(cache_file=cache.cache_file)
        
        data, age = new_cache.get(24.86, 67.01)
        
        assert data == test_data
    
    def test_cache_multiple_locations(self, cache):
        """Cache handles multiple locations independently."""
        data1 = {'aqi': 100, 'city': 'Karachi'}
        data2 = {'aqi': 200, 'city': 'Lahore'}
        
        cache.set(24.86, 67.01, data1)
        cache.set(31.55, 74.34, data2)
        
        # Retrieve each
        retrieved1, age1 = cache.get(24.86, 67.01)
        retrieved2, age2 = cache.get(31.55, 74.34)
        
        assert retrieved1 == data1
        assert retrieved2 == data2
    
    def test_cache_overwrites_old_data(self, cache):
        """Setting cache twice overwrites first value."""
        data1 = {'aqi': 100}
        data2 = {'aqi': 150}
        
        cache.set(24.86, 67.01, data1)
        cache.set(24.86, 67.01, data2)
        
        data, age = cache.get(24.86, 67.01)
        assert data == data2
    
    def test_cache_handles_corrupted_file(self, cache):
        """Cache gracefully handles corrupted JSON."""
        # Write invalid JSON
        with open(cache.cache_file, 'w') as f:
            f.write('{ invalid json }')
        
        # Should return None, not crash
        data, age = cache.get(24.86, 67.01)
        assert data is None
    
    def test_cache_coordinates_precision(self, cache):
        """Cache keys are rounded to 4 decimal places."""
        test_data = {'aqi': 150}
        
        # Set with high precision
        cache.set(24.860123, 67.010456, test_data)
        
        # Should retrieve with rounded coordinates
        data, age = cache.get(24.8601, 67.0105)
        assert data == test_data
    
    def test_cache_clear(self, cache):
        """Clear removes all cached data."""
        cache.set(24.86, 67.01, {'aqi': 150})
        cache.set(31.55, 74.34, {'aqi': 200})
        
        assert cache.cache_file.exists()
        
        cache.clear()
        
        assert not cache.cache_file.exists()
        
        # Should get None for any location
        data, age = cache.get(24.86, 67.01)
        assert data is None
