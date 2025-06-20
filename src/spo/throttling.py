"""
Throttling mechanism for API rate limiting with exponential backoff and graceful error handling.

This module provides decorators to prevent API rate limit violations and handle
429 (Too Many Requests) responses gracefully with automatic retries.
"""

import time
from collections import defaultdict, deque
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Union

import spotipy

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


class ThrottleManager:
    """
    Manages API request throttling using token bucket and sliding window algorithms.

    Features:
    - Token bucket for burst handling
    - Sliding window for rate limiting over time periods
    - Per-client rate limiting support
    - Exponential backoff for 429 responses
    - Configurable rate limits and retry policies
    """

    def __init__(
        self,
        requests_per_second: float = 1.0,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
    ):
        """
        Initialize the throttle manager.

        Args:
            requests_per_second: Maximum requests per second (default: 1.0)
            requests_per_minute: Maximum requests per minute (default: 60)
            burst_size: Maximum burst requests allowed (default: 10)
            max_retries: Maximum retry attempts for 429 responses (default: 5)
            base_delay: Base delay for exponential backoff in seconds (default: 1.0)
            max_delay: Maximum delay between retries in seconds (default: 60.0)
            backoff_multiplier: Multiplier for exponential backoff (default: 2.0)
        """
        self.requests_per_second = requests_per_second
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier

        # Token bucket for burst handling
        self.tokens = float(burst_size)
        self.last_refill = time.time()

        # Sliding window for minute-based rate limiting
        self.request_times: deque = deque()

        # Per-client tracking (if needed for multi-client scenarios)
        self.client_buckets: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "tokens": float(self.burst_size),
                "last_refill": time.time(),
                "request_times": deque(),
            }
        )

    def _refill_tokens(self, client_id: Optional[str] = None) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()

        if client_id:
            bucket = self.client_buckets[client_id]
            elapsed = now - bucket["last_refill"]
            bucket["tokens"] = min(
                self.burst_size, bucket["tokens"] + elapsed * self.requests_per_second
            )
            bucket["last_refill"] = now
        else:
            elapsed = now - self.last_refill
            self.tokens = min(
                self.burst_size, self.tokens + elapsed * self.requests_per_second
            )
            self.last_refill = now

    def _clean_old_requests(self, request_times: deque) -> None:
        """Remove requests older than 1 minute from the sliding window."""
        now = time.time()
        while request_times and request_times[0] < now - 60:
            request_times.popleft()

    def can_make_request(self, client_id: Optional[str] = None) -> bool:
        """
        Check if a request can be made without violating rate limits.

        Args:
            client_id: Optional client identifier for per-client limiting

        Returns:
            bool: True if request can be made, False otherwise
        """
        if client_id:
            bucket = self.client_buckets[client_id]
            self._refill_tokens(client_id)
            self._clean_old_requests(bucket["request_times"])

            return (
                bucket["tokens"] >= 1.0
                and len(bucket["request_times"]) < self.requests_per_minute
            )
        else:
            self._refill_tokens()
            self._clean_old_requests(self.request_times)

            return (
                self.tokens >= 1.0
                and len(self.request_times) < self.requests_per_minute
            )

    def consume_token(self, client_id: Optional[str] = None) -> None:
        """
        Consume a token for making a request.

        Args:
            client_id: Optional client identifier for per-client limiting
        """
        now = time.time()

        if client_id:
            bucket = self.client_buckets[client_id]
            bucket["tokens"] -= 1.0
            bucket["request_times"].append(now)
        else:
            self.tokens -= 1.0
            self.request_times.append(now)

    def wait_for_slot(self, client_id: Optional[str] = None) -> None:
        """
        Wait until a request slot is available.

        Args:
            client_id: Optional client identifier for per-client limiting
        """
        while not self.can_make_request(client_id):
            sleep_time = min(1.0 / self.requests_per_second, 0.1)
            time.sleep(sleep_time)

    def calculate_retry_delay(
        self, attempt: int, retry_after: Optional[Union[int, str]] = None
    ) -> float:
        """
        Calculate delay for retry attempt with exponential backoff.

        Args:
            attempt: Current retry attempt number (0-based)
            retry_after: Optional Retry-After header value from API response

        Returns:
            float: Delay in seconds before next retry
        """
        if retry_after:
            try:
                # Handle both integer seconds and HTTP date format
                if isinstance(retry_after, str):
                    # Try parsing as integer first
                    try:
                        return float(retry_after)
                    except ValueError:
                        # Could add HTTP date parsing here if needed
                        pass
                else:
                    return float(retry_after)
            except (ValueError, TypeError):
                pass

        # Exponential backoff with jitter
        delay = min(
            self.base_delay * (self.backoff_multiplier**attempt), self.max_delay
        )

        # Add small random jitter to prevent thundering herd
        import random

        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter


