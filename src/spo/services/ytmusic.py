"""YouTube Music adapter implementation used by spo."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn, ParamSpec, TypeVar

import requests
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth.credentials import OAuthCredentials
from ytmusicapi.exceptions import YTMusicServerError
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
YTMUSIC_OAUTH_TOKEN_FIELDS = frozenset(
    {
        "access_token",
        "expires_at",
        "expires_in",
        "refresh_token",
        "scope",
        "token_type",
    },
)
YTMUSIC_SERVER_STATUS_PATTERN = re.compile(r"Server returned HTTP (?P<status_code>\d+):")
YTMUSIC_OAUTH_INVALID_ARGUMENT_MESSAGE = (
    "YouTube Music accepted the Google OAuth consent, but rejected the authenticated library request. "
    "This matches a known upstream ytmusicapi OAuth issue that currently causes "
    "`Request contains an invalid argument` failures for some OAuth sessions."
)
YTMUSIC_EXPERIMENTAL_OAUTH_FALLBACK_MESSAGE = (
    "YouTube Music OAuth only worked after switching to an experimental client profile. "
    "This can unblock connection setup, but later library reads may still depend on upstream "
    "ytmusicapi compatibility with that profile."
)


@dataclass(frozen=True, slots=True)
class YouTubeMusicOAuthProfile:
    """Runtime YouTube client profile used for experimental OAuth compatibility."""

    key: str
    client_name: str | None = None
    client_version: str | None = None
    hl: str | None = None
    gl: str | None = None
    use_raw_auth_probe: bool = False


YTMUSIC_WEB_REMIX_OAUTH_PROFILE = YouTubeMusicOAuthProfile(key="web_remix")
YTMUSIC_IOS_MUSIC_OAUTH_PROFILE = YouTubeMusicOAuthProfile(
    key="ios_music_v6_42",
    client_name="IOS_MUSIC",
    client_version="6.42",
    hl="en",
    gl="US",
    use_raw_auth_probe=True,
)
YTMUSIC_TVHTML5_OAUTH_PROFILE = YouTubeMusicOAuthProfile(
    key="tvhtml5_v7",
    client_name="TVHTML5",
    client_version="7.20241013.17.00",
    hl="en",
    gl="US",
    use_raw_auth_probe=True,
)
YTMUSIC_TVHTML5_LEGACY_OAUTH_PROFILE = YouTubeMusicOAuthProfile(
    key="tvhtml5_v2",
    client_name="TVHTML5",
    client_version="2.0",
    hl="en",
    gl="US",
    use_raw_auth_probe=True,
)
YTMUSIC_OAUTH_PROFILES = (
    YTMUSIC_WEB_REMIX_OAUTH_PROFILE,
    YTMUSIC_IOS_MUSIC_OAUTH_PROFILE,
    YTMUSIC_TVHTML5_OAUTH_PROFILE,
    YTMUSIC_TVHTML5_LEGACY_OAUTH_PROFILE,
)
YTMUSIC_OAUTH_PROFILES_BY_KEY = {profile.key: profile for profile in YTMUSIC_OAUTH_PROFILES}
YTMUSIC_DEFAULT_OAUTH_PROFILE_KEY = YTMUSIC_WEB_REMIX_OAUTH_PROFILE.key
YTMUSIC_AUTH_PROBE_BROWSE_ID = "FEmusic_liked_playlists"


def _raise_authentication_error(message: str) -> NoReturn:
    raise AuthenticationError(message)


def sanitize_ytmusic_oauth_token_data(raw_data: object) -> dict[str, Any]:
    """Keep only the OAuth token fields accepted by ``ytmusicapi`` token models."""
    if isinstance(raw_data, str):
        parsed = json.loads(raw_data)
    elif isinstance(raw_data, dict):
        parsed = dict(raw_data)
    else:
        parsed = json.loads(json.dumps(raw_data))

    if not isinstance(parsed, dict):
        _raise_authentication_error("YouTube Music credentials are invalid.")

    token_data = {key: parsed[key] for key in YTMUSIC_OAUTH_TOKEN_FIELDS if key in parsed}
    for key in ("expires_at", "expires_in"):
        if key not in token_data:
            continue
        try:
            token_data[key] = int(token_data[key])
        except TypeError, ValueError:
            token_data.pop(key, None)
    return token_data


def _ytmusic_server_status_code(exc: YTMusicServerError) -> int | None:
    """Extract the HTTP status code embedded in ``ytmusicapi`` server errors."""
    match = YTMUSIC_SERVER_STATUS_PATTERN.search(str(exc))
    if match is None:
        return None
    try:
        return int(match.group("status_code"))
    except ValueError:
        return None


def _apply_ytmusic_oauth_profile(client: YTMusic, profile: YouTubeMusicOAuthProfile) -> None:
    """Mutate a ``YTMusic`` client instance to emulate an alternate YouTube client profile."""
    context = getattr(client, "context", None)
    if not isinstance(context, dict):
        return
    client_context = context.get("context")
    if not isinstance(client_context, dict):
        return
    client_metadata = client_context.get("client")
    if not isinstance(client_metadata, dict):
        return
    if profile.client_name is not None:
        client_metadata["clientName"] = profile.client_name
    if profile.client_version is not None:
        client_metadata["clientVersion"] = profile.client_version
    if profile.hl is not None:
        client_metadata["hl"] = profile.hl
    if profile.gl is not None:
        client_metadata["gl"] = profile.gl


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
        payload_profile_key = self.credential_payload.get("oauth_profile")
        self._oauth_profile_key = str(payload_profile_key) if payload_profile_key else None
        self._oauth_fallback_used = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return the collection operations supported by YouTube Music."""
        return self._capabilities

    def _auth_file_path(self) -> Path:
        auth_dir = self.settings.app_data_dir / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        return auth_dir / f"ytmusic-account-{self.account_id}.json"

    def _oauth_token_data(self) -> dict[str, Any]:
        """Return the token payload that should be written to the SDK auth file."""
        auth_file = self._auth_file_path()
        if auth_file.exists():
            return sanitize_ytmusic_oauth_token_data(auth_file.read_text(encoding="utf-8"))
        return sanitize_ytmusic_oauth_token_data(self.credential_payload.get("data", {}))

    @property
    def persisted_payload(self) -> dict[str, Any]:
        """Return credentials, including refreshed OAuth token data when available."""
        payload = dict(self.credential_payload)
        payload["data"] = self._oauth_token_data()
        if self._oauth_profile_key is not None:
            payload["oauth_profile"] = self._oauth_profile_key
        if self._oauth_fallback_used:
            payload["oauth_profile_notice"] = YTMUSIC_EXPERIMENTAL_OAUTH_FALLBACK_MESSAGE
        return payload

    def _oauth_profile(self) -> YouTubeMusicOAuthProfile:
        """Return the currently selected OAuth client profile."""
        if self._oauth_profile_key is None:
            return YTMUSIC_OAUTH_PROFILES_BY_KEY[YTMUSIC_DEFAULT_OAUTH_PROFILE_KEY]
        return YTMUSIC_OAUTH_PROFILES_BY_KEY.get(
            self._oauth_profile_key,
            YTMUSIC_OAUTH_PROFILES_BY_KEY[YTMUSIC_DEFAULT_OAUTH_PROFILE_KEY],
        )

    def _oauth_profile_candidates(self) -> tuple[YouTubeMusicOAuthProfile, ...]:
        """Return OAuth client profiles to try, preferring any previously successful profile."""
        seen_keys: set[str] = set()
        candidates: list[YouTubeMusicOAuthProfile] = []
        preferred_keys: list[str] = []
        if self._oauth_profile_key is not None:
            preferred_keys.append(self._oauth_profile_key)
        preferred_keys.extend(profile.key for profile in YTMUSIC_OAUTH_PROFILES)
        for key in preferred_keys:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            profile = YTMUSIC_OAUTH_PROFILES_BY_KEY.get(key)
            if profile is not None:
                candidates.append(profile)
        return tuple(candidates)

    def _oauth_client_credentials(self) -> OAuthCredentials:
        """Build OAuth credentials for the stored Google client."""
        oauth_client = self.credential_payload.get("oauth_client")
        if not isinstance(oauth_client, dict):
            _raise_authentication_error("YouTube Music OAuth client credentials are missing.")
        client_id = str(oauth_client.get("client_id") or "").strip()
        client_secret = str(oauth_client.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            _raise_authentication_error("YouTube Music OAuth client credentials are incomplete.")
        return OAuthCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )

    def _build_client(self, profile: YouTubeMusicOAuthProfile) -> YTMusic:
        """Instantiate a ``YTMusic`` client configured for the given OAuth profile."""
        token_data = self._oauth_token_data()
        if not token_data:
            _raise_authentication_error("YouTube Music credentials are missing.")
        auth_file = self._auth_file_path()
        auth_file.write_text(
            json.dumps(token_data),
            encoding="utf-8",
        )
        client = YTMusic(
            str(auth_file),
            oauth_credentials=self._oauth_client_credentials(),
        )
        _apply_ytmusic_oauth_profile(client, profile)
        return client

    def _validate_client(self, client: YTMusic, profile: YouTubeMusicOAuthProfile) -> None:
        """Run the cheapest practical authenticated probe for the selected profile."""
        if profile.use_raw_auth_probe and hasattr(client, "_send_request"):
            send_request = client._send_request  # noqa: SLF001 - experimental OAuth probe uses the raw InnerTube request
            self._call(
                send_request,
                "browse",
                {"browseId": YTMUSIC_AUTH_PROBE_BROWSE_ID},
            )
            return
        self._call(client.get_library_playlists, limit=1)

    def _ensure_client(self) -> YTMusic:
        if self._client is not None:
            return self._client
        credential_type = self.credential_payload.get("credential_type")
        if not credential_type:
            raise AuthenticationError("YouTube Music credentials are missing.")
        try:
            if credential_type != "ytmusic_oauth":
                _raise_authentication_error("Unsupported YouTube Music credential type.")
            self._client = self._build_client(self._oauth_profile())
        except Exception as exc:  # pragma: no cover - library internals
            message = f"YouTube Music authentication failed: {exc}"
            raise AuthenticationError(message) from exc
        return self._client

    def _call(self, fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except YTMusicServerError as exc:  # pragma: no cover - library internals
            status_code = _ytmusic_server_status_code(exc)
            if status_code == HTTP_TOO_MANY_REQUESTS:
                raise RateLimitError("YouTube Music rate limit exceeded.", None) from exc
            if status_code in {HTTP_UNAUTHORIZED, HTTP_FORBIDDEN}:
                raise AuthenticationError("YouTube Music credentials are invalid.") from exc
            if (
                status_code == requests.codes["bad_request"]
                and self.credential_payload.get("credential_type") == "ytmusic_oauth"
                and "Request contains an invalid argument." in str(exc)
            ):
                raise AuthenticationError(YTMUSIC_OAUTH_INVALID_ARGUMENT_MESSAGE) from exc
            raise
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
        if self._identity is None:
            last_error: AuthenticationError | None = None
            credential_type = self.credential_payload.get("credential_type")
            if credential_type != "ytmusic_oauth":
                client = self._ensure_client()
                self._call(client.get_library_playlists, limit=1)
            else:
                profiles = self._oauth_profile_candidates()
                for index, profile in enumerate(profiles):
                    self._client = self._build_client(profile)
                    try:
                        self._validate_client(self._client, profile)
                        self._oauth_profile_key = profile.key
                        self._oauth_fallback_used = index > 0
                        break
                    except AuthenticationError as exc:
                        last_error = exc
                        self._client = None
                        if index + 1 < len(profiles):
                            continue
                        raise
                if self._client is None:
                    if last_error is not None:
                        raise last_error
                    raise AuthenticationError("YouTube Music credentials are invalid.")
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
