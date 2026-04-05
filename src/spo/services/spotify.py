"""Spotify adapter implementation used by spo."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spo.exceptions import AuthenticationError, RateLimitError
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

    from spo.config import Settings

SPOTIFY_SCOPES = (
    "user-library-read "
    "user-library-modify "
    "playlist-read-private "
    "playlist-read-collaborative "
    "playlist-modify-public "
    "playlist-modify-private "
    "user-follow-read "
    "user-follow-modify "
    "user-read-private"
)


class SpotifyAdapter(StreamingServiceAdapter):
    """Read and write Spotify collections through the Spotipy client."""

    service = Service.SPOTIFY
    _capabilities = AdapterCapabilities(
        readable=frozenset(
            {
                CollectionKind.PLAYLIST,
                CollectionKind.SAVED_TRACK,
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
                CollectionKind.SAVED_ALBUM,
                CollectionKind.FOLLOWED_ARTIST,
                CollectionKind.SAVED_PODCAST,
                CollectionKind.SAVED_EPISODE,
            },
        ),
    )

    def __init__(self, *, account_id: int, credential_payload: dict[str, Any], settings: Settings) -> None:
        """Initialize the Spotify adapter for a stored account."""
        super().__init__(
            account_id=account_id,
            credential_payload=credential_payload,
            settings=settings,
        )
        self._client: spotipy.Spotify | None = None
        self._identity: AccountIdentity | None = None

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return the collection operations supported by Spotify."""
        return self._capabilities

    @staticmethod
    def default_redirect_uri(settings: Settings) -> str:
        """Return the default Spotify OAuth callback URL."""
        return f"http://{settings.bind_host}:{settings.bind_port}/callback/spotify"

    @classmethod
    def build_authorize_url(cls, settings: Settings, credential_payload: dict[str, Any], state: str) -> str:
        """Build the Spotify OAuth authorization URL for a pending login."""
        redirect_uri = credential_payload.get("redirect_uri") or cls.default_redirect_uri(settings)
        oauth = SpotifyOAuth(
            client_id=credential_payload["client_id"],
            client_secret=credential_payload["client_secret"],
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            show_dialog=True,
            open_browser=False,
            cache_handler=None,
        )
        return oauth.get_authorize_url(state=state)

    @classmethod
    def exchange_code(
        cls,
        *,
        settings: Settings,
        credential_payload: dict[str, Any],
        code: str,
    ) -> dict[str, Any]:
        """Exchange an OAuth code for a persisted Spotify credential payload."""
        redirect_uri = credential_payload.get("redirect_uri") or cls.default_redirect_uri(settings)
        oauth = SpotifyOAuth(
            client_id=credential_payload["client_id"],
            client_secret=credential_payload["client_secret"],
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            open_browser=False,
            cache_handler=None,
        )
        token_info = oauth.get_access_token(code, as_dict=True, check_cache=False)
        if not token_info:
            raise AuthenticationError("Spotify did not return an access token.")
        payload = dict(credential_payload)
        payload["token_info"] = token_info
        return payload

    def _oauth(self) -> SpotifyOAuth:
        redirect_uri = self.credential_payload.get("redirect_uri") or self.default_redirect_uri(self.settings)
        return SpotifyOAuth(
            client_id=self.credential_payload["client_id"],
            client_secret=self.credential_payload["client_secret"],
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            open_browser=False,
            cache_handler=None,
        )

    def _ensure_client(self) -> spotipy.Spotify:
        if self._client is not None:
            return self._client

        token_info = self.credential_payload.get("token_info")
        if not token_info:
            raise AuthenticationError("Spotify account is not authorized yet.")

        oauth = self._oauth()
        expires_at = int(token_info.get("expires_at", 0))
        if expires_at <= time.time() + 60:
            refresh_token = token_info.get("refresh_token")
            if not refresh_token:
                raise AuthenticationError("Spotify refresh token is missing.")
            token_info = oauth.refresh_access_token(refresh_token)
            self.credential_payload["token_info"] = token_info

        self._client = spotipy.Spotify(
            auth=token_info["access_token"],
            requests_timeout=30,
            retries=0,
        )
        return self._client

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as exc:  # pragma: no cover - behavior from library
            if exc.http_status == 429:
                retry_after = None
                headers = getattr(exc, "headers", None) or {}
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
                raise RateLimitError("Spotify rate limit exceeded.", retry_after) from exc
            if exc.http_status == 401:
                raise AuthenticationError("Spotify access token is invalid.") from exc
            raise

    def authenticate(self) -> AccountIdentity:
        """Validate credentials and return the authenticated Spotify account."""
        client = self._ensure_client()
        if self._identity is None:
            current_user = self._call(client.current_user)
            self._identity = AccountIdentity(
                remote_account_id=str(current_user["id"]),
                display_name=str(current_user.get("display_name") or current_user["id"]),
            )
        return self._identity

    def _offset_cursor(self, cursor: str | None) -> int:
        return int(cursor or "0")

    def list_collection(self, kind: CollectionKind, cursor: str | None = None, page_size: int = 50) -> Page:
        """Return a page of Spotify library items for the requested kind."""
        client = self._ensure_client()
        offset = self._offset_cursor(cursor)
        if kind == CollectionKind.PLAYLIST:
            payload = self._call(client.current_user_playlists, limit=page_size, offset=offset)
            items = payload.get("items", [])
            next_cursor = str(offset + page_size) if payload.get("next") else None
            return Page(items=items, next_cursor=next_cursor)
        if kind == CollectionKind.SAVED_TRACK:
            payload = self._call(client.current_user_saved_tracks, limit=page_size, offset=offset)
            items = [item["track"] for item in payload.get("items", []) if item.get("track")]
            next_cursor = str(offset + page_size) if payload.get("next") else None
            return Page(items=items, next_cursor=next_cursor)
        if kind == CollectionKind.SAVED_ALBUM:
            payload = self._call(client.current_user_saved_albums, limit=page_size, offset=offset)
            items = [item["album"] for item in payload.get("items", []) if item.get("album")]
            next_cursor = str(offset + page_size) if payload.get("next") else None
            return Page(items=items, next_cursor=next_cursor)
        if kind == CollectionKind.FOLLOWED_ARTIST:
            payload = self._call(client.current_user_followed_artists, limit=page_size, after=cursor)
            artists = payload.get("artists", {})
            items = artists.get("items", [])
            next_cursor = artists.get("cursors", {}).get("after")
            return Page(items=items, next_cursor=next_cursor)
        if kind == CollectionKind.SAVED_PODCAST:
            payload = self._call(client.current_user_saved_shows, limit=page_size, offset=offset)
            items = [item["show"] for item in payload.get("items", []) if item.get("show")]
            next_cursor = str(offset + page_size) if payload.get("next") else None
            return Page(items=items, next_cursor=next_cursor)
        if kind == CollectionKind.SAVED_EPISODE:
            payload = self._call(client.current_user_saved_episodes, limit=page_size, offset=offset)
            items = [item["episode"] for item in payload.get("items", []) if item.get("episode")]
            next_cursor = str(offset + page_size) if payload.get("next") else None
            return Page(items=items, next_cursor=next_cursor)
        raise ValueError(f"Unsupported Spotify collection: {kind}")

    def get_playlist_items(self, playlist_id: str, cursor: str | None = None, page_size: int = 100) -> Page:
        """Return a page of tracks or episodes from a Spotify playlist."""
        client = self._ensure_client()
        offset = self._offset_cursor(cursor)
        payload = self._call(
            client.playlist_items,
            playlist_id,
            limit=page_size,
            offset=offset,
            additional_types=("track", "episode"),
        )
        items: list[dict[str, Any]] = []
        for item in payload.get("items", []):
            track = item.get("track")
            if track:
                items.append(track)
        next_cursor = str(offset + page_size) if payload.get("next") else None
        return Page(items=items, next_cursor=next_cursor)

    def search(self, kind: CollectionKind, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search Spotify for catalog items matching the query."""
        client = self._ensure_client()
        search_type = {
            CollectionKind.SAVED_TRACK: "track",
            CollectionKind.LIKED_TRACK: "track",
            CollectionKind.SAVED_ALBUM: "album",
            CollectionKind.FOLLOWED_ARTIST: "artist",
            CollectionKind.SAVED_PODCAST: "show",
            CollectionKind.SAVED_EPISODE: "episode",
            CollectionKind.PLAYLIST: "playlist",
        }[kind]
        payload = self._call(client.search, q=query, type=search_type, limit=min(limit, 10))
        return payload.get(f"{search_type}s", {}).get("items", [])

    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a private Spotify playlist."""
        client = self._ensure_client()
        owner = self.authenticate().remote_account_id
        payload = self._call(
            client.user_playlist_create,
            owner,
            name,
            public=False,
            description=description,
        )
        return {"id": payload["id"], "name": payload["name"]}

    def add_playlist_items(self, playlist_id: str, item_ids: list[str]) -> None:
        """Append items to a Spotify playlist in API-sized batches."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 100):
            self._call(client.playlist_add_items, playlist_id, batch)

    def save_tracks(self, item_ids: list[str]) -> None:
        """Save tracks to the current Spotify library."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 50):
            self._call(client.current_user_saved_tracks_add, batch)

    def save_albums(self, item_ids: list[str]) -> None:
        """Save albums to the current Spotify library."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 20):
            self._call(client.current_user_saved_albums_add, batch)

    def follow_artists(self, item_ids: list[str]) -> None:
        """Follow artists on behalf of the current Spotify user."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 50):
            self._call(client.user_follow_artists, batch)

    def save_podcasts(self, item_ids: list[str]) -> None:
        """Save shows to the current Spotify library."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 20):
            self._call(client.current_user_saved_shows_add, batch)

    def save_episodes(self, item_ids: list[str]) -> None:
        """Save podcast episodes to the current Spotify library."""
        client = self._ensure_client()
        for batch in chunked(item_ids, 20):
            self._call(client.current_user_saved_episodes_add, batch)


def sanitize_redirect_uri(raw_redirect_uri: str | None, settings: Settings) -> str:
    """Return a valid redirect URI or fall back to the default callback."""
    if not raw_redirect_uri:
        return SpotifyAdapter.default_redirect_uri(settings)
    parsed = urlparse(raw_redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return SpotifyAdapter.default_redirect_uri(settings)
    return raw_redirect_uri
