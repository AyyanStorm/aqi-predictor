"""
Test suite for cache.py — prediction caching and graceful degradation.
"""

import pytest
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.inference.cache import PredictionCache


class TestPredictionCache:
    """Test suite for prediction caching."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create isolated cache for testing."""
        cache_file = tmp_path / '.prediction_cache.json'
        return PredictionCache(cache_file=cache_file, max_age_hours=24)

    @pytest.fixture
    def sample_prediction(self):
        """Sample prediction data."""
        return {
            'current_aqi': 150,
            'forecast': {
                '24': 155,
                '48': 165,
                '72': 170,
            },
            'model_name': 'lgbm',
            'model_version': 1,
        }

    def test_cache_initialization(self, cache):
        """Cache initializes without file."""
        assert cache.cache_file is not None
        assert not cache.cache_file.exists()

    def test_get_empty_cache(self, cache):
        """Getting from empty cache returns None."""
        data, age = cache.get(24.86, 67.01)
        
        assert data is None
        assert age is None

    def test_set_and_get_prediction(self, cache, sample_prediction):
        """Test saving and retrieving prediction."""
        cache.set(24.86, 67.01, sample_prediction)
        
        data, age = cache.get(24.86, 67.01)
        
        assert data == sample_prediction
        assert age >= 0
        assert age < 0.1  # Should be very fresh

    def test_cache_persists_to_file(self, cache, sample_prediction):
        """Cache data is written to disk."""
        cache.set(24.86, 67.01, sample_prediction)
        
        assert cache.cache_file.exists()
        
        # Verify file contents
        with open(cache.cache_file, 'r') as f:
            data = json.load(f)
        
        assert '24.86,67.01' in data

    def test_cache_file_reloaded_on_new_instance(self, tmp_path, sample_prediction):
        """Cache data survives to disk and can be reloaded."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # Create cache and save
        cache1 = PredictionCache(cache_file=cache_file)
        cache1.set(24.86, 67.01, sample_prediction)
        
        # Create new instance pointing to same file
        cache2 = PredictionCache(cache_file=cache_file)
        data, age = cache2.get(24.86, 67.01)
        
        assert data == sample_prediction

    def test_cache_expires_after_max_age(self, tmp_path, sample_prediction):
        """Cache returns None when data is older than max_age_hours."""
        cache_file = tmp_path / '.prediction_cache.json'
        # Very short max age: 0.1 seconds
        cache = PredictionCache(cache_file=cache_file, max_age_hours=0.00003)  # ~0.1 seconds
        
        cache.set(24.86, 67.01, sample_prediction)
        
        # Wait for expiry (more than 0.1 seconds)
        time.sleep(0.15)
        
        data, age = cache.get(24.86, 67.01)
        
        assert data is None
        assert age is None

    def test_cache_returns_age_in_hours(self, cache, sample_prediction):
        """Cache returns age in hours."""
        cache.set(24.86, 67.01, sample_prediction)
        
        time.sleep(0.1)  # Wait 100ms
        
        data, age = cache.get(24.86, 67.01)
        
        assert age is not None
        # Should be roughly 0.0001 to 0.001 hours (100ms)
        assert 0 < age < 0.01

    def test_multiple_locations_cached(self, cache, sample_prediction):
        """Cache stores multiple locations independently."""
        cache.set(24.86, 67.01, sample_prediction)
        
        pred_lahore = sample_prediction.copy()
        pred_lahore['current_aqi'] = 180
        cache.set(31.52, 74.36, pred_lahore)
        
        data_karachi, _ = cache.get(24.86, 67.01)
        data_lahore, _ = cache.get(31.52, 74.36)
        
        assert data_karachi['current_aqi'] == 150
        assert data_lahore['current_aqi'] == 180

    def test_cache_update_overwrites(self, cache, sample_prediction):
        """Setting same location overwrites old data."""
        cache.set(24.86, 67.01, sample_prediction)
        
        updated = sample_prediction.copy()
        updated['current_aqi'] = 200
        cache.set(24.86, 67.01, updated)
        
        data, _ = cache.get(24.86, 67.01)
        
        assert data['current_aqi'] == 200

    def test_cache_corrupt_file_handled(self, tmp_path):
        """Corrupt cache file doesn't crash get()."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # Write corrupt JSON
        cache_file.write_text("this is not valid json {")
        
        cache = PredictionCache(cache_file=cache_file)
        data, age = cache.get(24.86, 67.01)
        
        assert data is None
        assert age is None

    def test_cache_missing_timestamp_handled(self, tmp_path):
        """Cache entry without timestamp is gracefully handled."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # Write cache with missing timestamp
        cache_file.write_text(json.dumps({
            '24.86,67.01': {
                'data': {'aqi': 150}
                # missing 'timestamp'
            }
        }))
        
        cache = PredictionCache(cache_file=cache_file)
        data, age = cache.get(24.86, 67.01)
        
        assert data is None
        assert age is None

    def test_cache_invalid_timestamp_handled(self, tmp_path):
        """Cache entry with invalid timestamp is gracefully handled."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # Write cache with invalid timestamp
        cache_file.write_text(json.dumps({
            '24.86,67.01': {
                'data': {'aqi': 150},
                'timestamp': 'not-a-valid-iso-timestamp'
            }
        }))
        
        cache = PredictionCache(cache_file=cache_file)
        data, age = cache.get(24.86, 67.01)
        
        assert data is None
        assert age is None

    def test_cache_clear(self, cache, sample_prediction):
        """clear() removes cache file."""
        cache.set(24.86, 67.01, sample_prediction)
        assert cache.cache_file.exists()
        
        cache.clear()
        
        assert not cache.cache_file.exists()

    def test_cache_clear_nonexistent_file(self, cache):
        """clear() handles missing cache file gracefully."""
        # Should not raise
        cache.clear()
        assert True

    def test_cache_key_format(self, cache, sample_prediction):
        """Cache keys are formatted as 'lat,lon'."""
        cache.set(24.86, 67.01, sample_prediction)
        
        with open(cache.cache_file, 'r') as f:
            data = json.load(f)
        
        keys = list(data.keys())
        assert len(keys) == 1
        assert keys[0] == '24.86,67.01'

    def test_cache_negative_coordinates(self, cache, sample_prediction):
        """Cache handles negative coordinates."""
        cache.set(-33.87, 151.21, sample_prediction)
        
        data, age = cache.get(-33.87, 151.21)
        
        assert data == sample_prediction

    def test_cache_boundary_coordinates(self, cache, sample_prediction):
        """Cache handles boundary coordinates (poles, dateline)."""
        # North pole
        cache.set(90.0, 0.0, sample_prediction)
        data, _ = cache.get(90.0, 0.0)
        assert data == sample_prediction
        
        # Date line
        cache.set(0.0, 180.0, sample_prediction)
        data, _ = cache.get(0.0, 180.0)
        assert data == sample_prediction

    def test_cache_fresh_prediction_under_max_age(self, cache, sample_prediction):
        """Fresh prediction within max_age returns valid data."""
        cache.set(24.86, 67.01, sample_prediction)
        
        # Immediately retrieve
        data, age = cache.get(24.86, 67.01)
        
        assert data == sample_prediction
        assert age >= 0
        assert age < 1  # Less than 1 hour old

    def test_cache_edge_case_just_expired(self, tmp_path, sample_prediction):
        """Prediction just at or past max_age expires."""
        cache_file = tmp_path / '.prediction_cache.json'
        # Set max_age to 0.05 seconds (50ms)
        cache = PredictionCache(cache_file=cache_file, max_age_hours=0.00001389)  # ~50ms
        
        cache.set(24.86, 67.01, sample_prediction)
        
        # Sleep just over max_age (60ms > 50ms)
        time.sleep(0.06)
        
        data, age = cache.get(24.86, 67.01)
        assert data is None

    def test_cache_manual_timestamp(self, tmp_path):
        """Cache accepts manually set timestamps."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # Manually write cache with old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        cache_file.write_text(json.dumps({
            '24.86,67.01': {
                'data': {'aqi': 150},
                'timestamp': old_time
            }
        }))
        
        cache = PredictionCache(cache_file=cache_file, max_age_hours=24)
        data, age = cache.get(24.86, 67.01)
        
        # Should be expired
        assert data is None

    def test_cache_large_prediction_data(self, cache):
        """Cache handles large prediction data."""
        large_data = {
            'current_aqi': 150,
            'forecast': {str(i): i * 10 for i in range(1000)},
            'metadata': {f'key_{i}': f'value_{i}' for i in range(100)},
        }
        
        cache.set(24.86, 67.01, large_data)
        data, age = cache.get(24.86, 67.01)
        
        assert data == large_data

    def test_cache_special_characters_in_data(self, cache):
        """Cache handles special characters in data."""
        data = {
            'current_aqi': 150,
            'message': 'Testing 中文 العربية émojis 🎉',
            'unicode': '\u00e9\u00e0\u00fc',
        }
        
        cache.set(24.86, 67.01, data)
        retrieved, age = cache.get(24.86, 67.01)
        
        assert retrieved == data

    def test_cache_read_then_write_merges(self, cache, sample_prediction):
        """Cache read-modify-write preserves existing entries."""
        # Save first prediction
        cache.set(24.86, 67.01, sample_prediction)
        
        # Save different location
        pred_2 = sample_prediction.copy()
        pred_2['current_aqi'] = 200
        cache.set(31.52, 74.36, pred_2)
        
        # Verify both exist
        data1, _ = cache.get(24.86, 67.01)
        data2, _ = cache.get(31.52, 74.36)
        
        assert data1['current_aqi'] == 150
        assert data2['current_aqi'] == 200

    def test_different_max_ages_for_different_instances(self, tmp_path, sample_prediction):
        """Different cache instances can have different max_age_hours."""
        cache_file = tmp_path / '.prediction_cache.json'
        
        # cache1: very short TTL (0.05 seconds / 50ms)
        cache1 = PredictionCache(cache_file=cache_file, max_age_hours=0.00001389)
        # cache2: long TTL (1 hour)
        cache2 = PredictionCache(cache_file=cache_file, max_age_hours=1)
        
        cache1.set(24.86, 67.01, sample_prediction)
        
        # Sleep longer than cache1's max_age but less than cache2's
        time.sleep(0.1)
        
        # cache1 should see it as expired
        data1, _ = cache1.get(24.86, 67.01)
        # cache2 should see it as fresh
        data2, _ = cache2.get(24.86, 67.01)
        
        assert data1 is None
        assert data2 == sample_prediction
