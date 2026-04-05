"""Tests for the YouTube Music service adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spo.models import CollectionKind
from spo.services.ytmusic import YouTubeMusicAdapter

if TYPE_CHECKING:
    import pytest

    from spo.config import Settings

LIBRARY_PAGE_LIMIT = 5000


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

    adapter = YouTubeMusicAdapter(
        account_id=1,
        credential_payload={
            "credential_type": "ytmusic_headers",
            "data": {"headers": {}},
        },
        settings=settings,
    )

    def fake_ensure_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)

    liked_page = adapter.list_collection(CollectionKind.LIKED_TRACK, page_size=1)
    saved_episode_page = adapter.list_collection(CollectionKind.SAVED_EPISODE, cursor="1", page_size=1)

    assert liked_page.items == [{"videoId": "liked-1"}]
    assert liked_page.next_cursor == "1"
    assert saved_episode_page.items == [{"videoId": "episode-2"}]
    assert saved_episode_page.next_cursor is None
