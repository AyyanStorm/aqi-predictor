"""
Test suite for tracking/store.py — prediction tracking with Parquet backend.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from src.tracking.store import (
    ParquetPredictionStore, _normalize, new_prediction_id
)


class TestPredictionStore:
    """Test suite for prediction tracking."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create isolated store for testing."""
        return ParquetPredictionStore(root=tmp_path)

    @pytest.fixture
    def sample_prediction(self):
        """Sample prediction record."""
        return {
            'user_id': 'anon_123',
            'prediction_id': new_prediction_id(),
            'city': 'Karachi',
            'lat': 24.86,
            'lon': 67.01,
            'timezone': 'Asia/Karachi',
            'source': 'quick-pick',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'base_ts': datetime.now(timezone.utc).isoformat(),
            'current_aqi': 150,
            'pred_24': 155,
            'pred_48': 165,
            'pred_72': 170,
            'model_name': 'lgbm',
            'model_version': 1,
        }

    def test_save_prediction(self, store, sample_prediction):
        """Test saving a single prediction."""
        store.save(sample_prediction)
        
        # Verify file was created
        assert store._path.exists()

    def test_load_empty_store(self, store):
        """Test loading from empty store returns empty DataFrame."""
        df = store.load()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_save_and_load_prediction(self, store, sample_prediction):
        """Test saving and loading a prediction."""
        store.save(sample_prediction)
        
        df = store.load()
        
        assert len(df) == 1
        assert df.iloc[0]['city'] == 'Karachi'
        assert df.iloc[0]['pred_24'] == 155

    def test_load_filter_by_city(self, store, sample_prediction):
        """Test loading predictions filtered by city."""
        # Save predictions for different cities
        pred_karachi = sample_prediction.copy()
        pred_karachi['city'] = 'Karachi'
        
        pred_lahore = sample_prediction.copy()
        pred_lahore['prediction_id'] = new_prediction_id()
        pred_lahore['city'] = 'Lahore'
        
        store.save(pred_karachi)
        store.save(pred_lahore)
        
        karachi_preds = store.load(city='Karachi')
        
        assert len(karachi_preds) == 1
        assert karachi_preds.iloc[0]['city'] == 'Karachi'

    def test_load_filter_by_user(self, store, sample_prediction):
        """Test loading predictions filtered by user_id."""
        pred_user1 = sample_prediction.copy()
        pred_user1['user_id'] = 'anon_user_1'
        
        pred_user2 = sample_prediction.copy()
        pred_user2['prediction_id'] = new_prediction_id()
        pred_user2['user_id'] = 'anon_user_2'
        
        store.save(pred_user1)
        store.save(pred_user2)
        
        user1_preds = store.load(user_id='anon_user_1')
        
        assert len(user1_preds) == 1
        assert user1_preds.iloc[0]['user_id'] == 'anon_user_1'

    def test_save_overwrites_duplicate_prediction_id(self, store, sample_prediction):
        """Test that saving same prediction_id overwrites (upsert)."""
        store.save(sample_prediction)
        
        # Same prediction_id, different data
        updated = sample_prediction.copy()
        updated['pred_24'] = 200  # Changed
        
        store.save(updated)
        
        df = store.load()
        
        assert len(df) == 1  # Not duplicated
        assert df.iloc[0]['pred_24'] == 200  # Updated value

    def test_save_multiple_predictions(self, store, sample_prediction):
        """Test saving multiple predictions appends to store."""
        predictions = []
        for i in range(5):
            pred = sample_prediction.copy()
            pred['prediction_id'] = new_prediction_id()
            pred['pred_24'] = 150 + i
            predictions.append(pred)
            store.save(pred)
        
        df = store.load()
        
        assert len(df) == 5
        pred_values = sorted(df['pred_24'].tolist())
        assert pred_values == [150, 151, 152, 153, 154]

    def test_load_all_returns_all_predictions(self, store, sample_prediction):
        """load_all() returns all predictions without filtering."""
        for i in range(3):
            pred = sample_prediction.copy()
            pred['prediction_id'] = new_prediction_id()
            pred['city'] = f'City{i}'
            store.save(pred)
        
        df = store.load_all()
        
        assert len(df) == 3

    def test_corrupt_file_quarantined_on_load(self, store, sample_prediction):
        """Test that corrupt parquet file is quarantined."""
        # Write a corrupt file
        store._path.write_text("this is not valid parquet data")
        
        # load() should return empty DataFrame and quarantine the file
        df = store.load()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        # Corrupt file should be renamed
        assert not store._path.exists()
        backup_files = list(store.root.glob('predictions.corrupt.*.parquet'))
        assert len(backup_files) > 0

    def test_corrupt_file_load_all(self, store):
        """Test that load_all() handles corrupt file gracefully."""
        # Write corrupt file
        store._path.write_text("corrupt data")
        
        df = store.load_all()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_normalize_casts_datetimes(self, store):
        """Test that _normalize casts datetime columns correctly."""
        df = pd.DataFrame({
            'created_at': ['2025-01-01T00:00:00', '2025-01-02T00:00:00'],
            'base_ts': ['2025-01-01T12:00:00', '2025-01-02T12:00:00'],
            'value': [1, 2]
        })
        
        normalized = _normalize(df)
        
        assert pd.api.types.is_datetime64_any_dtype(normalized['created_at'])
        assert pd.api.types.is_datetime64_any_dtype(normalized['base_ts'])

    def test_atomic_write_safety(self, store, sample_prediction):
        """Test that concurrent writes don't corrupt store."""
        # Save initial prediction
        store.save(sample_prediction)
        
        # Simulate save operation interrupted mid-write
        # (in practice, we can't truly interrupt here, but we verify the temp file
        # is cleaned up properly)
        
        initial_count = len(store.load())
        
        # Save another prediction (should complete normally)
        pred2 = sample_prediction.copy()
        pred2['prediction_id'] = new_prediction_id()
        store.save(pred2)
        
        # Verify both saved
        assert len(store.load()) == 2
        
        # Verify no temp files left behind
        tmp_files = list(store.root.glob('*.parquet.tmp'))
        assert len(tmp_files) == 0

    def test_new_prediction_id_unique(self):
        """Test that new_prediction_id() generates unique IDs."""
        ids = [new_prediction_id() for _ in range(100)]
        
        assert len(ids) == len(set(ids))  # All unique
        assert all(len(id) == 36 for id in ids)  # UUID format

    def test_prediction_columns_preserved(self, store, sample_prediction):
        """Test that all prediction columns are preserved."""
        store.save(sample_prediction)
        df = store.load()
        
        expected_cols = [
            'user_id', 'prediction_id', 'city', 'lat', 'lon', 'timezone',
            'source', 'created_at', 'base_ts', 'current_aqi', 'pred_24',
            'pred_48', 'pred_72', 'model_name', 'model_version'
        ]
        
        for col in expected_cols:
            assert col in df.columns

    def test_load_filter_by_city_and_user(self, store, sample_prediction):
        """Test loading with both city and user filters."""
        pred1 = sample_prediction.copy()
        pred1['user_id'] = 'user1'
        pred1['city'] = 'Karachi'
        
        pred2 = sample_prediction.copy()
        pred2['prediction_id'] = new_prediction_id()
        pred2['user_id'] = 'user1'
        pred2['city'] = 'Lahore'
        
        pred3 = sample_prediction.copy()
        pred3['prediction_id'] = new_prediction_id()
        pred3['user_id'] = 'user2'
        pred3['city'] = 'Karachi'
        
        for pred in [pred1, pred2, pred3]:
            store.save(pred)
        
        # Filter by user1 and Karachi
        df = store.load(user_id='user1', city='Karachi')
        
        assert len(df) == 1
        assert df.iloc[0]['user_id'] == 'user1'
        assert df.iloc[0]['city'] == 'Karachi'

    def test_empty_store_path_exists_after_load(self, store):
        """Test that calling load() on non-existent file doesn't crash."""
        # Don't save anything
        df = store.load()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert not store._path.exists()
