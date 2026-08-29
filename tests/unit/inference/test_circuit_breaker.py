"""
test_circuit_breaker.py — Unit tests for circuit breaker pattern.
"""

import pytest
import time
from datetime import datetime, timezone
from src.inference.circuit_breaker import CircuitBreaker, CircuitBreakerState


class TestCircuitBreaker:
    """Test suite for CircuitBreaker."""
    
    @pytest.fixture
    def breaker(self):
        """Create circuit breaker for testing."""
        return CircuitBreaker(name='TestAPI', fail_max=3, reset_timeout=1)
    
    def test_circuit_starts_closed(self, breaker):
        """Circuit breaker starts in CLOSED state."""
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
    
    def test_successful_call_in_closed_state(self, breaker):
        """Successful call returns result in CLOSED state."""
        result = breaker.call(lambda: 'success')
        assert result == 'success'
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_failed_call_increments_failure_count(self, breaker):
        """Failed call increments failure counter."""
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
            assert breaker.failure_count == i + 1
    
    def test_circuit_opens_after_max_failures(self, breaker):
        """Circuit opens after fail_max consecutive failures."""
        # Fail fail_max times
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        # Circuit should be OPEN
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.is_open
    
    def test_circuit_open_rejects_requests(self, breaker):
        """Open circuit rejects new requests with RuntimeError."""
        # Open the circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        # Next request should be rejected immediately
        with pytest.raises(RuntimeError, match='OPEN'):
            breaker.call(lambda: 'success')
    
    def test_circuit_transitions_to_half_open_after_timeout(self, breaker):
        """Circuit transitions to HALF-OPEN after reset_timeout."""
        # Open circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for timeout
        time.sleep(breaker.reset_timeout + 0.1)
        
        # Next call should attempt (transition to HALF-OPEN)
        result = breaker.call(lambda: 'success')
        
        # Should recover
        assert result == 'success'
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_circuit_reopens_on_half_open_failure(self, breaker):
        """Circuit reopens if HALF-OPEN recovery attempt fails."""
        # Open circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        # Wait for timeout
        time.sleep(breaker.reset_timeout + 0.1)
        
        # Recovery attempt fails
        with pytest.raises(RuntimeError):
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError('still broken')))
        
        # Should re-open
        assert breaker.state == CircuitBreakerState.OPEN
    
    def test_is_open_property(self, breaker):
        """is_open property checks state and timeout."""
        # Closed -> not open
        assert not breaker.is_open
        
        # Open circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        # Open and within timeout
        assert breaker.is_open
        
        # Wait for timeout
        time.sleep(breaker.reset_timeout + 0.1)
        
        # Timeout elapsed, but still OPEN state
        # is_open checks if timeout has passed
        assert not breaker.is_open
    
    def test_status_property(self, breaker):
        """status property returns human-readable string."""
        assert breaker.status == 'CLOSED'
        
        # Open circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        status = breaker.status
        assert 'OPEN' in status
        assert 'retry in' in status
    
    def test_custom_names(self):
        """Circuit breaker names are included in messages."""
        breaker = CircuitBreaker(name='CustomAPI', fail_max=1)
        
        # Fail once
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        # Check error message includes name
        with pytest.raises(RuntimeError, match='CustomAPI'):
            breaker.call(lambda: 'success')
    
    def test_successful_call_resets_counter(self, breaker):
        """Successful call resets failure counter."""
        # One failure
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        assert breaker.failure_count == 1
        
        # One success
        breaker.call(lambda: 'success')
        assert breaker.failure_count == 0
    
    def test_half_open_success_closes_circuit(self, breaker):
        """Successful call in HALF-OPEN state closes circuit."""
        # Open circuit
        for _ in range(breaker.fail_max):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError('test')))
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait and attempt recovery
        time.sleep(breaker.reset_timeout + 0.1)
        
        # Recovery succeeds
        result = breaker.call(lambda: 'recovered')
        
        assert result == 'recovered'
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
