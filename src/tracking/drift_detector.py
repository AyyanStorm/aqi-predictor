"""
drift_detector.py — Model performance drift detection in production.

Detects when model accuracy degrades below acceptable thresholds,
enabling proactive alerts and model rollback decisions.

Issue #38: No model drift detection - silent model degradation.
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DriftDetector:
    """Detects model performance degradation in production.
    
    Monitors RMSE, MAE, and prediction accuracy over time windows
    to identify when production models have drifted below acceptable
    performance thresholds.
    """
    
    def __init__(
        self,
        rmse_threshold: float = 25.0,
        mae_threshold: float = 20.0,
        window_hours: int = 24,
        min_predictions: int = 10,
        accuracy_threshold: float = 70.0  # % within 10 AQI points
    ):
        """Initialize drift detector with thresholds.
        
        Args:
            rmse_threshold: RMSE error threshold (default 25)
            mae_threshold: MAE error threshold (default 20)
            window_hours: Time window for checking drift (default 24h)
            min_predictions: Minimum predictions to trigger check (default 10)
            accuracy_threshold: Min % predictions within ±10 AQI (default 70%)
        """
        self.rmse_threshold = rmse_threshold
        self.mae_threshold = mae_threshold
        self.window_hours = window_hours
        self.min_predictions = min_predictions
        self.accuracy_threshold = accuracy_threshold
    
    def check_drift(
        self,
        predictions_df: pd.DataFrame,
        horizon_h: int = 24,
        city: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> Dict:
        """Check for model drift in recent predictions.
        
        Args:
            predictions_df: DataFrame with columns: pred_aqi, actual_aqi, created_at, city, model_version
            horizon_h: Forecast horizon (24, 48, or 72 hours)
            city: Optional city filter (if None, checks all cities)
            since: Optional start datetime (if None, uses window_hours)
        
        Returns:
            dict: {
                drifted: bool,
                rmse: float or None,
                mae: float or None,
                accuracy: float or None,  # % within ±10
                count: int,
                details: str,
                reason: str (if not drifted)
            }
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=self.window_hours)
        
        # Filter by time window
        window_df = predictions_df.copy()
        if 'created_at' in window_df.columns:
            # Convert to datetime with UTC timezone
            window_df['created_at'] = pd.to_datetime(window_df['created_at'], utc=True)
            # Ensure since is timezone-aware
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            window_df = window_df[window_df['created_at'] >= pd.Timestamp(since)].copy()
        
        # Filter by city if specified
        if city is not None and 'city' in predictions_df.columns:
            window_df = window_df[window_df['city'] == city]
        
        # Filter by horizon if column exists
        if 'horizon_h' in window_df.columns:
            window_df = window_df[window_df['horizon_h'] == horizon_h]
        
        # Handle empty DataFrame
        if window_df.empty:
            return {
                'drifted': False,
                'reason': 'insufficient_data (0 < {})'.format(self.min_predictions),
                'rmse': None,
                'mae': None,
                'accuracy': None,
                'count': 0,
                'details': 'No predictions in window'
            }
        
        # Check minimum predictions
        if len(window_df) < self.min_predictions:
            return {
                'drifted': False,
                'reason': f'insufficient_data ({len(window_df)} < {self.min_predictions})',
                'rmse': None,
                'mae': None,
                'accuracy': None,
                'count': len(window_df),
                'details': f'Only {len(window_df)} predictions in window, need {self.min_predictions}'
            }
        
        # Get predictions with actual values
        has_actual = window_df['actual_aqi'].notna()
        actual_df = window_df[has_actual].copy()
        
        if len(actual_df) < self.min_predictions:
            return {
                'drifted': False,
                'reason': f'insufficient_actuals ({len(actual_df)} < {self.min_predictions})',
                'rmse': None,
                'mae': None,
                'accuracy': None,
                'count': len(actual_df),
                'details': f'Only {len(actual_df)} predictions with actuals, need {self.min_predictions}'
            }
        
        # Compute metrics
        pred_aqi = actual_df['pred_aqi'].values.astype(float)
        actual_aqi = actual_df['actual_aqi'].values.astype(float)
        
        # RMSE
        rmse = float(np.sqrt(np.mean((pred_aqi - actual_aqi) ** 2)))
        
        # MAE
        mae = float(np.mean(np.abs(pred_aqi - actual_aqi)))
        
        # Accuracy: % within ±10 AQI
        within_tolerance = np.abs(pred_aqi - actual_aqi) <= 10
        accuracy = float(within_tolerance.sum() / len(actual_aqi) * 100)
        
        # Determine if drifted
        drifted = (rmse > self.rmse_threshold or 
                  mae > self.mae_threshold or 
                  accuracy < self.accuracy_threshold)
        
        details = (
            f'RMSE={rmse:.1f} (threshold: {self.rmse_threshold}), '
            f'MAE={mae:.1f} (threshold: {self.mae_threshold}), '
            f'Accuracy={accuracy:.1f}% within ±10 (threshold: {self.accuracy_threshold}%), '
            f'n={len(actual_df)} predictions'
        )
        
        if drifted:
            logger.error(
                f'Model drift detected: {details} | '
                f'city={city or "all"}, horizon={horizon_h}h'
            )
        
        return {
            'drifted': drifted,
            'rmse': rmse,
            'mae': mae,
            'accuracy': accuracy,
            'count': len(actual_df),
            'details': details
        }
    
    def compare_model_versions(
        self,
        predictions_df: pd.DataFrame,
        horizon_h: int = 24,
        city: Optional[str] = None
    ) -> Dict[str, Dict]:
        """Compare accuracy across model versions.
        
        Args:
            predictions_df: DataFrame with columns: pred_aqi, actual_aqi, model_version, city
            horizon_h: Forecast horizon
            city: Optional city filter
        
        Returns:
            dict: {
                model_version: {
                    rmse: float,
                    mae: float,
                    accuracy: float,  # % within ±10
                    count: int,
                    drifted: bool
                }
            }
        """
        # Filter by city
        if city is not None and 'city' in predictions_df.columns:
            df = predictions_df[predictions_df['city'] == city].copy()
        else:
            df = predictions_df.copy()
        
        # Filter by horizon
        if 'horizon_h' in df.columns:
            df = df[df['horizon_h'] == horizon_h]
        
        # Group by model version
        by_model = {}
        
        if 'model_version' not in df.columns:
            logger.warning('model_version column not found in predictions DataFrame')
            return {}
        
        for model_ver, group_df in df.groupby('model_version'):
            # Get predictions with actuals
            has_actual = group_df['actual_aqi'].notna()
            actual_group = group_df[has_actual].copy()
            
            if len(actual_group) == 0:
                continue
            
            pred_aqi = actual_group['pred_aqi'].values.astype(float)
            actual_aqi = actual_group['actual_aqi'].values.astype(float)
            
            rmse = float(np.sqrt(np.mean((pred_aqi - actual_aqi) ** 2)))
            mae = float(np.mean(np.abs(pred_aqi - actual_aqi)))
            
            within_tolerance = np.abs(pred_aqi - actual_aqi) <= 10
            accuracy = float(within_tolerance.sum() / len(actual_aqi) * 100)
            
            # Check if this version has drifted
            drifted = (rmse > self.rmse_threshold or 
                      mae > self.mae_threshold or 
                      accuracy < self.accuracy_threshold)
            
            by_model[str(model_ver)] = {
                'rmse': rmse,
                'mae': mae,
                'accuracy': accuracy,
                'count': len(actual_group),
                'drifted': drifted
            }
        
        return by_model
    
    def get_performance_trend(
        self,
        predictions_df: pd.DataFrame,
        horizon_h: int = 24,
        city: Optional[str] = None,
        periods: int = 7
    ) -> List[Dict]:
        """Get performance metrics by day over past N periods.
        
        Args:
            predictions_df: DataFrame with predictions
            horizon_h: Forecast horizon
            city: Optional city filter
            periods: Number of days to analyze (default 7)
        
        Returns:
            list: [{date, rmse, mae, accuracy, count}, ...]
        """
        # Filter
        df = predictions_df.copy()
        if city is not None and 'city' in df.columns:
            df = df[df['city'] == city]
        if 'horizon_h' in df.columns:
            df = df[df['horizon_h'] == horizon_h]
        
        if 'created_at' not in df.columns:
            logger.warning('created_at column not found')
            return []
        
        df['created_at'] = pd.to_datetime(df['created_at'], utc=True)
        df['date'] = df['created_at'].dt.date
        
        trend = []
        now = datetime.now(timezone.utc).date()
        
        for i in range(periods):
            date = now - timedelta(days=i)
            day_df = df[df['date'] == date]
            
            if len(day_df) == 0:
                continue
            
            has_actual = day_df['actual_aqi'].notna()
            actual_day = day_df[has_actual]
            
            if len(actual_day) == 0:
                continue
            
            pred_aqi = actual_day['pred_aqi'].values.astype(float)
            actual_aqi = actual_day['actual_aqi'].values.astype(float)
            
            rmse = float(np.sqrt(np.mean((pred_aqi - actual_aqi) ** 2)))
            mae = float(np.mean(np.abs(pred_aqi - actual_aqi)))
            
            within_tolerance = np.abs(pred_aqi - actual_aqi) <= 10
            accuracy = float(within_tolerance.sum() / len(actual_aqi) * 100)
            
            trend.append({
                'date': str(date),
                'rmse': rmse,
                'mae': mae,
                'accuracy': accuracy,
                'count': len(actual_day)
            })
        
        return sorted(trend, key=lambda x: x['date'], reverse=True)


__all__ = ['DriftDetector']
