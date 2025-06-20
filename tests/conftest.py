"""
Pytest configuration and shared fixtures.
"""

from unittest.mock import Mock

import pytest

from src.spo.throttling import ThrottleManager


@pytest.fixture
def throttle_manager():
    """Create a test ThrottleManager instance with fast settings."""
    return ThrottleManager(
        requests_per_second=10.0,  # Fast for testing
        requests_per_minute=100,
        burst_size=5,
        max_retries=2,
        base_delay=0.01,  # Very fast delays
        max_delay=0.1,
    )


@pytest.fixture
def mock_spotify_client():
    """Create a mock Spotify client for testing."""
    mock_client = Mock()
    mock_client.user_playlists.return_value = {
        "items": [
            {"id": "playlist1", "name": "Test Playlist 1"},
            {"id": "playlist2", "name": "Test Playlist 2"},
        ]
    }
    mock_client.playlist_tracks.return_value = {
        "items": [
            {
                "track": {
                    "id": "track1",
                    "name": "Test Song",
                    "artists": [{"name": "Test Artist"}],
                }
            }
        ]
    }
    return mock_client