# Global throttle manager instance
_default_throttle_manager = ThrottleManager()


def throttle(
    requests_per_second: float = 1.0,
    requests_per_minute: int = 60,
    burst_size: int = 10,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    client_id_func: Optional[Callable] = None,
    manager: Optional[ThrottleManager] = None,
) -> Callable[[F], F]:
    """
    Decorator to add throttling and retry logic to functions that make API calls.

    This decorator implements:
    - Rate limiting using token bucket and sliding window algorithms
    - Automatic retry with exponential backoff for 429 responses
    - Graceful handling of Spotify API rate limits
    - Optional per-client rate limiting

    Args:
        requests_per_second: Maximum requests per second (default: 1.0)
        requests_per_minute: Maximum requests per minute (default: 60)
        burst_size: Maximum burst requests allowed (default: 10)
        max_retries: Maximum retry attempts for 429 responses (default: 5)
        base_delay: Base delay for exponential backoff in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 60.0)
        backoff_multiplier: Multiplier for exponential backoff (default: 2.0)
        client_id_func: Optional function to extract client ID from function args
        manager: Optional custom ThrottleManager instance

    Returns:
        Decorated function with throttling and retry logic

    Example:
        @throttle(requests_per_second=0.5, max_retries=3)
        def search_tracks(self, query: str, limit: int = 10):
            return self._spotify.search(q=query, type="track", limit=limit)
    """

    # Use provided manager or create a new one
    if manager is None:
        manager = ThrottleManager(
            requests_per_second=requests_per_second,
            requests_per_minute=requests_per_minute,
            burst_size=burst_size,
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            backoff_multiplier=backoff_multiplier,
        )

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Extract client ID if function provided
            client_id = None
            if client_id_func:
                try:
                    client_id = client_id_func(*args, **kwargs)
                except Exception:
                    pass  # Ignore errors in client ID extraction

            last_exception = None

            for attempt in range(manager.max_retries + 1):
                try:
                    # Wait for available slot before making request
                    manager.wait_for_slot(client_id)

                    # Consume token and make request
                    manager.consume_token(client_id)

                    result = func(*args, **kwargs)

                    return result

                except spotipy.SpotifyException as e:
                    last_exception = e

                    # Handle different types of Spotify exceptions
                    if e.http_status == 429:  # Too Many Requests
                        if attempt >= manager.max_retries:
                            break

                        # Extract retry-after header if available
                        retry_after = getattr(e, "retry_after", None)
                        if not retry_after and hasattr(e, "headers"):
                            retry_after = e.headers.get("Retry-After")

                        delay = manager.calculate_retry_delay(attempt, retry_after)

                        time.sleep(delay)
                        continue

                    elif e.http_status in [500, 502, 503, 504]:  # Server errors
                        if attempt >= manager.max_retries:
                            break

                        delay = manager.calculate_retry_delay(attempt)

                        time.sleep(delay)
                        continue

                    else:
                        # Other errors (4xx client errors) - don't retry
                        raise

                except Exception as e:
                    last_exception = e

                    # For non-Spotify exceptions, only retry on connection-related errors
                    if any(
                        error_type in str(type(e)).lower()
                        for error_type in ["connection", "timeout", "network"]
                    ):
                        if attempt >= manager.max_retries:
                            break

                        delay = manager.calculate_retry_delay(attempt)

                        time.sleep(delay)
                        continue
                    else:
                        # Non-retryable error
                        raise

            # All retries exhausted
            if last_exception:
                raise last_exception

            # This should never happen, but just in case
            raise RuntimeError(
                f"Unexpected error in throttled function {func.__name__}"
            )

        return wrapper  # type: ignore

    return decorator


def spotify_throttle(
    requests_per_second: float = 0.5,
    requests_per_minute: int = 30,
    burst_size: int = 5,
    max_retries: int = 5,
    **kwargs,
) -> Callable[[F], F]:
    """
    Specialized throttle decorator optimized for Spotify API rate limits.

    Spotify's rate limits are not officially documented but are generally:
    - Around 100 requests per minute for most endpoints
    - Burst handling varies by endpoint
    - 429 responses include Retry-After headers

    This decorator uses conservative defaults to avoid hitting rate limits.

    Args:
        requests_per_second: Max requests per second (default: 0.5 for Spotify)
        requests_per_minute: Max requests per minute (default: 30 for Spotify)
        burst_size: Max burst requests (default: 5 for Spotify)
        max_retries: Maximum retry attempts (default: 5)
        **kwargs: Additional arguments passed to throttle decorator

    Returns:
        Decorated function with Spotify-optimized throttling
    """
    return throttle(
        requests_per_second=requests_per_second,
        requests_per_minute=requests_per_minute,
        burst_size=burst_size,
        max_retries=max_retries,
        **kwargs,
    )
