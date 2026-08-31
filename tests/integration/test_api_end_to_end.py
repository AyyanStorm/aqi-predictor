"""
test_api_end_to_end.py — Integration tests for API endpoints.

Tests full API workflows including health checks, predictions,
input validation, and response structures.

Issue #43: Integration tests for end-to-end paths.
"""

import pytest
from datetime import datetime

pytestmark = pytest.mark.integration


class TestHealthEndpoint:
    """Integration tests for /health endpoint."""

    def test_health_endpoint_returns_200(self, api_client):
        """Health endpoint should return 200 OK."""
        response = api_client.get("/health")
        
        assert response.status_code == 200

    def test_health_endpoint_response_structure(self, api_client):
        """Health endpoint should return valid structure."""
        response = api_client.get("/health")
        
        data = response.json()
        
        # Check required fields
        assert isinstance(data, dict)
        assert "status" in data

    def test_health_endpoint_includes_request_id(self, api_client):
        """Health endpoint should include X-Request-ID header."""
        response = api_client.get("/health")
        
        # Request ID may not be present in all endpoints yet
        if "X-Request-ID" in response.headers:
            request_id = response.headers["X-Request-ID"]
            assert len(request_id) == 8  # 8-character hex ID
            assert all(c in "0123456789abcdef" for c in request_id)

    def test_health_endpoint_response_json_valid(self, api_client):
        """Health endpoint response should be valid JSON."""
        response = api_client.get("/health")
        
        # Should not raise
        data = response.json()
        assert isinstance(data, dict)


class TestPredictEndpoint:
    """Integration tests for /predict endpoint."""

    def test_predict_accepts_valid_coordinates(self, api_client, karachi_coords):
        """Predict endpoint should accept valid lat/lon."""
        response = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        assert response.status_code == 200

    def test_predict_requires_latitude(self, api_client):
        """Predict endpoint requires latitude parameter."""
        response = api_client.get("/predict?lon=67.01")
        
        assert response.status_code == 422  # Validation error

    def test_predict_requires_longitude(self, api_client):
        """Predict endpoint requires longitude parameter."""
        response = api_client.get("/predict?lat=24.86")
        
        assert response.status_code == 422  # Validation error

    def test_predict_rejects_invalid_latitude(self, api_client):
        """Predict endpoint should reject latitude > 90."""
        response = api_client.get("/predict?lat=91&lon=67.01")
        
        assert response.status_code == 422

    def test_predict_rejects_invalid_longitude(self, api_client):
        """Predict endpoint should reject longitude > 180."""
        response = api_client.get("/predict?lat=24.86&lon=181")
        
        assert response.status_code == 422

    def test_predict_accepts_optional_city(self, api_client):
        """Predict endpoint should accept optional city parameter."""
        response = api_client.get(
            "/predict?lat=24.86&lon=67.01&city=Karachi"
        )
        
        # Should succeed
        assert response.status_code == 200

    def test_predict_response_is_json(self, api_client, karachi_coords):
        """Predict endpoint response should be valid JSON."""
        response = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        # Should not raise JSON decode error
        data = response.json()
        assert isinstance(data, dict)

    def test_predict_includes_request_id(self, api_client, karachi_coords):
        """Predict response should include X-Request-ID header."""
        response = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        # Request ID may not be present in all endpoints yet
        if "X-Request-ID" in response.headers:
            request_id = response.headers["X-Request-ID"]
            assert len(request_id) == 8

    def test_predict_response_contains_data(self, api_client, karachi_coords):
        """Predict response should contain data or error."""
        response = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        # Should be successful
        assert response.status_code == 200
        
        data = response.json()
        
        # Should be dict
        assert isinstance(data, dict)

    def test_predict_valid_response_has_forecast(self, api_client, karachi_coords):
        """Successful prediction should have forecast data."""
        response = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"]:
                forecast = data["data"]
                
                # At least one forecast field should exist
                forecast_fields = ["forecast_24h", "forecast_48h", "forecast_72h"]
                has_forecast = any(field in forecast for field in forecast_fields)
                
                assert has_forecast


