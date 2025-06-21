import json
import os
from unittest.mock import Mock, mock_open, patch

import pytest

from spo.youtube_music_client import YouTubeMusicClient


@pytest.fixture
def patch_env():
    with patch.dict(
        os.environ,
        {"YTMUSIC_CLIENT_SECRET": "test_secret"},
    ):
        yield


@pytest.fixture
def mock_ytmusic():
    with patch("spo.youtube_music_client.YTMusic") as mock_ytmusic:
        yield mock_ytmusic


@pytest.fixture
def mock_setup_oauth():
    with patch("ytmusicapi.setup_oauth") as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_headers_file():
    headers_data = {
        "cookie": "test_cookie",
        "x-goog-authuser": "0",
        "x-goog-visitor-id": "test_visitor",
    }
    return json.dumps(headers_data)


@pytest.fixture
def mock_oauth_file():
    oauth_data = {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "token_type": "Bearer",
    }
    return json.dumps(oauth_data)


@pytest.fixture
def authenticated_client(mock_ytmusic):
    # Mock YTMusic client
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    # Mock successful authentication
    with patch("os.path.exists", return_value=True):
        with patch(
            "builtins.open",
            mock_open(read_data='{"name": "Test User", "email": "test@example.com"}'),
        ):
            client = YouTubeMusicClient()

    return client


# --- Authentication tests ---


@patch.dict(os.environ, {}, clear=True)
def test_missing_credentials_raises_error():
    with patch("os.path.exists", return_value=False):
        with pytest.raises(Exception, match="YouTube Music authentication required"):
            YouTubeMusicClient()


def test_oauth_authentication_success(mock_ytmusic, mock_oauth_file):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    with patch(
        "os.path.exists", side_effect=lambda path: path == ".ytmusic_oauth.json"
    ):
        with patch("builtins.open", mock_open(read_data=mock_oauth_file)):
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    mock_ytmusic.assert_called_once_with(".ytmusic_oauth.json")


def test_oauth_authentication_failure_falls_back_to_headers(
    mock_ytmusic, mock_headers_file
):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    # First call fails (OAuth), second succeeds (headers)
    def mock_exists(path):
        if path == ".ytmusic_oauth.json":
            return True
        elif path == ".ytmusic_headers.json":
            return True
        return False

    with patch("os.path.exists", side_effect=mock_exists):
        with patch("builtins.open", mock_open(read_data=mock_headers_file)):
            # Mock OAuth failure
            mock_ytmusic.side_effect = [Exception("OAuth failed"), mock_client]
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    assert mock_ytmusic.call_count == 2


def test_browser_headers_authentication_success(mock_ytmusic, mock_headers_file):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    with patch(
        "os.path.exists", side_effect=lambda path: path == ".ytmusic_headers.json"
    ):
        with patch("builtins.open", mock_open(read_data=mock_headers_file)):
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    mock_ytmusic.assert_called_once()


def test_browser_json_auto_copy_success(mock_ytmusic):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    browser_headers = {
        "Cookie": "test_cookie",
        "X-Goog-AuthUser": "0",
        "X-Goog-Visitor-Id": "test_visitor",
    }

    def mock_exists(path):
        if path == ".ytmusic_headers.json":
            return False
        elif path == "browser.json":
            return True
        return False

    with patch("os.path.exists", side_effect=mock_exists):
        with patch("builtins.open", mock_open(read_data=json.dumps(browser_headers))):
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    mock_ytmusic.assert_called_once()


def test_browser_json_auto_copy_failure_falls_back(mock_ytmusic):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    def mock_exists(path):
        if path == ".ytmusic_headers.json":
            return False
        elif path == "browser.json":
            return True
        return False

    with patch("os.path.exists", side_effect=mock_exists):
        with patch("builtins.open", side_effect=Exception("File read error")):
            # Should fall back to OAuth setup attempt
            with patch("ytmusicapi.setup_oauth") as mock_setup:
                mock_setup.side_effect = Exception("OAuth setup failed")
                with pytest.raises(
                    Exception, match="YouTube Music authentication required"
                ):
                    YouTubeMusicClient()


def test_oauth_setup_with_client_secret(mock_ytmusic, mock_setup_oauth):
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {"YTMUSIC_CLIENT_SECRET": "test_secret"}):
            mock_setup_oauth.return_value = None
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    mock_setup_oauth.assert_called_once_with(".ytmusic_oauth.json", "test_secret")


def test_oauth_setup_without_client_secret(mock_ytmusic):
    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                Exception, match="YouTube Music authentication required"
            ):
                YouTubeMusicClient()


