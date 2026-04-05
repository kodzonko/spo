"""Tests for the Spotify service adapter."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

import pytest
import spotipy

import spo.services.spotify as spotify_service
from spo.exceptions import AuthenticationError, RateLimitError
from spo.models import AccountIdentity, CollectionKind
from spo.services.spotify import SpotifyAdapter, sanitize_redirect_uri

if TYPE_CHECKING:
    from spo.config import Settings


def _make_adapter(
    settings: Settings,
    credential_payload: dict[str, Any] | None = None,
) -> SpotifyAdapter:
    payload = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "token_info": {
            "access_token": "access-token",
            "expires_at": int(time.time()) + 3600,
            "refresh_token": "refresh-token",
        },
    }
    if credential_payload is not None:
        payload.update(credential_payload)
    return SpotifyAdapter(
        account_id=1,
        credential_payload=payload,
        settings=settings,
    )


def test_build_authorize_url_and_exchange_code_use_expected_oauth_settings(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Spotify OAuth helper methods build requests using the default callback."""
    constructor_calls: list[dict[str, Any]] = []

    class FakeOAuth:
        def __init__(self, **kwargs: object) -> None:
            constructor_calls.append(kwargs)

        def get_authorize_url(self, *, state: str) -> str:
            return f"https://accounts.spotify.test/authorize?state={state}"

        def get_access_token(self, code: str, *, as_dict: bool, check_cache: bool) -> dict[str, Any]:
            assert code == "oauth-code"
            assert as_dict is True
            assert check_cache is False
            return {
                "access_token": "fresh-token",
                "refresh_token": "fresh-refresh-token",
                "expires_at": 1234,
            }

    monkeypatch.setattr(spotify_service, "SpotifyOAuth", FakeOAuth)

    credential_payload = {
        "client_id": "client-id",
        "client_secret": "client-secret",
    }

    authorize_url = SpotifyAdapter.build_authorize_url(settings, credential_payload, "state-123")
    exchanged_payload = SpotifyAdapter.exchange_code(
        settings=settings,
        credential_payload=credential_payload,
        code="oauth-code",
    )

    expected_redirect_uri = "http://127.0.0.1:8899/callback/spotify"

    assert authorize_url == "https://accounts.spotify.test/authorize?state=state-123"
    assert constructor_calls[0]["redirect_uri"] == expected_redirect_uri
    assert constructor_calls[0]["show_dialog"] is True
    assert constructor_calls[1]["redirect_uri"] == expected_redirect_uri
    assert exchanged_payload["token_info"]["access_token"] == "fresh-token"


