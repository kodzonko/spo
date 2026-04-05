"""Synchronization orchestration for moving libraries between services."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from spo.exceptions import (
    AuthenticationError,
    RateLimitError,
    UnsupportedOperationError,
)
from spo.matching import (
    MatchResult,
    canonicalize,
    choose_best_match,
    normalize_text,
    playlist_name_match_score,
)
from spo.models import CanonicalWork, CollectionKind, JobStatus, Service, TaskState
from spo.services import SpotifyAdapter, YouTubeMusicAdapter
from spo.utils import json_dumps, stable_hash, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

    from spo.config import Settings
    from spo.persistence import Database
    from spo.services.base import StreamingServiceAdapter

logger = logging.getLogger(__name__)
PLAYLIST_NAME_REUSE_THRESHOLD = 0.85


class ServiceRegistry:
    """Factory registry for instantiating service adapters."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the registry with built-in adapter factories."""
        self.settings = settings
        self._factories: dict[Service, type[StreamingServiceAdapter]] = {
            Service.SPOTIFY: SpotifyAdapter,
            Service.YTMUSIC: YouTubeMusicAdapter,
        }

    def register(self, service: Service, factory: type[StreamingServiceAdapter]) -> None:
        """Register an adapter factory for a service."""
        self._factories[service] = factory

    def create(
        self,
        *,
        service: Service,
        account_id: int,
        credential_payload: dict[str, Any],
    ) -> StreamingServiceAdapter:
        """Create a configured adapter instance for the requested service."""
        factory = self._factories.get(service)
        if factory is None:
            raise ValueError(f"No adapter registered for service {service.value}")
        return factory(
            account_id=account_id,
            credential_payload=credential_payload,
            settings=self.settings,
        )


def remote_item_id(raw: dict[str, Any]) -> str:
    """Extract the primary identifier from a service payload."""
    for key in ("id", "videoId", "playlistId", "browseId", "channelId"):
        value = raw.get(key)
        if value:
            return str(value)
    feedback_token = raw.get("feedbackToken")
    if feedback_token:
        return str(feedback_token)
    raise ValueError(f"Could not determine remote id from payload: {raw}")


def playlist_child_kind(raw: dict[str, Any]) -> CollectionKind:
    """Infer the collection kind represented by a playlist child payload."""
    item_type = str(raw.get("type") or raw.get("resultType") or "").lower()
    if "episode" in item_type or raw.get("videoType") == "MUSIC_VIDEO_TYPE_PODCAST_EPISODE":
        return CollectionKind.SAVED_EPISODE
    return CollectionKind.SAVED_TRACK


def build_queries(work: CanonicalWork) -> list[str]:
    """Build deduplicated search queries for matching a canonical work."""
    creators = " ".join(work.primary_creators[:2]).strip()
    queries = []
    if creators:
        queries.append(f"{work.title} {creators}".strip())
    if work.container_title and creators:
        queries.append(f"{work.title} {creators} {work.container_title}".strip())
    queries.append(work.title)
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        normalized = normalize_text(query)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(query)
    return unique


