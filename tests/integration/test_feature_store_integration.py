"""
test_feature_store_integration.py — Integration tests for feature store module.

Tests the public API in src/features/feature_store.py and verifies backend
abstraction works end-to-end.

Issue #42: Abstraction layer for feature store backends.
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.features.backends import ParquetBackend
from src.features.feature_store import (
    write_features,
    read_features,
    list_cities,
)


@pytest.fixture
def parquet_store():
    """Fixture: ParquetBackend for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch the global backend to use test directory
        from src.features import backends
        original_backend = backends.feature_store_backend
        test_backend = ParquetBackend(root=Path(tmpdir))
        backends.feature_store_backend = test_backend
        
        yield test_backend
        
        # Restore original backend
        backends.feature_store_backend = original_backend


class TestFeatureStorePublicAPI:
    """Test the public API functions in feature_store.py."""

    def test_write_features_delegates_to_backend(self, parquet_store):
        """write_features() should call backend.write_features()."""
        test_data = pd.DataFrame({
            "city": ["Karachi"],
            "date": [pd.Timestamp("2026-01-01")],
            "pm25": [50],
        })

        # Patch the global backend
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            write_features(test_data)
            
            # Verify data was written
            result = parquet_store.read_features()
            assert len(result) == 1
            assert result.iloc[0]["city"] == "Karachi"
        finally:
            feature_store.feature_store_backend = original

    def test_read_features_delegates_to_backend(self, parquet_store):
        """read_features() should call backend.read_features()."""
        # Write test data directly to backend
        test_data = pd.DataFrame({
            "city": ["Karachi", "Lahore"],
            "date": pd.date_range("2026-01-01", periods=2),
            "pm25": [50, 60],
        })
        parquet_store.write_features(test_data)

        # Patch the global backend
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            result = read_features()
            
            assert len(result) == 2
            assert set(result["city"]) == {"Karachi", "Lahore"}
        finally:
            feature_store.feature_store_backend = original

    def test_read_features_with_filters(self, parquet_store):
        """read_features() should pass through filters to backend."""
        # Write test data
        test_data = pd.DataFrame({
            "city": ["Karachi"] * 5,
            "date": pd.date_range("2026-01-01", periods=5),
            "pm25": range(50, 55),
        })
        parquet_store.write_features(test_data)

        # Patch the global backend
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # Read with date filter
            result = read_features(
                start="2026-01-02",
                end="2026-01-04"
            )
            
            assert len(result) == 3
            assert result["date"].min() >= pd.Timestamp("2026-01-02")
            assert result["date"].max() <= pd.Timestamp("2026-01-04")
        finally:
            feature_store.feature_store_backend = original

    def test_list_cities_delegates_to_backend(self, parquet_store):
        """list_cities() should call backend.list_cities()."""
        # Write test data
        for city in ["Karachi", "Lahore", "Islamabad"]:
            test_data = pd.DataFrame({
                "city": [city],
                "date": [pd.Timestamp("2026-01-01")],
                "pm25": [50],
            })
            parquet_store.write_features(test_data)

        # Patch the global backend
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            cities = list_cities()
            
            assert set(cities) == {"karachi", "lahore", "islamabad"}
        finally:
            feature_store.feature_store_backend = original


class TestFeatureStoreWorkflow:
    """Test realistic feature store workflows."""

    def test_write_read_workflow(self, parquet_store):
        """Test complete write → read workflow."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # Create sample feature data
            original_data = pd.DataFrame({
                "city": ["Karachi"] * 24,
                "date": pd.date_range("2026-01-01", periods=24, freq="H"),
                "pm25": range(50, 74),
                "pm10": range(100, 124),
                "temperature": range(25, 49),
            })

            # Write features
            write_features(original_data)

            # Read all features
            all_features = read_features()
            assert len(all_features) == 24

            # Read with date range
            filtered = read_features(
                start="2026-01-01 06:00:00",
                end="2026-01-01 12:00:00"
            )
            assert len(filtered) == 7  # 6h to 12h inclusive

            # Read specific cities
            cities_result = read_features(cities=["Karachi"])
            assert all(cities_result["city"] == "Karachi")
        finally:
            feature_store.feature_store_backend = original

    def test_multi_city_workflow(self, parquet_store):
        """Test workflow with multiple cities."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # Write data for multiple cities
            for city in ["Karachi", "Lahore", "Islamabad"]:
                city_data = pd.DataFrame({
                    "city": [city] * 5,
                    "date": pd.date_range("2026-01-01", periods=5),
                    "pm25": range(50, 55),
                })
                write_features(city_data)

            # Verify all cities are present
            all_data = read_features()
            assert len(all_data) == 15  # 3 cities × 5 records

            cities = list_cities()
            assert len(cities) == 3

            # Read specific city
            karachi_data = read_features(cities=["Karachi"])
            assert len(karachi_data) == 5
            assert all(karachi_data["city"] == "Karachi")
        finally:
            feature_store.feature_store_backend = original

    def test_incremental_writes(self, parquet_store):
        """Test incremental writes (upsert behavior)."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # First batch
            batch1 = pd.DataFrame({
                "city": ["Karachi"] * 3,
                "date": pd.date_range("2026-01-01", periods=3),
                "pm25": [50, 60, 70],
            })
            write_features(batch1)

            # Second batch (overlapping date)
            batch2 = pd.DataFrame({
                "city": ["Karachi"] * 3,
                "date": pd.date_range("2026-01-02", periods=3),
                "pm25": [65, 75, 85],  # Different values for overlapping dates
            })
            write_features(batch2)

            # Read and verify upsert worked
            result = read_features().sort_values("date").reset_index(drop=True)

            # Should have 4 unique dates (1,2,3,4)
            assert len(result) == 4
            
            # Check that latest values are kept for overlapping dates
            jan2 = result[result["date"] == pd.Timestamp("2026-01-02")]
            assert jan2["pm25"].values[0] == 65  # Latest value
        finally:
            feature_store.feature_store_backend = original


class TestBackendSwitching:
    """Test that backends can be switched without code changes."""

    def test_api_independent_of_backend(self):
        """Public API should work regardless of backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = ParquetBackend(root=Path(tmpdir))

            test_data = pd.DataFrame({
                "city": ["Karachi"],
                "date": [pd.Timestamp("2026-01-01")],
                "pm25": [50],
            })

            # Use backend directly
            backend.write_features(test_data)
            result = backend.read_features()

            assert len(result) == 1
            assert result.iloc[0]["pm25"] == 50


class TestErrorHandling:
    """Test error handling in feature store operations."""

    def test_read_empty_store_returns_empty_df(self, parquet_store):
        """Reading from empty store should return empty DataFrame."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            result = read_features()
            
            assert isinstance(result, pd.DataFrame)
            assert result.empty
        finally:
            feature_store.feature_store_backend = original

    def test_write_empty_dataframe_is_noop(self, parquet_store):
        """Writing empty DataFrame should not crash."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # Should not raise
            write_features(pd.DataFrame())
            
            # Store should still be empty
            result = read_features()
            assert result.empty
        finally:
            feature_store.feature_store_backend = original

    def test_write_none_is_noop(self, parquet_store):
        """Writing None should not crash."""
        from src.features import feature_store
        original = feature_store.feature_store_backend
        feature_store.feature_store_backend = parquet_store
        
        try:
            # Should not raise
            write_features(None)
            
            # Store should still be empty
            result = read_features()
            assert result.empty
        finally:
            feature_store.feature_store_backend = original