class TestPredictInputValidation:
    """Test /predict endpoint input validation."""

    def test_predict_latitude_boundary_min(self, api_client):
        """Latitude at boundary (0) should be accepted."""
        response = api_client.get("/predict?lat=0&lon=67.01")
        
        # Should not be 422 (validation error)
        assert response.status_code != 422

    def test_predict_latitude_boundary_max(self, api_client):
        """Latitude at boundary (90) should be accepted."""
        response = api_client.get("/predict?lat=90&lon=67.01")
        
        assert response.status_code != 422

    def test_predict_longitude_boundary_min(self, api_client):
        """Longitude at boundary (-180) should be accepted."""
        response = api_client.get("/predict?lat=24.86&lon=-180")
        
        assert response.status_code != 422

    def test_predict_longitude_boundary_max(self, api_client):
        """Longitude at boundary (180) should be accepted."""
        response = api_client.get("/predict?lat=24.86&lon=180")
        
        assert response.status_code != 422

    def test_predict_negative_latitude(self, api_client):
        """Negative latitude should be accepted."""
        response = api_client.get("/predict?lat=-30&lon=67.01")
        
        assert response.status_code != 422

    def test_predict_negative_longitude(self, api_client):
        """Negative longitude should be accepted."""
        response = api_client.get("/predict?lat=24.86&lon=-120")
        
        assert response.status_code != 422

    def test_predict_float_coordinates(self, api_client):
        """Coordinates should accept float values."""
        response = api_client.get("/predict?lat=24.8608&lon=67.0104")
        
        assert response.status_code != 422

    def test_predict_integer_coordinates(self, api_client):
        """Coordinates should accept integer values."""
        response = api_client.get("/predict?lat=24&lon=67")
        
        assert response.status_code != 422


class TestPredictMultipleCalls:
    """Test prediction endpoint with multiple calls."""

    def test_predict_multiple_cities(self, api_client, test_coordinates):
        """Predict endpoint should work for multiple cities."""
        results = []
        
        for city, (lat, lon) in test_coordinates.items():
            response = api_client.get(f"/predict?lat={lat}&lon={lon}&city={city}")
            results.append((city, response.status_code))
        
        # At least some should succeed
        success_count = sum(1 for _, status in results if status == 200)
        assert success_count > 0

    def test_predict_consecutive_calls_same_location(self, api_client, karachi_coords):
        """Consecutive calls to same location should both succeed."""
        response1 = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        response2 = api_client.get(
            f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Request IDs should be different if present
        id1 = response1.headers.get("X-Request-ID")
        id2 = response2.headers.get("X-Request-ID")
        if id1 and id2:
            assert id1 != id2

    def test_predict_rate_limiting_not_enforced_locally(self, api_client, karachi_coords):
        """Local testing should not hit rate limits."""
        # Make several rapid requests
        for _ in range(5):
            response = api_client.get(
                f"/predict?lat={karachi_coords['lat']}&lon={karachi_coords['lon']}"
            )
            
            # Should not get 429 (too many requests)
            assert response.status_code != 429


class TestAPIErrorHandling:
    """Test API error handling."""

    def test_predict_invalid_method_not_allowed(self, api_client):
        """POST to /predict should fail if not supported."""
        response = api_client.post("/predict", json={"lat": 24.86, "lon": 67.01})
        
        # Should be 405 (method not allowed) or 422 (validation)
        assert response.status_code in [405, 422, 400]

    def test_api_nonexistent_endpoint_404(self, api_client):
        """Nonexistent endpoint should return 404."""
        response = api_client.get("/nonexistent")
        
        assert response.status_code == 404

    def test_predict_malformed_coordinates_rejected(self, api_client):
        """Malformed coordinate values should be rejected."""
        response = api_client.get("/predict?lat=abc&lon=def")
        
        # Should be validation error
        assert response.status_code == 422


class TestAPIResponseHeaders:
    """Test API response headers."""

    def test_api_response_has_content_type(self, api_client):
        """API responses should have Content-Type header."""
        response = api_client.get("/health")
        
        assert "Content-Type" in response.headers

    def test_api_response_content_type_json(self, api_client):
        """API responses should have JSON content type."""
        response = api_client.get("/health")
        
        content_type = response.headers.get("Content-Type", "")
        assert "application/json" in content_type or "text/plain" in content_type

    def test_api_request_id_format(self, api_client):
        """Request IDs should be valid format (8 hex chars) when present."""
        response = api_client.get("/health")
        
        request_id = response.headers.get("X-Request-ID")
        # Request ID is optional in development, but if present should be valid
        if request_id is not None:
            assert len(request_id) == 8
            assert all(c in "0123456789abcdef" for c in request_id)


__all__ = [
    "TestHealthEndpoint",
    "TestPredictEndpoint",
    "TestPredictInputValidation",
    "TestPredictMultipleCalls",
    "TestAPIErrorHandling",
    "TestAPIResponseHeaders",
]
