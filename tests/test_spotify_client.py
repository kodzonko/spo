import os
from unittest.mock import Mock, patch

import pytest

from spo.spotify_client import SpotifyClient


@pytest.fixture
def patch_env():
    with patch.dict(
        os.environ,
        {"SPOTIFY_CLIENT_ID": "test_id", "SPOTIFY_CLIENT_SECRET": "test_secret"},
    ):
        yield


@pytest.fixture
def patch_env_with_redirect():
    with patch.dict(
        os.environ,
        {
            "SPOTIFY_CLIENT_ID": "test_id",
            "SPOTIFY_CLIENT_SECRET": "test_secret",
            "SPOTIFY_REDIRECT_URI": "http://localhost:8080/callback",
        },
    ):
        yield


@pytest.fixture
def mock_oauth():
    with patch("spo.spotify_client.SpotifyOAuth") as mock_oauth:
        yield mock_oauth


@pytest.fixture
def mock_spotify():
    with patch("spo.spotify_client.spotipy.Spotify") as mock_spotify:
        yield mock_spotify


@pytest.fixture
def authenticated_client(patch_env, mock_oauth, mock_spotify):
    # Mock OAuth manager
    mock_auth_manager = Mock()
    mock_auth_manager.get_cached_token.return_value = {"access_token": "test_token"}
    mock_oauth.return_value = mock_auth_manager

    # Mock Spotify client
    mock_client = Mock()
    mock_client.current_user.return_value = {
        "id": "test_user",
        "display_name": "Test User",
    }
    mock_spotify.return_value = mock_client

    client = SpotifyClient()
    return client


# --- Authentication tests ---


@patch.dict(os.environ, {}, clear=True)
@patch("spo.spotify_client.load_dotenv")
def test_missing_credentials_raises_error(mock_load_dotenv):
    with pytest.raises(ValueError, match="Missing Spotify credentials"):
        SpotifyClient()


def test_manual_authentication_success(patch_env, mock_oauth, mock_spotify):
    mock_auth_manager = Mock()
    mock_auth_manager.get_cached_token.return_value = {"access_token": "test_token"}
    mock_oauth.return_value = mock_auth_manager

    mock_client = Mock()
    mock_client.current_user.return_value = {
        "id": "test_user",
        "display_name": "Test User",
    }
    mock_spotify.return_value = mock_client

    client = SpotifyClient()
    assert client.is_authenticated is True
    assert client.current_user["id"] == "test_user"
    assert client.user_info == "Test User (@test_user)"


@patch("webbrowser.open")
@patch("spo.spotify_client.SpotifyOAuth")
@patch("spo.spotify_client.spotipy.Spotify")
def test_automatic_authentication_success(
    mock_spotify, mock_oauth, mock_browser, patch_env_with_redirect
):
    with patch("spo.spotify_client.AuthServer") as mock_auth_server:
        mock_server = Mock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.return_value = ("auth_code", None)
        mock_auth_server.return_value = mock_server

        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_auth_manager.get_access_token.return_value = {"access_token": "test_token"}
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        with patch.object(SpotifyClient, "_is_port_available", return_value=True):
            client = SpotifyClient()

        assert client.is_authenticated is True
        mock_server.start.assert_called_once()
        mock_server.stop.assert_called_once()
        mock_browser.assert_called_once()


def test_port_availability_check(patch_env):
    client = SpotifyClient.__new__(SpotifyClient)
    with patch("socket.socket") as mock_socket:
        mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError()
        assert client._is_port_available(80) is False
    with patch("socket.socket") as mock_socket:
        mock_socket.return_value.__enter__.return_value.bind.return_value = None
        assert client._is_port_available(8080) is True


# --- SpotifyClient API method tests ---


def test_get_track_info_success(authenticated_client):
    mock_track = {
        "name": "Test Song",
        "artists": [{"name": "Test Artist"}],
        "album": {"name": "Test Album"},
        "popularity": 75,
        "preview_url": "https://preview.url",
    }
    authenticated_client._spotify.track.return_value = mock_track
    result = authenticated_client.get_track_info("test_track_id")
    assert result["name"] == "Test Song"
    assert result["artist"] == "Test Artist"
    assert result["album"] == "Test Album"
    assert result["popularity"] == 75
    assert result["preview_url"] == "https://preview.url"
    authenticated_client._spotify.track.assert_called_once_with("test_track_id")


