"""Tests for the SQLite persistence layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spo.models import CredentialType, TaskState
from spo.persistence import Database, TaskUpsert

if TYPE_CHECKING:
    from pathlib import Path


def test_database_persists_credentials_and_job_scope(tmp_path: Path) -> None:
    """Test that credentials and job scope values round-trip through storage."""
    db = Database(tmp_path / "state.db")
    db.initialize()

    source_account_id = db.upsert_account(
        service="spotify",
        auth_status="connected",
        remote_account_id="spotify-user",
        display_name="Spotify User",
    )
    target_account_id = db.upsert_account(
        service="ytmusic",
        auth_status="connected",
        remote_account_id="yt-user",
        display_name="YT User",
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
        service="spotify",
        auth_status="connected",
        remote_account_id="spotify-user",
        display_name="Spotify User",
    )
    target_account_id = db.upsert_account(
        service="ytmusic",
        auth_status="connected",
        remote_account_id="yt-user",
        display_name="YT User",
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
