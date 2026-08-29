"""
circuit_breaker.py — Circuit breaker pattern for API resilience.

Prevents cascading failures by stopping requests to failing services.
After N failures, circuit "opens" and rejects requests for a cooldown period.
"""

from datetime import datetime, timezone, timedelta
import logging
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitBreakerState:
    """Circuit breaker states."""
    CLOSED = 'closed'      # Normal operation
    OPEN = 'open'          # Failing, reject requests
    HALF_OPEN = 'half-open'  # Testing recovery


class CircuitBreaker:
    """
    Implements circuit breaker pattern for fault tolerance.
    
    Transitions:
    - CLOSED (normal) → OPEN (after fail_max failures)
    - OPEN (failing) → HALF-OPEN (after reset_timeout)
    - HALF-OPEN → CLOSED (if next call succeeds)
    - HALF-OPEN → OPEN (if next call fails)
    
    Usage:
        breaker = CircuitBreaker(name='OpenMeteo', fail_max=5, reset_timeout=300)
        
        try:
            result = breaker.call(fetch_forecast, lat, lon)
        except RuntimeError as e:
            # Circuit is open or other error
            logger.error(e)
    """
    
    def __init__(self, name='API', fail_max=5, reset_timeout=300):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name for logging (e.g., 'OpenMeteo')
            fail_max: Consecutive failures before opening (default: 5)
            reset_timeout: Seconds before attempting recovery (default: 300 = 5min)
        """
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.last_success_time = None
    
    def call(self, func, *args, **kwargs):
        """
        Execute func with circuit breaker protection.
        
        Args:
            func: Callable to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
        
        Returns:
            Result of func(*args, **kwargs)
        
        Raises:
            RuntimeError: If circuit is open or func raises an exception
        """
        
        # Check if we should attempt recovery
        if self.state == CircuitBreakerState.OPEN:
            elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
            
            if elapsed >= self.reset_timeout:
                # Timeout elapsed, try recovery
                self.state = CircuitBreakerState.HALF_OPEN
                self.failure_count = 0
                logger.info(
                    f'Circuit {self.name} → HALF-OPEN (attempting recovery '
                    f'after {self.reset_timeout}s)'
                )
            else:
                # Still in cooldown
                retry_in = self.reset_timeout - int(elapsed)
                raise RuntimeError(
                    f'Circuit {self.name} OPEN. '
                    f'Will retry in {retry_in}s. '
                    f'(After {self.fail_max} consecutive failures)'
                )
        
        # Execute function
        try:
            result = func(*args, **kwargs)
            
            # Success!
            if self.state == CircuitBreakerState.HALF_OPEN:
                # Recovered
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                self.last_success_time = datetime.now(timezone.utc)
                logger.info(f'Circuit {self.name} → CLOSED (recovered)')
            elif self.state == CircuitBreakerState.CLOSED:
                # Still healthy
                self.failure_count = 0
                self.last_success_time = datetime.now(timezone.utc)
            
            return result
        
        except Exception as e:
            # Failure
            self.failure_count += 1
            self.last_failure_time = datetime.now(timezone.utc)
            
            logger.warning(
                f'Circuit {self.name}: failure {self.failure_count}/{self.fail_max}'
            )
            
            # Check if we should open circuit
            if self.failure_count >= self.fail_max:
                self.state = CircuitBreakerState.OPEN
                logger.error(
                    f'Circuit {self.name} → OPEN '
                    f'(after {self.fail_max} failures). '
                    f'Will retry in {self.reset_timeout}s'
                )
            
            # Re-raise exception
            raise
    
    @property
    def is_open(self):
        """Check if circuit is currently open."""
        if self.state != CircuitBreakerState.OPEN:
            return False
        
        # Check if timeout has elapsed
        if self.last_failure_time is None:
            return False
        
        elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
        return elapsed < self.reset_timeout
    
    @property
    def status(self):
        """Get human-readable status."""
        if self.state == CircuitBreakerState.OPEN and self.is_open:
            retry_in = self.reset_timeout - int(
                (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
            )
            return f'OPEN (retry in {retry_in}s)'
        else:
            return self.state.upper()