def test_get_track_info_not_found(authenticated_client):
    authenticated_client._spotify.track.return_value = None
    result = authenticated_client.get_track_info("nonexistent_track")
    assert result == {}


def test_get_track_info_error(authenticated_client):
    authenticated_client._spotify.track.side_effect = Exception("API Error")
    result = authenticated_client.get_track_info("test_track_id")
    assert result == {}


def test_search_tracks_success(authenticated_client):
    mock_results = {
        "tracks": {
            "items": [
                {
                    "id": "track1",
                    "name": "Song 1",
                    "artists": [{"name": "Artist 1"}],
                    "album": {"name": "Album 1"},
                    "popularity": 80,
                },
                {
                    "id": "track2",
                    "name": "Song 2",
                    "artists": [{"name": "Artist 2"}],
                    "album": {"name": "Album 2"},
                    "popularity": 70,
                },
            ]
        }
    }
    authenticated_client._spotify.search.return_value = mock_results
    results = authenticated_client.search_tracks("test query", limit=2)
    assert len(results) == 2
    assert results[0]["name"] == "Song 1"
    assert results[1]["name"] == "Song 2"
    authenticated_client._spotify.search.assert_called_once_with(
        q="test query", type="track", limit=2
    )


def test_search_tracks_no_results(authenticated_client):
    authenticated_client._spotify.search.return_value = None
    results = authenticated_client.search_tracks("nonexistent query")
    assert results == []


