"""Tests for the YouTube Music service adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import requests
from ytmusicapi.exceptions import YTMusicServerError
from ytmusicapi.models.content.enums import LikeStatus

import spo.services.ytmusic as ytmusic_service
from spo.exceptions import AuthenticationError, RateLimitError, UnsupportedOperationError
from spo.models import AccountIdentity, CollectionKind
from spo.services.ytmusic import YouTubeMusicAdapter

if TYPE_CHECKING:
    from typing import Any

    from spo.config import Settings

LIBRARY_PAGE_LIMIT = 5000


def _make_adapter(
    settings: Settings,
    credential_payload: dict[str, Any] | None = None,
) -> YouTubeMusicAdapter:
    payload: dict[str, Any] = {
        "credential_type": "ytmusic_oauth",
        "data": {"access_token": "test-token"},
        "oauth_client": {"client_id": "test-id", "client_secret": "test-secret"},
    }
    if credential_payload is not None:
        payload.update(credential_payload)
    return YouTubeMusicAdapter(
        account_id=1,
        credential_payload=payload,
        settings=settings,
    )


def test_list_collection_handles_wrapped_payload_items(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that wrapped YouTube Music payloads are sliced into pages correctly."""

    class FakeClient:
        def get_liked_songs(self, *, limit: int) -> dict[str, list[dict[str, str]]]:
            assert limit == LIBRARY_PAGE_LIMIT
            return {
                "tracks": [
                    {"videoId": "liked-1"},
                    {"videoId": "liked-2"},
                ],
            }

        def get_saved_episodes(self, *, limit: int) -> dict[str, list[dict[str, str]]]:
            assert limit == LIBRARY_PAGE_LIMIT
            return {
                "items": [
                    {"videoId": "episode-1"},
                    {"videoId": "episode-2"},
                ],
            }

    adapter = _make_adapter(settings)

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    liked_page = adapter.list_collection(CollectionKind.LIKED_TRACK, page_size=1)
    saved_episode_page = adapter.list_collection(CollectionKind.SAVED_EPISODE, cursor="1", page_size=1)

    assert liked_page.items == [{"videoId": "liked-1"}]
    assert liked_page.next_cursor == "1"
    assert saved_episode_page.items == [{"videoId": "episode-2"}]
    assert saved_episode_page.next_cursor is None


