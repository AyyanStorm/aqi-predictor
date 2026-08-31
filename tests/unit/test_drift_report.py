"""
test_drift_report.py — Unit tests for DriftReport class.

Tests drift detection reporting, alert formatting, and GitHub issue generation.

Issue #38: No model drift detection - silent model degradation.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from src.tracking.drift_report import DriftReport
from src.tracking.drift_detector import DriftDetector


@pytest.fixture
def mock_store():
    """Fixture: Mock prediction store."""
    store = Mock()
    store.load_all.return_value = pd.DataFrame(columns=[
        'pred_aqi', 'actual_aqi', 'created_at', 'city', 'horizon_h', 'model_version'
    ])
    return store


@pytest.fixture
def good_predictions_df():
    """Fixture: DataFrame with good (no-drift) predictions."""
    np.random.seed(42)
    predictions = []
    
    for city in ['Karachi', 'Lahore', 'Islamabad']:
        for horizon in [24, 48, 72]:
            for i in range(20):
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 3)
                
                predictions.append({
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                    'city': city,
                    'horizon_h': horizon,
                    'model_version': 'v12'
                })
    
    return pd.DataFrame(predictions)


@pytest.fixture
def mixed_predictions_df():
    """Fixture: DataFrame with some drifted predictions."""
    np.random.seed(43)
    predictions = []
    
    # Good cities
    for city in ['Karachi', 'Lahore']:
        for horizon in [24, 48, 72]:
            for i in range(20):
                actual = np.random.uniform(50, 150)
                pred = actual + np.random.normal(0, 3)
                
                predictions.append({
                    'pred_aqi': pred,
                    'actual_aqi': actual,
                    'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                    'city': city,
                    'horizon_h': horizon,
                    'model_version': 'v12'
                })
    
    # Bad city (drifted)
    for horizon in [24, 48, 72]:
        for i in range(20):
            predictions.append({
                'pred_aqi': 100,
                'actual_aqi': 50,  # Very bad predictions
                'created_at': datetime.now(timezone.utc) - timedelta(hours=i),
                'city': 'Islamabad',
                'horizon_h': horizon,
                'model_version': 'v12'
            })
    
    return pd.DataFrame(predictions)


@pytest.fixture
def drift_report(mock_store):
    """Fixture: DriftReport with mock store."""
    return DriftReport(store=mock_store)


class TestHourlyReportGeneration:
    """Test hourly drift report generation."""
    
    def test_generate_hourly_report_success(self, drift_report, good_predictions_df):
        """Should generate hourly report successfully."""
        drift_report.store.load_all.return_value = good_predictions_df
        
        report = drift_report.generate_hourly_report()
        
        assert 'timestamp' in report
        assert 'checks' in report
        assert 'drifted_count' in report
        assert 'total_checks' in report
        assert 'status' in report
        assert 'summary' in report
        assert report['status'] in ['OK', 'ALERT']
    
    def test_hourly_report_no_drift(self, drift_report, good_predictions_df):
        """Hourly report should show OK status when no drift."""
        drift_report.store.load_all.return_value = good_predictions_df
        
        report = drift_report.generate_hourly_report()
        
        assert report['status'] == 'OK'
        assert report['drifted_count'] == 0
        assert report['total_checks'] > 0
    
    def test_hourly_report_with_drift(self, drift_report, mixed_predictions_df):
        """Hourly report should show ALERT status when drift detected."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        
        report = drift_report.generate_hourly_report()
        
        assert report['status'] == 'ALERT'
        assert report['drifted_count'] > 0
        assert 'Islamabad' in str(report['checks'])
    
    def test_hourly_report_empty_store(self, drift_report):
        """Hourly report should handle empty store gracefully."""
        drift_report.store.load_all.return_value = pd.DataFrame(columns=[
            'pred_aqi', 'actual_aqi', 'created_at', 'city', 'horizon_h', 'model_version'
        ])
        
        report = drift_report.generate_hourly_report()
        
        assert report['status'] == 'OK'
        assert report['drifted_count'] == 0
        assert 'No predictions' in report['summary']


