"""
Test suite for model_registry.py — versioning, promotion, and rollback.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from src.training.model_registry import (
    ModelRegistry, STATUS_PRODUCTION, STATUS_CANDIDATE, STATUS_ARCHIVED
)


class TestModelRegistry:
    """Test suite for model versioning and promotion logic."""

    @pytest.fixture
    def temp_registry_dir(self, tmp_path):
        """Create isolated registry for testing."""
        registry_dir = tmp_path / 'registry'
        registry_dir.mkdir()
        return registry_dir

    @pytest.fixture
    def registry(self, temp_registry_dir):
        """ModelRegistry instance pointing to temp directory."""
        return ModelRegistry(registry_dir=temp_registry_dir)

    @pytest.fixture
    def dummy_model(self):
        """A simple dummy model dict for testing."""
        return {
            24: "model_24h",
            48: "model_48h",
            72: "model_72h",
        }

    @pytest.fixture
    def dummy_metrics(self):
        """Dummy metrics dict matching horizons."""
        return {
            24: {"rmse": 17.6, "mae": 12.3, "r2": 0.75},
            48: {"rmse": 22.1, "mae": 15.8, "r2": 0.68},
            72: {"rmse": 25.4, "mae": 18.2, "r2": 0.61},
        }

    def test_registry_initialization(self, registry, temp_registry_dir):
        """Registry creates index file on first access."""
        assert registry.index_file.exists()
        
        # Index should have structure
        with open(registry.index_file, 'r') as f:
            data = json.load(f)
        assert 'versions' in data
        assert 'production' in data

    def test_register_candidate_model(self, registry, dummy_model, dummy_metrics):
        """Test registering a new candidate model."""
        version = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp', 'humidity', 'wind'],
            params={'n_estimators': 100, 'max_depth': 7},
            n_train_rows=5000,
            train_window={'start': '2025-01-01', 'end': '2025-08-01'},
            notes='Grid searched with cv=5'
        )
        
        assert version == 1
        
        # Verify in registry
        entry = registry.production('lgbm')
        assert entry is None  # Not promoted yet
        
        versions = registry.list_versions('lgbm')
        assert len(versions) == 1
        assert versions[0]['status'] == STATUS_CANDIDATE
        assert versions[0]['mean_rmse'] == pytest.approx(21.7, abs=0.1)

    def test_register_multiple_versions(self, registry, dummy_model, dummy_metrics):
        """Test registering multiple versions of same model."""
        for i in range(3):
            registry.register(
                name='lgbm',
                models=dummy_model,
                metrics=dummy_metrics,
                feature_cols=['temp', 'humidity', 'wind'],
            )
        
        versions = registry.list_versions('lgbm')
        assert len(versions) == 3
        assert [v['version'] for v in versions] == [3, 2, 1]  # newest first

    def test_promote_candidate_to_production(self, registry, dummy_model, dummy_metrics):
        """Test promoting a candidate to production."""
        version = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp', 'humidity'],
        )
        
        assert registry.production('lgbm') is None
        
        registry.promote('lgbm', version)
        
        entry = registry.production('lgbm')
        assert entry is not None
        assert entry['version'] == version
        assert entry['status'] == STATUS_PRODUCTION
        assert entry['promoted_at'] is not None

    def test_promote_non_existent_version_raises(self, registry):
        """Promoting non-existent version raises KeyError."""
        with pytest.raises(KeyError, match='No version'):
            registry.promote('lgbm', 999)

    def test_promote_if_better_passes_gate(self, registry, dummy_model):
        """Candidate RMSE < production RMSE → auto-promote."""
        # Register worse production
        worse_metrics = {
            24: {"rmse": 30.0, "mae": 20.0, "r2": 0.5},
            48: {"rmse": 35.0, "mae": 25.0, "r2": 0.4},
            72: {"rmse": 40.0, "mae": 30.0, "r2": 0.3},
        }
        
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=worse_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Register better candidate
        better_metrics = {
            24: {"rmse": 10.0, "mae": 8.0, "r2": 0.9},
            48: {"rmse": 15.0, "mae": 12.0, "r2": 0.85},
            72: {"rmse": 18.0, "mae": 14.0, "r2": 0.80},
        }
        v2 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=better_metrics,
            feature_cols=['temp'],
        )
        
        promoted = registry.promote_if_better('lgbm', v2)
        
        assert promoted is True
        assert registry.production('lgbm')['version'] == v2

    def test_promote_if_better_fails_gate(self, registry, dummy_model, dummy_metrics):
        """Candidate RMSE >= production RMSE → stay candidate."""
        # Register good production
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Register worse candidate
        worse_metrics = dummy_metrics.copy()
        worse_metrics[24]['rmse'] = 30.0
        worse_metrics[48]['rmse'] = 35.0
        worse_metrics[72]['rmse'] = 40.0
        
        v2 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=worse_metrics,
            feature_cols=['temp'],
        )
        
        promoted = registry.promote_if_better('lgbm', v2)
        
        assert promoted is False
        assert registry.production('lgbm')['version'] == v1
        assert registry.list_versions('lgbm')[0]['status'] == STATUS_CANDIDATE

    def test_promote_if_better_force_flag(self, registry, dummy_model, dummy_metrics):
        """force=True promotes regardless of metrics."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Worse candidate
        worse_metrics = {
            24: {"rmse": 30.0, "mae": 20.0, "r2": 0.5},
            48: {"rmse": 35.0, "mae": 25.0, "r2": 0.4},
            72: {"rmse": 40.0, "mae": 30.0, "r2": 0.3},
        }
        
        v2 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=worse_metrics,
            feature_cols=['temp'],
        )
        
        promoted = registry.promote_if_better('lgbm', v2, force=True)
        
        assert promoted is True
        assert registry.production('lgbm')['version'] == v2

    def test_promote_demotes_previous_production(self, registry, dummy_model, dummy_metrics):
        """Promoting new version demotes old to archived."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        assert registry.production('lgbm')['version'] == v1
        
        # Better metrics for v2
        better_metrics = {
            24: {"rmse": 10.0, "mae": 8.0, "r2": 0.9},
            48: {"rmse": 15.0, "mae": 12.0, "r2": 0.85},
            72: {"rmse": 18.0, "mae": 14.0, "r2": 0.80},
        }
        
        v2 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=better_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v2)
        
        # v1 should be archived
        v1_entry = [v for v in registry.list_versions('lgbm') if v['version'] == v1][0]
        assert v1_entry['status'] == STATUS_ARCHIVED
        assert registry.production('lgbm')['version'] == v2

    def test_rollback_to_previous_version(self, registry, dummy_model, dummy_metrics):
        """Rollback moves production back to previous version."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Better v2
        better_metrics = {
            24: {"rmse": 10.0, "mae": 8.0, "r2": 0.9},
            48: {"rmse": 15.0, "mae": 12.0, "r2": 0.85},
            72: {"rmse": 18.0, "mae": 14.0, "r2": 0.80},
        }
        v2 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=better_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v2)
        
        assert registry.production('lgbm')['version'] == v2
        
        # Rollback
        registry.rollback('lgbm')
        
        assert registry.production('lgbm')['version'] == v1

    def test_rollback_fails_without_history(self, registry, dummy_model, dummy_metrics):
        """Rollback raises error if no previous production."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Only one promotion in history
        with pytest.raises(ValueError, match='Cannot rollback'):
            registry.rollback('lgbm')

    def test_list_versions_newest_first(self, registry, dummy_model, dummy_metrics):
        """List returns versions newest first."""
        for _ in range(3):
            registry.register(
                name='lgbm',
                models=dummy_model,
                metrics=dummy_metrics,
                feature_cols=['temp'],
            )
        
        versions = registry.list_versions('lgbm')
        version_numbers = [v['version'] for v in versions]
        
        assert version_numbers == [3, 2, 1]

    def test_list_versions_filter_by_name(self, registry, dummy_model, dummy_metrics):
        """List filters by model name."""
        for name in ['lgbm', 'rf', 'ridge']:
            registry.register(
                name=name,
                models=dummy_model,
                metrics=dummy_metrics,
                feature_cols=['temp'],
            )
        
        lgbm_versions = registry.list_versions('lgbm')
        assert len(lgbm_versions) == 1
        assert lgbm_versions[0]['name'] == 'lgbm'

    def test_production_entry_returns_latest_promoted(self, registry, dummy_model, dummy_metrics):
        """production_entry() returns most recent production across all names."""
        # Promote lgbm_v1
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Promote rf_v1 later
        v2 = registry.register(
            name='rf',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('rf', v2)
        
        # Should return rf_v1 (more recently promoted)
        entry = registry.production_entry()
        assert entry['name'] == 'rf'
        assert entry['version'] == v2

    def test_production_entry_returns_none_when_empty(self, registry):
        """production_entry() returns None when no production exists."""
        assert registry.production_entry() is None

    def test_load_production_model(self, registry, dummy_model, dummy_metrics, tmp_path):
        """Load returns the serialized model dict."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        loaded, entry = registry.load('lgbm')
        
        assert loaded == dummy_model
        assert entry['version'] == v1
        assert entry['status'] == STATUS_PRODUCTION

    def test_load_specific_version(self, registry, dummy_model, dummy_metrics):
        """Load can retrieve a specific version even if not production."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        
        v2 = registry.register(
            name='lgbm',
            models={'24': 'other', '48': 'other', '72': 'other'},
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v2)
        
        # Load v1 (not production)
        loaded, entry = registry.load('lgbm', version=v1)
        assert entry['version'] == v1

    def test_load_raises_when_no_production(self, registry):
        """Load raises KeyError when no production version exists."""
        with pytest.raises(KeyError, match='No production model'):
            registry.load('nonexistent')

    def test_load_raises_when_artifact_missing(self, registry, dummy_model, dummy_metrics):
        """Load raises FileNotFoundError if artifact was deleted."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Delete the artifact
        artifact_file = registry.artifacts_dir / f"lgbm_v{v1}.joblib"
        artifact_file.unlink()
        
        with pytest.raises(FileNotFoundError, match='missing'):
            registry.load('lgbm')

    def test_registry_persists_to_disk(self, registry, dummy_model, dummy_metrics):
        """Registry data survives to disk and can be reloaded."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        # Load from disk directly
        with open(registry.index_file, 'r') as f:
            data = json.load(f)
        
        assert 'versions' in data
        assert len(data['versions']) == 1
        assert data['versions'][0]['status'] == STATUS_PRODUCTION

    def test_mean_rmse_calculated_correctly(self, registry):
        """mean_rmse is average of three horizon RMSEs."""
        metrics = {
            24: {"rmse": 20.0, "mae": 15.0, "r2": 0.7},
            48: {"rmse": 30.0, "mae": 22.0, "r2": 0.6},
            72: {"rmse": 40.0, "mae": 30.0, "r2": 0.5},
        }
        
        registry.register(
            name='lgbm',
            models={24: 'm1', 48: 'm2', 72: 'm3'},
            metrics=metrics,
            feature_cols=['temp'],
        )
        
        entry = registry.list_versions('lgbm')[0]
        expected_mean = (20.0 + 30.0 + 40.0) / 3
        assert entry['mean_rmse'] == pytest.approx(expected_mean)

    def test_status_human_readable(self, registry, dummy_model, dummy_metrics):
        """status() returns readable string representation."""
        v1 = registry.register(
            name='lgbm',
            models=dummy_model,
            metrics=dummy_metrics,
            feature_cols=['temp'],
        )
        registry.promote('lgbm', v1)
        
        status_str = registry.status()
        
        assert 'lgbm_v1' in status_str
        assert 'PRODUCTION' in status_str
        assert 'mean RMSE' in status_str
