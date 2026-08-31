"""
drift_report.py — Drift detection reports and alerting.

Generates comprehensive drift detection reports and formats alerts
for notification systems (Slack, email, GitHub issues).

Issue #38: No model drift detection - silent model degradation.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from src.tracking.drift_detector import DriftDetector
from src.tracking.store import ParquetPredictionStore
from src.config import CITIES
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DriftReport:
    """Generates drift detection reports for alerting.
    
    Produces hourly/daily reports of model performance across all
    city/horizon combinations and formats alerts for human consumption.
    """
    
    def __init__(
        self,
        store: Optional[ParquetPredictionStore] = None,
        detector: Optional[DriftDetector] = None
    ):
        """Initialize report generator.
        
        Args:
            store: PredictionStore instance (default: ParquetPredictionStore)
            detector: DriftDetector instance (default: standard thresholds)
        """
        self.store = store or ParquetPredictionStore()
        self.detector = detector or DriftDetector()
    
    def generate_hourly_report(self) -> Dict:
        """Generate report for last hour of predictions.
        
        Checks all city/horizon combinations for drift.
        
        Returns:
            dict: {
                timestamp: ISO datetime,
                window_hours: int,
                checks: {city_horizon_key: drift_result},
                drifted_count: int,
                total_checks: int,
                status: 'OK' | 'ALERT',
                summary: str
            }
        """
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'window_hours': self.detector.window_hours,
            'checks': {},
            'drifted_count': 0,
            'total_checks': 0,
            'status': 'OK'
        }
        
        try:
            # Load all predictions
            predictions_df = self.store.load_all()
            
            if predictions_df.empty:
                report['summary'] = 'No predictions in store'
                logger.warning('No predictions available for drift report')
                return report
            
            # Check each city x horizon combination
            cities = list(CITIES.keys())
            horizons = [24, 48, 72]
            
            for city in cities:
                for horizon in horizons:
                    key = f'{city}_{horizon}h'
                    
                    drift_result = self.detector.check_drift(
                        predictions_df,
                        horizon_h=horizon,
                        city=city
                    )
                    
                    report['checks'][key] = drift_result
                    report['total_checks'] += 1
                    
                    if drift_result.get('drifted'):
                        report['drifted_count'] += 1
            
            # Determine overall status
            report['status'] = 'ALERT' if report['drifted_count'] > 0 else 'OK'
            
            # Generate summary
            if report['drifted_count'] > 0:
                report['summary'] = (
                    f'⚠️ DRIFT DETECTED: {report["drifted_count"]} of '
                    f'{report["total_checks"]} checks drifted'
                )
            else:
                report['summary'] = (
                    f'✓ All {report["total_checks"]} checks passed'
                )
            
            logger.info(
                f'Drift report generated: {report["summary"]} '
                f'({report["timestamp"]})'
            )
        
        except Exception as e:
            logger.error(f'Error generating drift report: {e}', exc_info=True)
            report['status'] = 'ERROR'
            report['summary'] = f'Report generation failed: {str(e)}'
        
        return report
    
    def generate_daily_report(self) -> Dict:
        """Generate report for last 24 hours with trend analysis.
        
        Returns:
            dict: {
                timestamp: ISO datetime,
                summary: str,
                status: 'OK' | 'ALERT' | 'ERROR',
                checks: {...},
                trends: {city_horizon: [performance_by_day]},
                worst_performers: [{city, horizon, rmse, mae, accuracy}]
            }
        """
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'window_hours': 24,
            'summary': '',
            'status': 'OK',
            'checks': {},
            'trends': {},
            'worst_performers': []
        }
        
        try:
            predictions_df = self.store.load_all()
            
            if predictions_df.empty:
                report['summary'] = 'No predictions in store'
                return report
            
            # Run hourly report
            hourly = self.generate_hourly_report()
            report['checks'] = hourly['checks']
            report['drifted_count'] = hourly['drifted_count']
            report['total_checks'] = hourly['total_checks']
            
            # Collect trends
            cities = list(CITIES.keys())
            horizons = [24, 48, 72]
            worst_performers = []
            
            for city in cities:
                for horizon in horizons:
                    key = f'{city}_{horizon}h'
                    
                    # Get performance trend
                    trend = self.detector.get_performance_trend(
                        predictions_df,
                        horizon_h=horizon,
                        city=city,
                        periods=7
                    )
                    report['trends'][key] = trend
                    
                    # Track worst performers
                    if trend:
                        latest = trend[0]
                        worst_performers.append({
                            'city': city,
                            'horizon': horizon,
                            'rmse': latest['rmse'],
                            'mae': latest['mae'],
                            'accuracy': latest['accuracy'],
                            'count': latest['count']
                        })
            
            # Sort by RMSE (worst first)
            worst_performers.sort(key=lambda x: x['rmse'], reverse=True)
            report['worst_performers'] = worst_performers[:5]  # Top 5 worst
            
            # Determine status
            if report['drifted_count'] > 0:
                report['status'] = 'ALERT'
                report['summary'] = (
                    f'⚠️ ALERT: {report["drifted_count"]} drifted. '
                    f'Worst: {report["worst_performers"][0]["city"]} '
                    f'{report["worst_performers"][0]["horizon"]}h '
                    f'(RMSE={report["worst_performers"][0]["rmse"]:.1f})'
                )
            else:
                report['status'] = 'OK'
                report['summary'] = f'✓ All checks passed ({report["total_checks"]} monitors)'
        
        except Exception as e:
            logger.error(f'Error generating daily report: {e}', exc_info=True)
            report['status'] = 'ERROR'
            report['summary'] = f'Report generation failed: {str(e)}'
        
        return report
    
    def should_alert(self, report: Dict) -> bool:
        """Determine if alert should be sent based on report.
        
        Args:
            report: Output from generate_hourly_report()
        
        Returns:
            bool: True if any drift detected
        """
        return report.get('status') == 'ALERT'
    
    def format_alert_message(self, report: Dict) -> str:
        """Format drift report for alerting (Slack, email, etc.).
        
        Args:
            report: Output from generate_hourly_report() or generate_daily_report()
        
        Returns:
            str: Human-readable alert message
        """
        lines = ['🚨 MODEL DRIFT ALERT']
        lines.append(f"Timestamp: {report['timestamp']}")
        lines.append(f"Status: {report['status']}")
        lines.append(f"Drifted: {report.get('drifted_count', 0)}/{report.get('total_checks', 0)}")
        lines.append('')
        
        # List drifted checks
        drifted_checks = [
            (key, result) for key, result in report.get('checks', {}).items()
            if result.get('drifted')
        ]
        
        if drifted_checks:
            lines.append('❌ Drifted Predictions:')
            for key, result in sorted(drifted_checks):
                lines.append(f"  • {key}")
                lines.append(f"    {result['details']}")
        
        # Include worst performers if present
        if 'worst_performers' in report and report['worst_performers']:
            lines.append('')
            lines.append('📊 Worst Performers (by RMSE):')
            for perf in report['worst_performers'][:3]:
                lines.append(
                    f"  • {perf['city']} {perf['horizon']}h: "
                    f"RMSE={perf['rmse']:.1f}, MAE={perf['mae']:.1f}, "
                    f"Accuracy={perf['accuracy']:.1f}% (n={perf['count']})"
                )
        
        lines.append('')
        lines.append(f"Summary: {report.get('summary', 'Unknown')}")
        
        return '\n'.join(lines)
    
    def format_alert_json(self, report: Dict) -> str:
        """Format drift report as JSON (for APIs).
        
        Args:
            report: Drift report dict
        
        Returns:
            str: JSON-formatted report
        """
        return json.dumps(report, indent=2, default=str)
    
    def format_github_issue_body(self, report: Dict) -> str:
        """Format drift report for GitHub issue creation.
        
        Args:
            report: Output from generate_daily_report()
        
        Returns:
            str: Markdown-formatted issue body
        """
        lines = []
        lines.append(f'## Model Drift Detected - {report["timestamp"]}')
        lines.append('')
        lines.append(f'**Status:** {report["status"]}')
        lines.append(f'**Drifted:** {report.get("drifted_count", 0)}/{report.get("total_checks", 0)}')
        lines.append('')
        lines.append(report.get('summary', ''))
        lines.append('')
        
        # Worst performers table
        if 'worst_performers' in report and report['worst_performers']:
            lines.append('### Worst Performers')
            lines.append('')
            lines.append('| City | Horizon | RMSE | MAE | Accuracy | Count |')
            lines.append('|------|---------|------|-----|----------|-------|')
            for perf in report['worst_performers'][:5]:
                lines.append(
                    f"| {perf['city']} | {perf['horizon']}h | "
                    f"{perf['rmse']:.2f} | {perf['mae']:.2f} | "
                    f"{perf['accuracy']:.1f}% | {perf['count']} |"
                )
            lines.append('')
        
        # Drifted list
        drifted_checks = [
            (key, result) for key, result in report.get('checks', {}).items()
            if result.get('drifted')
        ]
        
        if drifted_checks:
            lines.append('### Drifted Checks')
            lines.append('')
            for key, result in sorted(drifted_checks):
                lines.append(f'- **{key}**: {result["details"]}')
            lines.append('')
        
        lines.append('## Recommended Actions')
        lines.append('')
        lines.append('1. Review prediction accuracy in production')
        lines.append('2. Check for data quality issues (Issue #37)')
        lines.append('3. Consider retraining the model')
        lines.append('4. Evaluate rolling back to previous model version')
        lines.append('')
        lines.append('---')
        lines.append(f'*Generated by drift detection system*')
        
        return '\n'.join(lines)


__all__ = ['DriftReport']
