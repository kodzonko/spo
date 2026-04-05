from __future__ import annotations

"""Tests for synchronization engine behavior."""

from typing import TYPE_CHECKING

from spo.exceptions import RateLimitError
from spo.models import CollectionKind, CredentialType, JobStatus, Service
from spo.utils import utcnow
from tests.fakes import FakeSpotifyAdapter, FakeYouTubeMusicAdapter

if TYPE_CHECKING:
    from spo.app import AppState


def test_sync_engine_skips_existing_items_and_resumes_without_duplicates(app_state: AppState) -> None:
    """Test that sync skips existing items and does not duplicate them on resume."""
    source_state = {
        "identity": {
            "remote_account_id": "spotify-src",
            "display_name": "Source Spotify",
        },
        "collections": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "id": "sp-track-1",
                    "name": "Already There",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration_ms": 180000,
                },
                {
                    "id": "sp-track-2",
                    "name": "Needs Migration",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Album Two"},
                    "duration_ms": 200000,
                },
            ],
        },
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }
    target_state = {
        "identity": {
            "remote_account_id": "yt-target",
            "display_name": "Target YT Music",
        },
        "collections": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "videoId": "yt-track-1",
                    "title": "Already There",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration": "3:00",
                },
            ],
        },
        "playlist_items": {},
        "search": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "videoId": "yt-track-2",
                    "title": "Needs Migration",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Different Release"},
                    "duration": "3:20",
                },
            ],
        },
        "catalog": {
            CollectionKind.SAVED_TRACK.value: {
                "yt-track-1": {
                    "videoId": "yt-track-1",
                    "title": "Already There",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration": "3:00",
                },
                "yt-track-2": {
                    "videoId": "yt-track-2",
                    "title": "Needs Migration",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Different Release"},
                    "duration": "3:20",
                },
            },
        },
    }
    FakeSpotifyAdapter.STATE["source"] = source_state
    FakeYouTubeMusicAdapter.STATE["target"] = target_state

    source_account_id = app_state.db.upsert_account(
        service=Service.SPOTIFY.value,
        auth_status="connected",
        remote_account_id="spotify-src",
        display_name="Source Spotify",
    )
    target_account_id = app_state.db.upsert_account(
        service=Service.YTMUSIC.value,
        auth_status="connected",
        remote_account_id="yt-target",
        display_name="Target YT Music",
    )
    app_state.db.save_credentials(
        source_account_id,
        CredentialType.SPOTIFY_OAUTH.value,
        {"state_key": "source"},
    )
    app_state.db.save_credentials(
        target_account_id,
        CredentialType.YTMUSIC_HEADERS.value,
        {"state_key": "target"},
    )
    job_id = app_state.db.create_job(
        source_account_id,
        target_account_id,
        [CollectionKind.SAVED_TRACK.value],
    )

    app_state.runner.start(job_id)
    app_state.runner.wait()

    job = app_state.db.get_job(job_id)
    assert job is not None
    assert job["status"] == JobStatus.COMPLETED_WITH_WARNINGS.value
    assert job["progress_applied_count"] == 1
    assert job["progress_skipped_count"] >= 1
    assert target_state["save_track_calls"] == [["yt-track-2"]]

    app_state.runner.start(job_id)
    app_state.runner.wait()

    assert target_state["save_track_calls"] == [["yt-track-2"]]


