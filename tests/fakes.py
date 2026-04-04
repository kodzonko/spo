from __future__ import annotations

from typing import Any

from spo.config import Settings
from spo.exceptions import AuthenticationError
from spo.models import (
    AccountIdentity,
    AdapterCapabilities,
    CollectionKind,
    Page,
    Service,
)
from spo.services.base import StreamingServiceAdapter


class _BaseFakeAdapter(StreamingServiceAdapter):
    STATE: dict[str, dict[str, Any]] = {}
    service: Service
    capabilities = AdapterCapabilities(
        readable=frozenset(CollectionKind),
        writable=frozenset(CollectionKind),
    )

    def __init__(
        self, *, account_id: int, credential_payload: dict[str, Any], settings: Settings
    ) -> None:
        super().__init__(
            account_id=account_id,
            credential_payload=credential_payload,
            settings=settings,
        )
        payload_state_key = credential_payload.get("state_key")
        if payload_state_key is None and isinstance(credential_payload.get("data"), dict):
            payload_state_key = credential_payload["data"].get("state_key")
        self.state_key = str(payload_state_key)
        self.state = self.__class__.STATE[self.state_key]

    def authenticate(self) -> AccountIdentity:
        self._consume_effect("authenticate_effects")
        identity = self.state["identity"]
        return AccountIdentity(
            remote_account_id=identity["remote_account_id"],
            display_name=identity["display_name"],
        )

    def list_collection(
        self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50
    ) -> Page:
        items = list(self.state["collections"].get(kind.value, []))
        offset = int(cursor or "0")
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(items) else None
        return Page(items=items[offset:next_offset], next_cursor=next_cursor)

    def get_playlist_items(
        self, playlist_id: str, cursor: str | None = None, page_size: int = 100
    ) -> Page:
        items = list(self.state["playlist_items"].get(playlist_id, []))
        offset = int(cursor or "0")
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(items) else None
        return Page(items=items[offset:next_offset], next_cursor=next_cursor)

    def search(
        self, kind: CollectionKind, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        candidates = list(self.state["search"].get(kind.value, []))
        if candidates:
            return candidates[:limit]
        return list(self.state["catalog"].get(kind.value, {}).values())[:limit]

    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        self._consume_effect("create_playlist_effects")
        playlist_id = f"{self.state_key}-playlist-{len(self.state['collections'].setdefault(CollectionKind.PLAYLIST.value, [])) + 1}"
        playlist = {"id": playlist_id, "name": name, "description": description}
        self.state["collections"].setdefault(CollectionKind.PLAYLIST.value, []).append(
            playlist
        )
        self.state["playlist_items"].setdefault(playlist_id, [])
        self.state.setdefault("created_playlists", []).append(playlist)
        return {"id": playlist_id, "name": name}

    def add_playlist_items(self, playlist_id: str, item_ids: list[str]) -> None:
        self._consume_effect("add_playlist_items_effects")
        destination = self.state["playlist_items"].setdefault(playlist_id, [])
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                destination.append(raw)
        self.state.setdefault("playlist_add_calls", []).append(
            (playlist_id, list(item_ids))
        )

    def save_tracks(self, item_ids: list[str]) -> None:
        self._consume_effect("save_tracks_effects")
        collection = self.state["collections"].setdefault(
            CollectionKind.SAVED_TRACK.value, []
        )
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                collection.append(raw)
        self.state.setdefault("save_track_calls", []).append(list(item_ids))

    def save_albums(self, item_ids: list[str]) -> None:
        self._consume_effect("save_albums_effects")
        collection = self.state["collections"].setdefault(
            CollectionKind.SAVED_ALBUM.value, []
        )
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                collection.append(raw)

    def follow_artists(self, item_ids: list[str]) -> None:
        self._consume_effect("follow_artists_effects")
        collection = self.state["collections"].setdefault(
            CollectionKind.FOLLOWED_ARTIST.value, []
        )
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                collection.append(raw)

    def save_podcasts(self, item_ids: list[str]) -> None:
        self._consume_effect("save_podcasts_effects")
        collection = self.state["collections"].setdefault(
            CollectionKind.SAVED_PODCAST.value, []
        )
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                collection.append(raw)

    def save_episodes(self, item_ids: list[str]) -> None:
        self._consume_effect("save_episodes_effects")
        collection = self.state["collections"].setdefault(
            CollectionKind.SAVED_EPISODE.value, []
        )
        for item_id in item_ids:
            raw = self._lookup_catalog_item(item_id)
            if raw is not None:
                collection.append(raw)

    def _lookup_catalog_item(self, item_id: str) -> dict[str, Any] | None:
        for catalog in self.state["catalog"].values():
            if item_id in catalog:
                return catalog[item_id]
        return None

    def _consume_effect(self, effect_key: str) -> None:
        effects = self.state.get(effect_key, [])
        if not effects:
            return
        effect = effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        if effect == "auth_error":
            raise AuthenticationError("Injected authentication failure.")


class FakeSpotifyAdapter(_BaseFakeAdapter):
    service = Service.SPOTIFY


class FakeYouTubeMusicAdapter(_BaseFakeAdapter):
    service = Service.YTMUSIC
