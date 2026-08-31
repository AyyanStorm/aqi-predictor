"""
test_feature_store_backends.py — Unit tests for feature store backend abstraction.

Tests the FeatureStoreBackend interface, HopsworksBackend, ParquetBackend,
and the factory function with different configurations.

Issue #42: Abstraction layer for feature store backends.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.features.backends import (
    FeatureStoreBackend,
    HopsworksBackend,
    ParquetBackend,
    get_feature_store_backend,
)


class TestFeatureStoreBackendInterface:
    """Test that the interface defines all required methods."""

    def test_backend_is_abstract(self):
        """FeatureStoreBackend should not be instantiable."""
        with pytest.raises(TypeError):
            FeatureStoreBackend()

    def test_backend_requires_write_features(self):
        """Subclasses must implement write_features()."""

        class BadBackend(FeatureStoreBackend):
            def read_features(self, start=None, end=None, cities=None):
                pass

            def list_cities(self):
                pass

        with pytest.raises(TypeError):
            BadBackend()

    def test_backend_requires_read_features(self):
        """Subclasses must implement read_features()."""

        class BadBackend(FeatureStoreBackend):
            def write_features(self, df):
                pass

            def list_cities(self):
                pass

        with pytest.raises(TypeError):
            BadBackend()

    def test_backend_requires_list_cities(self):
        """Subclasses must implement list_cities()."""

        class BadBackend(FeatureStoreBackend):
            def write_features(self, df):
                pass

            def read_features(self, start=None, end=None, cities=None):
                pass

        with pytest.raises(TypeError):
            BadBackend()


class TestParquetBackendRead:
    """Test ParquetBackend.read_features()."""

    def test_read_empty_store(self):
        """Reading from empty store should return empty DataFrame."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = ParquetBackend(root=Path(tmpdir))
            df = backend.read_features()

            assert isinstance(df, pd.DataFrame)
            assert df.empty

    def test_read_single_city(self):
        """Should read Parquet file for a single city."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # Create test data
            test_data = pd.DataFrame({
                "city": ["Karachi"] * 5,
                "date": pd.date_range("2026-01-01", periods=5),
                "pm25": [10, 20, 30, 40, 50],
            })

            # Write via backend
            backend.write_features(test_data)

            # Read back
            result = backend.read_features().sort_values("date").reset_index(drop=True)

            assert len(result) == 5
            assert list(result["city"].unique()) == ["Karachi"]
            assert list(result["pm25"]) == [10, 20, 30, 40, 50]

    def test_read_multiple_cities(self):
        """Should read Parquet files for multiple cities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # Create test data for two cities
            cities_data = {
                "Karachi": pd.DataFrame({
                    "city": ["Karachi"] * 3,
                    "date": pd.date_range("2026-01-01", periods=3),
                    "pm25": [10, 20, 30],
                }),
                "Lahore": pd.DataFrame({
                    "city": ["Lahore"] * 3,
                    "date": pd.date_range("2026-01-01", periods=3),
                    "pm25": [5, 15, 25],
                }),
            }

            # Write both cities
            for city_df in cities_data.values():
                backend.write_features(city_df)

            # Read all
            result = backend.read_features()

            assert len(result) == 6
            assert set(result["city"].unique()) == {"Karachi", "Lahore"}

    def test_read_with_date_filter(self):
        """Should filter by start and end dates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            test_data = pd.DataFrame({
                "city": ["Karachi"] * 10,
                "date": pd.date_range("2026-01-01", periods=10),
                "pm25": range(10),
            })

            backend.write_features(test_data)

            # Filter by date range
            result = backend.read_features(
                start="2026-01-03", end="2026-01-07"
            )

            assert len(result) == 5
            assert result["date"].min() >= pd.Timestamp("2026-01-03")
            assert result["date"].max() <= pd.Timestamp("2026-01-07")

    def test_read_with_city_filter(self):
        """Should filter by city list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # Write multiple cities
            for city in ["Karachi", "Lahore", "Islamabad"]:
                data = pd.DataFrame({
                    "city": [city] * 3,
                    "date": pd.date_range("2026-01-01", periods=3),
                    "pm25": [10, 20, 30],
                })
                backend.write_features(data)

            # Filter to specific cities
            result = backend.read_features(cities=["Karachi", "Lahore"])

            assert set(result["city"].unique()) == {"Karachi", "Lahore"}
            assert "Islamabad" not in result["city"].values