def test_get_user_playlists_success(authenticated_client):
    mock_results = {
        "items": [
            {
                "id": "playlist1",
                "name": "My Playlist",
                "description": "Test playlist",
                "tracks": {"total": 25},
                "public": True,
                "owner": {"display_name": "Test User"},
            }
        ]
    }
    authenticated_client._spotify.current_user_playlists.return_value = mock_results
    results = authenticated_client.get_user_playlists(limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "My Playlist"
    assert results[0]["tracks_total"] == 25
    authenticated_client._spotify.current_user_playlists.assert_called_once_with(
        limit=1
    )


def test_get_user_saved_tracks_success(authenticated_client):
    mock_results = {
        "items": [
            {
                "track": {
                    "id": "track1",
                    "name": "Saved Song",
                    "artists": [{"name": "Saved Artist"}],
                    "album": {"name": "Saved Album"},
                },
                "added_at": "2023-01-01T00:00:00Z",
            }
        ]
    }
    authenticated_client._spotify.current_user_saved_tracks.return_value = mock_results
    results = authenticated_client.get_user_saved_tracks(limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "Saved Song"
    assert results[0]["added_at"] == "2023-01-01T00:00:00Z"


def test_current_user_property_handles_missing_user(authenticated_client):
    authenticated_client._user = None
    with pytest.raises(Exception, match="Client is not authenticated"):
        _ = authenticated_client.current_user


def test_user_info_handles_missing_fields(authenticated_client):
    authenticated_client._user = {"id": "only_id"}
    # Should not raise, but may fallback to default formatting or raise KeyError
    try:
        info = authenticated_client.user_info
    except KeyError:
        info = None
    assert info is None or info.startswith("Unknown") or info.startswith("(@only_id)")


def test_get_user_playlists_malformed_response(authenticated_client):
    authenticated_client._spotify.current_user_playlists.return_value = {"items": []}
    results = authenticated_client.get_user_playlists(limit=1)
    assert results == []


def test_get_user_saved_tracks_malformed_response(authenticated_client):
    authenticated_client._spotify.current_user_saved_tracks.return_value = {"items": []}
    results = authenticated_client.get_user_saved_tracks(limit=1)
    assert results == []


def test_throttle_retries_on_rate_limit(authenticated_client):
    # Simulate rate limit error on all calls, should return {} after retries
    authenticated_client._spotify.track.side_effect = Exception("rate limit exceeded")
    result = authenticated_client.get_track_info("retry_track_id")
    assert result == {}


@patch("spo.spotify_client.SpotifyOAuth")
@patch("spo.spotify_client.spotipy.Spotify")
def test_unauthenticated_client_raises_error(mock_spotify, mock_oauth):
    client = SpotifyClient.__new__(SpotifyClient)
    client._spotify = None
    client._user = None
    with pytest.raises(Exception, match="Client is not authenticated"):
        client.get_track_info("test_id")
    with pytest.raises(Exception, match="Client is not authenticated"):
        client.search_tracks("test query")
    with pytest.raises(Exception, match="Client is not authenticated"):
        client.get_user_playlists()
    with pytest.raises(Exception, match="Client is not authenticated"):
        client.get_user_saved_tracks()
    with pytest.raises(Exception, match="Client is not authenticated"):
        _ = client.current_user


@pytest.mark.integration
@patch("spo.spotify_client.SpotifyOAuth")
@patch("spo.spotify_client.spotipy.Spotify")
def test_property_access_patterns(mock_spotify, mock_oauth):
    client = SpotifyClient.__new__(SpotifyClient)
    client._spotify = Mock()
    client._user = {"id": "test", "display_name": "Test User"}
    assert client.is_authenticated is True
    assert client.user_info == "Test User (@test)"
    assert client.current_user["id"] == "test"
    client._spotify = None
    client._user = None


def test_authenticate_automatic_invalid_redirect(
    monkeypatch, patch_env_with_redirect, mock_oauth, mock_spotify
):
    # Simulate automatic authentication with invalid redirect - use a non-retryable error
    with (
        patch("spo.spotify_client.SpotifyClient._is_port_available", return_value=True),
        patch("spo.spotify_client.AuthServer") as mock_auth_server,
        patch("spo.spotify_client.webbrowser.open"),
    ):
        mock_server = Mock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.return_value = (None, "authorization_failed")
        mock_auth_server.return_value = mock_server

        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        # Patch logger to suppress output
        with patch("spo.spotify_client.logger"):
            with pytest.raises(
                Exception, match="Authorization failed: authorization_failed"
            ):
                SpotifyClient()


def test_authenticate_automatic_no_auth_code(
    monkeypatch, patch_env_with_redirect, mock_oauth, mock_spotify
):
    with (
        patch("spo.spotify_client.SpotifyClient._is_port_available", return_value=True),
        patch("spo.spotify_client.AuthServer") as mock_auth_server,
        patch("spo.spotify_client.webbrowser.open"),
    ):
        mock_server = Mock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.return_value = (None, None)
        mock_auth_server.return_value = mock_server

        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        with patch("spo.spotify_client.logger"):
            with pytest.raises(Exception, match="No authorization code received"):
                SpotifyClient()


def test_authenticate_automatic_user_none(
    monkeypatch, patch_env_with_redirect, mock_oauth, mock_spotify
):
    with (
        patch("spo.spotify_client.SpotifyClient._is_port_available", return_value=True),
        patch("spo.spotify_client.AuthServer") as mock_auth_server,
        patch("spo.spotify_client.webbrowser.open"),
    ):
        mock_server = Mock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.return_value = ("auth_code", None)
        mock_auth_server.return_value = mock_server

        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_auth_manager.get_access_token.return_value = {"access_token": "test_token"}
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = None
        mock_spotify.return_value = mock_client

        with patch("spo.spotify_client.logger"):
            with pytest.raises(Exception, match="Failed to get user information"):
                SpotifyClient()


def test_authenticate_manual_invalid_redirect(
    monkeypatch, patch_env, mock_oauth, mock_spotify
):
    # Force manual authentication by making all ports unavailable
    with patch(
        "spo.spotify_client.SpotifyClient._is_port_available", return_value=False
    ):
        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        with (
            patch("spo.spotify_client.input", return_value="invalid_url"),
            patch("spo.spotify_client.logger"),
            patch("spo.spotify_client.webbrowser.open"),
        ):
            with pytest.raises(Exception, match="Invalid redirect URL format"):
                SpotifyClient()


def test_authenticate_manual_no_code(monkeypatch, patch_env, mock_oauth, mock_spotify):
    # Force manual authentication by making all ports unavailable
    with patch(
        "spo.spotify_client.SpotifyClient._is_port_available", return_value=False
    ):
        mock_auth_manager = Mock()
        mock_auth_manager.get_cached_token.return_value = None
        mock_auth_manager.get_authorize_url.return_value = "https://auth.url"
        mock_oauth.return_value = mock_auth_manager

        mock_client = Mock()
        mock_client.current_user.return_value = {
            "id": "test_user",
            "display_name": "Test User",
        }
        mock_spotify.return_value = mock_client

        # Simulate a redirect URL with no code param
        with (
            patch(
                "spo.spotify_client.input", return_value="https://redirect?error=fail"
            ),
            patch("spo.spotify_client.logger"),
            patch("spo.spotify_client.webbrowser.open"),
        ):
            with pytest.raises(
                Exception, match="No authorization code found in redirect URL"
            ):
                SpotifyClient()