def test_oauth_setup_failure(mock_ytmusic, mock_setup_oauth):
    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {"YTMUSIC_CLIENT_SECRET": "test_secret"}):
            mock_setup_oauth.side_effect = Exception("OAuth setup failed")
            with pytest.raises(
                Exception, match="YouTube Music authentication required"
            ):
                YouTubeMusicClient()


def test_oauth_setup_success_and_client_creation(mock_ytmusic, mock_setup_oauth):
    """Test OAuth setup success and subsequent client creation."""
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {"YTMUSIC_CLIENT_SECRET": "test_secret"}):
            # Mock successful OAuth setup
            mock_setup_oauth.return_value = None
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    mock_setup_oauth.assert_called_once_with(".ytmusic_oauth.json", "test_secret")
    # Verify that YTMusic was called with the OAuth path after successful setup
    assert mock_ytmusic.call_count == 1
    mock_ytmusic.assert_called_with(".ytmusic_oauth.json")


# --- Property tests ---


def test_is_authenticated_property(authenticated_client):
    assert authenticated_client.is_authenticated is True


def test_is_authenticated_property_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None
    assert client.is_authenticated is False


def test_current_user_property(authenticated_client):
    user = authenticated_client.current_user
    assert user["name"] == "YouTube Music User"
    assert user["email"] == "N/A"


def test_current_user_property_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None

    with pytest.raises(Exception, match="Client is not authenticated"):
        _ = client.current_user


def test_user_info_property(authenticated_client):
    info = authenticated_client.user_info
    assert info == "YouTube Music User (N/A)"


def test_user_info_property_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None

    with pytest.raises(Exception, match="Client is not authenticated"):
        _ = client.user_info


# --- API method tests ---


def test_search_tracks_success(authenticated_client):
    mock_results = [
        {
            "videoId": "test_video_id",
            "title": "Test Song",
            "artists": [{"name": "Test Artist"}],
            "album": {"name": "Test Album"},
            "duration": "3:30",
        }
    ]
    authenticated_client._ytmusic.search.return_value = mock_results

    results = authenticated_client.search_tracks("test query", limit=5)

    assert len(results) == 1
    assert results[0]["videoId"] == "test_video_id"
    assert results[0]["title"] == "Test Song"
    assert results[0]["artist"] == "Test Artist"
    assert results[0]["album"] == "Test Album"
    assert results[0]["duration"] == "3:30"

    authenticated_client._ytmusic.search.assert_called_once_with(
        "test query", filter="songs", limit=5
    )


def test_search_tracks_no_results(authenticated_client):
    authenticated_client._ytmusic.search.return_value = []

    results = authenticated_client.search_tracks("nonexistent query")

    assert results == []


def test_search_tracks_error(authenticated_client):
    authenticated_client._ytmusic.search.side_effect = Exception("API Error")

    results = authenticated_client.search_tracks("test query")

    assert results == []


def test_search_tracks_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None

    with pytest.raises(Exception, match="Client is not authenticated"):
        client.search_tracks("test query")


def test_search_tracks_malformed_response(authenticated_client):
    # Test with missing fields
    mock_results = [
        {
            "videoId": "test_video_id",
            "title": "Test Song",
            # Missing artists and album
        }
    ]
    authenticated_client._ytmusic.search.return_value = mock_results

    results = authenticated_client.search_tracks("test query")

    assert len(results) == 1
    assert results[0]["videoId"] == "test_video_id"
    assert results[0]["title"] == "Test Song"
    assert results[0]["artist"] == "Unknown"
    assert results[0]["album"] == "Unknown"


def test_get_user_playlists_success(authenticated_client):
    mock_playlists = [
        {
            "playlistId": "playlist1",
            "title": "Test Playlist 1",
            "count": 10,
        },
        {
            "playlistId": "playlist2",
            "title": "Test Playlist 2",
            "count": 5,
        },
    ]
    authenticated_client._ytmusic.get_library_playlists.return_value = mock_playlists

    results = authenticated_client.get_user_playlists(limit=5)

    assert len(results) == 2
    assert results[0]["playlistId"] == "playlist1"
    assert results[0]["title"] == "Test Playlist 1"
    assert results[0]["trackCount"] == 10
    assert results[1]["playlistId"] == "playlist2"
    assert results[1]["title"] == "Test Playlist 2"
    assert results[1]["trackCount"] == 5

    authenticated_client._ytmusic.get_library_playlists.assert_called_once_with(limit=5)


def test_get_user_playlists_no_results(authenticated_client):
    authenticated_client._ytmusic.get_library_playlists.return_value = []

    results = authenticated_client.get_user_playlists()

    assert results == []