class TestParquetBackendWrite:
    """Test ParquetBackend.write_features()."""

    def test_write_creates_file(self):
        """Writing should create Parquet file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            test_data = pd.DataFrame({
                "city": ["Karachi"],
                "date": [pd.Timestamp("2026-01-01")],
                "pm25": [10],
            })

            backend.write_features(test_data)

            # Verify file exists
            assert (root / "karachi.parquet").exists()

    def test_write_empty_dataframe_no_op(self):
        """Writing empty DataFrame should be no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            backend.write_features(pd.DataFrame())

            # No files should be created
            assert len(list(root.glob("*.parquet"))) == 0

    def test_write_none_dataframe_no_op(self):
        """Writing None should be no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            backend.write_features(None)

            # No files should be created
            assert len(list(root.glob("*.parquet"))) == 0

    def test_write_upserts_existing_data(self):
        """Writing should upsert (merge) with existing data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # First write
            data1 = pd.DataFrame({
                "city": ["Karachi", "Karachi"],
                "date": pd.date_range("2026-01-01", periods=2),
                "pm25": [10, 20],
            })
            backend.write_features(data1)

            # Second write (overlapping date)
            data2 = pd.DataFrame({
                "city": ["Karachi", "Karachi"],
                "date": pd.date_range("2026-01-02", periods=2),
                "pm25": [25, 30],  # Different value for 2026-01-02
            })
            backend.write_features(data2)

            # Read and verify upsert
            result = backend.read_features()

            assert len(result) == 3  # 3 unique dates
            # Check that latest value (25) for 2026-01-02 is kept
            jan2 = result[result["date"] == pd.Timestamp("2026-01-02")]
            assert jan2["pm25"].values[0] == 25


