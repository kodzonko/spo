from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
from ytmusicapi import YTMusic
from ytmusicapi.models.content.enums import LikeStatus

from spo.config import Settings
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


class YouTubeMusicAdapter(StreamingServiceAdapter):
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
            }
        ),
        writable=frozenset(
            {
                CollectionKind.PLAYLIST,
                CollectionKind.SAVED_TRACK,
                CollectionKind.LIKED_TRACK,
                CollectionKind.FOLLOWED_ARTIST,
            }
        ),
    )

    def __init__(
        self, *, account_id: int, credential_payload: dict[str, Any], settings: Settings
    ) -> None:
        super().__init__(
            account_id=account_id,
            credential_payload=credential_payload,
            settings=settings,
        )
        self._client: YTMusic | None = None
        self._identity: AccountIdentity | None = None

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    def _auth_file_path(self) -> Path:
        auth_dir = self.settings.app_data_dir / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        return auth_dir / f"ytmusic-account-{self.account_id}.json"

    def _ensure_client(self) -> YTMusic:
        if self._client is not None:
            return self._client
        credential_type = self.credential_payload.get("credential_type")
        data = self.credential_payload.get("data")
        if not credential_type or not data:
            raise AuthenticationError("YouTube Music credentials are missing.")
        try:
            if credential_type == "ytmusic_headers":
                headers = (
                    json.loads(data)
                    if isinstance(data, str)
                    else json.loads(json.dumps(data))
                )
                self._client = YTMusic(headers)
            elif credential_type == "ytmusic_oauth":
                auth_file = self._auth_file_path()
                auth_file.write_text(
                    json.dumps(data if isinstance(data, dict) else json.loads(data)),
                    encoding="utf-8",
                )
                self._client = YTMusic(str(auth_file))
            else:
                raise AuthenticationError("Unsupported YouTube Music credential type.")
        except Exception as exc:  # pragma: no cover - library internals
            raise AuthenticationError(
                f"YouTube Music authentication failed: {exc}"
            ) from exc
        return self._client

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except requests.HTTPError as exc:  # pragma: no cover - library internals
            if exc.response is not None and exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After")
                raise RateLimitError(
                    "YouTube Music rate limit exceeded.", retry_after
                ) from exc
            if exc.response is not None and exc.response.status_code in {401, 403}:
                raise AuthenticationError(
                    "YouTube Music credentials are invalid."
                ) from exc
            raise

    def authenticate(self) -> AccountIdentity:
        client = self._ensure_client()
        if self._identity is None:
            self._call(client.get_library_playlists, limit=1)
            self._identity = AccountIdentity(
                remote_account_id=f"ytmusic-account-{self.account_id}",
                display_name="YouTube Music User",
            )
        return self._identity

    def _slice(
        self, items: list[dict[str, Any]], cursor: str | None, page_size: int
    ) -> Page:
        offset = int(cursor or "0")
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(items) else None
        return Page(items=items[offset:next_offset], next_cursor=next_cursor)

    def list_collection(
        self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50
    ) -> Page:
        client = self._ensure_client()
        if kind == CollectionKind.PLAYLIST:
            items = self._call(client.get_library_playlists, limit=None)
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.SAVED_TRACK:
            items = self._call(client.get_library_songs, limit=5000)
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.LIKED_TRACK:
            payload = self._call(client.get_liked_songs, limit=5000)
            items = payload.get("tracks", []) if isinstance(payload, dict) else []
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.SAVED_ALBUM:
            items = self._call(client.get_library_albums, limit=5000)
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.FOLLOWED_ARTIST:
            items = self._call(client.get_library_subscriptions, limit=5000)
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.SAVED_PODCAST:
            items = self._call(client.get_library_podcasts, limit=5000)
            return self._slice(items, cursor, page_size)
        if kind == CollectionKind.SAVED_EPISODE:
            payload = self._call(client.get_saved_episodes, limit=5000)
            items = payload.get("items", []) if isinstance(payload, dict) else []
            return self._slice(items, cursor, page_size)
        raise ValueError(f"Unsupported YouTube Music collection: {kind}")

    def get_playlist_items(
        self, playlist_id: str, cursor: str | None = None, page_size: int = 100
    ) -> Page:
        client = self._ensure_client()
        payload = self._call(client.get_playlist, playlist_id, limit=None)
        items = payload.get("tracks", []) if isinstance(payload, dict) else []
        return self._slice(items, cursor, page_size)

    def search(
        self, kind: CollectionKind, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
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
        client = self._ensure_client()
        for batch in chunked(item_ids, 100):
            self._call(client.add_playlist_items, playlist_id, batch, duplicates=True)

    def save_tracks(self, item_ids: list[str]) -> None:
        client = self._ensure_client()
        for item_id in item_ids:
            self._call(client.rate_song, item_id, LikeStatus.LIKE)

    def save_albums(self, item_ids: list[str]) -> None:
        raise UnsupportedOperationError(
            "YouTube Music album writes are not supported in v1."
        )

    def follow_artists(self, item_ids: list[str]) -> None:
        client = self._ensure_client()
        for batch in chunked(item_ids, 25):
            self._call(client.subscribe_artists, batch)

    def save_podcasts(self, item_ids: list[str]) -> None:
        raise UnsupportedOperationError(
            "YouTube Music podcast writes are not supported in v1."
        )

    def save_episodes(self, item_ids: list[str]) -> None:
        raise UnsupportedOperationError(
            "YouTube Music episode writes are not supported in v1."
        )