def test_get_user_playlists_error(authenticated_client):
    authenticated_client._ytmusic.get_library_playlists.side_effect = Exception(
        "API Error"
    )

    results = authenticated_client.get_user_playlists()

    assert results == []


def test_get_user_playlists_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None

    with pytest.raises(Exception, match="Client is not authenticated"):
        client.get_user_playlists()


def test_get_user_saved_tracks_success(authenticated_client):
    mock_liked_songs = {
        "tracks": [
            {
                "videoId": "video1",
                "title": "Liked Song 1",
                "artists": [{"name": "Artist 1"}],
                "album": {"name": "Album 1"},
                "duration": "3:45",
            },
            {
                "videoId": "video2",
                "title": "Liked Song 2",
                "artists": [{"name": "Artist 2"}],
                "album": {"name": "Album 2"},
                "duration": "4:20",
            },
        ]
    }
    authenticated_client._ytmusic.get_liked_songs.return_value = mock_liked_songs

    results = authenticated_client.get_user_saved_tracks(limit=10)

    assert len(results) == 2
    assert results[0]["videoId"] == "video1"
    assert results[0]["title"] == "Liked Song 1"
    assert results[0]["artist"] == "Artist 1"
    assert results[0]["album"] == "Album 1"
    assert results[0]["duration"] == "3:45"
    assert results[1]["videoId"] == "video2"
    assert results[1]["title"] == "Liked Song 2"
    assert results[1]["artist"] == "Artist 2"
    assert results[1]["album"] == "Album 2"
    assert results[1]["duration"] == "4:20"

    authenticated_client._ytmusic.get_liked_songs.assert_called_once_with(limit=10)


def test_get_user_saved_tracks_no_results(authenticated_client):
    mock_liked_songs = {"tracks": []}
    authenticated_client._ytmusic.get_liked_songs.return_value = mock_liked_songs

    results = authenticated_client.get_user_saved_tracks()

    assert results == []


def test_get_user_saved_tracks_error(authenticated_client):
    authenticated_client._ytmusic.get_liked_songs.side_effect = Exception("API Error")

    results = authenticated_client.get_user_saved_tracks()

    assert results == []


def test_get_user_saved_tracks_unauthenticated():
    client = YouTubeMusicClient.__new__(YouTubeMusicClient)
    client._ytmusic = None
    client._user = None

    with pytest.raises(Exception, match="Client is not authenticated"):
        client.get_user_saved_tracks()


def test_get_user_saved_tracks_invalid_response_type(authenticated_client):
    # Test when get_liked_songs returns non-dict
    authenticated_client._ytmusic.get_liked_songs.return_value = "invalid_response"

    results = authenticated_client.get_user_saved_tracks()

    assert results == []


def test_get_user_saved_tracks_missing_tracks_key(authenticated_client):
    # Test when response dict doesn't have 'tracks' key
    authenticated_client._ytmusic.get_liked_songs.return_value = {"other_key": "value"}

    results = authenticated_client.get_user_saved_tracks()

    assert results == []


def test_get_user_saved_tracks_tracks_not_list(authenticated_client):
    # Test when 'tracks' is not a list
    authenticated_client._ytmusic.get_liked_songs.return_value = {
        "tracks": "not_a_list"
    }

    results = authenticated_client.get_user_saved_tracks()

    assert results == []


def test_get_user_saved_tracks_malformed_track_item(authenticated_client):
    # Test with malformed track items
    mock_liked_songs = {
        "tracks": [
            {
                "videoId": "video1",
                "title": "Valid Song",
                "artists": [{"name": "Artist 1"}],
                "album": {"name": "Album 1"},
                "duration": "3:45",
            },
            "invalid_track_item",  # This should be skipped
            {
                "videoId": "video2",
                "title": "Another Valid Song",
                "artists": [{"name": "Artist 2"}],
                "album": {"name": "Album 2"},
                "duration": "4:20",
            },
        ]
    }
    authenticated_client._ytmusic.get_liked_songs.return_value = mock_liked_songs

    results = authenticated_client.get_user_saved_tracks()

    assert len(results) == 2
    assert results[0]["title"] == "Valid Song"
    assert results[1]["title"] == "Another Valid Song"


def test_get_user_saved_tracks_missing_fields(authenticated_client):
    # Test with missing fields in track items
    mock_liked_songs = {
        "tracks": [
            {
                "videoId": "video1",
                "title": "Test Song",
                # Missing artists and album
            }
        ]
    }
    authenticated_client._ytmusic.get_liked_songs.return_value = mock_liked_songs

    results = authenticated_client.get_user_saved_tracks()

    assert len(results) == 1
    assert results[0]["videoId"] == "video1"
    assert results[0]["title"] == "Test Song"
    assert results[0]["artist"] == "Unknown"
    assert results[0]["album"] == "Unknown"


