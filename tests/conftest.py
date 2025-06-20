import pytest
from unittest.mock import patch, Mock


@pytest.fixture(autouse=True)
def patch_spotify_auth_and_client(request):
    skip_for = {
        "test_missing_credentials_raises_error",
        "test_automatic_authentication_success",
    }
    if request.node.name in skip_for:
        yield
        return
    with (
        patch("spo.spotify_client.SpotifyOAuth") as mock_oauth,
        patch("spo.spotify_client.spotipy.Spotify") as mock_spotify,
    ):
        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = {"access_token": "test_token"}
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        yield


import sys
import os

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

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
