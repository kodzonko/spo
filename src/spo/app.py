"""Application state, web factory, and route handlers for spo."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote_plus

import requests
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from jinja2 import DictLoader, Environment, select_autoescape
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from ytmusicapi.auth.oauth.credentials import OAuthCredentials
from ytmusicapi.auth.oauth.exceptions import BadOAuthClient, UnauthorizedOAuthClient
from ytmusicapi.exceptions import YTMusicServerError

from spo.config import Settings, load_settings
from spo.exceptions import AuthenticationError, RateLimitError, ValidationError
from spo.models import CollectionKind, CredentialType, Service
from spo.persistence import Database
from spo.services.spotify import SpotifyAdapter, sanitize_redirect_uri
from spo.sync import JobRunner, ServiceRegistry, SyncEngine
from spo.utils import utcnow
from spo.web.templates import TEMPLATES

if TYPE_CHECKING:
    from starlette.datastructures import UploadFile

template_env = Environment(
    loader=DictLoader(TEMPLATES),
    autoescape=select_autoescape(default_for_string=True),
)


@dataclass(slots=True)
class AppState:
    """Shared application dependencies used by the web layer."""

    settings: Settings
    db: Database
    registry: ServiceRegistry
    engine: SyncEngine
    runner: JobRunner
    pending_ytmusic_oauth: dict[str, PendingYouTubeMusicOAuth]


@dataclass(slots=True)
class PendingYouTubeMusicOAuth:
    """In-progress device-flow metadata for a YouTube Music connection."""

    account_id: int
    client_id: str
    client_secret: str
    device_code: str
    user_code: str
    verification_url: str
    interval_seconds: int
    expires_at: datetime

    def is_expired(self) -> bool:
        """Return whether the pending OAuth flow has expired."""
        return datetime.now(UTC) >= self.expires_at


def _configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(settings.log_level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


def create_state(settings: Settings | None = None) -> AppState:
    """Create the shared application state and initialize persistence."""
    resolved_settings = settings or load_settings()
    resolved_settings.app_data_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(resolved_settings)
    db = Database(resolved_settings.db_path)
    db.initialize()
    registry = ServiceRegistry(resolved_settings)
    engine = SyncEngine(db, resolved_settings, registry)
    runner = JobRunner(engine, db)
    return AppState(
        settings=resolved_settings,
        db=db,
        registry=registry,
        engine=engine,
        runner=runner,
        pending_ytmusic_oauth={},
    )


def render_template(name: str, *, title: str, request: Request, **context: Any) -> HTMLResponse:
    """Render a named page template inside the shared base layout."""
    body = template_env.get_template(name).render(**context)
    html = template_env.get_template("base.html").render(
        title=title,
        body=body,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )
    return HTMLResponse(html)


def _service_description(kind: CollectionKind) -> dict[str, str]:
    descriptions = {
        CollectionKind.PLAYLIST: "Playlist containers and ordered items.",
        CollectionKind.SAVED_TRACK: "Saved tracks or library songs.",
        CollectionKind.LIKED_TRACK: "Liked songs when the source exposes them separately.",
        CollectionKind.SAVED_ALBUM: "Saved albums.",
        CollectionKind.FOLLOWED_ARTIST: "Followed or subscribed artists.",
        CollectionKind.SAVED_PODCAST: "Saved podcasts or shows.",
        CollectionKind.SAVED_EPISODE: "Saved podcast episodes.",
    }
    return {
        "value": kind.value,
        "label": kind.value.replace("_", " ").title(),
        "description": descriptions[kind],
    }


def _latest_account_for_service(db: Database, service: Service) -> dict[str, Any] | None:
    accounts = db.find_account_by_service(service.value)
    return accounts[0] if accounts else None


def _form_int(value: UploadFile | str, field_name: str) -> int:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}.")
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}.") from exc


def _ytmusic_account_defaults(existing: dict[str, Any] | None) -> dict[str, str | None]:
    return {
        "remote_account_id": existing.get("remote_account_id") if existing else None,
        "display_name": existing.get("display_name") if existing else "YouTube Music account",
    }


def _start_ytmusic_oauth_flow(
    account_id: int,
    *,
    client_id: str,
    client_secret: str,
) -> PendingYouTubeMusicOAuth:
    try:
        code = OAuthCredentials(client_id, client_secret).get_code()
    except (BadOAuthClient, UnauthorizedOAuthClient) as exc:
        raise AuthenticationError(f"YouTube Music OAuth setup failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - network and library internals
        raise AuthenticationError(f"Could not start YouTube Music OAuth: {exc}") from exc

    device_code = str(code.get("device_code") or "")
    user_code = str(code.get("user_code") or "")
    verification_url = str(code.get("verification_url") or "")
    if not device_code or not user_code or not verification_url:
        raise AuthenticationError("YouTube Music OAuth did not return a usable device code.")

    interval_seconds = max(int(code.get("interval") or 5), 1)
    expires_in = max(int(code.get("expires_in") or 1800), 1)
    return PendingYouTubeMusicOAuth(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
        device_code=device_code,
        user_code=user_code,
        verification_url=verification_url,
        interval_seconds=interval_seconds,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


def _get_pending_ytmusic_oauth(
    app_state: AppState,
    flow_id: str,
) -> PendingYouTubeMusicOAuth | None:
    flow = app_state.pending_ytmusic_oauth.get(flow_id)
    if flow is None:
        return None
    if flow.is_expired():
        app_state.pending_ytmusic_oauth.pop(flow_id, None)
        return None
    return flow


def create_app(state: AppState | None = None) -> FastAPI:
    """Create the FastAPI application and register its routes."""
    app_state = state or create_state()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if app_state.settings.auto_resume:
            app_state.runner.auto_resume()
        yield

    app = FastAPI(title="spo", lifespan=lifespan)
    app.state.spo = app_state

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        jobs = app_state.db.list_jobs()
        accounts = app_state.db.list_accounts()
        return render_template(
            "dashboard.html",
            title="Dashboard",
            request=request,
            jobs=jobs,
            accounts=accounts,
        )

    @app.get("/connections", response_class=HTMLResponse)
    def connections(request: Request) -> HTMLResponse:
        return render_template(
            "connections.html",
            title="Connections",
            request=request,
            accounts=app_state.db.list_accounts(),
        )

    @app.post("/api/connections/spotify")
    async def save_spotify_connection(
        client_id: Annotated[str, Form()],
        client_secret: Annotated[str, Form()],
        redirect_uri: Annotated[str | None, Form()] = None,
    ) -> RedirectResponse:
        redirect_uri = sanitize_redirect_uri(redirect_uri, app_state.settings)
        oauth_state = secrets.token_urlsafe(24)
        existing = _latest_account_for_service(app_state.db, Service.SPOTIFY)
        account_id = app_state.db.upsert_account(
            account_id=int(existing["id"]) if existing else None,
            service=Service.SPOTIFY.value,
            remote_account_id=existing.get("remote_account_id") if existing else None,
            display_name=existing.get("display_name") if existing else "Spotify account",
            auth_status="pending",
            oauth_state=oauth_state,
        )
        payload = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "redirect_uri": redirect_uri,
        }
        app_state.db.save_credentials(
            account_id,
            CredentialType.SPOTIFY_OAUTH.value,
            payload,
        )
        auth_url = SpotifyAdapter.build_authorize_url(
            app_state.settings,
            payload,
            oauth_state,
        )
        return RedirectResponse(auth_url, status_code=303)

    @app.get("/callback/spotify")
    async def spotify_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        if error:
            error_message = f"Spotify authorization failed: {error}"
            return RedirectResponse(
                f"/connections?error={quote_plus(error_message)}",
                status_code=303,
            )
        if not code or not state:
            return RedirectResponse(
                "/connections?error=Spotify callback is missing code or state.",
                status_code=303,
            )
        account = app_state.db.find_account_by_oauth_state(Service.SPOTIFY.value, state)
        if not account:
            return RedirectResponse(
                "/connections?error=Spotify callback state is not recognized.",
                status_code=303,
            )
        credentials = app_state.db.get_credentials(int(account["id"]))
        if not credentials:
            return RedirectResponse(
                "/connections?error=Spotify credentials were not found for this callback.",
                status_code=303,
            )
        try:
            payload = SpotifyAdapter.exchange_code(
                settings=app_state.settings,
                credential_payload=credentials["payload"],
                code=code,
            )
            adapter = SpotifyAdapter(
                account_id=int(account["id"]),
                credential_payload=payload,
                settings=app_state.settings,
            )
            identity = adapter.authenticate()
        except (
            AuthenticationError,
            RateLimitError,
            SpotifyException,
            SpotifyOauthError,
            requests.RequestException,
        ) as exc:
            error_message = f"Spotify authorization failed: {exc}"
            return RedirectResponse(
                f"/connections?error={quote_plus(error_message)}",
                status_code=303,
            )
        app_state.db.save_credentials(
            int(account["id"]),
            CredentialType.SPOTIFY_OAUTH.value,
            adapter.persisted_payload,
            last_validated_at=utcnow(),
        )
        app_state.db.upsert_account(
            account_id=int(account["id"]),
            service=Service.SPOTIFY.value,
            remote_account_id=identity.remote_account_id,
            display_name=identity.display_name,
            auth_status="connected",
            oauth_state=None,
        )
        return RedirectResponse(
            f"/connections?message={quote_plus(f'Connected Spotify account {identity.display_name}.')}",
            status_code=303,
        )

    @app.post("/api/connections/ytmusic")
    async def save_ytmusic_connection(
        headers_json: Annotated[str | None, Form()] = None,
    ) -> RedirectResponse:
        try:
            payload: dict[str, Any]
            credential_type: str
            if headers_json and headers_json.strip():
                payload = {
                    "credential_type": CredentialType.YTMUSIC_HEADERS.value,
                    "data": json.loads(headers_json),
                }
                credential_type = CredentialType.YTMUSIC_HEADERS.value
            else:
                raise ValidationError("Paste browser headers JSON, or use Connect YouTube Music above.")
            existing = _latest_account_for_service(app_state.db, Service.YTMUSIC)
            account_defaults = _ytmusic_account_defaults(existing)
            account_id = app_state.db.upsert_account(
                account_id=int(existing["id"]) if existing else None,
                service=Service.YTMUSIC.value,
                remote_account_id=account_defaults["remote_account_id"],
                display_name=account_defaults["display_name"],
                auth_status="pending",
                oauth_state=None,
            )
            app_state.db.save_credentials(account_id, credential_type, payload)
            adapter = app_state.registry.create(
                service=Service.YTMUSIC,
                account_id=account_id,
                credential_payload=payload,
            )
            identity = adapter.authenticate()
            app_state.db.save_credentials(
                account_id,
                credential_type,
                adapter.persisted_payload,
                last_validated_at=utcnow(),
            )
            app_state.db.upsert_account(
                account_id=account_id,
                service=Service.YTMUSIC.value,
                remote_account_id=identity.remote_account_id,
                display_name=identity.display_name,
                auth_status="connected",
                oauth_state=None,
            )
            return RedirectResponse(
                f"/connections?message={quote_plus('YouTube Music credentials saved.')}",
                status_code=303,
            )
        except (json.JSONDecodeError, ValidationError, AuthenticationError) as exc:
            return RedirectResponse(
                f"/connections?error={quote_plus(str(exc))}",
                status_code=303,
            )

    @app.post("/api/connections/ytmusic/oauth/start")
    async def start_ytmusic_connection(
        client_id: Annotated[str, Form()],
        client_secret: Annotated[str, Form()],
    ) -> RedirectResponse:
        try:
            resolved_client_id = client_id.strip()
            resolved_client_secret = client_secret.strip()
            if not resolved_client_id or not resolved_client_secret:
                raise ValidationError("Provide a Google OAuth client ID and secret for YouTube Music.")

            existing = _latest_account_for_service(app_state.db, Service.YTMUSIC)
            account_defaults = _ytmusic_account_defaults(existing)
            account_id = app_state.db.upsert_account(
                account_id=int(existing["id"]) if existing else None,
                service=Service.YTMUSIC.value,
                remote_account_id=account_defaults["remote_account_id"],
                display_name=account_defaults["display_name"],
                auth_status="pending",
                oauth_state=None,
            )
            flow = _start_ytmusic_oauth_flow(
                account_id,
                client_id=resolved_client_id,
                client_secret=resolved_client_secret,
            )
            flow_id = secrets.token_urlsafe(24)
            app_state.pending_ytmusic_oauth[flow_id] = flow
            return RedirectResponse(f"/connections/ytmusic/oauth/{flow_id}", status_code=303)
        except (ValidationError, AuthenticationError) as exc:
            return RedirectResponse(
                f"/connections?error={quote_plus(str(exc))}",
                status_code=303,
            )

    @app.get("/connections/ytmusic/oauth/{flow_id}", response_class=HTMLResponse)
    def ytmusic_oauth_page(flow_id: str, request: Request) -> HTMLResponse | RedirectResponse:
        flow = _get_pending_ytmusic_oauth(app_state, flow_id)
        if flow is None:
            return RedirectResponse(
                "/connections?error=YouTube Music authorization expired. Start the connection again.",
                status_code=303,
            )

        return render_template(
            "ytmusic_oauth.html",
            title="Connect YouTube Music",
            request=request,
            flow_id=flow_id,
            user_code=flow.user_code,
            verification_url=flow.verification_url,
            interval_seconds=flow.interval_seconds,
        )

    @app.get("/api/connections/ytmusic/oauth/{flow_id}/status")
    async def ytmusic_oauth_status(flow_id: str) -> JSONResponse:
        flow = _get_pending_ytmusic_oauth(app_state, flow_id)
        if flow is None:
            message = "YouTube Music authorization expired. Start the connection again."
            return JSONResponse(
                {
                    "status": "expired",
                    "message": message,
                    "redirect_url": f"/connections?error={quote_plus(message)}",
                },
                status_code=410,
            )

        try:
            token_response = OAuthCredentials(flow.client_id, flow.client_secret).token_from_code(flow.device_code)
        except (BadOAuthClient, UnauthorizedOAuthClient) as exc:
            app_state.pending_ytmusic_oauth.pop(flow_id, None)
            message = f"YouTube Music OAuth setup failed: {exc}"
            return JSONResponse(
                {
                    "status": "error",
                    "message": message,
                    "redirect_url": f"/connections?error={quote_plus(message)}",
                },
                status_code=400,
            )
        except (YTMusicServerError, requests.RequestException, ValueError) as exc:
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Could not finish YouTube Music OAuth: {exc}",
                },
                status_code=502,
            )

        error_code = token_response.get("error")
        if error_code == "authorization_pending":
            return JSONResponse(
                {
                    "status": "pending",
                    "interval_seconds": flow.interval_seconds,
                },
            )
        if error_code == "slow_down":
            flow.interval_seconds += 5
            return JSONResponse(
                {
                    "status": "pending",
                    "interval_seconds": flow.interval_seconds,
                },
            )
        if error_code in {"access_denied", "expired_token"}:
            app_state.pending_ytmusic_oauth.pop(flow_id, None)
            message = "YouTube Music authorization was denied or expired. Start the connection again."
            return JSONResponse(
                {
                    "status": "error",
                    "message": message,
                    "redirect_url": f"/connections?error={quote_plus(message)}",
                },
                status_code=400,
            )
        if not token_response.get("access_token") or not token_response.get("refresh_token"):
            return JSONResponse(
                {
                    "status": "error",
                    "message": "YouTube Music OAuth did not return usable tokens.",
                },
                status_code=502,
            )

        expires_in = int(token_response.get("expires_in") or 0)
        persisted_token = {
            **token_response,
            "expires_at": int(time.time()) + expires_in,
        }
        payload = {
            "credential_type": CredentialType.YTMUSIC_OAUTH.value,
            "data": persisted_token,
            "oauth_client": {
                "client_id": flow.client_id,
                "client_secret": flow.client_secret,
            },
        }
        try:
            adapter = app_state.registry.create(
                service=Service.YTMUSIC,
                account_id=flow.account_id,
                credential_payload=payload,
            )
            identity = adapter.authenticate()
            app_state.db.save_credentials(
                flow.account_id,
                CredentialType.YTMUSIC_OAUTH.value,
                adapter.persisted_payload,
                last_validated_at=utcnow(),
            )
            app_state.db.upsert_account(
                account_id=flow.account_id,
                service=Service.YTMUSIC.value,
                remote_account_id=identity.remote_account_id,
                display_name=identity.display_name,
                auth_status="connected",
                oauth_state=None,
            )
        except AuthenticationError as exc:
            app_state.pending_ytmusic_oauth.pop(flow_id, None)
            return JSONResponse(
                {
                    "status": "error",
                    "message": str(exc),
                    "redirect_url": f"/connections?error={quote_plus(str(exc))}",
                },
                status_code=400,
            )

        app_state.pending_ytmusic_oauth.pop(flow_id, None)
        message = f"Connected YouTube Music account {identity.display_name}."
        return JSONResponse(
            {
                "status": "connected",
                "message": message,
                "redirect_url": f"/connections?message={quote_plus(message)}",
            },
        )

    @app.post("/api/connections/{service}/test")
    async def test_connection(service: str) -> JSONResponse:
        try:
            enum_service = Service(service)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Unknown service") from exc
        account = _latest_account_for_service(app_state.db, enum_service)
        if not account:
            raise HTTPException(status_code=404, detail="No account stored for this service.")
        credentials = app_state.db.get_credentials(int(account["id"]))
        if not credentials:
            raise HTTPException(status_code=400, detail="Credentials are missing.")
        adapter = app_state.registry.create(
            service=enum_service,
            account_id=int(account["id"]),
            credential_payload=credentials["payload"],
        )
        identity = adapter.authenticate()
        return JSONResponse(
            {
                "service": service,
                "display_name": identity.display_name,
                "remote_account_id": identity.remote_account_id,
            },
        )

    @app.get("/sync/new", response_class=HTMLResponse)
    def new_sync(request: Request) -> HTMLResponse:
        accounts = [row for row in app_state.db.list_accounts() if row["auth_status"] == "connected"]
        collections = [_service_description(kind) for kind in CollectionKind]
        return render_template(
            "sync_new.html",
            title="New Sync",
            request=request,
            accounts=accounts,
            collections=collections,
        )

    @app.post("/api/jobs")
    async def create_job(request: Request) -> RedirectResponse:
        form = await request.form()
        source_account_id = _form_int(form["source_account_id"], "source account")
        target_account_id = _form_int(form["target_account_id"], "target account")
        collection_kinds = [str(value) for value in form.getlist("collection_kinds")]
        if source_account_id == target_account_id:
            return RedirectResponse(
                "/sync/new?error=Source and target must be different accounts.",
                status_code=303,
            )
        if not collection_kinds:
            collection_kinds = [kind.value for kind in CollectionKind]
        job_id = app_state.db.create_job(source_account_id, target_account_id, collection_kinds)
        try:
            app_state.runner.start(job_id)
        except RuntimeError as exc:
            app_state.db.update_job(
                job_id,
                status="draft",
                phase="draft",
                last_error=str(exc),
            )
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(job_id: int, request: Request) -> HTMLResponse:
        job = app_state.db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        source = app_state.db.get_account(int(job["source_account_id"]))
        target = app_state.db.get_account(int(job["target_account_id"]))
        events = app_state.db.list_events(job_id)
        return render_template(
            "job_detail.html",
            title=f"Job #{job_id}",
            request=request,
            job=job,
            source=source,
            target=target,
            events=events,
        )

    @app.post("/api/jobs/{job_id}/resume")
    async def resume_job(job_id: int) -> RedirectResponse:
        if not app_state.db.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found.")
        try:
            app_state.runner.start(job_id)
            message = f"Resuming job #{job_id}."
            return RedirectResponse(
                f"/jobs/{job_id}?message={quote_plus(message)}",
                status_code=303,
            )
        except RuntimeError as exc:
            return RedirectResponse(
                f"/jobs/{job_id}?error={quote_plus(str(exc))}",
                status_code=303,
            )

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: int) -> RedirectResponse:
        if not app_state.db.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found.")
        app_state.runner.cancel(job_id)
        return RedirectResponse(
            f"/jobs/{job_id}?message={quote_plus(f'Cancel requested for job #{job_id}.')}",
            status_code=303,
        )

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request) -> HTMLResponse:
        return render_template(
            "history.html",
            title="History",
            request=request,
            jobs=app_state.db.list_jobs(),
        )

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int) -> JSONResponse:
        job = app_state.db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return JSONResponse(job)

    @app.get("/api/jobs/{job_id}/events")
    async def stream_events(request: Request, job_id: int) -> StreamingResponse:
        if not app_state.db.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found.")

        async def event_stream():
            last_id = 0
            while True:
                if await request.is_disconnected():
                    break
                events = app_state.db.list_events(job_id, after_id=last_id)
                if events:
                    for event in events:
                        last_id = max(last_id, int(event["id"]))
                        yield f"data: {json.dumps(event)}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app
