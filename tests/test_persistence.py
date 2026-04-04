from spo.models import CredentialType
from spo.persistence import Database


def test_database_persists_credentials_and_job_scope(tmp_path):
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
    job_id = db.create_job(
        source_account_id, target_account_id, ["saved_track", "playlist"]
    )

    credentials = db.get_credentials(source_account_id)
    job = db.get_job(job_id)

    assert credentials is not None
    assert credentials["payload"]["client_id"] == "abc"
    assert job is not None
    assert job["scope"] == ["saved_track", "playlist"]