def test_call_ignores_invalid_retry_after_header(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that invalid Retry-After values still raise a rate-limit error without retry metadata."""
    adapter = _make_adapter(settings)
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "not-a-number"
    response.url = "https://music.youtube.com/library"
    error = requests.HTTPError(response=response)

    class FakeClient:
        def get_library_songs(self, *, limit: int) -> list[dict[str, str]]:
            assert limit == LIBRARY_PAGE_LIMIT
            raise error

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    with pytest.raises(RateLimitError) as exc_info:
        adapter.list_collection(CollectionKind.SAVED_TRACK)

    assert exc_info.value.retry_after is None


def test_persisted_payload_reads_refreshed_oauth_data_from_auth_file(settings: Settings) -> None:
    """Test persisted payload prefers refreshed OAuth data written by the library."""
    adapter = _make_adapter(
        settings,
        credential_payload={
            "credential_type": "ytmusic_oauth",
            "data": {"access_token": "stale-token"},
            "oauth_client": {
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
        },
    )

    auth_file_path = adapter._auth_file_path  # noqa: SLF001 - testing persisted OAuth file handling
    auth_file = auth_file_path()
    auth_file.write_text(
        json.dumps({"access_token": "fresh-token", "refresh_token_expires_in": 604800}),
        encoding="utf-8",
    )

    assert adapter.persisted_payload["data"] == {"access_token": "fresh-token"}


def test_ensure_client_builds_oauth_client_and_caches_the_instance(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test OAuth-based YT Music auth writes an auth file and reuses the built client."""
    constructor_calls: list[dict[str, Any]] = []

    class FakeYTMusic:
        def __init__(self, auth: str, *, oauth_credentials: object) -> None:
            constructor_calls.append(
                {
                    "auth": auth,
                    "oauth_credentials": oauth_credentials,
                },
            )

    monkeypatch.setattr(ytmusic_service, "YTMusic", FakeYTMusic)

    adapter = _make_adapter(
        settings,
        credential_payload={
            "credential_type": "ytmusic_oauth",
            "data": {"access_token": "access-token"},
            "oauth_client": {
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
        },
    )

    ensure_client = adapter._ensure_client  # noqa: SLF001 - testing OAuth client construction directly
    auth_file_path = adapter._auth_file_path  # noqa: SLF001 - testing persisted OAuth file handling

    first_client = ensure_client()
    second_client = ensure_client()
    auth_file = auth_file_path()

    assert first_client is second_client
    assert len(constructor_calls) == 1
    assert constructor_calls[0]["auth"] == str(auth_file)
    assert constructor_calls[0]["oauth_credentials"].client_id == "client-id"
    assert constructor_calls[0]["oauth_credentials"].client_secret == "client-secret"
    assert json.loads(auth_file.read_text(encoding="utf-8")) == {"access_token": "access-token"}


def test_ensure_client_strips_sdk_incompatible_google_token_fields(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test OAuth auth files drop Google-only fields before ``ytmusicapi`` loads them."""
    constructor_calls: list[dict[str, Any]] = []

    class FakeYTMusic:
        def __init__(self, auth: str, *, oauth_credentials: object) -> None:
            constructor_calls.append(
                {
                    "auth": auth,
                    "oauth_credentials": oauth_credentials,
                    "auth_payload": json.loads(Path(auth).read_text(encoding="utf-8")),
                },
            )

    monkeypatch.setattr(ytmusic_service, "YTMusic", FakeYTMusic)

    adapter = _make_adapter(
        settings,
        credential_payload={
            "data": {
                "access_token": "access-token",
                "expires_at": "1712400000",
                "expires_in": "3600",
                "refresh_token": "refresh-token",
                "refresh_token_expires_in": 604800,
                "scope": "https://www.googleapis.com/auth/youtube",
                "token_type": "Bearer",
            },
        },
    )

    ensure_client = adapter._ensure_client  # noqa: SLF001 - testing OAuth file persistence directly

    ensure_client()

    assert constructor_calls[0]["auth_payload"] == {
        "access_token": "access-token",
        "expires_at": 1712400000,
        "expires_in": 3600,
        "refresh_token": "refresh-token",
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer",
    }


def test_ensure_client_prefers_existing_auth_file_over_stale_db_token_data(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the on-disk auth file remains the source of truth for refreshed OAuth tokens."""
    constructor_calls: list[dict[str, Any]] = []

    class FakeYTMusic:
        def __init__(self, auth: str, *, oauth_credentials: object) -> None:
            constructor_calls.append(
                {
                    "auth": auth,
                    "oauth_credentials": oauth_credentials,
                    "auth_payload": json.loads(Path(auth).read_text(encoding="utf-8")),
                },
            )

    monkeypatch.setattr(ytmusic_service, "YTMusic", FakeYTMusic)

    adapter = _make_adapter(
        settings,
        credential_payload={
            "data": {
                "access_token": "stale-token",
                "expires_at": 10,
                "expires_in": 1,
                "refresh_token": "stale-refresh",
                "scope": "https://www.googleapis.com/auth/youtube",
                "token_type": "Bearer",
            },
        },
    )

    auth_file_path = adapter._auth_file_path  # noqa: SLF001 - testing persisted OAuth file handling
    auth_file = auth_file_path()
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "fresh-token",
                "expires_at": 1712400000,
                "expires_in": 3600,
                "refresh_token": "fresh-refresh",
                "refresh_token_expires_in": 604800,
                "scope": "https://www.googleapis.com/auth/youtube",
                "token_type": "Bearer",
            },
        ),
        encoding="utf-8",
    )

    ensure_client = adapter._ensure_client  # noqa: SLF001 - testing OAuth file persistence directly

    ensure_client()

    assert constructor_calls[0]["auth_payload"]["access_token"] == "fresh-token"
    assert constructor_calls[0]["auth_payload"]["refresh_token"] == "fresh-refresh"
    assert "refresh_token_expires_in" not in constructor_calls[0]["auth_payload"]


