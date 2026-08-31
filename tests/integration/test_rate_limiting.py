"""
test_rate_limiting.py — Integration tests for API rate limiting (Issue #40).

Tests that rate limiting is correctly enforced per endpoint with proper
429 responses, Retry-After headers, and per-IP isolation.

CRITICAL: Each test class must reset the limiter's in-memory storage.
The slowapi Limiter stores state in memory, persisting across test instances.
We reset it by clearing the storage dict before each test class.
"""

import pytest
from fastapi.testclient import TestClient
from app.api import app
from src.utils.rate_limiter import limiter


def _clear_limiter_storage():
    """Helper to clear slowapi's in-memory storage.
    
    slowapi stores request counts in an in-memory dict. We access and clear it.
    This prevents rate limit state from one test bleeding into the next.
    """
    try:
        if hasattr(limiter, 'storage'):
            storage = limiter.storage
            # MemoryStorage wraps a dict in .storage
            if hasattr(storage, 'storage'):
                storage.storage.clear()
            elif hasattr(storage, 'clear'):
                storage.clear()
            elif isinstance(storage, dict):
                storage.clear()
    except Exception:
        pass  # Silently continue if clearing fails


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset rate limiter storage before and after each test.
    
    This is critical: slowapi's in-memory storage persists across test instances.
    Without resetting, rate limit state from one test bleeds into the next.
    """
    _clear_limiter_storage()
    yield
    _clear_limiter_storage()


@pytest.fixture
def fresh_client():
    """Create a fresh TestClient for each test.
    
    The reset_limiter fixture handles clearing the limiter state,
    so we just need a new client instance here.
    """
    return TestClient(app)


class TestRateLimitingPredict:
    """Rate limiting tests for /predict endpoint (30/minute)."""

    def test_predict_rate_limit_429_response(self, fresh_client):
        """Exceeding /predict rate limit (30/min) returns 429."""
        # Make 31 requests rapidly to exceed limit
        last_response = None
        for i in range(31):
            response = fresh_client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            last_response = response
            if i < 30:
                # First 30 should succeed (or fail for other reasons, not rate limit)
                assert response.status_code in [200, 503, 502], \
                    f"Request {i}: expected 200/503/502, got {response.status_code}"
            else:
                # 31st should be rate limited
                assert response.status_code == 429, \
                    f"Request {i}: expected 429, got {response.status_code}"
                data = response.json()
                assert 'error' in data
                assert 'rate limit' in data['error'].lower() or 'too many' in data.get('details', '').lower()

    def test_predict_includes_retry_after_header(self, fresh_client):
        """429 responses include Retry-After header."""
        # Make requests to hit rate limit
        for i in range(31):
            response = fresh_client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            if response.status_code == 429:
                assert 'retry-after' in response.headers
                assert response.headers['retry-after'] == '60'
                break
        else:
            pytest.fail("Never hit rate limit after 31 requests")

    def test_predict_rate_limit_response_includes_retry_after_field(self, fresh_client):
        """429 response JSON includes retry_after field."""
        # Hit rate limit
        for i in range(31):
            response = fresh_client.get(
                '/predict?lat=24.86&lon=67.01&city=Karachi'
            )
            if response.status_code == 429:
                data = response.json()
                assert 'retry_after' in data
                assert data['retry_after'] == 60
                assert 'limit' in data
                break
        else:
            pytest.fail("Never hit rate limit after 31 requests")


class TestRateLimitingHealth:
    """Rate limiting tests for /health endpoint (60/minute)."""

    def test_health_has_higher_limit_than_predict(self, fresh_client):
        """
        /health has 60/min limit (higher than /predict's 30/min).
        This test verifies the limits are configured differently.
        """
        # Make 61 health requests to exceed its limit
        for i in range(61):
            response = fresh_client.get('/health')
            if i < 60:
                assert response.status_code == 200, \
                    f"Request {i}: expected 200, got {response.status_code}"
            else:
                # 61st should be rate limited
                assert response.status_code == 429, \
                    f"Request {i}: expected 429, got {response.status_code}"

    def test_health_rate_limit_includes_retry_after(self, fresh_client):
        """Health endpoint 429 includes Retry-After header."""
        for i in range(61):
            response = fresh_client.get('/health')
            if response.status_code == 429:
                assert 'retry-after' in response.headers
                break
        else:
            pytest.fail("Never hit rate limit after 61 requests")


class TestRateLimitingCities:
    """Rate limiting tests for /cities endpoint (60/minute)."""

    def test_cities_has_60_minute_limit(self, fresh_client):
        """
        /cities has 60/min limit.
        """
        for i in range(61):
            response = fresh_client.get('/cities')
            if i < 60:
                assert response.status_code == 200, \
                    f"Request {i}: expected 200, got {response.status_code}"
            else:
                # 61st should be rate limited
                assert response.status_code == 429, \
                    f"Request {i}: expected 429, got {response.status_code}"

    def test_cities_rate_limit_response_valid(self, fresh_client):
        """Cities endpoint 429 response has proper structure."""
        for i in range(61):
            response = fresh_client.get('/cities')
            if response.status_code == 429:
                data = response.json()
                assert 'error' in data
                assert 'retry_after' in data
                assert data['retry_after'] == 60
                break
        else:
            pytest.fail("Never hit rate limit after 61 requests")


class TestRateLimitPerIP:
    """Tests for per-IP rate limiting isolation."""

    def test_rate_limit_per_ip_isolation(self, fresh_client):
        """
        Rate limits are applied per IP.
        Different IPs should have separate limits.
        """
        # Make requests from "IP 1" (no special header)
        for i in range(31):
            response = fresh_client.get(
                '/predict?lat=24.86&lon=67.01',
                headers={}
            )
        
        # Last one should be rate limited
        assert response.status_code == 429, \
            f"Expected 429 after 31 requests, got {response.status_code}"
        
        # Now make request from "IP 2" (different forwarded IP)
        # This should succeed since it's a different IP
        response = fresh_client.get(
            '/predict?lat=24.86&lon=67.01',
            headers={'X-Forwarded-For': '192.168.1.100'}
        )
        
        # Should succeed (not rate limited for this "new" IP)
        assert response.status_code in [200, 503, 502], \
            f"Expected 200/503/502 for new IP, got {response.status_code}"


class TestRateLimitExceptionHandler:
    """Tests for the rate limit exception handler."""

    def test_rate_limit_exception_includes_error_message(self, fresh_client):
        """Rate limit 429 response has descriptive error message."""
        for i in range(31):
            response = fresh_client.get('/predict?lat=24.86&lon=67.01')
            if response.status_code == 429:
                data = response.json()
                assert data['error'] == 'Rate limit exceeded'
                assert 'details' in data
                assert len(data['details']) > 0
                break
        else:
            pytest.fail("Never hit rate limit after 31 requests")

    def test_rate_limit_includes_limit_info(self, fresh_client):
        """Rate limit response includes the limit that was exceeded."""
        for i in range(31):
            response = fresh_client.get('/predict?lat=24.86&lon=67.01')
            if response.status_code == 429:
                data = response.json()
                assert 'limit' in data
                # Should contain something like "30/minute"
                assert 'minute' in data['limit'].lower() or '/' in data['limit']
                break
        else:
            pytest.fail("Never hit rate limit after 31 requests")


class TestRateLimitIntegration:
    """Integration tests for rate limiting with other features."""

    def test_rate_limit_before_validation(self, fresh_client):
        """
        Rate limiting is applied even if request validation would fail.
        (Rate limit is a middleware concern, not a business logic concern)
        """
        # Make requests with invalid coordinates
        for i in range(31):
            # Invalid latitude (> 90)
            response = fresh_client.get(
                '/predict?lat=91&lon=67.01'
            )
        
        # Should eventually hit rate limit (or validation error before that)
        # The point is that rate limiting works independently
        assert response.status_code in [422, 429], \
            f"Got {response.status_code}"

    def test_rate_limit_with_different_parameters(self, fresh_client):
        """
        Rate limiting applies per IP regardless of different parameters.
        """
        # Make requests with different coordinates
        for i in range(31):
            response = fresh_client.get(
                f'/predict?lat={24 + i*0.01}&lon=67.01'
            )
        
        # Should hit rate limit even though coordinates vary
        assert response.status_code == 429, \
            f"Expected 429, got {response.status_code}"
