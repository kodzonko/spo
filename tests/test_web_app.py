"""Tests for the FastAPI web application flows."""

from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from anyio.lowlevel import checkpoint
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from spo.app import AppState, create_app
from spo.models import AccountIdentity, CredentialType, JobStatus, Service
from spo.persistence import AccountUpsert
from spo.services.spotify import SpotifyAdapter
from tests.fakes import FakeSpotifyAdapter, FakeYouTubeMusicAdapter

HTTP_OK = int(requests.codes["ok"])
HTTP_NO_CONTENT = int(requests.codes["no_content"])
HTTP_SEE_OTHER = int(requests.codes["see_other"])
HTTP_NOT_FOUND = int(requests.codes["not_found"])


def _redirect_query_value(location: str, key: str) -> str | None:
    values = parse_qs(urlparse(location).query).get(key)
    return values[0] if values else None


def test_web_app_renders_pages_and_creates_job(app_state: AppState) -> None:
    """Test that the web app renders core pages and creates jobs."""
    FakeSpotifyAdapter.shared_state["source"] = {
        "identity": {
            "remote_account_id": "spotify-src",
            "display_name": "Source Spotify",
        },
        "collections": {},
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }
    FakeYouTubeMusicAdapter.shared_state["target"] = {
        "identity": {
            "remote_account_id": "yt-target",
            "display_name": "Target YT Music",
        },
        "collections": {},
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }

    source_account_id = app_state.db.upsert_account(
        AccountUpsert(
            service=Service.SPOTIFY.value,
            auth_status="connected",
            remote_account_id="spotify-src",
            display_name="Source Spotify",
        ),
    )
    target_account_id = app_state.db.upsert_account(
        AccountUpsert(
            service=Service.YTMUSIC.value,
            auth_status="connected",
            remote_account_id="yt-target",
            display_name="Target YT Music",
        ),
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

    client = TestClient(create_app(app_state))

    assert client.get("/").status_code == HTTP_OK
    assert client.get("/connections").status_code == HTTP_OK
    assert client.get("/sync/new").status_code == HTTP_OK

    response = client.post(
        "/api/jobs",
        data={
            "source_account_id": str(source_account_id),
            "target_account_id": str(target_account_id),
            "collection_kinds": "saved_track",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    location = response.headers["location"]
    assert location.startswith("/jobs/")

    app_state.runner.wait()
    detail = client.get(location)
    assert detail.status_code == HTTP_OK
    history = client.get("/history")
    assert history.status_code == HTTP_OK
    jobs = app_state.db.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["status"] in {
        JobStatus.COMPLETED.value,
        JobStatus.COMPLETED_WITH_WARNINGS.value,
    }


def test_web_app_declares_empty_icons_and_handles_common_icon_probes(app_state: AppState) -> None:
    """Test that the web app avoids favicon 404s without shipping icon assets."""
    client = TestClient(create_app(app_state))

    response = client.get("/")

    assert response.status_code == HTTP_OK
    assert '<link rel="icon" href="data:,">' in response.text
    assert '<link rel="apple-touch-icon" href="data:,">' in response.text
    assert '<link rel="apple-touch-icon-precomposed" href="data:,">' in response.text

    for path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        icon_response = client.get(path)
        assert icon_response.status_code == HTTP_NO_CONTENT
        assert icon_response.content == b""


def test_web_app_can_save_and_validate_ytmusic_connection(app_state: AppState) -> None:
    """Test that YouTube Music headers can be saved and validated."""
    FakeYouTubeMusicAdapter.shared_state["connect"] = {
        "identity": {
            "remote_account_id": "yt-connected",
            "display_name": "Connected YT Music",
        },
        "collections": {},
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }

    client = TestClient(create_app(app_state))

    response = client.post(
        "/api/connections/ytmusic",
        data={"headers_json": '{"state_key":"connect"}'},
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert "/connections?message=" in response.headers["location"]

    accounts = app_state.db.find_account_by_service(Service.YTMUSIC.value)
    assert len(accounts) == 1
    assert accounts[0]["auth_status"] == "connected"

    credentials = app_state.db.get_credentials(int(accounts[0]["id"]))
    assert credentials is not None
    assert credentials["payload"]["data"]["state_key"] == "connect"

    test_response = client.post("/api/connections/ytmusic/test")
    assert test_response.status_code == HTTP_OK
    assert test_response.json()["display_name"] == "Connected YT Music"

    invalid = client.post(
        "/api/connections/ytmusic",
        data={"headers_json": "{not-json}"},
        follow_redirects=False,
    )
    assert invalid.status_code == HTTP_SEE_OTHER
    assert "/connections?error=" in invalid.headers["location"]


def test_web_app_requires_ytmusic_headers_json_for_manual_connection(app_state: AppState) -> None:
    """Test that the manual YouTube Music flow rejects blank headers JSON."""
    client = TestClient(create_app(app_state))

    response = client.post(
        "/api/connections/ytmusic",
        data={"headers_json": "   "},
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert _redirect_query_value(response.headers["location"], "error") == (
        "Paste browser headers JSON, or use Connect YouTube Music above."
    )


def test_web_app_can_start_and_complete_ytmusic_oauth_connection(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the YouTube Music OAuth flow can complete successfully."""
    FakeYouTubeMusicAdapter.shared_state["yt-oauth"] = {
        "identity": {
            "remote_account_id": "yt-oauth-account",
            "display_name": "OAuth YT Music",
        },
        "collections": {},
        "playlist_items": {},
        "search": {},
        "catalog": {},
    }

    class FakeOAuthCredentials:
        def __init__(self, client_id: str, client_secret: str) -> None:
            assert client_id == "google-client-id"
            assert client_secret == "google-client-secret"

        def get_code(self) -> dict[str, str | int]:
            return {
                "device_code": "device-code",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://google.example/device",
                "interval": 1,
                "expires_in": 600,
            }

        def token_from_code(self, device_code: str) -> dict[str, str | int]:
            assert device_code == "device-code"
            return {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "https://www.googleapis.com/auth/youtube",
                "state_key": "yt-oauth",
            }

    monkeypatch.setattr("spo.app.OAuthCredentials", FakeOAuthCredentials)

    client = TestClient(create_app(app_state))

    start = client.post(
        "/api/connections/ytmusic/oauth/start",
        data={
            "client_id": "google-client-id",
            "client_secret": "google-client-secret",
        },
        follow_redirects=False,
    )
    assert start.status_code == HTTP_SEE_OTHER
    flow_url = start.headers["location"]
    assert flow_url.startswith("/connections/ytmusic/oauth/")

    flow_page = client.get(flow_url)
    assert flow_page.status_code == HTTP_OK
    assert "Continue with Google" in flow_page.text
    assert "ABCD-EFGH" in flow_page.text

    flow_id = flow_url.rsplit("/", maxsplit=1)[-1]
    status = client.get(f"/api/connections/ytmusic/oauth/{flow_id}/status")
    assert status.status_code == HTTP_OK
    assert status.json()["status"] == "connected"
    assert "/connections?message=" in status.json()["redirect_url"]

    accounts = app_state.db.find_account_by_service(Service.YTMUSIC.value)
    assert len(accounts) == 1
    assert accounts[0]["auth_status"] == "connected"
    assert accounts[0]["display_name"] == "OAuth YT Music"

    credentials = app_state.db.get_credentials(int(accounts[0]["id"]))
    assert credentials is not None
    assert credentials["credential_type"] == CredentialType.YTMUSIC_OAUTH.value
    assert credentials["payload"]["data"]["refresh_token"] == "oauth-refresh-token"
    assert credentials["payload"]["oauth_client"]["client_id"] == "google-client-id"


def test_web_app_requires_ytmusic_oauth_client_credentials(app_state: AppState) -> None:
    """Test that the YouTube Music OAuth flow rejects blank client credentials."""
    client = TestClient(create_app(app_state))

    response = client.post(
        "/api/connections/ytmusic/oauth/start",
        data={"client_id": " ", "client_secret": " "},
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert _redirect_query_value(response.headers["location"], "error") == (
        "Provide a Google OAuth client ID and secret for YouTube Music."
    )


def test_web_app_keeps_ytmusic_oauth_pending_and_slows_polling_interval(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that pending OAuth polls keep the flow alive and honor slow-down responses."""

    class FakeOAuthCredentials:
        token_responses: ClassVar[list[dict[str, str]]] = [
            {"error": "authorization_pending"},
            {"error": "slow_down"},
        ]

        def __init__(self, client_id: str, client_secret: str) -> None:
            assert client_id == "google-client-id"
            assert client_secret == "google-client-secret"

        def get_code(self) -> dict[str, str | int]:
            return {
                "device_code": "device-code",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://google.example/device",
                "interval": 1,
                "expires_in": 600,
            }

        def token_from_code(self, device_code: str) -> dict[str, str]:
            assert device_code == "device-code"
            return self.token_responses.pop(0)

    monkeypatch.setattr("spo.app.OAuthCredentials", FakeOAuthCredentials)

    client = TestClient(create_app(app_state))
    start = client.post(
        "/api/connections/ytmusic/oauth/start",
        data={
            "client_id": "google-client-id",
            "client_secret": "google-client-secret",
        },
        follow_redirects=False,
    )
    flow_id = start.headers["location"].rsplit("/", maxsplit=1)[-1]

    first_status = client.get(f"/api/connections/ytmusic/oauth/{flow_id}/status")
    second_status = client.get(f"/api/connections/ytmusic/oauth/{flow_id}/status")

    assert first_status.status_code == HTTP_OK
    assert first_status.json() == {
        "status": "pending",
        "interval_seconds": 1,
    }
    assert second_status.status_code == HTTP_OK
    assert second_status.json() == {
        "status": "pending",
        "interval_seconds": 6,
    }


def test_web_app_handles_spotify_connect_callback_and_event_stream(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that Spotify OAuth callbacks update accounts and expose job events."""
    app = create_app(app_state)
    client = TestClient(app)

    def fake_prepare_authorization(
        _settings: object,
        _payload: dict[str, object],
        state: str,
    ) -> tuple[str, dict[str, object]]:
        return (
            f"https://spotify.example/authorize?state={state}",
            {
                "client_id": "client-id",
                "redirect_uri": "http://127.0.0.1:8899/callback/spotify",
                "pkce_code_verifier": "verifier-123",
                "pkce_code_challenge": "challenge-123",
            },
        )

    def fake_exchange_code(
        *,
        settings: object,
        credential_payload: dict[str, object],
        code: str,
    ) -> dict[str, object]:
        assert code == "oauth-code"
        assert settings is app_state.settings
        return {
            "client_id": credential_payload["client_id"],
            "redirect_uri": credential_payload["redirect_uri"],
            "token_info": {
                "access_token": "token",
                "refresh_token": "refresh",
                "expires_at": 9999999999,
            },
        }

    def fake_authenticate(_self: SpotifyAdapter) -> AccountIdentity:
        return AccountIdentity(
            remote_account_id="spotify-connected",
            display_name="Connected Spotify",
        )

    monkeypatch.setattr(SpotifyAdapter, "prepare_authorization", staticmethod(fake_prepare_authorization))
    monkeypatch.setattr(SpotifyAdapter, "exchange_code", staticmethod(fake_exchange_code))
    monkeypatch.setattr(SpotifyAdapter, "authenticate", fake_authenticate)

    auth_redirect = client.post(
        "/api/connections/spotify",
        data={
            "client_id": "client-id",
            "redirect_uri": "http://127.0.0.1:8899/callback/spotify",
        },
        follow_redirects=False,
    )
    assert auth_redirect.status_code == HTTP_SEE_OTHER
    assert auth_redirect.headers["location"].startswith("https://spotify.example/")

    accounts = app_state.db.find_account_by_service(Service.SPOTIFY.value)
    assert len(accounts) == 1
    oauth_state = accounts[0]["oauth_state"]
    assert oauth_state is not None
    pending_credentials = app_state.db.get_credentials(int(accounts[0]["id"]))
    assert pending_credentials is not None
    assert pending_credentials["payload"]["client_id"] == "client-id"
    assert "pkce_code_verifier" in pending_credentials["payload"]

    callback_redirect = client.get(
        f"/callback/spotify?code=oauth-code&state={oauth_state}",
        follow_redirects=False,
    )
    assert callback_redirect.status_code == HTTP_SEE_OTHER
    assert "/connections?message=" in callback_redirect.headers["location"]

    updated = app_state.db.find_account_by_service(Service.SPOTIFY.value)[0]
    assert updated["auth_status"] == "connected"
    assert updated["display_name"] == "Connected Spotify"
    persisted_credentials = app_state.db.get_credentials(int(updated["id"]))
    assert persisted_credentials is not None
    assert "pkce_code_verifier" not in persisted_credentials["payload"]

    target_account_id = app_state.db.upsert_account(
        AccountUpsert(
            service=Service.YTMUSIC.value,
            auth_status="connected",
            remote_account_id="yt-stream",
            display_name="YT Stream",
        ),
    )
    job_id = app_state.db.create_job(int(updated["id"]), target_account_id, ["saved_track"])
    app_state.db.append_event(job_id, "info", "hello stream")

    assert client.get(f"/api/jobs/{job_id}").status_code == HTTP_OK
    assert client.get("/api/jobs/999999").status_code == HTTP_NOT_FOUND


def test_web_app_preserves_spotify_callback_validation_errors(app_state: AppState) -> None:
    """Test that Spotify callback validation errors are redirected without extra wrapping."""
    client = TestClient(create_app(app_state))

    response = client.get("/callback/spotify?code=oauth-code", follow_redirects=False)

    assert response.status_code == HTTP_SEE_OTHER
    assert _redirect_query_value(response.headers["location"], "error") == (
        "Spotify callback is missing code or state."
    )


def test_web_app_requires_spotify_client_id(app_state: AppState) -> None:
    """Test Spotify connection setup rejects blank client identifiers."""
    client = TestClient(create_app(app_state))

    response = client.post(
        "/api/connections/spotify",
        data={"client_id": " ", "redirect_uri": "http://127.0.0.1:8899/callback/spotify"},
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert _redirect_query_value(response.headers["location"], "error") == "Provide a Spotify client ID."


def test_app_startup_can_auto_resume_jobs(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that app startup triggers auto-resume when enabled."""
    app_state.settings.auto_resume = True
    called = {"count": 0}

    def fake_auto_resume() -> None:
        called["count"] += 1

    monkeypatch.setattr(app_state.runner, "auto_resume", fake_auto_resume)

    with TestClient(create_app(app_state)) as client:
        assert client.get("/").status_code == HTTP_OK

    assert called["count"] >= 1


@pytest.mark.anyio
async def test_event_stream_endpoint_yields_existing_events(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the event stream endpoint yields already stored events."""
    app = create_app(app_state)
    source_account_id = app_state.db.upsert_account(
        AccountUpsert(
            service=Service.SPOTIFY.value,
            auth_status="connected",
            remote_account_id="spotify-stream",
            display_name="Spotify Stream",
        ),
    )
    target_account_id = app_state.db.upsert_account(
        AccountUpsert(
            service=Service.YTMUSIC.value,
            auth_status="connected",
            remote_account_id="yt-stream",
            display_name="YT Stream",
        ),
    )
    job_id = app_state.db.create_job(source_account_id, target_account_id, ["saved_track"])
    app_state.db.append_event(job_id, "info", "hello stream")

    route = next(route for route in app.router.routes if getattr(route, "path", "") == "/api/jobs/{job_id}/events")
    assert isinstance(route, APIRoute)

    class FakeRequest:
        def __init__(self) -> None:
            self.calls = 0

        async def is_disconnected(self) -> bool:
            await checkpoint()
            self.calls += 1
            return self.calls > 1

    async def immediate_sleep(_seconds: float) -> None:
        await checkpoint()

    monkeypatch.setattr("spo.app.asyncio.sleep", immediate_sleep)

    response = await route.endpoint(FakeRequest(), job_id)
    chunks = [chunk async for chunk in response.body_iterator]

    assert any("hello stream" in chunk for chunk in chunks)
