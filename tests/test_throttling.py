import time
from unittest.mock import Mock, patch

import pytest
import spotipy

from spo.throttling import ThrottleManager, spotify_throttle, throttle


@pytest.fixture
def manager():
    """Create a test ThrottleManager instance."""
    return ThrottleManager(
        requests_per_second=2.0,
        requests_per_minute=10,
        burst_size=5,
        max_retries=3,
        base_delay=0.1,
        max_delay=1.0,
    )


@pytest.fixture
def mock_manager():
    """Create a mock ThrottleManager for testing."""
    manager = Mock(spec=ThrottleManager)
    manager.max_retries = 2
    manager.wait_for_slot = Mock()
    manager.consume_token = Mock()
    manager.calculate_retry_delay = Mock(return_value=0.01)
    return manager


# --- ThrottleManager tests ---


def test_token_bucket_initialization(manager):
    assert manager.tokens == 5.0
    assert manager.burst_size == 5
    assert manager.requests_per_second == 2.0


def test_can_make_request_initial(manager):
    assert manager.can_make_request() is True


def test_token_consumption(manager):
    initial_tokens = manager.tokens
    manager.consume_token()
    assert manager.tokens == initial_tokens - 1.0


def test_token_refill(manager):
    for _ in range(5):
        manager.consume_token()
    assert manager.tokens == 0.0
    time.sleep(0.6)
    manager._refill_tokens()
    assert manager.tokens >= 1.0


def test_request_tracking(manager):
    manager.consume_token()
    assert len(manager.request_times) == 1
    for _ in range(3):
        manager.consume_token()
    assert len(manager.request_times) == 4


def test_old_request_cleanup(manager):
    now = time.time()
    manager.request_times.append(now - 120)
    manager.request_times.append(now - 30)
    manager.request_times.append(now)
    manager._clean_old_requests(manager.request_times)
    assert len(manager.request_times) == 2


def test_retry_delay_calculation(manager):
    delay1 = manager.calculate_retry_delay(0)
    assert delay1 >= 0.1
    delay2 = manager.calculate_retry_delay(1)
    assert delay2 > delay1
    delay_max = manager.calculate_retry_delay(10)
    assert delay_max <= manager.max_delay + 0.3


def test_retry_after_header(manager):
    delay = manager.calculate_retry_delay(0, retry_after="5")
    assert delay == 5.0
    delay = manager.calculate_retry_delay(0, retry_after=3)
    assert delay == 3.0


# --- Throttle decorator tests ---


def test_successful_request(mock_manager):
    call_count = 0

    @throttle(manager=mock_manager)
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        return {"success": True}

    result = mock_api_call()
    assert result == {"success": True}
    assert call_count == 1
    mock_manager.wait_for_slot.assert_called_once()
    mock_manager.consume_token.assert_called_once()


def test_retry_on_429(mock_manager):
    call_count = 0

    @throttle(manager=mock_manager)
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            error = spotipy.SpotifyException(
                http_status=429, code=-1, msg="Rate limit exceeded"
            )
            raise error
        return {"success": True}

    result = mock_api_call()
    assert result == {"success": True}
    assert call_count == 2
    assert mock_manager.wait_for_slot.call_count == 2
    assert mock_manager.consume_token.call_count == 2


def test_retry_exhaustion(mock_manager):
    call_count = 0

    @throttle(manager=mock_manager)
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        error = spotipy.SpotifyException(
            http_status=429, code=-1, msg="Rate limit exceeded"
        )
        raise error

    with pytest.raises(spotipy.SpotifyException):
        mock_api_call()
    assert call_count == mock_manager.max_retries + 1


def test_no_retry_on_4xx_errors(mock_manager):
    call_count = 0

    @throttle(manager=mock_manager)
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        error = spotipy.SpotifyException(http_status=400, code=-1, msg="Bad request")
        raise error

    with pytest.raises(spotipy.SpotifyException):
        mock_api_call()
    assert call_count == 1


def test_retry_on_5xx_errors(mock_manager):
    call_count = 0

    @throttle(manager=mock_manager)
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            error = spotipy.SpotifyException(
                http_status=500, code=-1, msg="Internal server error"
            )
            raise error
        return {"success": True}

    result = mock_api_call()
    assert result == {"success": True}
    assert call_count == 2


# --- Spotify throttle decorator tests ---


def test_spotify_defaults():
    call_count = 0

    @spotify_throttle()
    def mock_spotify_call():
        nonlocal call_count
        call_count += 1
        return {"tracks": {"items": []}}

    result = mock_spotify_call()
    assert call_count == 1
    assert "tracks" in result


@patch("time.sleep")
def test_rate_limiting_behavior(mock_sleep):
    call_times = []

    @spotify_throttle(requests_per_second=1.0)
    def mock_spotify_call():
        call_times.append(time.time())
        return {"success": True}

    for _ in range(3):
        mock_spotify_call()
    assert len(call_times) == 3


# --- Integration tests ---


@pytest.mark.integration
def test_throttle_manager_integration():
    manager = ThrottleManager(
        requests_per_second=5.0,
        requests_per_minute=20,
        burst_size=3,
        max_retries=2,
        base_delay=0.01,
        max_delay=0.1,
    )
    call_count = 0

    @throttle(manager=manager)
    def test_function():
        nonlocal call_count
        call_count += 1
        return f"call_{call_count}"

    results = []
    for i in range(5):
        result = test_function()
        results.append(result)
    assert len(results) == 5
    assert call_count == 5
    assert results[0] == "call_1"
    assert results[4] == "call_5"


@pytest.mark.integration
def test_concurrent_client_support():
    manager = ThrottleManager(
        requests_per_second=2.0, requests_per_minute=10, burst_size=2
    )

    def client_id_extractor(*args, **kwargs):
        return kwargs.get("client_id", "default")

    call_counts: dict[str | None, int] = {}

    @throttle(manager=manager, client_id_func=client_id_extractor)
    def test_function(client_id=None):
        call_counts[client_id] = call_counts.get(client_id, 0) + 1
        return f"client_{client_id}_call_{call_counts[client_id]}"

    result1 = test_function(client_id="client1")
    result2 = test_function(client_id="client2")
    result3 = test_function(client_id="client1")
    assert result1 == "client_client1_call_1"
    assert result2 == "client_client2_call_1"
    assert result3 == "client_client1_call_2"
    assert call_counts["client1"] == 2
    assert call_counts["client2"] == 1
