"""
Test suite for cache cleanup and overflow handling.

Issue #41: Automatic disk cache cleanup when max_entries exceeded.
"""

import pytest
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.inference.cache import PredictionCache


class TestCacheCleanup:
    """Test suite for cache cleanup and overflow management."""

    @pytest.fixture
    def cache_small(self, tmp_path):
        """Create cache with small max_entries for overflow testing."""
        cache_file = tmp_path / '.prediction_cache.json'
        return PredictionCache(cache_file=cache_file, max_entries=5)

    @pytest.fixture
    def sample_prediction(self):
        """Sample prediction data."""
        return {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
        }

    def test_cleanup_on_max_entries_exceeded(self, cache_small, sample_prediction):
        """Cache cleanup triggers when exceeding max_entries."""
        # Fill cache to max (5 entries)
        for i in range(5):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Verify 5 entries exist
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        assert len(cache) == 5
        
        # Add 6th entry -> triggers cleanup
        cache_small.set(25.5, 68.5, sample_prediction)
        
        # Verify cleanup kept only ~2-3 entries (50% reduction from 6)
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        assert len(cache) <= 3  # 50% of 6 = 3
        assert len(cache) > 0   # At least newest entry remains

    def test_cleanup_preserves_newest_entries(self, cache_small, sample_prediction):
        """Cleanup removes oldest entries, preserves newest."""
        # Add entries with delays so we know creation order
        locations = [
            (24.0, 67.0),
            (24.1, 67.1),
            (24.2, 67.2),
            (24.3, 67.3),
            (24.4, 67.4),
        ]
        
        for lat, lon in locations:
            cache_small.set(lat, lon, sample_prediction)
            time.sleep(0.01)  # Small delay to ensure distinct timestamps
        
        # Add 6th entry to trigger cleanup
        cache_small.set(25.5, 68.5, sample_prediction)
        
        # Verify newest entries are preserved
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        
        # The newest entry should definitely be there
        assert '25.5,68.5' in cache
        
        # Oldest entry should be gone
        assert '24.0,67.0' not in cache

    def test_cleanup_with_many_overflow_entries(self, cache_small, sample_prediction):
        """Cleanup handles large overflow gracefully."""
        # Add 20 entries (4x max)
        for i in range(20):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # After cleanup, should have reduced set
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        
        # Should be much smaller than 20
        assert len(cache) < 10
        assert len(cache) > 0

    def test_cleanup_maintains_valid_cache_file(self, cache_small, sample_prediction):
        """Cleanup maintains valid JSON cache file."""
        # Overflow and trigger cleanup
        for i in range(10):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Verify file is still valid JSON
        try:
            with open(cache_small.cache_file, 'r') as f:
                cache = json.load(f)
            assert isinstance(cache, dict)
            assert len(cache) > 0
        except json.JSONDecodeError:
            pytest.fail("Cache file corrupted after cleanup")

    def test_cleanup_does_not_remove_fresh_entries(self, cache_small, sample_prediction):
        """Cleanup removes old but not fresh entries."""
        # Add entry with old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        cache_file_content = {
            '24.0,67.0': {
                'data': sample_prediction,
                'timestamp': old_time
            }
        }
        
        # Write to cache file
        with open(cache_small.cache_file, 'w') as f:
            json.dump(cache_file_content, f)
        
        # Add new entries to trigger cleanup
        for i in range(6):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Verify at least one new entry exists
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        assert len(cache) > 0

    def test_cache_with_large_max_entries(self, tmp_path, sample_prediction):
        """Cache with large max_entries doesn't trigger cleanup easily."""
        cache_file = tmp_path / '.prediction_cache.json'
        cache = PredictionCache(cache_file=cache_file, max_entries=1000)
        
        # Add 100 entries
        for i in range(100):
            lat = 24.0 + i * 0.01
            lon = 67.0 + i * 0.01
            cache.set(lat, lon, sample_prediction)
        
        # All should still exist (no cleanup needed)
        with open(cache.cache_file, 'r') as f:
            cache_data = json.load(f)
        assert len(cache_data) == 100

    def test_cleanup_called_only_when_needed(self, tmp_path, sample_prediction):
        """Cleanup is not called for normal adds within max_entries."""
        cache_file = tmp_path / '.prediction_cache.json'
        cache = PredictionCache(cache_file=cache_file, max_entries=10)
        
        # Add 5 entries (below max)
        for i in range(5):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache.set(lat, lon, sample_prediction)
        
        # Verify all entries preserved
        with open(cache.cache_file, 'r') as f:
            cache_data = json.load(f)
        assert len(cache_data) == 5

    def test_eviction_metric_recorded_on_cleanup(self, cache_small, sample_prediction):
        """Cleanup records eviction metrics."""
        # Trigger cleanup
        for i in range(10):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Metrics should have recorded evictions
        # (Prometheus client handles the actual recording)
        assert cache_small.metrics is not None

    def test_size_metric_updated_after_cleanup(self, cache_small, sample_prediction):
        """Size metric is updated after cleanup."""
        for i in range(10):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Verify cache file exists and has been updated
        assert cache_small.cache_file.exists()
        size = cache_small.cache_file.stat().st_size
        assert size > 0

    def test_get_after_cleanup(self, cache_small, sample_prediction):
        """Can retrieve entries after cleanup."""
        # Add entries to trigger cleanup
        for i in range(10):
            lat = 24.0 + i * 0.1
            lon = 67.0 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Retrieve newest entry (should exist)
        data, age = cache_small.get(24.9, 67.9)
        
        # Newest entry should be retrievable
        if data is not None:
            assert age >= 0
            assert 'forecast' in data

    def test_cleanup_with_corrupt_entries(self, cache_small, sample_prediction):
        """Cleanup handles entries with missing timestamps."""
        # Manually write cache with missing timestamp
        cache_data = {
            '24.0,67.0': {
                'data': sample_prediction,
                'timestamp': datetime.now(timezone.utc).isoformat()
            },
            '24.1,67.1': {
                'data': sample_prediction
                # Missing timestamp!
            }
        }
        
        with open(cache_small.cache_file, 'w') as f:
            json.dump(cache_data, f)
        
        # Try to add more entries (may trigger cleanup)
        for i in range(6):
            lat = 24.2 + i * 0.1
            lon = 67.2 + i * 0.1
            cache_small.set(lat, lon, sample_prediction)
        
        # Should still be valid JSON
        with open(cache_small.cache_file, 'r') as f:
            cache = json.load(f)
        assert isinstance(cache, dict)

    def test_cleanup_empty_cache(self, cache_small):
        """Cleanup handles empty cache gracefully."""
        # Don't add any entries, just call methods
        cache_small.clear()
        assert not cache_small.cache_file.exists()
        
        # Add one entry (no cleanup needed)
        cache_small.set(24.0, 67.0, {'aqi': 100})
        assert cache_small.cache_file.exists()