class SyncEngine:
    """Execute synchronization jobs between a source and target service."""

    def __init__(self, db: Database, settings: Settings, registry: ServiceRegistry) -> None:
        """Initialize the synchronization engine with its dependencies."""
        self.db = db
        self.settings = settings
        self.registry = registry

    def run_job(self, job_id: int, is_cancelled: Callable[[], bool]) -> None:
        """Run a synchronization job until completion, pause, or failure."""
        job = self.db.get_job(job_id)
        if not job:
            raise ValueError(f"Unknown job {job_id}")

        source_account = self.db.get_account(int(job["source_account_id"]))
        target_account = self.db.get_account(int(job["target_account_id"]))
        if not source_account or not target_account:
            raise ValueError("Job references missing accounts.")

        source_credentials = self.db.get_credentials(int(source_account["id"]))
        target_credentials = self.db.get_credentials(int(target_account["id"]))
        if not source_credentials or not target_credentials:
            self.db.update_job(
                job_id,
                status=JobStatus.PAUSED_AUTH.value,
                phase=JobStatus.PAUSED_AUTH.value,
                last_error="One or more accounts are missing credentials.",
            )
            return

        source_service = Service(source_account["service"])
        target_service = Service(target_account["service"])
        source_adapter = self.registry.create(
            service=source_service,
            account_id=int(source_account["id"]),
            credential_payload=source_credentials["payload"],
        )
        target_adapter = self.registry.create(
            service=target_service,
            account_id=int(target_account["id"]),
            credential_payload=target_credentials["payload"],
        )

        if not job["started_at"]:
            self.db.update_job(job_id, started_at=utcnow())

        try:
            source_identity = source_adapter.authenticate()
            target_identity = target_adapter.authenticate()
            self.db.save_credentials(
                int(source_account["id"]),
                source_credentials["credential_type"],
                source_adapter.persisted_payload,
                last_validated_at=utcnow(),
            )
            self.db.save_credentials(
                int(target_account["id"]),
                target_credentials["credential_type"],
                target_adapter.persisted_payload,
                last_validated_at=utcnow(),
            )
            self.db.upsert_account(
                account_id=int(source_account["id"]),
                service=source_service.value,
                remote_account_id=source_identity.remote_account_id,
                display_name=source_identity.display_name,
                auth_status="connected",
                oauth_state=None,
            )
            self.db.upsert_account(
                account_id=int(target_account["id"]),
                service=target_service.value,
                remote_account_id=target_identity.remote_account_id,
                display_name=target_identity.display_name,
                auth_status="connected",
                oauth_state=None,
            )
            self.db.append_event(
                job_id,
                "info",
                f"Authenticated {source_identity.display_name} -> {target_identity.display_name}.",
            )

            selected_kinds = [CollectionKind(value) for value in job["scope"]]
            for kind in selected_kinds:
                if is_cancelled():
                    self._cancel_job(job_id)
                    return
                self.db.update_job(
                    job_id,
                    status=JobStatus.SNAPSHOTTING.value,
                    phase=JobStatus.SNAPSHOTTING.value,
                    current_collection_kind=kind.value,
                )
                if not source_adapter.capabilities.can_read(kind):
                    self._skip_collection(
                        job_id,
                        kind,
                        f"{source_service.value} cannot read {kind.value}.",
                    )
                    continue

                self._snapshot_collection(job_id, source_adapter, kind, is_cancelled)

                self.db.update_job(
                    job_id,
                    status=JobStatus.APPLYING.value,
                    phase=JobStatus.APPLYING.value,
                    current_collection_kind=kind.value,
                )
                if not target_adapter.capabilities.can_write(kind):
                    count = self.db.count_source_entities(job_id, collection_kind=kind.value)
                    if count:
                        self.db.increment_job_counter(job_id, "progress_skipped_count", count)
                    self._skip_collection(
                        job_id,
                        kind,
                        f"{target_service.value} cannot write {kind.value} in v1.",
                    )
                    continue

                if kind == CollectionKind.PLAYLIST:
                    self._apply_playlists(job_id, source_adapter, target_adapter, is_cancelled)
                else:
                    self._apply_library_collection(job_id, source_adapter, target_adapter, kind, is_cancelled)

            final_job = self.db.get_job(job_id)
            status = JobStatus.COMPLETED.value
            if final_job and (
                int(final_job["progress_skipped_count"]) > 0 or int(final_job["progress_failed_count"]) > 0
            ):
                status = JobStatus.COMPLETED_WITH_WARNINGS.value
            self.db.update_job(
                job_id,
                status=status,
                phase=status,
                current_collection_kind=None,
                finished_at=utcnow(),
                last_error=None,
            )
            self.db.append_event(job_id, "info", "Synchronization completed.")
        except AuthenticationError as exc:
            self.db.update_job(
                job_id,
                status=JobStatus.PAUSED_AUTH.value,
                phase=JobStatus.PAUSED_AUTH.value,
                last_error=str(exc),
            )
            self.db.append_event(job_id, "error", str(exc))
        except RateLimitError as exc:
            retry_after_seconds = int(float(exc.retry_after or 3600))
            cooldown_until = (
                (datetime.now(UTC) + timedelta(seconds=retry_after_seconds)).replace(microsecond=0).isoformat()
            )
            account_id = int(target_account["id"])
            job_state = self.db.get_job(job_id)
            if job_state is not None and job_state["phase"] == JobStatus.SNAPSHOTTING.value:
                account_id = int(source_account["id"])
            self.db.set_cooldown(
                account_id=account_id,
                operation="sync",
                cooldown_until=cooldown_until,
                reason=str(exc),
                vendor_hint=f"retry_after={retry_after_seconds}",
            )
            self.db.update_job(
                job_id,
                status=JobStatus.PAUSED_RATE_LIMIT.value,
                phase=JobStatus.PAUSED_RATE_LIMIT.value,
                last_error=str(exc),
                resume_token=cooldown_until,
            )
            self.db.append_event(
                job_id,
                "warning",
                f"Paused due to rate limiting until {cooldown_until}.",
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception("Job %s failed", job_id)
            self.db.update_job(
                job_id,
                status=JobStatus.FAILED.value,
                phase=JobStatus.FAILED.value,
                last_error=str(exc),
                finished_at=utcnow(),
            )
            self.db.append_event(job_id, "error", f"Synchronization failed: {exc}")

    def _cancel_job(self, job_id: int) -> None:
        self.db.update_job(
            job_id,
            status=JobStatus.CANCELED.value,
            phase=JobStatus.CANCELED.value,
            finished_at=utcnow(),
        )
        self.db.append_event(job_id, "warning", "Synchronization canceled.")

    def _skip_collection(self, job_id: int, kind: CollectionKind, reason: str) -> None:
        self.db.append_event(job_id, "warning", reason, {"collection_kind": kind.value})

    def _snapshot_collection(
        self,
        job_id: int,
        adapter: StreamingServiceAdapter,
        kind: CollectionKind,
        is_cancelled: Callable[[], bool],
    ) -> None:
        self.db.append_event(job_id, "info", f"Snapshotting {kind.value}.")
        cursor: str | None = None
        while True:
            if is_cancelled():
                return
            page = adapter.list_collection(kind, cursor=cursor, page_size=50)
            for raw in page.items:
                entity_id = self._store_entity(job_id, adapter.service, kind, raw, cursor)
                if kind == CollectionKind.PLAYLIST and entity_id:
                    self._snapshot_playlist_items(job_id, adapter, entity_id, raw, is_cancelled)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    def _snapshot_playlist_items(
        self,
        job_id: int,
        adapter: StreamingServiceAdapter,
        playlist_entity_id: int,
        playlist_raw: dict[str, Any],
        is_cancelled: Callable[[], bool],
    ) -> None:
        cursor: str | None = None
        absolute_index = 0
        playlist_id = remote_item_id(playlist_raw)
        while True:
            if is_cancelled():
                return
            page = adapter.get_playlist_items(playlist_id, cursor=cursor, page_size=100)
            for offset, raw in enumerate(page.items):
                kind = playlist_child_kind(raw)
                dedupe_key = f"{job_id}:playlist-child:{playlist_entity_id}:{absolute_index + offset}"
                item_id = remote_item_id(raw)
                canonical = canonicalize(adapter.service, kind, item_id, raw)
                _, created = self.db.upsert_source_entity(
                    job_id=job_id,
                    dedupe_key=dedupe_key,
                    collection_kind=kind.value,
                    source_id=item_id,
                    parent_source_id=playlist_entity_id,
                    canonical_payload=canonical.to_dict(),
                    payload=raw,
                    order_index=absolute_index + offset,
                    page_cursor=cursor,
                    fingerprint=canonical.fingerprint,
                    snapshot_hash=stable_hash(json_dumps(raw)),
                )
                if created:
                    self.db.increment_job_counter(job_id, "progress_snapshot_count")
            absolute_index += len(page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    def _store_entity(
        self,
        job_id: int,
        service: Service,
        kind: CollectionKind,
        raw: dict[str, Any],
        cursor: str | None,
    ) -> int:
        item_id = remote_item_id(raw)
        canonical = canonicalize(service, kind, item_id, raw)
        entity_id, created = self.db.upsert_source_entity(
            job_id=job_id,
            dedupe_key=f"{job_id}:{kind.value}:{item_id}",
            collection_kind=kind.value,
            source_id=item_id,
            canonical_payload=canonical.to_dict(),
            payload=raw,
            order_index=None,
            page_cursor=cursor,
            fingerprint=canonical.fingerprint,
            snapshot_hash=stable_hash(json_dumps(raw)),
        )
        if created:
            self.db.increment_job_counter(job_id, "progress_snapshot_count")
        return entity_id

    def _build_existing_index(
        self,
        target: StreamingServiceAdapter,
        kind: CollectionKind,
    ) -> tuple[list[dict[str, Any]], Counter[str]]:
        effective_kind = (
            CollectionKind.SAVED_TRACK
            if target.service == Service.SPOTIFY and kind == CollectionKind.LIKED_TRACK
            else kind
        )
        items = target.get_existing_state(effective_kind)
        fingerprints: Counter[str] = Counter()
        for item in items:
            try:
                item_id = remote_item_id(item)
            except ValueError:
                continue
            item_kind = kind if kind == CollectionKind.PLAYLIST else effective_kind
            fingerprints[canonicalize(target.service, item_kind, item_id, item).fingerprint] += 1
        return items, fingerprints

    def _apply_library_collection(
        self,
        job_id: int,
        source: StreamingServiceAdapter,
        target: StreamingServiceAdapter,
        kind: CollectionKind,
        is_cancelled: Callable[[], bool],
    ) -> None:
        source_entities = self.db.list_source_entities(job_id, collection_kind=kind.value)
        if not source_entities:
            return
        _, target_counts = self._build_existing_index(target, kind)
        pending_ids: list[str] = []
        pending_task_ids: list[int] = []
        pending_fingerprints: list[str] = []

        for entity in source_entities:
            if is_cancelled():
                return
            canonical = CanonicalWork.from_dict(entity["canonical"])
            dedupe_key = f"{job_id}:collection:{entity['id']}"
            existing_task = self.db.get_task_by_dedupe_key(dedupe_key)
            if existing_task and existing_task["state"] in {
                TaskState.COMPLETED.value,
                TaskState.SKIPPED.value,
            }:
                continue

            if target_counts[canonical.fingerprint] > 0:
                task_id, _ = self.db.create_or_update_task(
                    job_id=job_id,
                    dedupe_key=dedupe_key,
                    action=f"mirror_{kind.value}",
                    collection_kind=kind.value,
                    source_entity_id=int(entity["id"]),
                    payload={"reason": "already_present"},
                    state=TaskState.SKIPPED.value,
                )
                self.db.increment_job_counter(job_id, "progress_skipped_count")
                self.db.update_task(task_id, last_error=None)
                continue

            match = self._resolve_target_match(source, target, canonical, kind)
            if not match.accepted or not match.candidate:
                self.db.create_or_update_task(
                    job_id=job_id,
                    dedupe_key=dedupe_key,
                    action=f"mirror_{kind.value}",
                    collection_kind=kind.value,
                    source_entity_id=int(entity["id"]),
                    payload={"reason": "unresolved"},
                    state=TaskState.SKIPPED.value,
                    last_error="No acceptable target candidate found.",
                )
                self.db.increment_job_counter(job_id, "progress_skipped_count")
                self.db.append_event(
                    job_id,
                    "warning",
                    f"Skipped {canonical.title} because no acceptable match was found.",
                )
                continue

            target_id = remote_item_id(match.candidate)
            task_id, _ = self.db.create_or_update_task(
                job_id=job_id,
                dedupe_key=dedupe_key,
                action=f"mirror_{kind.value}",
                collection_kind=kind.value,
                source_entity_id=int(entity["id"]),
                target_entity_id=target_id,
                payload={"match_method": match.method, "score": match.score},
                state=TaskState.PENDING.value,
            )
            pending_ids.append(target_id)
            pending_task_ids.append(task_id)
            pending_fingerprints.append(canonical.fingerprint)

        if not pending_ids:
            return

        try:
            self._write_collection(target, kind, pending_ids)
        except UnsupportedOperationError as exc:
            for task_id in pending_task_ids:
                self.db.update_task(
                    task_id,
                    state=TaskState.SKIPPED.value,
                    last_error=str(exc),
                )
                self.db.increment_job_counter(job_id, "progress_skipped_count")
            self.db.append_event(job_id, "warning", str(exc))
            return

        for task_id, fingerprint, target_id in zip(pending_task_ids, pending_fingerprints, pending_ids, strict=False):
            self.db.update_task(task_id, state=TaskState.COMPLETED.value, last_error=None)
            self.db.increment_job_counter(job_id, "progress_applied_count")
            self.db.upsert_mapping(
                source_service=source.service.value,
                target_service=target.service.value,
                source_fingerprint=fingerprint,
                target_id=target_id,
                target_kind=kind.value,
                confidence=1.0,
                match_method="applied",
            )

    def _apply_playlists(
        self,
        job_id: int,
        source: StreamingServiceAdapter,
        target: StreamingServiceAdapter,
        is_cancelled: Callable[[], bool],
    ) -> None:
        source_playlists = self.db.list_source_entities(job_id, collection_kind=CollectionKind.PLAYLIST.value)
        if not source_playlists:
            return

        target_playlists, _ = self._build_existing_index(target, CollectionKind.PLAYLIST)
        for source_playlist in source_playlists:
            if is_cancelled():
                return
            playlist_work = CanonicalWork.from_dict(source_playlist["canonical"])
            target_playlist = self._resolve_target_playlist(
                source,
                target,
                playlist_work,
                source_playlist["payload"],
                target_playlists,
            )
            playlist_id = target_playlist["id"]
            playlist_task_key = f"{job_id}:playlist:{source_playlist['id']}"
            playlist_task, _ = self.db.create_or_update_task(
                job_id=job_id,
                dedupe_key=playlist_task_key,
                action="ensure_playlist",
                collection_kind=CollectionKind.PLAYLIST.value,
                source_entity_id=int(source_playlist["id"]),
                target_entity_id=playlist_id,
                payload={"playlist_name": playlist_work.title},
                state=TaskState.COMPLETED.value,
            )
            self.db.update_task(playlist_task, last_error=None)
            self.db.upsert_mapping(
                source_service=source.service.value,
                target_service=target.service.value,
                source_fingerprint=playlist_work.fingerprint,
                target_id=playlist_id,
                target_kind=CollectionKind.PLAYLIST.value,
                confidence=1.0,
                match_method="playlist_name",
            )

            target_items_counter = self._playlist_target_counter(target, playlist_id)
            source_seen: Counter[str] = Counter()
            pending_item_ids: list[str] = []
            pending_task_ids: list[int] = []
            pending_fingerprints: list[str] = []

            source_items = self.db.list_source_entities(job_id, parent_source_id=int(source_playlist["id"]))
            for item in source_items:
                if is_cancelled():
                    return
                child_kind = CollectionKind(item["collection_kind"])
                work = CanonicalWork.from_dict(item["canonical"])
                source_seen[work.fingerprint] += 1
                task_key = f"{job_id}:playlist-item:{item['id']}"
                existing_task = self.db.get_task_by_dedupe_key(task_key)
                if existing_task and existing_task["state"] in {
                    TaskState.COMPLETED.value,
                    TaskState.SKIPPED.value,
                }:
                    continue

                if target_items_counter[work.fingerprint] >= source_seen[work.fingerprint]:
                    self.db.create_or_update_task(
                        job_id=job_id,
                        dedupe_key=task_key,
                        action="add_playlist_item",
                        collection_kind=child_kind.value,
                        source_entity_id=int(item["id"]),
                        target_entity_id=playlist_id,
                        payload={"reason": "already_present"},
                        state=TaskState.SKIPPED.value,
                    )
                    self.db.increment_job_counter(job_id, "progress_skipped_count")
                    continue

                match = self._resolve_target_match(source, target, work, child_kind)
                if not match.accepted or not match.candidate:
                    self.db.create_or_update_task(
                        job_id=job_id,
                        dedupe_key=task_key,
                        action="add_playlist_item",
                        collection_kind=child_kind.value,
                        source_entity_id=int(item["id"]),
                        target_entity_id=playlist_id,
                        payload={"reason": "unresolved"},
                        state=TaskState.SKIPPED.value,
                        last_error="No acceptable target candidate found.",
                    )
                    self.db.increment_job_counter(job_id, "progress_skipped_count")
                    self.db.append_event(
                        job_id,
                        "warning",
                        f"Skipped playlist item {work.title} because no acceptable match was found.",
                    )
                    continue

                matched_id = remote_item_id(match.candidate)
                task_id, _ = self.db.create_or_update_task(
                    job_id=job_id,
                    dedupe_key=task_key,
                    action="add_playlist_item",
                    collection_kind=child_kind.value,
                    source_entity_id=int(item["id"]),
                    target_entity_id=playlist_id,
                    payload={"matched_id": matched_id, "score": match.score},
                    state=TaskState.PENDING.value,
                )
                pending_item_ids.append(matched_id)
                pending_task_ids.append(task_id)
                pending_fingerprints.append(work.fingerprint)
                target_items_counter[work.fingerprint] += 1

            if pending_item_ids:
                target.add_playlist_items(playlist_id, pending_item_ids)
                for task_id, fingerprint, matched_id in zip(
                    pending_task_ids,
                    pending_fingerprints,
                    pending_item_ids,
                    strict=False,
                ):
                    self.db.update_task(task_id, state=TaskState.COMPLETED.value, last_error=None)
                    self.db.increment_job_counter(job_id, "progress_applied_count")
                    self.db.upsert_mapping(
                        source_service=source.service.value,
                        target_service=target.service.value,
                        source_fingerprint=fingerprint,
                        target_id=matched_id,
                        target_kind=child_kind.value,
                        confidence=1.0,
                        match_method="playlist_item",
                    )

    def _playlist_target_counter(self, target: StreamingServiceAdapter, playlist_id: str) -> Counter[str]:
        counter: Counter[str] = Counter()
        cursor: str | None = None
        while True:
            page = target.get_playlist_items(playlist_id, cursor=cursor, page_size=100)
            for raw in page.items:
                item_kind = playlist_child_kind(raw)
                try:
                    item_id = remote_item_id(raw)
                except ValueError:
                    continue
                fingerprint = canonicalize(target.service, item_kind, item_id, raw).fingerprint
                counter[fingerprint] += 1
            if page.next_cursor is None:
                return counter
            cursor = page.next_cursor

    def _resolve_target_playlist(
        self,
        source: StreamingServiceAdapter,
        target: StreamingServiceAdapter,
        playlist_work: CanonicalWork,
        playlist_raw: dict[str, Any],
        target_playlists: list[dict[str, Any]],
    ) -> dict[str, Any]:
        mapping = self.db.find_mapping(
            source_service=source.service.value,
            target_service=target.service.value,
            source_fingerprint=playlist_work.fingerprint,
            target_kind=CollectionKind.PLAYLIST.value,
        )
        if mapping:
            for existing in target_playlists:
                if remote_item_id(existing) == mapping["target_id"]:
                    return {
                        "id": mapping["target_id"],
                        "name": existing.get("name") or existing.get("title"),
                    }

        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for candidate in target_playlists:
            candidate_name = str(candidate.get("name") or candidate.get("title") or "")
            score = playlist_name_match_score(playlist_work.title, candidate_name)
            if score > best_score:
                best_score = score
                best_match = candidate

        if best_match and best_score >= PLAYLIST_NAME_REUSE_THRESHOLD:
            return {
                "id": remote_item_id(best_match),
                "name": best_match.get("name") or best_match.get("title"),
            }

        created = target.create_playlist(
            playlist_work.title,
            str(playlist_raw.get("description") or "Migrated by spo"),
        )
        target_playlists.append({"id": created["id"], "name": created["name"]})
        return created

    def _resolve_target_match(
        self,
        source: StreamingServiceAdapter,
        target: StreamingServiceAdapter,
        work: CanonicalWork,
        kind: CollectionKind,
    ) -> MatchResult:
        mapping = self.db.find_mapping(
            source_service=source.service.value,
            target_service=target.service.value,
            source_fingerprint=work.fingerprint,
            target_kind=kind.value,
        )
        if mapping:
            return MatchResult(
                candidate={"id": mapping["target_id"], "title": work.title},
                score=float(mapping["confidence"]),
                gap=1.0,
                accepted=True,
                method=str(mapping["match_method"]),
            )

        aggregated_candidates: list[dict[str, Any]] = []
        for query in build_queries(work):
            aggregated_candidates.extend(target.search(kind, query, limit=10))
        match = choose_best_match(work, aggregated_candidates, target.service)
        if match.accepted and match.candidate:
            self.db.upsert_mapping(
                source_service=source.service.value,
                target_service=target.service.value,
                source_fingerprint=work.fingerprint,
                target_id=remote_item_id(match.candidate),
                target_kind=kind.value,
                confidence=match.score,
                match_method=match.method,
            )
        return match

    def _write_collection(
        self,
        target: StreamingServiceAdapter,
        kind: CollectionKind,
        item_ids: list[str],
    ) -> None:
        if kind in {CollectionKind.SAVED_TRACK, CollectionKind.LIKED_TRACK}:
            target.save_tracks(item_ids)
            return
        if kind == CollectionKind.SAVED_ALBUM:
            target.save_albums(item_ids)
            return
        if kind == CollectionKind.FOLLOWED_ARTIST:
            target.follow_artists(item_ids)
            return
        if kind == CollectionKind.SAVED_PODCAST:
            target.save_podcasts(item_ids)
            return
        if kind == CollectionKind.SAVED_EPISODE:
            target.save_episodes(item_ids)
            return
        raise UnsupportedOperationError(f"Unhandled collection write for {kind.value}.")


class JobRunner:
    """Run synchronization jobs on a background thread."""

    def __init__(self, engine: SyncEngine, db: Database) -> None:
        """Initialize the job runner and its shared state."""
        self.engine = engine
        self.db = db
        self._lock = threading.Lock()
        self._active_job_id: int | None = None
        self._thread: threading.Thread | None = None
        self._cancelled: set[int] = set()

    def start(self, job_id: int) -> None:
        """Start a job unless another job is already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._active_job_id == job_id:
                    return
                raise RuntimeError(f"Job {self._active_job_id} is already running. Only one job can run at a time.")
            self._active_job_id = job_id
            self._cancelled.discard(job_id)
            self._thread = threading.Thread(
                target=self._run,
                args=(job_id,),
                daemon=True,
                name=f"spo-job-{job_id}",
            )
            self._thread.start()

    def _run(self, job_id: int) -> None:
        try:
            self.engine.run_job(job_id, lambda: job_id in self._cancelled)
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None
                    self._thread = None

    def cancel(self, job_id: int) -> None:
        """Cancel an active job or mark an idle job as canceled."""
        with self._lock:
            if self._active_job_id == job_id:
                self._cancelled.add(job_id)
                self.db.append_event(job_id, "warning", "Cancellation requested.")
                return
        self.db.update_job(
            job_id,
            status=JobStatus.CANCELED.value,
            phase=JobStatus.CANCELED.value,
            finished_at=utcnow(),
        )
        self.db.append_event(job_id, "warning", "Synchronization canceled.")

    def auto_resume(self) -> None:
        """Resume incomplete jobs that are eligible to run again."""
        for job in self.db.list_incomplete_jobs():
            if job["status"] == JobStatus.PAUSED_RATE_LIMIT.value:
                resume_token = job.get("resume_token")
                if resume_token:
                    try:
                        ready_at = datetime.fromisoformat(resume_token)
                    except ValueError:
                        ready_at = datetime.now(UTC)
                    if ready_at > datetime.now(UTC):
                        continue
            try:
                self.start(int(job["id"]))
            except RuntimeError:
                return

    def wait(self, timeout: float = 5.0) -> None:
        """Block until the active job thread exits or the timeout expires."""
        deadline = time.time() + timeout
        thread = self._thread
        while thread and thread.is_alive() and time.time() < deadline:
            thread.join(timeout=0.05)
