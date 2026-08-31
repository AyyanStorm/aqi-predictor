"""
test_drift_detection_integration.py — Integration tests for complete drift detection flow.

Tests end-to-end model drift detection: loading predictions, analyzing,
generating reports, and formatting alerts.

Issue #38: No model drift detection - silent model degradation.
"""

import pytest
import pandas as pd
import numpy as np
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from src.tracking.drift_detector import DriftDetector
from src.tracking.drift_report import DriftReport
from src.tracking.store import ParquetPredictionStore
from src.config import CITIES


@pytest.fixture
def temp_tracking_dir():
    """Fixture: Temporary directory for test predictions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_store(temp_tracking_dir):
    """Fixture: ParquetPredictionStore with test data directory."""
    return ParquetPredictionStore(root=temp_tracking_dir)


@pytest.fixture
def good_predictions(test_store):
    """Fixture: Save good predictions to store."""
    np.random.seed(42)
    
    for city in list(CITIES.keys())[:3]:  # Use 3 cities for testing
        for horizon in [24, 48, 72]:
            for i in range(25):
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 3)  # Small error
                
                record = {
                    'prediction_id': f'{city}_{horizon}_{i}',
                    'city': city,
                    'horizon_h': horizon,
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                    'model_version': 'v12',
                    'user_id': 'test_user',
                    'lat': 0.0,
                    'lon': 0.0,
                    'timezone': 'UTC',
                    'source': 'test',
                    'base_ts': datetime.now(timezone.utc),
                    'current_aqi': 100
                }
                test_store.save(record)
    
    return test_store


@pytest.fixture
def degraded_predictions(test_store):
    """Fixture: Save degraded predictions (with drift)."""
    np.random.seed(43)
    
    # Good cities
    for city in list(CITIES.keys())[:2]:
        for horizon in [24, 48, 72]:
            for i in range(25):
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 3)
                
                record = {
                    'prediction_id': f'{city}_{horizon}_{i}',
                    'city': city,
                    'horizon_h': horizon,
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                    'model_version': 'v12',
                    'user_id': 'test_user',
                    'lat': 0.0,
                    'lon': 0.0,
                    'timezone': 'UTC',
                    'source': 'test',
                    'base_ts': datetime.now(timezone.utc),
                    'current_aqi': 100
                }
                test_store.save(record)
    
    # Degraded city
    bad_city = list(CITIES.keys())[2]
    for horizon in [24, 48, 72]:
        for i in range(25):
            record = {
                'prediction_id': f'{bad_city}_{horizon}_{i}',
                'city': bad_city,
                'horizon_h': horizon,
                'pred_aqi': 100,
                'actual_aqi': 50,  # Large consistent error
                'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                'model_version': 'v12',
                'user_id': 'test_user',
                'lat': 0.0,
                'lon': 0.0,
                'timezone': 'UTC',
                'source': 'test',
                'base_ts': datetime.now(timezone.utc),
                'current_aqi': 100
            }
            test_store.save(record)
    
    return test_store


class TestDriftDetectionFlow:
    """Test complete drift detection flow."""
    
    def test_load_predictions_from_store(self, good_predictions):
        """Should load predictions from store."""
        df = good_predictions.load_all()
        
        assert not df.empty
        assert 'pred_aqi' in df.columns
        assert 'actual_aqi' in df.columns
        assert 'city' in df.columns
        assert len(df) > 0
    
    def test_run_drift_detector_on_good_data(self, good_predictions):
        """Drift detector should find no drift in good data."""
        df = good_predictions.load_all()
        detector = DriftDetector()
        
        result = detector.check_drift(df)
        
        assert result['drifted'] == False
        assert result['rmse'] is not None
        assert result['rmse'] < detector.rmse_threshold
    
    def test_run_drift_detector_on_degraded_data(self, degraded_predictions):
        """Drift detector should detect drift in degraded data."""
        df = degraded_predictions.load_all()
        detector = DriftDetector()
        
        # Check specific city that's degraded
        bad_city = list(CITIES.keys())[2]
        result = detector.check_drift(df, city=bad_city)
        
        assert result['drifted'] == True
        assert result['rmse'] is not None
        assert result['rmse'] > detector.rmse_threshold
    
    def test_generate_hourly_report_from_store(self, good_predictions):
        """Should generate hourly report from store."""
        report = DriftReport(store=good_predictions)
        hourly = report.generate_hourly_report()
        
        assert hourly['status'] in ['OK', 'ALERT']
        assert hourly['drifted_count'] >= 0
        assert hourly['total_checks'] > 0
        assert len(hourly['checks']) > 0
    
    def test_generate_daily_report_from_store(self, good_predictions):
        """Should generate daily report with trends."""
        report = DriftReport(store=good_predictions)
        daily = report.generate_daily_report()
        
        assert 'trends' in daily
        assert 'worst_performers' in daily
        assert isinstance(daily['worst_performers'], list)
    
    def test_detect_drift_and_alert(self, degraded_predictions):
        """Should detect drift and format alert."""
        report = DriftReport(store=degraded_predictions)
        hourly = report.generate_hourly_report()
        
        # Should have some drifted checks
        should_alert = report.should_alert(hourly)
        
        if hourly['drifted_count'] > 0:
            assert should_alert == True
        
        # Should format alert message
        message = report.format_alert_message(hourly)
        assert isinstance(message, str)
        assert len(message) > 0


class TestModelVersionComparison:
    """Test model version comparison flow."""
    
    def test_compare_v11_vs_v12(self, temp_tracking_dir):
        """Should compare performance across model versions."""
        store = ParquetPredictionStore(root=temp_tracking_dir)
        np.random.seed(44)
        
        # Save v11 predictions (worse)
        for i in range(20):
            actual = np.random.uniform(50, 150)
            pred = actual + np.random.normal(0, 25)  # Worse accuracy
            
            record = {
                'prediction_id': f'v11_{i}',
                'city': 'Karachi',
                'horizon_h': 24,
                'pred_aqi': pred,
                'actual_aqi': actual,
                'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                'model_version': 'v11',
                'user_id': 'test_user',
                'lat': 0.0,
                'lon': 0.0,
                'timezone': 'UTC',
                'source': 'test',
                'base_ts': datetime.now(timezone.utc),
                'current_aqi': 100
            }
            store.save(record)
        
        # Save v12 predictions (better)
        for i in range(20):
            actual = np.random.uniform(50, 150)
            pred = actual + np.random.normal(0, 3)  # Better accuracy
            
            record = {
                'prediction_id': f'v12_{i}',
                'city': 'Karachi',
                'horizon_h': 24,
                'pred_aqi': pred,
                'actual_aqi': actual,
                'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                'model_version': 'v12',
                'user_id': 'test_user',
                'lat': 0.0,
                'lon': 0.0,
                'timezone': 'UTC',
                'source': 'test',
                'base_ts': datetime.now(timezone.utc),
                'current_aqi': 100
            }
            store.save(record)
        
        # Compare versions
        df = store.load_all()
        detector = DriftDetector()
        comparison = detector.compare_model_versions(df, city='Karachi')
        
        assert 'v11' in comparison
        assert 'v12' in comparison
        assert comparison['v12']['rmse'] < comparison['v11']['rmse']


class TestPerformanceTrendAnalysis:
    """Test performance trend analysis over time."""
    
    def test_get_7day_trend(self, temp_tracking_dir):
        """Should get 7-day performance trend."""
        store = ParquetPredictionStore(root=temp_tracking_dir)
        np.random.seed(45)
        
        now = datetime.now(timezone.utc)
        
        # Create 7 days of predictions
        for day_offset in range(7):
            date = now - timedelta(days=day_offset)
            for i in range(15):
                ts = date.replace(hour=i)
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 3)
                
                record = {
                    'prediction_id': f'day{day_offset}_{i}',
                    'city': 'Karachi',
                    'horizon_h': 24,
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': ts,
                    'model_version': 'v12',
                    'user_id': 'test_user',
                    'lat': 0.0,
                    'lon': 0.0,
                    'timezone': 'UTC',
                    'source': 'test',
                    'base_ts': ts,
                    'current_aqi': 100
                }
                store.save(record)
        
        # Get trend
        df = store.load_all()
        detector = DriftDetector()
        trend = detector.get_performance_trend(df, city='Karachi', periods=7)
        
        assert len(trend) > 0
        assert len(trend) <= 7
        # Trend should be sorted by date (newest first)
        dates = [t['date'] for t in trend]
        assert dates == sorted(dates, reverse=True)


class TestAlertFormatsIntegration:
    """Test alert format generation end-to-end."""
    
    def test_json_alert_is_valid(self, degraded_predictions):
        """JSON alert should be valid and parseable."""
        report = DriftReport(store=degraded_predictions)
        hourly = report.generate_hourly_report()
        
        json_str = report.format_alert_json(hourly)
        parsed = json.loads(json_str)
        
        assert isinstance(parsed, dict)
        assert 'timestamp' in parsed or 'status' in parsed
    
    def test_github_issue_body_is_valid_markdown(self, degraded_predictions):
        """GitHub issue body should be valid markdown."""
        report = DriftReport(store=degraded_predictions)
        daily = report.generate_daily_report()
        
        body = report.format_github_issue_body(daily)
        
        # Should have markdown headers
        assert '#' in body
        # Should have tables if worst performers exist
        if daily['worst_performers']:
            assert '|' in body
        # Should be non-empty
        assert len(body) > 50
    
    def test_alert_message_readability(self, degraded_predictions):
        """Alert message should be human-readable."""
        report = DriftReport(store=degraded_predictions)
        hourly = report.generate_hourly_report()
        
        message = report.format_alert_message(hourly)
        
        # Should have good structure
        lines = message.split('\n')
        assert len(lines) > 3
        # Should not have excessive empty lines
        empty_lines = sum(1 for line in lines if not line.strip())
        assert empty_lines < len(lines) / 2


class TestEndToEndWorkflow:
    """Test complete end-to-end drift detection workflow."""
    
    def test_full_workflow_good_data(self, good_predictions):
        """Full workflow with good data should result in OK status."""
        # 1. Load predictions
        df = good_predictions.load_all()
        assert not df.empty
        
        # 2. Run detector
        detector = DriftDetector()
        result = detector.check_drift(df)
        assert not result['drifted']
        
        # 3. Generate reports
        reporter = DriftReport(store=good_predictions)
        hourly = reporter.generate_hourly_report()
        daily = reporter.generate_daily_report()
        
        assert hourly['status'] == 'OK'
        assert daily['status'] == 'OK'
        
        # 4. No alert needed
        assert not reporter.should_alert(hourly)
    
    def test_full_workflow_degraded_data(self, degraded_predictions):
        """Full workflow with degraded data should trigger alert."""
        # 1. Load predictions
        df = degraded_predictions.load_all()
        assert not df.empty
        
        # 2. Run detector on degraded city
        detector = DriftDetector()
        bad_city = list(CITIES.keys())[2]
        result = detector.check_drift(df, city=bad_city)
        assert result['drifted']
        
        # 3. Generate reports
        reporter = DriftReport(store=degraded_predictions)
        hourly = reporter.generate_hourly_report()
        daily = reporter.generate_daily_report()
        
        # 4. Should have alert status if drift detected
        if hourly['drifted_count'] > 0:
            assert hourly['status'] == 'ALERT'
            assert reporter.should_alert(hourly)
            
            # 5. Should format alerts
            message = reporter.format_alert_message(hourly)
            json_alert = reporter.format_alert_json(hourly)
            github_issue = reporter.format_github_issue_body(daily)
            
            assert len(message) > 0
            assert len(json_alert) > 0
            assert len(github_issue) > 0
