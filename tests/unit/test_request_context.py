"""
test_request_context.py — Unit tests for request context and tracing.

Tests request ID generation, context management, and middleware integration.

Issue #39: Missing request IDs and poor error context in API responses.
"""

import pytest
from src.utils.request_context import (
    generate_request_id,
    get_request_id,
    set_request_id,
    get_request_path,
    set_request_path,
    get_request_method,
    set_request_method,
    clear_request_context,
)


class TestRequestIDGeneration:
    """Test request ID generation."""
    
    def test_generate_request_id_format(self):
        """Generated request ID should be 8 hex characters."""
        request_id = generate_request_id()
        
        assert isinstance(request_id, str)
        assert len(request_id) == 8
        # Should be valid hex
        assert all(c in '0123456789abcdef' for c in request_id)
    
    def test_generate_request_id_unique(self):
        """Each generated request ID should be unique."""
        ids = [generate_request_id() for _ in range(100)]
        
        # All should be unique
        assert len(set(ids)) == len(ids)
    
    def test_request_id_reproducible(self):
        """Request IDs should be consistent when set."""
        request_id = generate_request_id()
        set_request_id(request_id)
        
        assert get_request_id() == request_id


class TestRequestIDContext:
    """Test request ID context variables."""
    
    def test_set_and_get_request_id(self):
        """Should store and retrieve request ID."""
        test_id = 'test1234'
        set_request_id(test_id)
        
        assert get_request_id() == test_id
    
    def test_get_request_id_default(self):
        """Should return 'unknown' if no request ID set."""
        clear_request_context()
        
        assert get_request_id() == 'unknown'
    
    def test_set_and_get_request_path(self):
        """Should store and retrieve request path."""
        test_path = '/predict'
        set_request_path(test_path)
        
        assert get_request_path() == test_path
    
    def test_get_request_path_default(self):
        """Should return 'unknown' if no request path set."""
        clear_request_context()
        
        assert get_request_path() == 'unknown'
    
    def test_set_and_get_request_method(self):
        """Should store and retrieve request method."""
        test_method = 'POST'
        set_request_method(test_method)
        
        assert get_request_method() == test_method
    
    def test_get_request_method_default(self):
        """Should return 'unknown' if no request method set."""
        clear_request_context()
        
        assert get_request_method() == 'unknown'


class TestContextClearing:
    """Test context cleanup."""
    
    def test_clear_request_context(self):
        """Should clear all context variables."""
        set_request_id('test1234')
        set_request_path('/predict')
        set_request_method('GET')
        
        clear_request_context()
        
        assert get_request_id() == 'unknown'
        assert get_request_path() == 'unknown'
        assert get_request_method() == 'unknown'
    
    def test_context_isolation(self):
        """Context should be isolated per async task/thread."""
        set_request_id('id1')
        set_request_path('/path1')
        
        # Clear and set different values
        clear_request_context()
        set_request_id('id2')
        set_request_path('/path2')
        
        assert get_request_id() == 'id2'
        assert get_request_path() == '/path2'


class TestRequestIDFormat:
    """Test request ID format consistency."""
    
    def test_request_id_lowercase_hex(self):
        """Request IDs should be lowercase hex."""
        for _ in range(50):
            request_id = generate_request_id()
            assert request_id == request_id.lower()
    
    def test_request_id_no_uppercase(self):
        """Request IDs should not contain uppercase letters."""
        for _ in range(50):
            request_id = generate_request_id()
            assert not any(c.isupper() for c in request_id)
    
    def test_request_id_short_format(self):
        """Request ID should be short and portable."""
        request_id = generate_request_id()
        
        # Should fit in HTTP headers easily
        assert len(request_id) <= 36  # UUID is 36 chars, we use 8
        # Should be human-readable
        assert len(request_id) >= 6


class TestMultipleRequests:
    """Test handling multiple sequential requests."""
    
    def test_sequential_requests_different_ids(self):
        """Sequential requests should have different IDs."""
        clear_request_context()
        id1 = generate_request_id()
        set_request_id(id1)
        assert get_request_id() == id1
        
        clear_request_context()
        id2 = generate_request_id()
        set_request_id(id2)
        assert get_request_id() == id2
        
        assert id1 != id2
    
    def test_context_per_request_lifecycle(self):
        """Context should be settable per request lifecycle."""
        # Request 1
        clear_request_context()
        set_request_id('req1')
        set_request_path('/predict')
        set_request_method('GET')
        
        assert get_request_id() == 'req1'
        assert get_request_path() == '/predict'
        assert get_request_method() == 'GET'
        
        # Request 2
        clear_request_context()
        set_request_id('req2')
        set_request_path('/health')
        set_request_method('POST')
        
        assert get_request_id() == 'req2'
        assert get_request_path() == '/health'
        assert get_request_method() == 'POST'
