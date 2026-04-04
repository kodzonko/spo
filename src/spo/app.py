from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from jinja2 import DictLoader, Environment, select_autoescape

from spo.config import Settings, load_settings
from spo.exceptions import AuthenticationError, ValidationError
from spo.models import CollectionKind, CredentialType, Service
from spo.persistence import Database
from spo.services.spotify import SpotifyAdapter, sanitize_redirect_uri
from spo.sync import JobRunner, ServiceRegistry, SyncEngine
from spo.utils import utcnow
from spo.web.templates import TEMPLATES

template_env = Environment(
    loader=DictLoader(TEMPLATES),
    autoescape=select_autoescape(default_for_string=True),
)


@dataclass(slots=True)
class AppState:
    settings: Settings
    db: Database
    registry: ServiceRegistry
    engine: SyncEngine
    runner: JobRunner


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
    )


def render_template(
    name: str, *, title: str, request: Request, **context: Any
) -> HTMLResponse:
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


def _latest_account_for_service(
    db: Database, service: Service
) -> dict[str, Any] | None:
    accounts = db.find_account_by_service(service.value)
    return accounts[0] if accounts else None


def create_app(state: AppState | None = None) -> FastAPI:
    app_state = state or create_state()
    app = FastAPI(title="spo")
    app.state.spo = app_state

    @app.on_event("startup")
    def startup() -> None:
        if app_state.settings.auto_resume:
            app_state.runner.auto_resume()

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
        client_id: str = Form(...),
        client_secret: str = Form(...),
        redirect_uri: str | None = Form(default=None),
    ) -> RedirectResponse:
        redirect_uri = sanitize_redirect_uri(redirect_uri, app_state.settings)
        oauth_state = secrets.token_urlsafe(24)
        existing = _latest_account_for_service(app_state.db, Service.SPOTIFY)
        account_id = app_state.db.upsert_account(
            account_id=int(existing["id"]) if existing else None,
            service=Service.SPOTIFY.value,
            remote_account_id=existing.get("remote_account_id") if existing else None,
            display_name=existing.get("display_name")
            if existing
            else "Spotify account",
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
            return RedirectResponse(
                f"/connections?error={quote_plus(f'Spotify authorization failed: {error}')}",
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
        except Exception as exc:
            return RedirectResponse(
                f"/connections?error={quote_plus(f'Spotify authorization failed: {exc}')}",
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
        headers_json: str | None = Form(default=None),
        oauth_json: str | None = Form(default=None),
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
            elif oauth_json and oauth_json.strip():
                payload = {
                    "credential_type": CredentialType.YTMUSIC_OAUTH.value,
                    "data": json.loads(oauth_json),
                }
                credential_type = CredentialType.YTMUSIC_OAUTH.value
            else:
                raise ValidationError(
                    "Paste headers JSON or OAuth JSON for YouTube Music."
                )
            existing = _latest_account_for_service(app_state.db, Service.YTMUSIC)
            account_id = app_state.db.upsert_account(
                account_id=int(existing["id"]) if existing else None,
                service=Service.YTMUSIC.value,
                remote_account_id=existing.get("remote_account_id")
                if existing
                else None,
                display_name=existing.get("display_name")
                if existing
                else "YouTube Music account",
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

    @app.post("/api/connections/{service}/test")
    async def test_connection(service: str) -> JSONResponse:
        try:
            enum_service = Service(service)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Unknown service") from exc
        account = _latest_account_for_service(app_state.db, enum_service)
        if not account:
            raise HTTPException(
                status_code=404, detail="No account stored for this service."
            )
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
            }
        )

    @app.get("/sync/new", response_class=HTMLResponse)
    def new_sync(request: Request) -> HTMLResponse:
        accounts = [
            row
            for row in app_state.db.list_accounts()
            if row["auth_status"] == "connected"
        ]
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
        source_account_id = int(form["source_account_id"])
        target_account_id = int(form["target_account_id"])
        collection_kinds = [str(value) for value in form.getlist("collection_kinds")]
        if source_account_id == target_account_id:
            return RedirectResponse(
                "/sync/new?error=Source and target must be different accounts.",
                status_code=303,
            )
        if not collection_kinds:
            collection_kinds = [kind.value for kind in CollectionKind]
        job_id = app_state.db.create_job(
            source_account_id, target_account_id, collection_kinds
        )
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
