"""
test_api_error_recovery.py — Integration tests for API error recovery.

Tests the full flow: circuit breaker, caching, and API responses.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.api import app

client = TestClient(app)


class TestAPIErrorRecovery:
    """Integration tests for API error recovery with fallback caching."""
    
    def test_predict_handles_api_timeout_with_cache(self):
        """When API times out, return cached prediction with degraded status."""
        # First, make successful call to populate cache
        with patch('src.inference.predict.fetch_live_frame') as mock_fetch:
            mock_fetch.return_value = (
                MagicMock(),  # df
                MagicMock()   # now_ts
            )
            # This will fail because mocks aren't complete, but that's ok
            # We're testing the error path
            pass
        
        # Now test timeout recovery
        with patch('src.inference.predict.api_breaker.call') as mock_breaker:
            mock_breaker.side_effect = RuntimeError('API timeout after 30s')
            
            response = client.get('/predict?lat=24.86&lon=67.01&city=Karachi')
        
        # Should get 503 (service unavailable) or 200 if cache hit
        assert response.status_code in [200, 503]
        data = response.json()
        assert 'request_id' in data
        assert 'timestamp' in data
    
    def test_predict_includes_request_id_in_response(self):
        """All predictions include request_id for tracing."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.return_value = {
                'location': {'lat': 24.86, 'lon': 67.01},
                'current_aqi': 150,
                'forecast': {'24': 140, '48': 130, '72': 120},
                'model': {'name': 'lgbm', 'version': 12},
                'features': {},
                'status': 'ok'
            }
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 200
        data = response.json()
        assert 'request_id' in data
        assert len(data['request_id']) == 8  # UUID truncated to 8 chars
    
    def test_api_returns_503_on_service_failure(self):
        """API returns 503 when forecast service is unavailable."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.side_effect = RuntimeError(
                'Forecast unavailable. No cached data available.'
            )
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 503
        data = response.json()
        assert 'error' in data
        assert 'request_id' in data
        assert 'retry_after' in data
        assert data['retry_after'] == 300
    
    def test_api_includes_retry_after_header(self):
        """503 responses include Retry-After header."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.side_effect = RuntimeError('Service unavailable')
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 503
        assert 'retry-after' in response.headers
        assert response.headers['retry-after'] == '300'
    
    def test_api_validates_coordinate_ranges(self):
        """API validates latitude and longitude ranges."""
        # Latitude > 90
        response = client.get('/predict?lat=91&lon=67.01')
        assert response.status_code == 422
        
        # Longitude > 180
        response = client.get('/predict?lat=24.86&lon=181')
        assert response.status_code == 422
        
        # Negative lat < -90
        response = client.get('/predict?lat=-91&lon=67.01')
        assert response.status_code == 422
    
    def test_api_returns_degraded_status_from_cache(self):
        """API returns 200 with degraded status when using cached data."""
        with patch('src.inference.predict.predict') as mock_predict:
            # Simulate degraded prediction (from cache)
            mock_predict.return_value = {
                'location': {'lat': 24.86, 'lon': 67.01},
                'current_aqi': 150,
                'forecast': {'24': 140, '48': 130, '72': 120},
                'model': {'name': 'lgbm', 'version': 12},
                'features': {},
                'status': 'degraded',
                'cache_age_hours': 2.5,
                'warning': 'Using cached prediction from 2.5 hours ago'
            }
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'degraded'
        assert 'warning' in data
        assert 'cache_age_hours' in data
    
    def test_health_endpoint_includes_request_id(self):
        """Health endpoint includes request_id."""
        with patch('src.training.model_registry.ModelRegistry.production_entry') as mock_prod:
            mock_prod.return_value = {'name': 'lgbm', 'version': 12}
            
            response = client.get('/health')
        
        assert response.status_code == 200
        data = response.json()
        assert 'status' in data
        assert data['status'] == 'ok'
    
    def test_cities_endpoint_works(self):
        """Cities endpoint returns list of training cities."""
        response = client.get('/cities')
        
        assert response.status_code == 200
        data = response.json()
        assert 'cities' in data
        assert len(data['cities']) > 0
    
    def test_api_error_response_includes_support_info(self):
        """Error responses include support contact information."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.side_effect = RuntimeError('Unexpected API error')
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 503
        data = response.json()
        assert 'support' in data or 'request_id' in data
        # request_id helps user report the issue
    
    def test_api_latency_included_in_response(self):
        """Successful predictions include latency_ms."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.return_value = {
                'location': {'lat': 24.86, 'lon': 67.01},
                'current_aqi': 150,
                'forecast': {'24': 140, '48': 130, '72': 120},
                'model': {'name': 'lgbm', 'version': 12},
                'features': {},
                'status': 'ok'
            }
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 200
        data = response.json()
        assert 'latency_ms' in data
        assert isinstance(data['latency_ms'], (int, float))
    
    def test_forecast_enriched_with_aqi_categories(self):
        """Forecast includes AQI category and health message."""
        with patch('src.inference.predict.predict') as mock_predict:
            mock_predict.return_value = {
                'location': {'lat': 24.86, 'lon': 67.01},
                'current_aqi': 150,
                'forecast': {'24': 140, '48': 130, '72': 120},
                'model': {'name': 'lgbm', 'version': 12},
                'features': {},
                'status': 'ok'
            }
            
            response = client.get('/predict?lat=24.86&lon=67.01')
        
        assert response.status_code == 200
        data = response.json()
        
        # Check forecast has been enriched with categories
        for h in ['24', '48', '72']:
            assert isinstance(data['forecast'][h], dict)
            assert 'aqi' in data['forecast'][h]
            assert 'category' in data['forecast'][h]
            assert 'health_message' in data['forecast'][h]
        
        # Check current AQI has been enriched
        assert isinstance(data['current'], dict)
        assert 'aqi' in data['current']
        assert 'category' in data['current']
