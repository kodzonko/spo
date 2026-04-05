"""Tests for the SQLite persistence layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spo.models import CredentialType, TaskState
from spo.persistence import AccountUpsert, Database, EntityMappingUpsert, SourceEntityUpsert, TaskUpsert

if TYPE_CHECKING:
    from pathlib import Path


def test_database_persists_credentials_and_job_scope(tmp_path: Path) -> None:
    """Test that credentials and job scope values round-trip through storage."""
    db = Database(tmp_path / "state.db")
    db.initialize()

    source_account_id = db.upsert_account(
        AccountUpsert(
            service="spotify",
            auth_status="connected",
            remote_account_id="spotify-user",
            display_name="Spotify User",
        ),
    )
    target_account_id = db.upsert_account(
        AccountUpsert(
            service="ytmusic",
            auth_status="connected",
            remote_account_id="yt-user",
            display_name="YT User",
        ),
    )
    db.save_credentials(
        source_account_id,
        CredentialType.SPOTIFY_OAUTH.value,
        {"client_id": "abc", "token_info": {"access_token": "secret"}},
    )
    job_id = db.create_job(source_account_id, target_account_id, ["saved_track", "playlist"])

    credentials = db.get_credentials(source_account_id)
    job = db.get_job(job_id)

    assert credentials is not None
    assert credentials["payload"]["client_id"] == "abc"
    assert job is not None
    assert job["scope"] == ["saved_track", "playlist"]


def test_database_create_or_update_task_round_trips_task_upsert(tmp_path: Path) -> None:
    """Test that task upserts insert once and then update the existing task row."""
    db = Database(tmp_path / "state.db")
    db.initialize()

    source_account_id = db.upsert_account(
        AccountUpsert(
            service="spotify",
            auth_status="connected",
            remote_account_id="spotify-user",
            display_name="Spotify User",
        ),
    )
    target_account_id = db.upsert_account(
        AccountUpsert(
            service="ytmusic",
            auth_status="connected",
            remote_account_id="yt-user",
            display_name="YT User",
        ),
    )
    job_id = db.create_job(source_account_id, target_account_id, ["saved_track"])

    task_id, created = db.create_or_update_task(
        TaskUpsert(
            job_id=job_id,
            dedupe_key="job-1:track:42",
            action="mirror_saved_track",
            collection_kind="saved_track",
            payload={"score": 0.92},
        ),
    )
    updated_task_id, created_again = db.create_or_update_task(
        TaskUpsert(
            job_id=job_id,
            dedupe_key="job-1:track:42",
            action="mirror_saved_track",
            collection_kind="saved_track",
            target_entity_id="yt-track-42",
            payload={"reason": "updated"},
            state=TaskState.COMPLETED.value,
            last_error=None,
        ),
    )

    task = db.get_task_by_dedupe_key("job-1:track:42")

    assert created is True
    assert created_again is False
    assert updated_task_id == task_id
    assert task is not None
    assert task["target_entity_id"] == "yt-track-42"
    assert task["state"] == TaskState.COMPLETED.value
    assert task["payload"] == {"reason": "updated"}


def test_database_structured_upserts_preserve_existing_rows(tmp_path: Path) -> None:
    """Test that account, source entity, and mapping upserts keep stable identities."""
    db = Database(tmp_path / "state.db")
    db.initialize()

    account_id = db.upsert_account(
        AccountUpsert(
            service="spotify",
            auth_status="pending",
            remote_account_id="spotify-user",
            display_name="Spotify User",
        ),
    )
    updated_account_id = db.upsert_account(
        AccountUpsert(
            service="spotify",
            auth_status="connected",
            remote_account_id="spotify-user",
            display_name="Connected Spotify User",
        ),
    )
    target_account_id = db.upsert_account(
        AccountUpsert(
            service="ytmusic",
            auth_status="connected",
            remote_account_id="yt-user",
            display_name="YT User",
        ),
    )
    job_id = db.create_job(account_id, target_account_id, ["saved_track"])

    source_entity_id, created = db.upsert_source_entity(
        SourceEntityUpsert(
            job_id=job_id,
            dedupe_key="job-1:saved_track:spotify-track-1",
            collection_kind="saved_track",
            source_id="spotify-track-1",
            canonical_payload={"fingerprint": "fp-1", "title": "Track 1"},
            payload={"id": "spotify-track-1", "name": "Track 1"},
            fingerprint="fp-1",
            snapshot_hash="hash-1",
        ),
    )
    repeated_source_entity_id, created_again = db.upsert_source_entity(
        SourceEntityUpsert(
            job_id=job_id,
            dedupe_key="job-1:saved_track:spotify-track-1",
            collection_kind="saved_track",
            source_id="spotify-track-1",
            canonical_payload={"fingerprint": "fp-1", "title": "Track 1"},
            payload={"id": "spotify-track-1", "name": "Track 1"},
            fingerprint="fp-1",
            snapshot_hash="hash-1",
        ),
    )

    db.upsert_mapping(
        EntityMappingUpsert(
            source_service="spotify",
            target_service="ytmusic",
            source_fingerprint="fp-1",
            target_id="yt-track-1",
            target_kind="saved_track",
            confidence=0.8,
            match_method="search",
        ),
    )
    db.upsert_mapping(
        EntityMappingUpsert(
            source_service="spotify",
            target_service="ytmusic",
            source_fingerprint="fp-1",
            target_id="yt-track-1b",
            target_kind="saved_track",
            confidence=1.0,
            match_method="applied",
        ),
    )

    account = db.get_account(account_id)
    mapping = db.find_mapping(
        source_service="spotify",
        target_service="ytmusic",
        source_fingerprint="fp-1",
        target_kind="saved_track",
    )

    assert account is not None
    assert account_id == updated_account_id
    assert account["display_name"] == "Connected Spotify User"
    assert account["auth_status"] == "connected"
    assert created is True
    assert created_again is False
    assert repeated_source_entity_id == source_entity_id
    assert mapping is not None
    assert mapping["target_id"] == "yt-track-1b"
    assert mapping["match_method"] == "applied"
