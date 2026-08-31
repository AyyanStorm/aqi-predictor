"""
test_drift_detector.py — Unit tests for DriftDetector class.

Tests model performance drift detection across various scenarios:
accuracy degradation, threshold crossing, version comparison, etc.

Issue #38: No model drift detection - silent model degradation.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from src.tracking.drift_detector import DriftDetector


@pytest.fixture
def good_predictions():
    """Fixture: predictions with good accuracy (no drift)."""
    np.random.seed(42)
    predictions = []
    
    for i in range(50):
        actual = np.random.uniform(50, 150)
        pred = actual + np.random.normal(0, 3)  # Small noise, RMSE ~3
        
        predictions.append({
            'pred_aqi': pred,
            'actual_aqi': actual,
            'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
    
    return pd.DataFrame(predictions)


@pytest.fixture
def bad_predictions():
    """Fixture: predictions with poor accuracy (drifted)."""
    np.random.seed(43)
    predictions = []
    
    for i in range(50):
        actual = np.random.uniform(50, 150)
        pred = actual + np.random.normal(0, 30)  # Large noise, RMSE ~30
        
        predictions.append({
            'pred_aqi': pred,
            'actual_aqi': actual,
            'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
    
    return pd.DataFrame(predictions)


@pytest.fixture
def detector():
    """Fixture: DriftDetector with standard thresholds."""
    return DriftDetector(
        rmse_threshold=25.0,
        mae_threshold=20.0,
        window_hours=24,
        min_predictions=10,
        accuracy_threshold=70.0
    )


class TestFreshnessCheck:
    """Test drift detection on fresh, good predictions."""
    
    def test_good_predictions_no_drift(self, detector, good_predictions):
        """Good predictions should not be flagged as drifted."""
        result = detector.check_drift(good_predictions)
        
        assert result['drifted'] == False
        assert result['rmse'] is not None
        assert result['rmse'] < detector.rmse_threshold
        assert result['count'] > 0  # Should have some predictions within time window
    
    def test_returns_all_metrics(self, detector, good_predictions):
        """Result should include RMSE, MAE, accuracy."""
        result = detector.check_drift(good_predictions)
        
        assert 'rmse' in result
        assert 'mae' in result
        assert 'accuracy' in result
        assert 'count' in result
        assert 'details' in result
        assert all(v is not None for v in [result['rmse'], result['mae'], result['accuracy']])


class TestDriftDetection:
    """Test drift detection on degraded models."""
    
    def test_detects_rmse_drift(self, detector, bad_predictions):
        """Should detect drift when RMSE exceeds threshold."""
        result = detector.check_drift(bad_predictions)
        
        assert result['drifted'] == True
        assert result['rmse'] is not None
        assert result['rmse'] > detector.rmse_threshold
    
    def test_detects_mae_drift(self, detector):
        """Should detect drift when MAE exceeds threshold."""
        # Create predictions with high MAE (consistent large bias)
        predictions = pd.DataFrame({
            'pred_aqi': [100] * 30,
            'actual_aqi': [50] * 30,  # Consistent 50-point bias
            'created_at': [datetime.now(timezone.utc) - timedelta(hours=i) for i in range(30)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        result = detector.check_drift(predictions)
        
        assert result['drifted'] == True
        assert result['mae'] is not None
        assert result['mae'] > detector.mae_threshold
    
    def test_detects_accuracy_drift(self, detector):
        """Should detect drift when accuracy (within ±10) falls below threshold."""
        # Create predictions that are mostly >±10 away
        predictions = pd.DataFrame({
            'pred_aqi': [100, 100, 100, 100] * 15,
            'actual_aqi': [50, 60, 140, 150] * 15,  # All >±10 away
            'created_at': [datetime.now(timezone.utc) - timedelta(hours=i) for i in range(60)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        result = detector.check_drift(predictions)
        
        assert result['drifted'] == True
        assert result['accuracy'] is not None
        assert result['accuracy'] < detector.accuracy_threshold


class TestInsufficientData:
    """Test handling of edge cases with insufficient data."""
    
    def test_insufficient_predictions(self, detector):
        """Should not flag drift when predictions are too few."""
        predictions = pd.DataFrame({
            'pred_aqi': [100, 105],
            'actual_aqi': [100, 105],
            'created_at': [datetime.now(timezone.utc), datetime.now(timezone.utc) - timedelta(hours=1)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        result = detector.check_drift(predictions)
        
        assert result['drifted'] == False
        assert 'insufficient_data' in result['reason']
        assert result['rmse'] is None
    
    def test_insufficient_actuals(self, detector):
        """Should not flag drift when few actuals are available."""
        now = datetime.now(timezone.utc)
        predictions = pd.DataFrame({
            'pred_aqi': list(range(30)),
            'actual_aqi': [None] * 25 + list(range(5)),  # Only 5 actuals
            'created_at': [now - timedelta(hours=i) for i in range(30)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        result = detector.check_drift(predictions)
        
        assert result['drifted'] == False
        assert 'insufficient_actuals' in result['reason']
    
    def test_empty_dataframe(self, detector):
        """Should handle empty DataFrame gracefully."""
        predictions = pd.DataFrame(columns=['pred_aqi', 'actual_aqi', 'created_at', 'city', 'horizon_h', 'model_version'])
        
        result = detector.check_drift(predictions)
        
        assert result['drifted'] == False
        assert result['count'] == 0


class TestCityFiltering:
    """Test drift detection with city filtering."""
    
    def test_single_city_filter(self, detector, good_predictions):
        """Should filter by city."""
        # Create two cities with different accuracies
        karachi_good = good_predictions.copy()
        karachi_good['city'] = 'Karachi'
        
        # Create Lahore with poor predictions
        lahore_bad = pd.DataFrame({
            'pred_aqi': [100] * 30,
            'actual_aqi': [50] * 30,
            'created_at': [datetime.now(timezone.utc) - timedelta(hours=i) for i in range(30)],
            'city': 'Lahore',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        combined = pd.concat([karachi_good, lahore_bad], ignore_index=True)
        
        # Check Karachi (should be good)
        karachi_result = detector.check_drift(combined, city='Karachi')
        
        # Check Lahore (should be degraded)
        lahore_result = detector.check_drift(combined, city='Lahore')
        
        assert karachi_result['drifted'] == False
        assert lahore_result['drifted'] == True


class TestHorizonFiltering:
    """Test drift detection with horizon filtering."""
    
    def test_horizon_filtering(self, detector, good_predictions):
        """Should filter by horizon_h."""
        # Create good 24h horizon
        h24_good = good_predictions.copy()
        h24_good['horizon_h'] = 24
        
        # Create degraded 48h horizon
        h48_bad = pd.DataFrame({
            'pred_aqi': [100] * 30,
            'actual_aqi': [50] * 30,
            'created_at': [datetime.now(timezone.utc) - timedelta(hours=i) for i in range(30)],
            'city': 'Karachi',
            'horizon_h': 48,
            'model_version': 'v12'
        })
        
        combined = pd.concat([h24_good, h48_bad], ignore_index=True)
        
        # Check 24h (should be good)
        result_24h = detector.check_drift(combined, horizon_h=24)
        
        # Check 48h (should be degraded)
        result_48h = detector.check_drift(combined, horizon_h=48)
        
        assert result_24h['drifted'] == False
        assert result_48h['drifted'] == True


class TestTimeWindowFiltering:
    """Test drift detection with time window filtering."""
    
    def test_time_window_filter(self, detector):
        """Should filter by time window (since parameter)."""
        now = datetime.now(timezone.utc)
        
        # Recent good predictions
        recent_good = pd.DataFrame({
            'pred_aqi': [100] * 20,
            'actual_aqi': [100 + np.random.normal(0, 2) for _ in range(20)],
            'created_at': [now - timedelta(hours=i) for i in range(20)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        # Old bad predictions
        old_bad = pd.DataFrame({
            'pred_aqi': [100] * 20,
            'actual_aqi': [50] * 20,  # Very bad
            'created_at': [now - timedelta(days=10, hours=i) for i in range(20)],
            'city': 'Karachi',
            'horizon_h': 24,
            'model_version': 'v12'
        })
        
        combined = pd.concat([recent_good, old_bad], ignore_index=True)
        
        # Check recent window (should be good)
        since = now - timedelta(hours=24)
        result = detector.check_drift(combined, since=since)
        
        assert result['drifted'] == False
        assert result['count'] == 20


class TestModelVersionComparison:
    """Test model version comparison."""
    
    def test_compare_two_versions(self, detector, good_predictions):
        """Should compare RMSE/MAE across versions."""
        # Create mixed versions
        v11_preds = good_predictions.copy()
        v11_preds['model_version'] = 'v11'
        v11_preds['actual_aqi'] = v11_preds['actual_aqi'] + np.random.normal(0, 25)  # Worse
        
        v12_preds = good_predictions.copy()
        v12_preds['model_version'] = 'v12'
        
        combined = pd.concat([v11_preds, v12_preds], ignore_index=True)
        
        comparison = detector.compare_model_versions(combined)
        
        assert 'v11' in comparison
        assert 'v12' in comparison
        assert comparison['v11']['rmse'] > comparison['v12']['rmse']
    
    def test_version_comparison_metrics(self, detector, good_predictions):
        """Version comparison should include all metrics."""
        good_predictions['model_version'] = 'v12'
        
        comparison = detector.compare_model_versions(good_predictions)
        
        for version, metrics in comparison.items():
            assert 'rmse' in metrics
            assert 'mae' in metrics
            assert 'accuracy' in metrics
            assert 'count' in metrics
            assert 'drifted' in metrics


class TestPerformanceTrend:
    """Test performance trend analysis."""
    
    def test_get_trend_7_days(self, detector):
        """Should get performance trend over 7 days."""
        now = datetime.now(timezone.utc).date()
        predictions = []
        
        for day_offset in range(7):
            date = now - timedelta(days=day_offset)
            for i in range(20):
                ts = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
                ts = ts + timedelta(hours=i)
                
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 5)
                
                predictions.append({
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': ts,
                    'city': 'Karachi',
                    'horizon_h': 24,
                    'model_version': 'v12'
                })
        
        df = pd.DataFrame(predictions)
        
        trend = detector.get_performance_trend(df, periods=7)
        
        assert len(trend) == 7
        assert all('date' in t for t in trend)
        assert all('rmse' in t for t in trend)
        assert all('mae' in t for t in trend)
        assert all('accuracy' in t for t in trend)
    
    def test_trend_sorted_by_date(self, detector):
        """Trend should be sorted by date (newest first)."""
        now = datetime.now(timezone.utc).date()
        predictions = []
        
        for day_offset in range(5):
            date = now - timedelta(days=day_offset)
            for i in range(15):
                ts = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
                ts = ts + timedelta(hours=i)
                
                predictions.append({
                    'pred_aqi': 100 + np.random.normal(0, 5),
                    'actual_aqi': 100 + np.random.normal(0, 5),
                    'created_at': ts,
                    'city': 'Karachi',
                    'horizon_h': 24,
                    'model_version': 'v12'
                })
        
        df = pd.DataFrame(predictions)
        trend = detector.get_performance_trend(df, periods=5)
        
        # Should be sorted newest first
        dates = [t['date'] for t in trend]
        assert dates == sorted(dates, reverse=True)
