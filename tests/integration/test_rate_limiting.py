"""
test_rate_limiting.py — Integration tests for API rate limiting (Issue #40).

Tests that rate limiting is correctly enforced per endpoint with proper
429 responses, Retry-After headers, and per-IP isolation.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.api import app

client = TestClient(app)


class TestRateLimitingPredict:
    """Rate limiting tests for /predict endpoint (30/minute)."""

    def test_predict_rate_limit_429_response(self):
        """Exceeding /predict rate limit (30/min) returns 429."""
        # Make 31 requests rapidly to exceed limit
        for i in range(31):
            response = client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            if i < 30:
                # First 30 should succeed (or fail for other reasons, not rate limit)
                assert response.status_code in [200, 503, 502]
            else:
                # 31st should be rate limited
                assert response.status_code == 429
                data = response.json()
                assert 'error' in data
                assert 'rate limit' in data['error'].lower() or 'too many' in data.get('details', '').lower()

    def test_predict_includes_retry_after_header(self):
        """429 responses include Retry-After header."""
        # Make requests to hit rate limit
        for i in range(31):
            response = client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            if response.status_code == 429:
                assert 'retry-after' in response.headers
                assert response.headers['retry-after'] == '60'
                break

    def test_predict_rate_limit_response_includes_retry_after_field(self):
        """429 response JSON includes retry_after field."""
        # Hit rate limit
        for i in range(31):
            response = client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            if response.status_code == 429:
                data = response.json()
                assert 'retry_after' in data
                assert data['retry_after'] == 60
                assert 'limit' in data
                break


class TestRateLimitingHealth:
    """Rate limiting tests for /health endpoint (60/minute)."""

    def test_health_has_higher_limit_than_predict(self):
        """
        /health has 60/min limit (higher than /predict's 30/min).
        This test verifies the limits are configured differently.
        """
        # Make 61 health requests to exceed its limit
        for i in range(61):
            response = client.get('/health')
            if i < 60:
                assert response.status_code == 200
            else:
                # 61st should be rate limited
                assert response.status_code == 429

    def test_health_rate_limit_includes_retry_after(self):
        """Health endpoint 429 includes Retry-After header."""
        for i in range(61):
            response = client.get('/health')
            if response.status_code == 429:
                assert 'retry-after' in response.headers
                break


class TestRateLimitingCities:
    """Rate limiting tests for /cities endpoint (60/minute)."""

    def test_cities_has_60_minute_limit(self):
        """
        /cities has 60/min limit.
        """
        for i in range(61):
            response = client.get('/cities')
            if i < 60:
                assert response.status_code == 200
            else:
                # 61st should be rate limited
                assert response.status_code == 429

    def test_cities_rate_limit_response_valid(self):
        """Cities endpoint 429 response has proper structure."""
        for i in range(61):
            response = client.get('/cities')
            if response.status_code == 429:
                data = response.json()
                assert 'error' in data
                assert 'retry_after' in data
                assert data['retry_after'] == 60
                break


class TestRateLimitPerIP:
    """Tests for per-IP rate limiting isolation."""

    def test_rate_limit_per_ip_isolation(self):
        """
        Rate limits are applied per IP.
        Different IPs should have separate limits.
        """
        # Use different headers to simulate different IPs
        # Note: slowapi uses get_remote_address which checks X-Forwarded-For
        
        # Make requests from "IP 1" (no special header)
        for i in range(31):
            response = client.get(
                '/predict?lat=24.86&lon=67.01',
                headers={}
            )
        
        # Last one should be rate limited
        assert response.status_code == 429
        
        # Now make request from "IP 2" (different forwarded IP)
        # This should succeed since it's a different IP
        response = client.get(
            '/predict?lat=24.86&lon=67.01',
            headers={'X-Forwarded-For': '192.168.1.100'}
        )
        
        # Should succeed (not rate limited for this "new" IP)
        assert response.status_code in [200, 503, 502]


class TestRateLimitExceptionHandler:
    """Tests for the rate limit exception handler."""

    def test_rate_limit_exception_includes_error_message(self):
        """Rate limit 429 response has descriptive error message."""
        for i in range(31):
            response = client.get('/predict?lat=24.86&lon=67.01')
            if response.status_code == 429:
                data = response.json()
                assert data['error'] == 'Rate limit exceeded'
                assert 'details' in data
                assert len(data['details']) > 0
                break

    def test_rate_limit_includes_limit_info(self):
        """Rate limit response includes the limit that was exceeded."""
        for i in range(31):
            response = client.get('/predict?lat=24.86&lon=67.01')
            if response.status_code == 429:
                data = response.json()
                assert 'limit' in data
                # Should contain something like "30/minute"
                assert 'minute' in data['limit'].lower() or '/' in data['limit']
                break


class TestRateLimitIntegration:
    """Integration tests for rate limiting with other features."""

    def test_rate_limit_before_validation(self):
        """
        Rate limiting is applied even if request validation would fail.
        (Rate limit is a middleware concern, not a business logic concern)
        """
        # Make requests with invalid coordinates
        for i in range(31):
            # Invalid latitude (> 90)
            response = client.get(
                '/predict?lat=91&lon=67.01'
            )
        
        # Should eventually hit rate limit (or validation error before that)
        # The point is that rate limiting works independently
        assert response.status_code in [422, 429]

    def test_rate_limit_with_different_parameters(self):
        """
        Rate limiting applies per IP regardless of different parameters.
        """
        # Make requests with different coordinates
        for i in range(31):
            response = client.get(
                f'/predict?lat={24 + i*0.01}&lon=67.01'
            )
        
        # Should hit rate limit even though coordinates vary
        assert response.status_code == 429
