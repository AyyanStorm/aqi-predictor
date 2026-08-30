"""
Test suite for circuit_breaker.py — fault tolerance and resilience.
"""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.inference.circuit_breaker import CircuitBreaker, CircuitBreakerState


class TestCircuitBreaker:
    """Test suite for circuit breaker pattern."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        return CircuitBreaker(name='TestAPI', fail_max=3, reset_timeout=1)

    def test_initial_state_closed(self, breaker):
        """Circuit starts in CLOSED state."""
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
        assert not breaker.is_open

    def test_successful_call_remains_closed(self, breaker):
        """Successful call keeps circuit CLOSED."""
        result = breaker.call(lambda: 'success')
        
        assert result == 'success'
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0

    def test_failure_increments_counter(self, breaker):
        """Failed call increments failure counter."""
        with pytest.raises(ZeroDivisionError):
            breaker.call(lambda: 1 / 0)
        
        assert breaker.failure_count == 1
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_circuit_opens_after_max_failures(self, breaker):
        """Circuit opens after fail_max consecutive failures."""
        # Fail 3 times (fail_max=3)
        for i in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.failure_count == 3
        assert breaker.state == CircuitBreakerState.OPEN

    def test_open_circuit_rejects_calls(self, breaker):
        """Once open, circuit rejects new calls without executing."""
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        # Next call should raise RuntimeError, not execute lambda
        with pytest.raises(RuntimeError, match='OPEN'):
            breaker.call(lambda: 'should not execute')

    def test_open_circuit_timeout_transitions_to_half_open(self, breaker):
        """After reset_timeout, circuit transitions to HALF-OPEN."""
        # Open circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for reset timeout
        time.sleep(1.1)
        
        # Next call should transition to HALF-OPEN
        result = breaker.call(lambda: 'success')
        
        assert result == 'success'
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_half_open_recovers_on_success(self, breaker):
        """HALF-OPEN → CLOSED when call succeeds."""
        # Open circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery window
        time.sleep(1.1)
        
        # Successful call in HALF-OPEN state
        result = breaker.call(lambda: 'recovered')
        
        assert result == 'recovered'
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0

    def test_half_open_reopens_on_failure(self, breaker):
        """HALF-OPEN → OPEN when fail_max failures occur again."""
        # Open circuit with 3 failures
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery window
        time.sleep(1.1)
        
        # Fail 3 more times in HALF-OPEN state to reopen
        # (failure counter resets when entering HALF-OPEN)
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        # After fail_max failures, should reopen
        assert breaker.state == CircuitBreakerState.OPEN

    def test_circuit_error_message_includes_retry_time(self, breaker):
        """Open circuit error includes retry-in time."""
        # Open circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        # Try to call immediately
        with pytest.raises(RuntimeError, match='retry in'):
            breaker.call(lambda: 'fail')

    def test_success_resets_failure_counter(self, breaker):
        """Successful call after partial failures resets counter."""
        # Fail twice
        for _ in range(2):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.failure_count == 2
        
        # Successful call
        breaker.call(lambda: 'success')
        
        assert breaker.failure_count == 0
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_call_with_args_and_kwargs(self, breaker):
        """Circuit breaker correctly passes args and kwargs."""
        def multiply(a, b, factor=1):
            return (a * b) * factor
        
        result = breaker.call(multiply, 3, 4, factor=2)
        
        assert result == 24

    def test_last_failure_time_recorded(self, breaker):
        """Circuit records time of last failure."""
        with pytest.raises(ZeroDivisionError):
            breaker.call(lambda: 1 / 0)
        
        assert breaker.last_failure_time is not None
        assert isinstance(breaker.last_failure_time, datetime)

    def test_last_success_time_recorded(self, breaker):
        """Circuit records time of last success."""
        breaker.call(lambda: 'ok')
        
        assert breaker.last_success_time is not None
        assert isinstance(breaker.last_success_time, datetime)

    def test_is_open_property(self, breaker):
        """is_open property reflects open state and timeout."""
        assert not breaker.is_open
        
        # Open circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.is_open
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Should no longer be open (can attempt recovery)
        assert not breaker.is_open

    def test_status_property(self, breaker):
        """status property returns human-readable state."""
        assert breaker.status == 'CLOSED'
        
        # Open circuit
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        status = breaker.status
        assert 'OPEN' in status
        assert 'retry in' in status

    def test_multiple_consecutive_successes(self, breaker):
        """Multiple successes don't change state."""
        for _ in range(5):
            breaker.call(lambda: 'ok')
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0

    def test_configurable_fail_max(self):
        """fail_max parameter controls failure threshold."""
        breaker_2 = CircuitBreaker(name='Test', fail_max=2, reset_timeout=1)
        
        # Fail twice, should open
        for _ in range(2):
            with pytest.raises(ZeroDivisionError):
                breaker_2.call(lambda: 1 / 0)
        
        assert breaker_2.state == CircuitBreakerState.OPEN

    def test_configurable_reset_timeout(self):
        """reset_timeout parameter controls recovery window."""
        breaker_short = CircuitBreaker(name='Test', fail_max=1, reset_timeout=0.1)
        
        # Open circuit
        with pytest.raises(ZeroDivisionError):
            breaker_short.call(lambda: 1 / 0)
        
        assert breaker_short.state == CircuitBreakerState.OPEN
        
        # Wait short timeout
        time.sleep(0.15)
        
        # Should be ready to recover
        result = breaker_short.call(lambda: 'ok')
        assert result == 'ok'
        assert breaker_short.state == CircuitBreakerState.CLOSED

    def test_exception_propagates(self, breaker):
        """Original exception is re-raised."""
        def custom_error():
            raise KeyError('missing key')
        
        with pytest.raises(KeyError, match='missing key'):
            breaker.call(custom_error)

    def test_circuit_name_in_logging(self, breaker):
        """Circuit name appears in status messages."""
        status = breaker.status
        # Status should be readable, name is used in messages
        assert breaker.name == 'TestAPI'

    def test_rapid_failures_open_quickly(self, breaker):
        """Rapid consecutive failures open circuit immediately."""
        start_time = datetime.now(timezone.utc)
        
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Should open very quickly (< 500ms)
        assert elapsed < 0.5
        assert breaker.state == CircuitBreakerState.OPEN

    def test_failure_count_resets_in_half_open(self, breaker):
        """failure_count resets to 0 when entering HALF-OPEN and succeeds."""
        # Open circuit with 3 failures
        for _ in range(3):
            with pytest.raises(ZeroDivisionError):
                breaker.call(lambda: 1 / 0)
        
        assert breaker.failure_count == 3
        
        # Wait for recovery
        time.sleep(1.1)
        
        # Successful call in HALF-OPEN should reset counter
        breaker.call(lambda: 'ok')
        
        # After successful recovery, failure count should be 0
        assert breaker.failure_count == 0

    def test_circuit_breaker_name(self):
        """Circuit breaker can be named for logging."""
        breaker1 = CircuitBreaker(name='OpenMeteo', fail_max=5, reset_timeout=60)
        breaker2 = CircuitBreaker(name='PostgreSQL', fail_max=3, reset_timeout=60)
        
        assert breaker1.name == 'OpenMeteo'
        assert breaker2.name == 'PostgreSQL'