def test_authenticate_retries_oauth_with_experimental_client_profiles(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test OAuth auth can fall back to experimental client profiles and persist the winner."""
    constructor_calls: list[tuple[str, str | None]] = []
    probe_calls: list[tuple[str, str | None]] = []
    invalid_argument_error = YTMusicServerError(
        "Server returned HTTP 400: Bad Request.\nRequest contains an invalid argument."
    )

    class FakeYTMusic:
        def __init__(self, auth: str, *, oauth_credentials: object) -> None:
            del auth, oauth_credentials
            self.context = {"context": {"client": {}}}

        def get_library_playlists(self, *, limit: int | None) -> list[dict[str, str]]:
            assert limit == 1
            client = self.context["context"]["client"]
            client_name = client.get("clientName", "WEB_REMIX")
            client_version = client.get("clientVersion")
            constructor_calls.append((client_name, client_version))
            raise invalid_argument_error

        def _send_request(self, endpoint: str, body: dict[str, str]) -> dict[str, object]:
            assert endpoint == "browse"
            assert body == {"browseId": ytmusic_service.YTMUSIC_AUTH_PROBE_BROWSE_ID}
            client = self.context["context"]["client"]
            client_name = client.get("clientName", "WEB_REMIX")
            client_version = client.get("clientVersion")
            probe_calls.append((client_name, client_version))
            if client_name == "TVHTML5" and client_version == "7.20241013.17.00":
                return {"responseContext": {}}
            raise invalid_argument_error

    monkeypatch.setattr(ytmusic_service, "YTMusic", FakeYTMusic)

    adapter = _make_adapter(
        settings,
        credential_payload={
            "credential_type": "ytmusic_oauth",
            "data": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
            "oauth_client": {
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
        },
    )

    identity = adapter.authenticate()

    assert identity == AccountIdentity(
        remote_account_id="ytmusic-account-1",
        display_name="YouTube Music User",
    )
    assert constructor_calls == [("WEB_REMIX", None)]
    assert probe_calls == [
        ("IOS_MUSIC", "6.42"),
        ("TVHTML5", "7.20241013.17.00"),
    ]
    assert adapter.persisted_payload["oauth_profile"] == "tvhtml5_v7"


@pytest.mark.parametrize(
    ("credential_payload", "message"),
    [
        (
            {
                "credential_type": "ytmusic_oauth",
            },
            "YouTube Music credentials are missing.",
        ),
        (
            {
                "credential_type": "ytmusic_oauth",
                "data": {"access_token": "access-token"},
            },
            "YouTube Music OAuth client credentials are missing.",
        ),
        (
            {
                "credential_type": "ytmusic_oauth",
                "data": {"access_token": "access-token"},
                "oauth_client": {
                    "client_id": "",
                    "client_secret": "client-secret",
                },
            },
            "YouTube Music OAuth client credentials are incomplete.",
        ),
        (
            {
                "credential_type": "unsupported",
                "data": {"access_token": "access-token"},
            },
            "Unsupported YouTube Music credential type.",
        ),
    ],
)
def test_ensure_client_rejects_invalid_credential_configurations(
    settings: Settings,
    credential_payload: dict[str, Any],
    message: str,
) -> None:
    """Test YouTube Music rejects invalid credential payloads before use."""
    adapter = YouTubeMusicAdapter(
        account_id=1,
        credential_payload=credential_payload,
        settings=settings,
    )
    ensure_client = adapter._ensure_client  # noqa: SLF001 - exercising auth validation directly

    with pytest.raises(AuthenticationError, match=message):
        ensure_client()


def test_authenticate_and_collection_reads_cache_identity_and_slice_payloads(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test YT Music authentication caches identity and collection reads use local slicing."""

    class FakeClient:
        def __init__(self) -> None:
            self.playlist_limits: list[int | None] = []

        def get_library_playlists(self, *, limit: int | None) -> list[dict[str, str]]:
            self.playlist_limits.append(limit)
            return [
                {"playlistId": "playlist-1"},
                {"playlistId": "playlist-2"},
            ]

        def get_library_albums(self, *, limit: int) -> list[dict[str, str]]:
            assert limit == LIBRARY_PAGE_LIMIT
            return [{"browseId": "album-1"}]

        def get_library_subscriptions(self, *, limit: int) -> list[dict[str, str]]:
            assert limit == LIBRARY_PAGE_LIMIT
            return [{"channelId": "artist-1"}]

        def get_library_podcasts(self, *, limit: int) -> list[dict[str, str]]:
            assert limit == LIBRARY_PAGE_LIMIT
            return [{"podcastId": "podcast-1"}]

        def get_playlist(self, playlist_id: str, *, limit: int | None) -> dict[str, list[dict[str, str]]]:
            assert playlist_id == "playlist-1"
            assert limit is None
            return {
                "tracks": [
                    {"videoId": "track-1"},
                    {"videoId": "track-2"},
                ],
            }

    fake_client = FakeClient()
    adapter = _make_adapter(settings)

    monkeypatch.setattr(adapter, "_build_client", lambda _profile: fake_client)
    monkeypatch.setattr(
        adapter,
        "_oauth_profile_candidates",
        lambda: (ytmusic_service.YTMUSIC_WEB_REMIX_OAUTH_PROFILE,),
    )

    first_identity = adapter.authenticate()
    second_identity = adapter.authenticate()
    playlist_page = adapter.list_collection(CollectionKind.PLAYLIST, page_size=1)
    album_page = adapter.list_collection(CollectionKind.SAVED_ALBUM, page_size=1)
    artist_page = adapter.list_collection(CollectionKind.FOLLOWED_ARTIST, page_size=1)
    podcast_page = adapter.list_collection(CollectionKind.SAVED_PODCAST, page_size=1)
    playlist_items_page = adapter.get_playlist_items("playlist-1", cursor="1", page_size=1)

    assert first_identity is second_identity
    assert first_identity == AccountIdentity(
        remote_account_id="ytmusic-account-1",
        display_name="YouTube Music User",
    )
    assert fake_client.playlist_limits == [1, None]
    assert playlist_page.items == [{"playlistId": "playlist-1"}]
    assert playlist_page.next_cursor == "1"
    assert album_page.items == [{"browseId": "album-1"}]
    assert artist_page.items == [{"channelId": "artist-1"}]
    assert podcast_page.items == [{"podcastId": "podcast-1"}]
    assert playlist_items_page.items == [{"videoId": "track-2"}]
    assert playlist_items_page.next_cursor is None


def test_search_create_playlist_and_write_methods_cover_batching_and_filtering(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test YT Music search and write helpers use the correct filters and batch sizes."""
    search_calls: list[dict[str, Any]] = []
    playlist_add_calls: list[tuple[str, list[str], bool]] = []
    rated_songs: list[tuple[str, LikeStatus]] = []
    subscribed_artist_batches: list[list[str]] = []

    class FakeClient:
        def search(self, query: str, *, limit: int, **kwargs: object) -> list[dict[str, str]]:
            search_filter = kwargs.get("filter")
            search_calls.append({"query": query, "filter": search_filter, "limit": limit})
            if search_filter is None:
                return [
                    {"resultType": "song", "videoId": "song-1"},
                    {"resultType": "episode", "videoId": "episode-1"},
                ]
            return [{"resultType": "song", "videoId": "song-1"}]

        def create_playlist(
            self,
            name: str,
            description: str,
            privacy_status: str,
        ) -> dict[str, str]:
            assert name == "Road Trip"
            assert description == "Songs for long drives"
            assert privacy_status == "PRIVATE"
            return {"playlistId": "playlist-1"}

        def add_playlist_items(
            self,
            playlist_id: str,
            item_ids: list[str],
            *,
            duplicates: bool,
        ) -> None:
            playlist_add_calls.append((playlist_id, list(item_ids), duplicates))

        def rate_song(self, item_id: str, status: LikeStatus) -> None:
            rated_songs.append((item_id, status))

        def subscribe_artists(self, item_ids: list[str]) -> None:
            subscribed_artist_batches.append(list(item_ids))

    adapter = _make_adapter(settings)

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    saved_track_results = adapter.search(CollectionKind.SAVED_TRACK, "focus", limit=5)
    saved_episode_results = adapter.search(CollectionKind.SAVED_EPISODE, "podcast", limit=5)
    playlist = adapter.create_playlist("Road Trip", "Songs for long drives")
    adapter.add_playlist_items("playlist-1", [f"item-{index}" for index in range(205)])
    adapter.save_tracks(["song-1", "song-2"])
    adapter.follow_artists([f"artist-{index}" for index in range(26)])

    assert saved_track_results == [{"resultType": "song", "videoId": "song-1"}]
    assert saved_episode_results == [{"resultType": "episode", "videoId": "episode-1"}]
    assert search_calls == [
        {"query": "focus", "filter": "songs", "limit": 5},
        {"query": "podcast", "filter": None, "limit": 5},
    ]
    assert playlist == {"id": "playlist-1", "name": "Road Trip"}
    assert [len(item_ids) for _, item_ids, _ in playlist_add_calls] == [100, 100, 5]
    assert all(duplicates is True for _, _, duplicates in playlist_add_calls)
    assert rated_songs == [
        ("song-1", LikeStatus.LIKE),
        ("song-2", LikeStatus.LIKE),
    ]
    assert [len(batch) for batch in subscribed_artist_batches] == [25, 1]


@pytest.mark.parametrize(
    "method_name",
    ["save_albums", "save_podcasts", "save_episodes"],
)
def test_unsupported_write_operations_raise_for_ytmusic(
    settings: Settings,
    method_name: str,
) -> None:
    """Test unsupported YT Music write operations fail explicitly."""
    adapter = _make_adapter(settings)
    method = getattr(adapter, method_name)

    with pytest.raises(UnsupportedOperationError):
        method(["item-1"])


def test_call_translates_unauthorized_responses_into_authentication_errors(settings: Settings) -> None:
    """Test HTTP auth failures from YT Music become application auth errors."""
    adapter = _make_adapter(settings)
    call = adapter._call  # noqa: SLF001 - exercising SDK-to-domain error translation directly
    response = requests.Response()
    response.status_code = 401
    response.url = "https://music.youtube.com/library"
    error = requests.HTTPError(response=response)

    def raise_unauthorized() -> None:
        raise error

    with pytest.raises(AuthenticationError, match=re.escape("YouTube Music credentials are invalid.")):
        call(raise_unauthorized)


def test_call_translates_server_side_oauth_invalid_argument_into_authentication_error(
    settings: Settings,
) -> None:
    """Test YT Music server-side OAuth 400 errors become controlled auth failures."""
    adapter = _make_adapter(settings)
    call = adapter._call  # noqa: SLF001 - exercising SDK-to-domain error translation directly
    error = YTMusicServerError("Server returned HTTP 400: Bad Request.\nRequest contains an invalid argument.")

    def raise_invalid_argument() -> None:
        raise error

    with pytest.raises(AuthenticationError, match="known upstream ytmusicapi OAuth issue"):
        call(raise_invalid_argument)
