from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Service(StrEnum):
    SPOTIFY = "spotify"
    YTMUSIC = "ytmusic"
    APPLE_MUSIC = "apple_music"


class CollectionKind(StrEnum):
    PLAYLIST = "playlist"
    SAVED_TRACK = "saved_track"
    LIKED_TRACK = "liked_track"
    SAVED_ALBUM = "saved_album"
    FOLLOWED_ARTIST = "followed_artist"
    SAVED_PODCAST = "saved_podcast"
    SAVED_EPISODE = "saved_episode"


class JobStatus(StrEnum):
    DRAFT = "draft"
    SNAPSHOTTING = "snapshotting"
    PLANNING = "planning"
    APPLYING = "applying"
    PAUSED_RATE_LIMIT = "paused_rate_limit"
    PAUSED_AUTH = "paused_auth"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class CredentialType(StrEnum):
    SPOTIFY_OAUTH = "spotify_oauth"
    YTMUSIC_HEADERS = "ytmusic_headers"
    YTMUSIC_OAUTH = "ytmusic_oauth"


@dataclass(slots=True)
class CanonicalWork:
    kind: CollectionKind
    source_service: Service
    source_id: str
    title: str
    primary_creators: list[str] = field(default_factory=list)
    secondary_creators: list[str] = field(default_factory=list)
    container_title: str | None = None
    duration_ms: int | None = None
    year: int | None = None
    explicit: bool | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CanonicalWork":
        return cls(
            kind=CollectionKind(payload["kind"]),
            source_service=Service(payload["source_service"]),
            source_id=str(payload["source_id"]),
            title=str(payload["title"]),
            primary_creators=list(payload.get("primary_creators", [])),
            secondary_creators=list(payload.get("secondary_creators", [])),
            container_title=payload.get("container_title"),
            duration_ms=payload.get("duration_ms"),
            year=payload.get("year"),
            explicit=payload.get("explicit"),
            external_ids=dict(payload.get("external_ids", {})),
            fingerprint=str(payload.get("fingerprint", "")),
        )


@dataclass(slots=True)
class Page:
    items: list[dict[str, Any]]
    next_cursor: str | None = None


@dataclass(slots=True)
class AccountIdentity:
    remote_account_id: str
    display_name: str


@dataclass(slots=True)
class AdapterCapabilities:
    readable: frozenset[CollectionKind]
    writable: frozenset[CollectionKind]

    def can_read(self, kind: CollectionKind) -> bool:
        return kind in self.readable

    def can_write(self, kind: CollectionKind) -> bool:
        return kind in self.writable


READABLE_COLLECTIONS = tuple(CollectionKind)
WRITABLE_COLLECTIONS = tuple(CollectionKind)
