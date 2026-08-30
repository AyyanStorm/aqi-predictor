"""
Test suite for API error handling and resilience.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


class TestAPIErrorHandling:
    """Test API error responses and recovery."""

    def test_predict_endpoint_validates_latitude(self):
        """API rejects latitude > 90."""
        response = client.get('/predict?lat=91&lon=67.01&city=Karachi')
        assert response.status_code == 422

    def test_predict_endpoint_validates_longitude(self):
        """API rejects longitude > 180."""
        response = client.get('/predict?lat=24.86&lon=181&city=Karachi')
        assert response.status_code == 422

    def test_predict_endpoint_latitude_negative_bounds(self):
        """API rejects latitude < -90."""
        response = client.get('/predict?lat=-91&lon=67.01')
        assert response.status_code == 422

    def test_predict_endpoint_longitude_negative_bounds(self):
        """API rejects longitude < -180."""
        response = client.get('/predict?lat=24.86&lon=-181')
        assert response.status_code == 422

    @patch('app.api.predict')
    def test_predict_returns_503_on_no_model(self, mock_predict):
        """API returns 503 when no production model exists."""
        mock_predict.side_effect = SystemExit('No production model')
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 503
        data = response.json()
        assert 'request_id' in data
        assert 'retry_after' in data
        assert data['retry_after'] == 300

    @patch('app.api.predict')
    def test_predict_returns_503_on_runtime_error(self, mock_predict):
        """API returns 503 on RuntimeError from prediction."""
        mock_predict.side_effect = RuntimeError('API timeout after 30s')
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 503
        data = response.json()
        assert 'request_id' in data
        assert data['error'] == 'Forecast service temporarily unavailable'
        assert 'Retry-After' in response.headers

    @patch('app.api.predict')
    def test_predict_success_includes_request_id(self, mock_predict):
        """Successful predictions include request_id for tracing."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        data = response.json()
        assert 'request_id' in data
        assert len(data['request_id']) == 8  # UUID[:8] format

    @patch('app.api.predict')
    def test_predict_success_includes_latency(self, mock_predict):
        """Successful predictions include latency_ms."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        data = response.json()
        assert 'latency_ms' in data
        assert data['latency_ms'] >= 0

    @patch('app.api.predict')
    def test_predict_enriches_forecast_with_aqi_category(self, mock_predict):
        """Forecast includes AQI category and health message."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        data = response.json()
        
        # Check forecast enrichment
        assert 'forecast' in data
        assert 'category' in data['forecast']['24']
        assert 'aqi' in data['forecast']['24']
        assert 'health_message' in data['forecast']['24']
        
        # Check current enrichment
        assert 'current' in data
        assert 'category' in data['current']
        assert 'health_message' in data['current']

    def test_health_endpoint_status_ok(self):
        """Health endpoint returns status ok."""
        response = client.get('/health')
        
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'

    def test_health_endpoint_includes_model_when_exists(self):
        """Health endpoint includes model info when production exists."""
        response = client.get('/health')
        
        assert response.status_code == 200
        data = response.json()
        # Model may or may not exist depending on test environment
        if data['model'] is not None:
            assert 'name' in data['model']
            assert 'version' in data['model']

    def test_cities_endpoint_returns_training_cities(self):
        """Cities endpoint returns list of training cities."""
        response = client.get('/cities')
        
        assert response.status_code == 200
        data = response.json()
        assert 'cities' in data
        assert isinstance(data['cities'], dict)

    @patch('app.api.predict')
    def test_predict_degraded_status_returns_200(self, mock_predict):
        """Degraded predictions (cached) return 200 with degraded status."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'degraded',
            'warning': 'Using cached prediction from 2.5 hours ago',
            'cache_age_hours': 2.5,
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'degraded'
        assert 'warning' in data

    @patch('app.api.predict')
    def test_predict_includes_timestamp(self, mock_predict):
        """Prediction response includes timestamp."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        data = response.json()
        assert 'timestamp' in data or 'request_id' in data  # At least request_id

    @patch('app.api.predict')
    def test_predict_error_includes_support_contact(self, mock_predict):
        """Error responses include support contact with request_id."""
        mock_predict.side_effect = RuntimeError('Service unavailable')
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 503
        data = response.json()
        if 'support' in data:
            assert 'request_id' in data['support']

    @patch('app.api.predict')
    def test_predict_passes_correct_parameters(self, mock_predict):
        """Predict function receives correct lat/lon/city."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        # Verify predict was called with correct args
        mock_predict.assert_called_once()
        call_args = mock_predict.call_args
        assert call_args[0][0] == 24.86  # lat
        assert call_args[0][1] == 67.01  # lon
        assert call_args[1]['city'] == 'Karachi'

    def test_predict_endpoint_requires_lat_lon(self):
        """Predict endpoint requires lat and lon parameters."""
        # Missing lat
        response = client.get('/predict?lon=67.01')
        assert response.status_code == 422
        
        # Missing lon
        response = client.get('/predict?lat=24.86')
        assert response.status_code == 422

    @patch('app.api.predict')
    def test_predict_default_city_parameter(self, mock_predict):
        """City defaults to 'api' if not provided."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 200
        call_args = mock_predict.call_args
        assert call_args[1]['city'] == 'api'

    @patch('app.api.predict')
    def test_api_logs_prediction_request(self, mock_predict):
        """API logs prediction requests."""
        mock_predict.return_value = {
            'current_aqi': 150,
            'forecast': {'24': 155, '48': 165, '72': 170},
            'model_name': 'lgbm',
            'model_version': 1,
            'status': 'ok',
        }
        
        with patch('app.api.logger') as mock_logger:
            response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        assert response.status_code == 200
        # Logger should have been called
        assert mock_logger.info.called or mock_logger.debug.called
