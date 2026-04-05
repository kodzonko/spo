"""Abstract interfaces for streaming service adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from spo.config import Settings
    from spo.models import (
        AccountIdentity,
        AdapterCapabilities,
        CollectionKind,
        Page,
        Service,
    )


class StreamingServiceAdapter(ABC):
    """Base contract implemented by each streaming service adapter."""

    service: ClassVar[Service]
    _capabilities: ClassVar[AdapterCapabilities]

    def __init__(
        self,
        *,
        account_id: int,
        credential_payload: dict[str, Any],
        settings: Settings,
    ) -> None:
        """Initialize the adapter with persisted credentials and settings."""
        self.account_id = account_id
        self.credential_payload = credential_payload
        self.settings = settings

    @property
    def persisted_payload(self) -> dict[str, Any]:
        """Return the credential payload that should be persisted."""
        return self.credential_payload

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return the collection operations supported by the adapter."""
        return self._capabilities

    @abstractmethod
    def authenticate(self) -> AccountIdentity:
        """Validate credentials and return the authenticated account identity."""
        raise NotImplementedError

    @abstractmethod
    def list_collection(self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50) -> Page:
        """Return a page of items for the requested library collection."""
        raise NotImplementedError

    @abstractmethod
    def get_playlist_items(self, playlist_id: str, cursor: str | None = None, page_size: int = 100) -> Page:
        """Return a page of items from the requested playlist."""
        raise NotImplementedError

    @abstractmethod
    def search(self, kind: CollectionKind, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the remote service for candidates matching the query."""
        raise NotImplementedError

    @abstractmethod
    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a playlist and return its identifying metadata."""
        raise NotImplementedError

    @abstractmethod
    def add_playlist_items(self, playlist_id: str, item_ids: list[str]) -> None:
        """Add the given item IDs to an existing playlist."""
        raise NotImplementedError

    @abstractmethod
    def save_tracks(self, item_ids: list[str]) -> None:
        """Save tracks to the user's library."""
        raise NotImplementedError

    @abstractmethod
    def save_albums(self, item_ids: list[str]) -> None:
        """Save albums to the user's library."""
        raise NotImplementedError

    @abstractmethod
    def follow_artists(self, item_ids: list[str]) -> None:
        """Follow or subscribe to artists."""
        raise NotImplementedError

    @abstractmethod
    def save_podcasts(self, item_ids: list[str]) -> None:
        """Save podcasts or shows to the user's library."""
        raise NotImplementedError

    @abstractmethod
    def save_episodes(self, item_ids: list[str]) -> None:
        """Save podcast episodes to the user's library."""
        raise NotImplementedError

    def get_existing_state(self, kind: CollectionKind) -> list[dict[str, Any]]:
        """Return the full current state for a collection by exhausting pagination."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.list_collection(kind, cursor=cursor, page_size=100)
            items.extend(page.items)
            if page.next_cursor is None:
                return items
            cursor = page.next_cursor