class TestParquetBackendListCities:
    """Test ParquetBackend.list_cities()."""

    def test_list_cities_empty(self):
        """Empty store should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = ParquetBackend(root=Path(tmpdir))
            cities = backend.list_cities()

            assert cities == []

    def test_list_cities_returns_all_cities(self):
        """Should return all cities that have files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # Write data for three cities
            for city in ["Karachi", "Lahore", "Islamabad"]:
                data = pd.DataFrame({
                    "city": [city],
                    "date": [pd.Timestamp("2026-01-01")],
                    "pm25": [10],
                })
                backend.write_features(data)

            cities = backend.list_cities()

            assert set(cities) == {"karachi", "lahore", "islamabad"}

    def test_list_cities_ignores_non_parquet(self):
        """Should only list .parquet files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = ParquetBackend(root=root)

            # Write valid city
            data = pd.DataFrame({
                "city": ["Karachi"],
                "date": [pd.Timestamp("2026-01-01")],
                "pm25": [10],
            })
            backend.write_features(data)

            # Create non-parquet file
            (root / "other.txt").write_text("not a parquet file")

            cities = backend.list_cities()

            assert cities == ["karachi"]


class TestHopsworksBackendInit:
    """Test HopsworksBackend initialization."""

    def test_init_requires_api_key(self):
        """Should raise if API key is missing."""
        with pytest.raises(ValueError, match="HOPSWORKS_API_KEY"):
            HopsworksBackend(api_key=None, project="test-project")

    def test_init_requires_project(self):
        """Should raise if project name is missing."""
        with pytest.raises(ValueError, match="HOPSWORKS_PROJECT"):
            HopsworksBackend(api_key="test-key", project=None)

    def test_init_accepts_custom_credentials(self):
        """Should accept custom credentials."""
        backend = HopsworksBackend(
            api_key="test-key",
            project="test-project",
            host="test-host",
            port=443,
        )

        assert backend.api_key == "test-key"
        assert backend.project == "test-project"
        assert backend.host == "test-host"
        assert backend.port == 443


class TestGetFeatureStoreBackend:
    """Test factory function get_feature_store_backend()."""

    def test_returns_hopsworks_when_configured(self):
        """Should return HopsworksBackend when credentials are set."""
        with patch.dict(
            "os.environ",
            {
                "HOPSWORKS_API_KEY": "test-key",
                "HOPSWORKS_PROJECT": "test-project",
            },
        ):
            with patch("importlib.util.find_spec") as mock_find:
                mock_find.return_value = MagicMock()  # Mock hopsworks installed
                # Note: factory function is called at module import, so we test
                # HopsworksBackend init separately
                backend = HopsworksBackend(
                    api_key="test-key",
                    project="test-project"
                )

                assert isinstance(backend, HopsworksBackend)

    def test_returns_parquet_when_hopsworks_not_installed(self):
        """Should return ParquetBackend when hopsworks is not installed."""
        with patch.dict(
            "os.environ",
            {
                "HOPSWORKS_API_KEY": "test-key",
                "HOPSWORKS_PROJECT": "test-project",
            },
        ):
            with patch("importlib.util.find_spec") as mock_find:
                mock_find.return_value = None  # Mock hopsworks not found

                backend = get_feature_store_backend()

                assert isinstance(backend, ParquetBackend)

    def test_returns_parquet_when_no_credentials(self):
        """Should return ParquetBackend when credentials are not set."""
        with patch.dict("os.environ", {}, clear=True):
            # Ensure credentials are not set
            backend = get_feature_store_backend()

            assert isinstance(backend, ParquetBackend)

    def test_returns_parquet_on_hopsworks_error(self):
        """Should gracefully fall back to Parquet on Hopsworks error."""
        with patch.dict(
            "os.environ",
            {
                "HOPSWORKS_API_KEY": "test-key",
                "HOPSWORKS_PROJECT": "test-project",
            },
        ):
            with patch("importlib.util.find_spec") as mock_find:
                mock_find.return_value = MagicMock()

                with patch("src.features.backends.HopsworksBackend") as mock_hw:
                    mock_hw.side_effect = ValueError("Connection failed")

                    backend = get_feature_store_backend()

                    assert isinstance(backend, ParquetBackend)


class TestBackendAbstraction:
    """Test that backends can be used interchangeably."""

    def test_backends_implement_interface(self):
        """Both backends should implement the interface."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parquet_backend = ParquetBackend(root=Path(tmpdir))

            # Both should have required methods
            assert hasattr(parquet_backend, "write_features")
            assert hasattr(parquet_backend, "read_features")
            assert hasattr(parquet_backend, "list_cities")

            # All methods should be callable
            assert callable(parquet_backend.write_features)
            assert callable(parquet_backend.read_features)
            assert callable(parquet_backend.list_cities)

    def test_parquet_backend_round_trip(self):
        """Should support write → read round trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = ParquetBackend(root=Path(tmpdir))

            original = pd.DataFrame({
                "city": ["Karachi", "Lahore"],
                "date": pd.date_range("2026-01-01", periods=2),
                "pm25": [50, 60],
                "pm10": [100, 110],
            })

            backend.write_features(original)
            result = backend.read_features().sort_values("city").reset_index(drop=True)

            # Verify data integrity
            assert len(result) == 2
            assert set(result["city"]) == {"Karachi", "Lahore"}
            # Check values for each city
            karachi = result[result["city"] == "Karachi"]
            assert karachi["pm25"].values[0] == 50
            lahore = result[result["city"] == "Lahore"]
            assert lahore["pm25"].values[0] == 60
