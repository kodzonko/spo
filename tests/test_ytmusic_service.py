"""Tests for the YouTube Music service adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import requests

from spo.exceptions import RateLimitError
from spo.models import CollectionKind
from spo.services.ytmusic import YouTubeMusicAdapter

if TYPE_CHECKING:
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


def test_call_ignores_invalid_retry_after_header(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that invalid Retry-After values still raise a rate-limit error without retry metadata."""
    adapter = YouTubeMusicAdapter(
        account_id=1,
        credential_payload={
            "credential_type": "ytmusic_headers",
            "data": {"headers": {}},
        },
        settings=settings,
    )
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