def test_ensure_client_refreshes_expired_tokens_and_authenticate_caches_identity(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test expired Spotify tokens are refreshed once and the fetched identity is cached."""
    refreshed_token = {
        "access_token": "fresh-access-token",
        "refresh_token": "refresh-token",
        "expires_at": int(time.time()) + 3600,
    }
    spotify_request_timeout = 30
    refresh_calls: list[str] = []
    created_clients: list[FakeSpotifyClient] = []

    class FakeOAuth:
        def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
            refresh_calls.append(refresh_token)
            return refreshed_token

    class FakeSpotifyClient:
        def __init__(self, *, auth: str, requests_timeout: int, retries: int) -> None:
            self.auth = auth
            self.requests_timeout = requests_timeout
            self.retries = retries
            self.current_user_calls = 0

        def current_user(self) -> dict[str, str]:
            self.current_user_calls += 1
            return {"id": "spotify-user"}

    def fake_spotify_client(*, auth: str, requests_timeout: int, retries: int) -> FakeSpotifyClient:
        client = FakeSpotifyClient(auth=auth, requests_timeout=requests_timeout, retries=retries)
        created_clients.append(client)
        return client

    adapter = _make_adapter(
        settings,
        credential_payload={
            "token_info": {
                "access_token": "stale-access-token",
                "expires_at": 0,
                "refresh_token": "refresh-token",
            },
        },
    )

    def fake_oauth() -> FakeOAuth:
        return FakeOAuth()

    monkeypatch.setattr(adapter, "_oauth", fake_oauth)
    monkeypatch.setattr(spotify_service.spotipy, "Spotify", fake_spotify_client)

    first_identity = adapter.authenticate()
    second_identity = adapter.authenticate()

    assert first_identity is second_identity
    assert first_identity == AccountIdentity(
        remote_account_id="spotify-user",
        display_name="spotify-user",
    )
    assert refresh_calls == ["refresh-token"]
    assert adapter.credential_payload["token_info"] == refreshed_token
    assert len(created_clients) == 1
    assert created_clients[0].auth == "fresh-access-token"
    assert created_clients[0].requests_timeout == spotify_request_timeout
    assert created_clients[0].retries == 0
    assert created_clients[0].current_user_calls == 1


@pytest.mark.parametrize(
    ("credential_payload", "message"),
    [
        (
            {
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            "Spotify account is not authorized yet.",
        ),
        (
            {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "token_info": {
                    "access_token": "stale-access-token",
                    "expires_at": 0,
                },
            },
            "Spotify refresh token is missing.",
        ),
    ],
)
def test_ensure_client_requires_authorized_tokens(
    settings: Settings,
    credential_payload: dict[str, Any],
    message: str,
) -> None:
    """Test Spotify rejects missing authorization state before building the API client."""
    adapter = SpotifyAdapter(
        account_id=1,
        credential_payload=credential_payload,
        settings=settings,
    )
    ensure_client = adapter._ensure_client  # noqa: SLF001 - exercising auth guard behavior directly

    with pytest.raises(AuthenticationError, match=message):
        ensure_client()


def test_call_translates_spotify_rate_limit_and_authentication_errors(settings: Settings) -> None:
    """Test Spotipy exceptions are converted into application-level errors."""
    adapter = _make_adapter(settings)
    call = adapter._call  # noqa: SLF001 - exercising SDK-to-domain error translation directly

    def raise_rate_limit() -> None:
        raise spotipy.SpotifyException(
            http_status=429,
            code=-1,
            msg="Too many requests",
            headers={"Retry-After": "7"},
        )

    def raise_unauthorized() -> None:
        raise spotipy.SpotifyException(
            http_status=401,
            code=-1,
            msg="Unauthorized",
        )

    with pytest.raises(RateLimitError) as rate_limit_error:
        call(raise_rate_limit)

    assert rate_limit_error.value.retry_after == "7"

    with pytest.raises(AuthenticationError, match=re.escape("Spotify access token is invalid.")):
        call(raise_unauthorized)


def test_list_collection_and_playlist_items_transform_spotify_payloads(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Spotify collection reads normalize wrapped payloads and pagination cursors."""
    playlist_offset = 4
    playlist_page_size = 2
    single_item_page_size = 1

    class FakeClient:
        def current_user_playlists(self, *, limit: int, offset: int) -> dict[str, Any]:
            assert limit == playlist_page_size
            assert offset == playlist_offset
            return {
                "items": [{"id": "playlist-1"}],
                "next": "next-page",
            }

        def current_user_saved_tracks(self, *, limit: int, offset: int) -> dict[str, Any]:
            assert limit == playlist_page_size
            assert offset == 0
            return {
                "items": [
                    {"track": {"id": "track-1"}},
                    {"track": None},
                ],
                "next": None,
            }

        def current_user_saved_albums(self, *, limit: int, offset: int) -> dict[str, Any]:
            assert limit == single_item_page_size
            assert offset == single_item_page_size
            return {
                "items": [
                    {"album": {"id": "album-1"}},
                    {"album": None},
                ],
                "next": None,
            }

        def current_user_followed_artists(self, *, limit: int, after: str | None) -> dict[str, Any]:
            assert limit == playlist_page_size
            assert after == "cursor-1"
            return {
                "artists": {
                    "items": [{"id": "artist-1"}],
                    "cursors": {"after": "cursor-2"},
                },
            }

        def current_user_saved_shows(self, *, limit: int, offset: int) -> dict[str, Any]:
            assert limit == single_item_page_size
            assert offset == 0
            return {
                "items": [
                    {"show": {"id": "show-1"}},
                    {"show": None},
                ],
                "next": "next-page",
            }

        def current_user_saved_episodes(self, *, limit: int, offset: int) -> dict[str, Any]:
            assert limit == single_item_page_size
            assert offset == 0
            return {
                "items": [
                    {"episode": {"id": "episode-1"}},
                    {"episode": None},
                ],
                "next": None,
            }

        def playlist_items(
            self,
            playlist_id: str,
            *,
            limit: int,
            offset: int,
            additional_types: tuple[str, str],
        ) -> dict[str, Any]:
            assert playlist_id == "playlist-1"
            assert limit == playlist_page_size
            assert offset == 0
            assert additional_types == ("track", "episode")
            return {
                "items": [
                    {"track": {"id": "track-1"}},
                    {"track": None},
                ],
                "next": "next-page",
            }

    adapter = _make_adapter(settings)

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    playlist_page = adapter.list_collection(
        CollectionKind.PLAYLIST,
        cursor=str(playlist_offset),
        page_size=playlist_page_size,
    )
    saved_track_page = adapter.list_collection(CollectionKind.SAVED_TRACK, page_size=playlist_page_size)
    saved_album_page = adapter.list_collection(
        CollectionKind.SAVED_ALBUM,
        cursor=str(single_item_page_size),
        page_size=single_item_page_size,
    )
    followed_artist_page = adapter.list_collection(
        CollectionKind.FOLLOWED_ARTIST,
        cursor="cursor-1",
        page_size=playlist_page_size,
    )
    saved_podcast_page = adapter.list_collection(CollectionKind.SAVED_PODCAST, page_size=single_item_page_size)
    saved_episode_page = adapter.list_collection(CollectionKind.SAVED_EPISODE, page_size=single_item_page_size)
    playlist_items_page = adapter.get_playlist_items("playlist-1", page_size=playlist_page_size)

    assert playlist_page.items == [{"id": "playlist-1"}]
    assert playlist_page.next_cursor == "6"
    assert saved_track_page.items == [{"id": "track-1"}]
    assert saved_track_page.next_cursor is None
    assert saved_album_page.items == [{"id": "album-1"}]
    assert saved_album_page.next_cursor is None
    assert followed_artist_page.items == [{"id": "artist-1"}]
    assert followed_artist_page.next_cursor == "cursor-2"
    assert saved_podcast_page.items == [{"id": "show-1"}]
    assert saved_podcast_page.next_cursor == "1"
    assert saved_episode_page.items == [{"id": "episode-1"}]
    assert playlist_items_page.items == [{"id": "track-1"}]
    assert playlist_items_page.next_cursor == "2"


def test_search_and_create_playlist_use_spotify_specific_mappings(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Spotify search and playlist creation use the expected service mappings."""
    search_calls: list[dict[str, Any]] = []
    created_playlists: list[tuple[str, str, bool, str]] = []

    class FakeClient:
        def current_user(self) -> dict[str, str]:
            return {
                "id": "spotify-user",
                "display_name": "Spotify User",
            }

        def search(self, *, q: str, limit: int, **kwargs: object) -> dict[str, Any]:
            search_type = str(kwargs["type"])
            search_calls.append({"q": q, "type": search_type, "limit": limit})
            return {
                f"{search_type}s": {
                    "items": [{"id": f"{search_type}-1"}],
                },
            }

        def user_playlist_create(
            self,
            owner: str,
            name: str,
            *,
            public: bool,
            description: str,
        ) -> dict[str, str]:
            created_playlists.append((owner, name, public, description))
            return {"id": "playlist-1", "name": name}

    adapter = _make_adapter(settings)

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    search_results = adapter.search(CollectionKind.SAVED_PODCAST, "science", limit=25)
    playlist = adapter.create_playlist("Road Trip", "Songs for long drives")

    assert search_results == [{"id": "show-1"}]
    assert search_calls == [{"q": "science", "type": "show", "limit": 10}]
    assert playlist == {"id": "playlist-1", "name": "Road Trip"}
    assert created_playlists == [
        ("spotify-user", "Road Trip", False, "Songs for long drives"),
    ]


def test_write_methods_batch_spotify_requests(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Spotify write helpers respect the API batch sizes."""
    playlist_add_batches: list[list[str]] = []
    save_track_batches: list[list[str]] = []
    save_album_batches: list[list[str]] = []
    follow_artist_batches: list[list[str]] = []
    save_show_batches: list[list[str]] = []
    save_episode_batches: list[list[str]] = []

    class FakeClient:
        def playlist_add_items(self, playlist_id: str, item_ids: list[str]) -> None:
            assert playlist_id == "playlist-1"
            playlist_add_batches.append(list(item_ids))

        def current_user_saved_tracks_add(self, item_ids: list[str]) -> None:
            save_track_batches.append(list(item_ids))

        def current_user_saved_albums_add(self, item_ids: list[str]) -> None:
            save_album_batches.append(list(item_ids))

        def user_follow_artists(self, item_ids: list[str]) -> None:
            follow_artist_batches.append(list(item_ids))

        def current_user_saved_shows_add(self, item_ids: list[str]) -> None:
            save_show_batches.append(list(item_ids))

        def current_user_saved_episodes_add(self, item_ids: list[str]) -> None:
            save_episode_batches.append(list(item_ids))

    adapter = _make_adapter(settings)

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    adapter.add_playlist_items("playlist-1", [f"item-{index}" for index in range(205)])
    adapter.save_tracks([f"track-{index}" for index in range(120)])
    adapter.save_albums([f"album-{index}" for index in range(41)])
    adapter.follow_artists([f"artist-{index}" for index in range(70)])
    adapter.save_podcasts([f"show-{index}" for index in range(25)])
    adapter.save_episodes([f"episode-{index}" for index in range(21)])

    assert [len(batch) for batch in playlist_add_batches] == [100, 100, 5]
    assert [len(batch) for batch in save_track_batches] == [50, 50, 20]
    assert [len(batch) for batch in save_album_batches] == [20, 20, 1]
    assert [len(batch) for batch in follow_artist_batches] == [50, 20]
    assert [len(batch) for batch in save_show_batches] == [20, 5]
    assert [len(batch) for batch in save_episode_batches] == [20, 1]


def test_sanitize_redirect_uri_uses_default_for_invalid_values(settings: Settings) -> None:
    """Test invalid Spotify callback values fall back to the app callback."""
    expected_default = "http://127.0.0.1:8899/callback/spotify"

    assert sanitize_redirect_uri(None, settings) == expected_default
    assert sanitize_redirect_uri("spotify-callback", settings) == expected_default
    assert sanitize_redirect_uri("http://localhost:3000/callback", settings) == "http://localhost:3000/callback"