def test_playlist_sync_merges_into_existing_playlist_and_preserves_target_only_items(
    app_state: AppState,
) -> None:
    """Test that playlist sync merges without removing target-only items."""
    source_state = {
        "identity": {
            "remote_account_id": "spotify-src",
            "display_name": "Source Spotify",
        },
        "collections": {
            CollectionKind.PLAYLIST.value: [
                {
                    "id": "sp-playlist-1",
                    "name": "Road Trip",
                    "description": "High mileage songs",
                },
            ],
        },
        "playlist_items": {
            "sp-playlist-1": [
                {
                    "id": "sp-track-1",
                    "name": "Existing Favorite",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration_ms": 180000,
                },
                {
                    "id": "sp-track-1b",
                    "name": "Existing Favorite",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration_ms": 180000,
                },
                {
                    "id": "sp-track-2",
                    "name": "Fresh Find",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Album Two"},
                    "duration_ms": 201000,
                },
            ],
        },
        "search": {},
        "catalog": {},
    }
    target_state = {
        "identity": {
            "remote_account_id": "yt-target",
            "display_name": "Target YT Music",
        },
        "collections": {
            CollectionKind.PLAYLIST.value: [{"id": "yt-playlist-1", "name": "Road Trip", "description": "Existing"}],
        },
        "playlist_items": {
            "yt-playlist-1": [
                {
                    "videoId": "yt-track-1",
                    "title": "Existing Favorite",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration": "3:00",
                },
            ],
        },
        "search": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "videoId": "yt-track-1",
                    "title": "Existing Favorite",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration": "3:00",
                },
                {
                    "videoId": "yt-track-2",
                    "title": "Fresh Find",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Compilation"},
                    "duration": "3:21",
                },
            ],
        },
        "catalog": {
            CollectionKind.SAVED_TRACK.value: {
                "yt-track-1": {
                    "videoId": "yt-track-1",
                    "title": "Existing Favorite",
                    "artists": [{"name": "Artist One"}],
                    "album": {"name": "Album One"},
                    "duration": "3:00",
                },
                "yt-track-2": {
                    "videoId": "yt-track-2",
                    "title": "Fresh Find",
                    "artists": [{"name": "Artist Two"}],
                    "album": {"name": "Compilation"},
                    "duration": "3:21",
                },
            },
        },
    }
    FakeSpotifyAdapter.STATE["source"] = source_state
    FakeYouTubeMusicAdapter.STATE["target"] = target_state

    source_account_id = app_state.db.upsert_account(
        service=Service.SPOTIFY.value,
        auth_status="connected",
        remote_account_id="spotify-src",
        display_name="Source Spotify",
    )
    target_account_id = app_state.db.upsert_account(
        service=Service.YTMUSIC.value,
        auth_status="connected",
        remote_account_id="yt-target",
        display_name="Target YT Music",
    )
    app_state.db.save_credentials(
        source_account_id,
        CredentialType.SPOTIFY_OAUTH.value,
        {"state_key": "source"},
    )
    app_state.db.save_credentials(
        target_account_id,
        CredentialType.YTMUSIC_HEADERS.value,
        {"state_key": "target"},
    )
    job_id = app_state.db.create_job(
        source_account_id,
        target_account_id,
        [CollectionKind.PLAYLIST.value],
    )

    app_state.runner.start(job_id)
    app_state.runner.wait()

    job = app_state.db.get_job(job_id)
    assert job is not None
    assert job["status"] == JobStatus.COMPLETED_WITH_WARNINGS.value
    assert target_state.get("created_playlists", []) == []
    assert target_state["playlist_add_calls"] == [("yt-playlist-1", ["yt-track-1", "yt-track-2"])]
    assert len(target_state["playlist_items"]["yt-playlist-1"]) == 3


def test_rate_limited_job_pauses_then_auto_resumes(app_state: AppState) -> None:
    """Test that rate-limited jobs pause and later auto-resume successfully."""
    source_state = {
        "identity": {
            "remote_account_id": "spotify-src",
            "display_name": "Source Spotify",
        },
        "collections": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "id": "sp-track-9",
                    "name": "Retry Me",
                    "artists": [{"name": "Artist Nine"}],
                    "album": {"name": "Album Nine"},
                    "duration_ms": 190000,
                },
            ],
        },
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }
    target_state = {
        "identity": {
            "remote_account_id": "yt-target",
            "display_name": "Target YT Music",
        },
        "collections": {},
        "playlist_items": {},
        "search": {
            CollectionKind.SAVED_TRACK.value: [
                {
                    "videoId": "yt-track-9",
                    "title": "Retry Me",
                    "artists": [{"name": "Artist Nine"}],
                    "album": {"name": "Album Nine"},
                    "duration": "3:10",
                },
            ],
        },
        "catalog": {
            CollectionKind.SAVED_TRACK.value: {
                "yt-track-9": {
                    "videoId": "yt-track-9",
                    "title": "Retry Me",
                    "artists": [{"name": "Artist Nine"}],
                    "album": {"name": "Album Nine"},
                    "duration": "3:10",
                },
            },
        },
        "save_tracks_effects": [RateLimitError("Slow down", retry_after=0)],
    }
    FakeSpotifyAdapter.STATE["source"] = source_state
    FakeYouTubeMusicAdapter.STATE["target"] = target_state

    source_account_id = app_state.db.upsert_account(
        service=Service.SPOTIFY.value,
        auth_status="connected",
        remote_account_id="spotify-src",
        display_name="Source Spotify",
    )
    target_account_id = app_state.db.upsert_account(
        service=Service.YTMUSIC.value,
        auth_status="connected",
        remote_account_id="yt-target",
        display_name="Target YT Music",
    )
    app_state.db.save_credentials(
        source_account_id,
        CredentialType.SPOTIFY_OAUTH.value,
        {"state_key": "source"},
    )
    app_state.db.save_credentials(
        target_account_id,
        CredentialType.YTMUSIC_HEADERS.value,
        {"state_key": "target"},
    )
    job_id = app_state.db.create_job(
        source_account_id,
        target_account_id,
        [CollectionKind.SAVED_TRACK.value],
    )

    app_state.runner.start(job_id)
    app_state.runner.wait()

    paused_job = app_state.db.get_job(job_id)
    assert paused_job is not None
    assert paused_job["status"] == JobStatus.PAUSED_RATE_LIMIT.value
    assert app_state.db.get_latest_cooldown(target_account_id) is not None
    assert target_state.get("save_track_calls", []) == []

    app_state.db.update_job(job_id, resume_token=utcnow())
    app_state.runner.auto_resume()
    app_state.runner.wait()

    completed_job = app_state.db.get_job(job_id)
    assert completed_job is not None
    assert completed_job["status"] == JobStatus.COMPLETED.value
    assert target_state["save_track_calls"] == [["yt-track-9"]]
