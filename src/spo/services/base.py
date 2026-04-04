from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from spo.config import Settings
from spo.models import (
    AccountIdentity,
    AdapterCapabilities,
    CollectionKind,
    Page,
    Service,
)


class StreamingServiceAdapter(ABC):
    service: Service
    capabilities: AdapterCapabilities

    def __init__(
        self,
        *,
        account_id: int,
        credential_payload: dict[str, Any],
        settings: Settings,
    ) -> None:
        self.account_id = account_id
        self.credential_payload = credential_payload
        self.settings = settings

    @property
    def persisted_payload(self) -> dict[str, Any]:
        return self.credential_payload

    @abstractmethod
    def authenticate(self) -> AccountIdentity:
        raise NotImplementedError

    @abstractmethod
    def list_collection(
        self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50
    ) -> Page:
        raise NotImplementedError

    @abstractmethod
    def get_playlist_items(
        self, playlist_id: str, cursor: str | None = None, page_size: int = 100
    ) -> Page:
        raise NotImplementedError

    @abstractmethod
    def search(
        self, kind: CollectionKind, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def add_playlist_items(self, playlist_id: str, item_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_tracks(self, item_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_albums(self, item_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def follow_artists(self, item_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_podcasts(self, item_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_episodes(self, item_ids: list[str]) -> None:
        raise NotImplementedError

    def get_existing_state(self, kind: CollectionKind) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.list_collection(kind, cursor=cursor, page_size=100)
            items.extend(page.items)
            if page.next_cursor is None:
                return items
            cursor = page.next_cursor