# --- Integration tests ---


@pytest.mark.integration
def test_full_authentication_flow(mock_ytmusic, mock_headers_file):
    """Test the complete authentication flow with browser headers."""
    mock_client = Mock()
    mock_ytmusic.return_value = mock_client

    with patch(
        "os.path.exists", side_effect=lambda path: path == ".ytmusic_headers.json"
    ):
        with patch("builtins.open", mock_open(read_data=mock_headers_file)):
            client = YouTubeMusicClient()

    assert client.is_authenticated is True
    assert client.user_info == "YouTube Music User (N/A)"


@pytest.mark.integration
def test_api_methods_work_together(authenticated_client):
    """Test that all API methods work together properly."""
    # Mock search results
    mock_search_results = [
        {
            "videoId": "search_video_id",
            "title": "Search Result",
            "artists": [{"name": "Search Artist"}],
            "album": {"name": "Search Album"},
            "duration": "3:00",
        }
    ]
    authenticated_client._ytmusic.search.return_value = mock_search_results

    # Mock playlist results
    mock_playlist_results = [
        {
            "playlistId": "test_playlist",
            "title": "Test Playlist",
            "count": 5,
        }
    ]
    authenticated_client._ytmusic.get_library_playlists.return_value = (
        mock_playlist_results
    )

    # Mock liked songs results
    mock_liked_results = {
        "tracks": [
            {
                "videoId": "liked_video_id",
                "title": "Liked Song",
                "artists": [{"name": "Liked Artist"}],
                "album": {"name": "Liked Album"},
                "duration": "4:00",
            }
        ]
    }
    authenticated_client._ytmusic.get_liked_songs.return_value = mock_liked_results

    # Test all methods work
    search_results = authenticated_client.search_tracks("test query")
    playlist_results = authenticated_client.get_user_playlists()
    liked_results = authenticated_client.get_user_saved_tracks()

    assert len(search_results) == 1
    assert len(playlist_results) == 1
    assert len(liked_results) == 1

    assert search_results[0]["title"] == "Search Result"
    assert playlist_results[0]["title"] == "Test Playlist"
    assert liked_results[0]["title"] == "Liked Song"


# --- Edge case tests ---


def test_headers_normalization():
    """Test that browser headers are properly normalized to lowercase."""
    browser_headers = {
        "Cookie": "test_cookie",
        "X-Goog-AuthUser": "0",
        "X-Goog-Visitor-Id": "test_visitor",
    }

    expected_normalized = {
        "cookie": "test_cookie",
        "x-goog-authuser": "0",
        "x-goog-visitor-id": "test_visitor",
    }

    with patch("os.path.exists", side_effect=lambda path: path == "browser.json"):
        with patch("builtins.open", mock_open(read_data=json.dumps(browser_headers))):
            with patch("json.dump") as mock_dump:
                with patch("spo.youtube_music_client.YTMusic") as mock_ytmusic:
                    mock_client = Mock()
                    mock_ytmusic.return_value = mock_client
                    YouTubeMusicClient()

                    # Check that headers were normalized
                    mock_dump.assert_called_once()
                    call_args = mock_dump.call_args[0][0]
                    assert call_args == expected_normalized


def test_environment_variable_paths():
    """Test that environment variables for paths are respected."""
    with patch.dict(
        os.environ,
        {
            "YTMUSIC_HEADERS_PATH": "/custom/headers.json",
            "YTMUSIC_OAUTH_PATH": "/custom/oauth.json",
        },
    ):
        client = YouTubeMusicClient.__new__(YouTubeMusicClient)
        # Initialize the attributes that would be set in __init__
        client._headers_path = os.getenv(
            "YTMUSIC_HEADERS_PATH", ".ytmusic_headers.json"
        )
        client._oauth_path = os.getenv("YTMUSIC_OAUTH_PATH", ".ytmusic_oauth.json")
        assert client._headers_path == "/custom/headers.json"
        assert client._oauth_path == "/custom/oauth.json"


def test_default_paths():
    """Test that default paths are used when environment variables are not set."""
    with patch.dict(os.environ, {}, clear=True):
        client = YouTubeMusicClient.__new__(YouTubeMusicClient)
        # Initialize the attributes that would be set in __init__
        client._headers_path = os.getenv(
            "YTMUSIC_HEADERS_PATH", ".ytmusic_headers.json"
        )
        client._oauth_path = os.getenv("YTMUSIC_OAUTH_PATH", ".ytmusic_oauth.json")
        assert client._headers_path == ".ytmusic_headers.json"
        assert client._oauth_path == ".ytmusic_oauth.json"
