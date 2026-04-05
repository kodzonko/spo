"""YouTube Music adapter implementation used by spo."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NoReturn, ParamSpec, TypeVar

import requests
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth.credentials import OAuthCredentials
from ytmusicapi.models.content.enums import LikeStatus

from spo.exceptions import (
    AuthenticationError,
    RateLimitError,
    UnsupportedOperationError,
)
from spo.models import (
    AccountIdentity,
    AdapterCapabilities,
    CollectionKind,
    Page,
    Service,
)
from spo.services.base import StreamingServiceAdapter
from spo.utils import chunked

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from spo.config import Settings

P = ParamSpec("P")
R = TypeVar("R")
HTTP_TOO_MANY_REQUESTS = int(requests.codes["too_many_requests"])
HTTP_UNAUTHORIZED = int(requests.codes["unauthorized"])
HTTP_FORBIDDEN = int(requests.codes["forbidden"])


def _raise_authentication_error(message: str) -> NoReturn:
    raise AuthenticationError(message)


class YouTubeMusicAdapter(StreamingServiceAdapter):
    """Read and write supported collections through the YTMusic client."""

    service = Service.YTMUSIC
    _capabilities = AdapterCapabilities(
        readable=frozenset(
            {
                CollectionKind.PLAYLIST,
                CollectionKind.SAVED_TRACK,
                CollectionKind.LIKED_TRACK,
                CollectionKind.SAVED_ALBUM,
                CollectionKind.FOLLOWED_ARTIST,
                CollectionKind.SAVED_PODCAST,
                CollectionKind.SAVED_EPISODE,
            },
        ),
        writable=frozenset(
            {
                CollectionKind.PLAYLIST,
                CollectionKind.SAVED_TRACK,
                CollectionKind.LIKED_TRACK,
                CollectionKind.FOLLOWED_ARTIST,
            },
        ),
    )

    def __init__(self, *, account_id: int, credential_payload: dict[str, Any], settings: Settings) -> None:
        """Initialize the YouTube Music adapter for a stored account."""
        super().__init__(
            account_id=account_id,
            credential_payload=credential_payload,
            settings=settings,
        )
        self._client: YTMusic | None = None
        self._identity: AccountIdentity | None = None

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return the collection operations supported by YouTube Music."""
        return self._capabilities

    def _auth_file_path(self) -> Path:
        auth_dir = self.settings.app_data_dir / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        return auth_dir / f"ytmusic-account-{self.account_id}.json"

    @property
    def persisted_payload(self) -> dict[str, Any]:
        """Return credentials, including refreshed OAuth token data when available."""
        if self.credential_payload.get("credential_type") != "ytmusic_oauth":
            return self.credential_payload

        auth_file = self._auth_file_path()
        if not auth_file.exists():
            return self.credential_payload

        payload = dict(self.credential_payload)
        payload["data"] = json.loads(auth_file.read_text(encoding="utf-8"))
        return payload

    def _ensure_client(self) -> YTMusic:
        if self._client is not None:
            return self._client
        credential_type = self.credential_payload.get("credential_type")
        data = self.credential_payload.get("data")
        if not credential_type or not data:
            raise AuthenticationError("YouTube Music credentials are missing.")
        try:
            if credential_type == "ytmusic_headers":
                headers = json.loads(data) if isinstance(data, str) else json.loads(json.dumps(data))
                self._client = YTMusic(headers)
            elif credential_type == "ytmusic_oauth":
                oauth_client = self.credential_payload.get("oauth_client")
                if not isinstance(oauth_client, dict):
                    _raise_authentication_error("YouTube Music OAuth client credentials are missing.")
                client_id = str(oauth_client.get("client_id") or "").strip()
                client_secret = str(oauth_client.get("client_secret") or "").strip()
                if not client_id or not client_secret:
                    _raise_authentication_error("YouTube Music OAuth client credentials are incomplete.")
                auth_file = self._auth_file_path()
                auth_file.write_text(
                    json.dumps(data if isinstance(data, dict) else json.loads(data)),
                    encoding="utf-8",
                )
                self._client = YTMusic(
                    str(auth_file),
                    oauth_credentials=OAuthCredentials(
                        client_id=client_id,
                        client_secret=client_secret,
                    ),
                )
            else:
                _raise_authentication_error("Unsupported YouTube Music credential type.")
        except Exception as exc:  # pragma: no cover - library internals
            message = f"YouTube Music authentication failed: {exc}"
            raise AuthenticationError(message) from exc
        return self._client

    def _call(self, fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except requests.HTTPError as exc:  # pragma: no cover - library internals
            if exc.response is not None and exc.response.status_code == HTTP_TOO_MANY_REQUESTS:
                retry_after_value = exc.response.headers.get("Retry-After")
                retry_after: float | None = None
                if retry_after_value is not None:
                    try:
                        retry_after = float(retry_after_value)
                    except TypeError, ValueError:
                        retry_after = None
                raise RateLimitError("YouTube Music rate limit exceeded.", retry_after) from exc
            if exc.response is not None and exc.response.status_code in {
                HTTP_UNAUTHORIZED,
                HTTP_FORBIDDEN,
            }:
                raise AuthenticationError("YouTube Music credentials are invalid.") from exc
            raise

    def authenticate(self) -> AccountIdentity:
        """Validate credentials and return the authenticated YouTube Music account."""
        client = self._ensure_client()
        if self._identity is None:
            self._call(client.get_library_playlists, limit=1)
            self._identity = AccountIdentity(
                remote_account_id=f"ytmusic-account-{self.account_id}",
                display_name="YouTube Music User",
            )
        return self._identity

    def _slice(self, items: list[dict[str, Any]], cursor: str | None, page_size: int) -> Page:
        offset = int(cursor or "0")
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(items) else None
        return Page(items=items[offset:next_offset], next_cursor=next_cursor)

    def list_collection(self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50) -> Page:
        """Return a page of YouTube Music library items for the requested kind."""
        client = self._ensure_client()
        items: list[dict[str, Any]]
        if kind == CollectionKind.PLAYLIST:
            items = self._call(client.get_library_playlists, limit=None)
        elif kind == CollectionKind.SAVED_TRACK:
            items = self._call(client.get_library_songs, limit=5000)
        elif kind == CollectionKind.LIKED_TRACK:
            payload = self._call(client.get_liked_songs, limit=5000)
            items = payload.get("tracks", []) if isinstance(payload, dict) else []
        elif kind == CollectionKind.SAVED_ALBUM:
            items = self._call(client.get_library_albums, limit=5000)
        elif kind == CollectionKind.FOLLOWED_ARTIST:
            items = self._call(client.get_library_subscriptions, limit=5000)
        elif kind == CollectionKind.SAVED_PODCAST:
            items = self._call(client.get_library_podcasts, limit=5000)
        elif kind == CollectionKind.SAVED_EPISODE:
            payload = self._call(client.get_saved_episodes, limit=5000)
            items = payload.get("items", []) if isinstance(payload, dict) else []
        else:
            message = f"Unsupported YouTube Music collection: {kind}"
            raise ValueError(message)
        return self._slice(items, cursor, page_size)

    def get_playlist_items(self, playlist_id: str, cursor: str | None = None, page_size: int = 100) -> Page:
        """Return a page of items from a YouTube Music playlist."""
        client = self._ensure_client()
        payload = self._call(client.get_playlist, playlist_id, limit=None)
        items = payload.get("tracks", []) if isinstance(payload, dict) else []
        return self._slice(items, cursor, page_size)

    def search(self, kind: CollectionKind, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search YouTube Music for catalog items matching the query."""
        client = self._ensure_client()
        filter_value = {
            CollectionKind.SAVED_TRACK: "songs",
            CollectionKind.LIKED_TRACK: "songs",
            CollectionKind.SAVED_ALBUM: "albums",
            CollectionKind.FOLLOWED_ARTIST: "artists",
            CollectionKind.PLAYLIST: "playlists",
            CollectionKind.SAVED_PODCAST: "podcasts",
        }.get(kind)
        payload = self._call(client.search, query, filter=filter_value, limit=limit)
        if kind == CollectionKind.SAVED_EPISODE:
            return [item for item in payload if item.get("resultType") == "episode"]
        return payload

    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a private YouTube Music playlist."""
        client = self._ensure_client()
        playlist_id = self._call(
            client.create_playlist,
            name,
            description,
            "PRIVATE",
        )
        if isinstance(playlist_id, dict):
            playlist_id = playlist_id.get("playlistId")
        return {"id": str(playlist_id), "name": name}

    def add_playlist_items(self, playlist_id: str, item_ids: list[str]) -> None:
        """Append items to a YouTube Music playlist in API-sized batches."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 100):
            self._call(client.add_playlist_items, playlist_id, batch, duplicates=True)

    def save_tracks(self, item_ids: list[str]) -> None:
        """Like tracks in the current YouTube Music library."""
        client = self._ensure_client()
        for item_id in item_ids:
            self._call(client.rate_song, item_id, LikeStatus.LIKE)

    def save_albums(self, item_ids: list[str]) -> None:
        """Raise because album writes are not supported for YouTube Music in v1."""
        del item_ids
        raise UnsupportedOperationError("YouTube Music album writes are not supported in v1.")

    def follow_artists(self, item_ids: list[str]) -> None:
        """Subscribe to artists in API-sized batches."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 25):
            self._call(client.subscribe_artists, batch)

    def save_podcasts(self, item_ids: list[str]) -> None:
        """Raise because podcast writes are not supported for YouTube Music in v1."""
        del item_ids
        raise UnsupportedOperationError("YouTube Music podcast writes are not supported in v1.")

    def save_episodes(self, item_ids: list[str]) -> None:
        """Raise because episode writes are not supported for YouTube Music in v1."""
        del item_ids
        raise UnsupportedOperationError("YouTube Music episode writes are not supported in v1.")