class TestDailyReportGeneration:
    """Test daily drift report with trends."""
    
    def test_generate_daily_report_success(self, drift_report, good_predictions_df):
        """Should generate daily report with trends."""
        drift_report.store.load_all.return_value = good_predictions_df
        
        report = drift_report.generate_daily_report()
        
        assert 'timestamp' in report
        assert 'status' in report
        assert 'summary' in report
        assert 'trends' in report
        assert 'worst_performers' in report
        assert isinstance(report['worst_performers'], list)
    
    def test_daily_report_contains_trends(self, drift_report, good_predictions_df):
        """Daily report should contain performance trends."""
        drift_report.store.load_all.return_value = good_predictions_df
        
        report = drift_report.generate_daily_report()
        
        assert len(report['trends']) > 0
        # Each trend should have date, rmse, mae, accuracy, count
        for key, trend_list in report['trends'].items():
            if trend_list:  # Only if trend exists
                for day in trend_list:
                    assert 'date' in day
                    assert 'rmse' in day
                    assert 'mae' in day
                    assert 'accuracy' in day
                    assert 'count' in day
    
    def test_daily_report_worst_performers(self, drift_report, mixed_predictions_df):
        """Daily report should identify worst performers."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        
        report = drift_report.generate_daily_report()
        
        # Should list worst performers by RMSE
        assert len(report['worst_performers']) > 0
        worst = report['worst_performers'][0]
        assert 'city' in worst
        assert 'horizon' in worst
        assert 'rmse' in worst
        assert 'mae' in worst
        assert 'accuracy' in worst


class TestAlertFormatting:
    """Test alert message formatting."""
    
    def test_should_alert_on_drift(self, drift_report, mixed_predictions_df):
        """should_alert should return True when drift detected."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_hourly_report()
        
        should_alert = drift_report.should_alert(report)
        
        assert should_alert == (report['status'] == 'ALERT')
    
    def test_should_not_alert_on_good_data(self, drift_report, good_predictions_df):
        """should_alert should return False when no drift."""
        drift_report.store.load_all.return_value = good_predictions_df
        report = drift_report.generate_hourly_report()
        
        should_alert = drift_report.should_alert(report)
        
        assert should_alert == False
    
    def test_format_alert_message(self, drift_report, mixed_predictions_df):
        """Alert message should be human-readable."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_hourly_report()
        
        message = drift_report.format_alert_message(report)
        
        assert isinstance(message, str)
        assert len(message) > 0
        assert 'MODEL DRIFT' in message or '✓' in message
    
    def test_alert_message_contains_key_info(self, drift_report, mixed_predictions_df):
        """Alert message should contain timestamp, status, and drifted count."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_hourly_report()
        
        message = drift_report.format_alert_message(report)
        
        assert 'Timestamp' in message
        assert 'Status' in message
        assert 'Drifted' in message
    
    def test_alert_message_with_drifted_checks(self, drift_report, mixed_predictions_df):
        """Alert message should list drifted checks."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_hourly_report()
        
        message = drift_report.format_alert_message(report)
        
        # If there are drifted checks, message should mention them
        if report.get('drifted_count', 0) > 0:
            assert 'Drifted' in message or 'Worst' in message


class TestJSONFormatting:
    """Test JSON alert formatting."""
    
    def test_format_alert_json(self, drift_report, good_predictions_df):
        """Should format report as valid JSON."""
        drift_report.store.load_all.return_value = good_predictions_df
        report = drift_report.generate_hourly_report()
        
        json_str = drift_report.format_alert_json(report)
        
        assert isinstance(json_str, str)
        # Verify it's valid JSON by parsing it
        import json
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
    
    def test_json_contains_all_keys(self, drift_report, good_predictions_df):
        """JSON should contain all report keys."""
        drift_report.store.load_all.return_value = good_predictions_df
        report = drift_report.generate_hourly_report()
        
        json_str = drift_report.format_alert_json(report)
        import json
        parsed = json.loads(json_str)
        
        # Should have key fields
        assert 'timestamp' in parsed or 'status' in parsed


class TestGitHubIssueFormatting:
    """Test GitHub issue body formatting."""
    
    def test_format_github_issue_body(self, drift_report, mixed_predictions_df):
        """Should format report as GitHub issue markdown."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_daily_report()
        
        body = drift_report.format_github_issue_body(report)
        
        assert isinstance(body, str)
        assert len(body) > 0
        assert 'Model Drift' in body
    
    def test_github_issue_contains_table(self, drift_report, mixed_predictions_df):
        """GitHub issue should contain worst performers table."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_daily_report()
        
        body = drift_report.format_github_issue_body(report)
        
        # Should have markdown table if there are worst performers
        if report['worst_performers']:
            assert '|' in body  # Markdown table format
    
    def test_github_issue_markdown_valid(self, drift_report, good_predictions_df):
        """GitHub issue body should be valid markdown."""
        drift_report.store.load_all.return_value = good_predictions_df
        report = drift_report.generate_daily_report()
        
        body = drift_report.format_github_issue_body(report)
        
        # Should have markdown headers
        assert '#' in body
        # Should have recommended actions section
        assert 'Recommended Actions' in body or 'actions' in body.lower()
    
    def test_github_issue_includes_drifted_checks(self, drift_report, mixed_predictions_df):
        """GitHub issue should list drifted checks if present."""
        drift_report.store.load_all.return_value = mixed_predictions_df
        report = drift_report.generate_daily_report()
        
        body = drift_report.format_github_issue_body(report)
        
        # If there are drifted checks, they should be listed
        if report.get('drifted_count', 0) > 0:
            assert 'Drifted Checks' in body or 'drifted' in body.lower()


class TestReportErrorHandling:
    """Test error handling in report generation."""
    
    def test_report_handles_store_error(self, drift_report):
        """Report should handle store errors gracefully."""
        drift_report.store.load_all.side_effect = Exception('Store error')
        
        report = drift_report.generate_hourly_report()
        
        assert report['status'] == 'ERROR'
        assert 'summary' in report
    
    def test_report_handles_missing_columns(self, drift_report):
        """Report should handle missing columns gracefully."""
        # DataFrame with missing required columns
        bad_df = pd.DataFrame({
            'pred_aqi': [100, 105],
            'actual_aqi': [100, 105]
        })
        drift_report.store.load_all.return_value = bad_df
        
        report = drift_report.generate_hourly_report()
        
        # Should handle gracefully
        assert 'status' in report
