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
from typing import TYPE_CHECKING, Annotated, Any, NoReturn
from urllib.parse import quote_plus

import requests
from fastapi import FastAPI, Form, HTTPException, Request, Response
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
from spo.models import AccountIdentity, CollectionKind, CredentialType, Service
from spo.persistence import AccountUpsert, Database
from spo.services.spotify import SpotifyAdapter, sanitize_redirect_uri
from spo.sync import JobRunner, ServiceRegistry, SyncEngine
from spo.utils import utcnow
from spo.web.templates import TEMPLATES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.datastructures import UploadFile
    from ytmusicapi.auth.oauth.models import RefreshableTokenDict

template_env = Environment(
    loader=DictLoader(TEMPLATES),
    autoescape=select_autoescape(default_for_string=True),
)

HTTP_BAD_REQUEST = int(requests.codes["bad_request"])
HTTP_NOT_FOUND = int(requests.codes["not_found"])
HTTP_GONE = int(requests.codes["gone"])
HTTP_BAD_GATEWAY = int(requests.codes["bad_gateway"])
HTTP_SEE_OTHER = int(requests.codes["see_other"])
HTTP_OK = int(requests.codes["ok"])

JOB_NOT_FOUND_MESSAGE = "Job not found."
SPOTIFY_ACCOUNT_LABEL = "Spotify account"
YTMUSIC_ACCOUNT_LABEL = "YouTube Music account"
YTMUSIC_HEADERS_REQUIRED_MESSAGE = "Paste browser headers JSON, or use Connect YouTube Music above."
YTMUSIC_OAUTH_CREDENTIALS_REQUIRED_MESSAGE = "Provide a Google OAuth client ID and secret for YouTube Music."
YTMUSIC_OAUTH_EXPIRED_MESSAGE = "YouTube Music authorization expired. Start the connection again."
YTMUSIC_CREDENTIALS_SAVED_MESSAGE = "YouTube Music credentials saved."


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


def render_template(name: str, *, title: str, request: Request, **context: object) -> HTMLResponse:
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
        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail=f"Invalid {field_name}.")
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail=f"Invalid {field_name}.") from exc


def _raise_validation_error(message: str) -> NoReturn:
    raise ValidationError(message)


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=HTTP_SEE_OTHER)


def _connections_redirect(message: str, *, error: bool) -> RedirectResponse:
    return _redirect(_connections_redirect_url(message, error=error))


def _job_redirect_url(job_id: int, *, message: str | None = None, error: str | None = None) -> str:
    if message is not None:
        return f"/jobs/{job_id}?message={quote_plus(message)}"
    if error is not None:
        return f"/jobs/{job_id}?error={quote_plus(error)}"
    return f"/jobs/{job_id}"


def _job_redirect(job_id: int, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    return _redirect(_job_redirect_url(job_id, message=message, error=error))


def _pending_account_upsert(
    service: Service,
    existing: dict[str, Any] | None,
    *,
    default_display_name: str,
    oauth_state: str | None,
) -> AccountUpsert:
    return AccountUpsert(
        account_id=int(existing["id"]) if existing else None,
        service=service.value,
        remote_account_id=existing.get("remote_account_id") if existing else None,
        display_name=existing.get("display_name") if existing else default_display_name,
        auth_status="pending",
        oauth_state=oauth_state,
    )


def _connected_account_upsert(account_id: int, service: Service, identity: AccountIdentity) -> AccountUpsert:
    return AccountUpsert(
        account_id=account_id,
        service=service.value,
        remote_account_id=identity.remote_account_id,
        display_name=identity.display_name,
        auth_status="connected",
        oauth_state=None,
    )


def _save_validated_credentials(
    app_state: AppState,
    account_id: int,
    credential_type: CredentialType,
    payload: dict[str, Any],
) -> None:
    app_state.db.save_credentials(
        account_id,
        credential_type.value,
        payload,
        last_validated_at=utcnow(),
    )


def _build_ytmusic_headers_payload(headers_json: str | None) -> tuple[CredentialType, dict[str, Any]]:
    if not headers_json or not headers_json.strip():
        _raise_validation_error(YTMUSIC_HEADERS_REQUIRED_MESSAGE)
    return (
        CredentialType.YTMUSIC_HEADERS,
        {
            "credential_type": CredentialType.YTMUSIC_HEADERS.value,
            "data": json.loads(headers_json),
        },
    )


def _resolve_ytmusic_oauth_client_credentials(client_id: str, client_secret: str) -> tuple[str, str]:
    resolved_client_id = client_id.strip()
    resolved_client_secret = client_secret.strip()
    if not resolved_client_id or not resolved_client_secret:
        _raise_validation_error(YTMUSIC_OAUTH_CREDENTIALS_REQUIRED_MESSAGE)
    return resolved_client_id, resolved_client_secret


def _start_spotify_oauth(
    app_state: AppState,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    oauth_state = secrets.token_urlsafe(24)
    existing = _latest_account_for_service(app_state.db, Service.SPOTIFY)
    account_id = app_state.db.upsert_account(
        _pending_account_upsert(
            Service.SPOTIFY,
            existing,
            default_display_name=SPOTIFY_ACCOUNT_LABEL,
            oauth_state=oauth_state,
        ),
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
    return SpotifyAdapter.build_authorize_url(
        app_state.settings,
        payload,
        oauth_state,
    )


def _resolve_spotify_callback_context(
    app_state: AppState,
    *,
    code: str | None,
    state: str | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not code or not state:
        _raise_validation_error("Spotify callback is missing code or state.")
    account = app_state.db.find_account_by_oauth_state(Service.SPOTIFY.value, state)
    if not account:
        _raise_validation_error("Spotify callback state is not recognized.")
    credentials = app_state.db.get_credentials(int(account["id"]))
    if not credentials:
        _raise_validation_error("Spotify credentials were not found for this callback.")
    return code, account, credentials


def _complete_spotify_callback(
    app_state: AppState,
    *,
    account: dict[str, Any],
    credential_payload: dict[str, Any],
    code: str,
) -> AccountIdentity:
    payload = SpotifyAdapter.exchange_code(
        settings=app_state.settings,
        credential_payload=credential_payload,
        code=code,
    )
    adapter = SpotifyAdapter(
        account_id=int(account["id"]),
        credential_payload=payload,
        settings=app_state.settings,
    )
    identity = adapter.authenticate()
    _save_validated_credentials(
        app_state,
        int(account["id"]),
        CredentialType.SPOTIFY_OAUTH,
        adapter.persisted_payload,
    )
    app_state.db.upsert_account(
        _connected_account_upsert(int(account["id"]), Service.SPOTIFY, identity),
    )
    return identity


def _save_ytmusic_connection(
    app_state: AppState,
    *,
    credential_type: CredentialType,
    payload: dict[str, Any],
) -> None:
    existing = _latest_account_for_service(app_state.db, Service.YTMUSIC)
    account_id = app_state.db.upsert_account(
        _pending_account_upsert(
            Service.YTMUSIC,
            existing,
            default_display_name=YTMUSIC_ACCOUNT_LABEL,
            oauth_state=None,
        ),
    )
    app_state.db.save_credentials(account_id, credential_type.value, payload)
    adapter = app_state.registry.create(
        service=Service.YTMUSIC,
        account_id=account_id,
        credential_payload=payload,
    )
    identity = adapter.authenticate()
    _save_validated_credentials(
        app_state,
        account_id,
        credential_type,
        adapter.persisted_payload,
    )
    app_state.db.upsert_account(
        _connected_account_upsert(account_id, Service.YTMUSIC, identity),
    )


def _start_pending_ytmusic_oauth(
    app_state: AppState,
    *,
    client_id: str,
    client_secret: str,
) -> str:
    resolved_client_id, resolved_client_secret = _resolve_ytmusic_oauth_client_credentials(client_id, client_secret)
    existing = _latest_account_for_service(app_state.db, Service.YTMUSIC)
    account_id = app_state.db.upsert_account(
        _pending_account_upsert(
            Service.YTMUSIC,
            existing,
            default_display_name=YTMUSIC_ACCOUNT_LABEL,
            oauth_state=None,
        ),
    )
    flow = _start_ytmusic_oauth_flow(
        account_id,
        client_id=resolved_client_id,
        client_secret=resolved_client_secret,
    )
    flow_id = secrets.token_urlsafe(24)
    app_state.pending_ytmusic_oauth[flow_id] = flow
    return flow_id


def _require_job(app_state: AppState, job_id: int) -> dict[str, Any]:
    job = app_state.db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=HTTP_NOT_FOUND, detail=JOB_NOT_FOUND_MESSAGE)
    return job


def _start_ytmusic_oauth_flow(
    account_id: int,
    *,
    client_id: str,
    client_secret: str,
) -> PendingYouTubeMusicOAuth:
    try:
        code = OAuthCredentials(client_id, client_secret).get_code()
    except (BadOAuthClient, UnauthorizedOAuthClient) as exc:
        message = f"YouTube Music OAuth setup failed: {exc}"
        raise AuthenticationError(message) from exc
    except Exception as exc:  # pragma: no cover - network and library internals
        message = f"Could not start YouTube Music OAuth: {exc}"
        raise AuthenticationError(message) from exc

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


def _connections_redirect_url(message: str, *, error: bool) -> str:
    query_key = "error" if error else "message"
    return f"/connections?{query_key}={quote_plus(message)}"


def _oauth_status_response(
    status: str,
    *,
    status_code: int = HTTP_OK,
    message: str | None = None,
    redirect_url: str | None = None,
    interval_seconds: int | None = None,
) -> JSONResponse:
    payload: dict[str, object] = {"status": status}
    if message is not None:
        payload["message"] = message
    if redirect_url is not None:
        payload["redirect_url"] = redirect_url
    if interval_seconds is not None:
        payload["interval_seconds"] = interval_seconds
    return JSONResponse(payload, status_code=status_code)


def _poll_ytmusic_oauth_token(
    app_state: AppState,
    flow_id: str,
    flow: PendingYouTubeMusicOAuth,
) -> RefreshableTokenDict | JSONResponse:
    try:
        return OAuthCredentials(flow.client_id, flow.client_secret).token_from_code(flow.device_code)
    except (BadOAuthClient, UnauthorizedOAuthClient) as exc:
        app_state.pending_ytmusic_oauth.pop(flow_id, None)
        message = f"YouTube Music OAuth setup failed: {exc}"
        return _oauth_status_response(
            "error",
            status_code=HTTP_BAD_REQUEST,
            message=message,
            redirect_url=_connections_redirect_url(message, error=True),
        )
    except (YTMusicServerError, requests.RequestException, ValueError) as exc:
        return _oauth_status_response(
            "error",
            status_code=HTTP_BAD_GATEWAY,
            message=f"Could not finish YouTube Music OAuth: {exc}",
        )


def _complete_ytmusic_oauth(
    app_state: AppState,
    flow_id: str,
    flow: PendingYouTubeMusicOAuth,
    token_response: RefreshableTokenDict,
) -> JSONResponse:
    error_code = token_response.get("error")
    if error_code == "authorization_pending":
        return _oauth_status_response("pending", interval_seconds=flow.interval_seconds)
    if error_code == "slow_down":
        flow.interval_seconds += 5
        return _oauth_status_response("pending", interval_seconds=flow.interval_seconds)
    if error_code in {"access_denied", "expired_token"}:
        app_state.pending_ytmusic_oauth.pop(flow_id, None)
        message = "YouTube Music authorization was denied or expired. Start the connection again."
        return _oauth_status_response(
            "error",
            status_code=HTTP_BAD_REQUEST,
            message=message,
            redirect_url=_connections_redirect_url(message, error=True),
        )
    if not token_response.get("access_token") or not token_response.get("refresh_token"):
        return _oauth_status_response(
            "error",
            status_code=HTTP_BAD_GATEWAY,
            message="YouTube Music OAuth did not return usable tokens.",
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
        _save_validated_credentials(
            app_state,
            flow.account_id,
            CredentialType.YTMUSIC_OAUTH,
            adapter.persisted_payload,
        )
        app_state.db.upsert_account(
            _connected_account_upsert(flow.account_id, Service.YTMUSIC, identity),
        )
    except AuthenticationError as exc:
        app_state.pending_ytmusic_oauth.pop(flow_id, None)
        message = str(exc)
        return _oauth_status_response(
            "error",
            status_code=HTTP_BAD_REQUEST,
            message=message,
            redirect_url=_connections_redirect_url(message, error=True),
        )

    app_state.pending_ytmusic_oauth.pop(flow_id, None)
    message = f"Connected YouTube Music account {identity.display_name}."
    return _oauth_status_response(
        "connected",
        message=message,
        redirect_url=_connections_redirect_url(message, error=False),
    )


def _register_page_routes(app: FastAPI, app_state: AppState) -> None:
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

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request) -> HTMLResponse:
        return render_template(
            "history.html",
            title="History",
            request=request,
            jobs=app_state.db.list_jobs(),
        )


def _register_connection_routes(app: FastAPI, app_state: AppState) -> None:
    _register_spotify_connection_routes(app, app_state)
    _register_ytmusic_connection_routes(app, app_state)
    _register_connection_test_route(app, app_state)


def _register_spotify_connection_routes(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/connections/spotify")
    async def save_spotify_connection(
        client_id: Annotated[str, Form()],
        client_secret: Annotated[str, Form()],
        redirect_uri: Annotated[str | None, Form()] = None,
    ) -> RedirectResponse:
        redirect_uri = sanitize_redirect_uri(redirect_uri, app_state.settings)
        auth_url = _start_spotify_oauth(
            app_state,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        return _redirect(auth_url)

    @app.get("/callback/spotify")
    async def spotify_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        if error:
            return _connections_redirect(f"Spotify authorization failed: {error}", error=True)
        try:
            resolved_code, account, credentials = _resolve_spotify_callback_context(
                app_state,
                code=code,
                state=state,
            )
            identity = _complete_spotify_callback(
                app_state,
                account=account,
                credential_payload=credentials["payload"],
                code=resolved_code,
            )
        except ValidationError as exc:
            return _connections_redirect(str(exc), error=True)
        except (
            AuthenticationError,
            RateLimitError,
            SpotifyException,
            SpotifyOauthError,
            requests.RequestException,
        ) as exc:
            return _connections_redirect(f"Spotify authorization failed: {exc}", error=True)
        return _connections_redirect(
            f"Connected Spotify account {identity.display_name}.",
            error=False,
        )


def _register_ytmusic_connection_routes(app: FastAPI, app_state: AppState) -> None:
    _register_ytmusic_manual_connection_route(app, app_state)
    _register_ytmusic_oauth_routes(app, app_state)


def _register_ytmusic_manual_connection_route(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/connections/ytmusic")
    async def save_ytmusic_connection(
        headers_json: Annotated[str | None, Form()] = None,
    ) -> RedirectResponse:
        try:
            credential_type, payload = _build_ytmusic_headers_payload(headers_json)
            _save_ytmusic_connection(
                app_state,
                credential_type=credential_type,
                payload=payload,
            )
            return _connections_redirect(YTMUSIC_CREDENTIALS_SAVED_MESSAGE, error=False)
        except (json.JSONDecodeError, ValidationError, AuthenticationError) as exc:
            return _connections_redirect(str(exc), error=True)


def _register_ytmusic_oauth_routes(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/connections/ytmusic/oauth/start")
    async def start_ytmusic_connection(
        client_id: Annotated[str, Form()],
        client_secret: Annotated[str, Form()],
    ) -> RedirectResponse:
        try:
            flow_id = _start_pending_ytmusic_oauth(
                app_state,
                client_id=client_id,
                client_secret=client_secret,
            )
            return _redirect(f"/connections/ytmusic/oauth/{flow_id}")
        except (ValidationError, AuthenticationError) as exc:
            return _connections_redirect(str(exc), error=True)

    @app.get("/connections/ytmusic/oauth/{flow_id}", response_class=HTMLResponse)
    def ytmusic_oauth_page(flow_id: str, request: Request) -> Response:
        flow = _get_pending_ytmusic_oauth(app_state, flow_id)
        if flow is None:
            return _connections_redirect(YTMUSIC_OAUTH_EXPIRED_MESSAGE, error=True)

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
            message = YTMUSIC_OAUTH_EXPIRED_MESSAGE
            return _oauth_status_response(
                "expired",
                status_code=HTTP_GONE,
                message=message,
                redirect_url=_connections_redirect_url(message, error=True),
            )

        token_response = _poll_ytmusic_oauth_token(app_state, flow_id, flow)
        if isinstance(token_response, JSONResponse):
            return token_response
        return _complete_ytmusic_oauth(app_state, flow_id, flow, token_response)


def _register_connection_test_route(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/connections/{service}/test")
    async def test_connection(service: str) -> JSONResponse:
        try:
            enum_service = Service(service)
        except ValueError as exc:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Unknown service") from exc
        account = _latest_account_for_service(app_state.db, enum_service)
        if not account:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="No account stored for this service.")
        credentials = app_state.db.get_credentials(int(account["id"]))
        if not credentials:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="Credentials are missing.")
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


def _register_job_routes(app: FastAPI, app_state: AppState) -> None:
    _register_job_management_routes(app, app_state)
    _register_job_api_routes(app, app_state)


def _register_job_management_routes(app: FastAPI, app_state: AppState) -> None:
    _register_job_creation_route(app, app_state)
    _register_job_detail_route(app, app_state)
    _register_job_control_routes(app, app_state)


def _register_job_creation_route(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/jobs")
    async def create_job(request: Request) -> RedirectResponse:
        form = await request.form()
        source_account_id = _form_int(form["source_account_id"], "source account")
        target_account_id = _form_int(form["target_account_id"], "target account")
        collection_kinds = [str(value) for value in form.getlist("collection_kinds")]
        if source_account_id == target_account_id:
            return _redirect("/sync/new?error=Source and target must be different accounts.")
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
        return _job_redirect(job_id)


def _register_job_detail_route(app: FastAPI, app_state: AppState) -> None:
    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(job_id: int, request: Request) -> HTMLResponse:
        job = _require_job(app_state, job_id)
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


def _register_job_control_routes(app: FastAPI, app_state: AppState) -> None:
    @app.post("/api/jobs/{job_id}/resume")
    async def resume_job(job_id: int) -> RedirectResponse:
        _require_job(app_state, job_id)
        try:
            app_state.runner.start(job_id)
            return _job_redirect(job_id, message=f"Resuming job #{job_id}.")
        except RuntimeError as exc:
            return _job_redirect(job_id, error=str(exc))

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: int) -> RedirectResponse:
        _require_job(app_state, job_id)
        app_state.runner.cancel(job_id)
        return _job_redirect(job_id, message=f"Cancel requested for job #{job_id}.")


def _register_job_api_routes(app: FastAPI, app_state: AppState) -> None:
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int) -> JSONResponse:
        return JSONResponse(_require_job(app_state, job_id))

    @app.get("/api/jobs/{job_id}/events")
    async def stream_events(request: Request, job_id: int) -> StreamingResponse:
        _require_job(app_state, job_id)

        async def event_stream() -> AsyncIterator[str]:
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


def create_app(state: AppState | None = None) -> FastAPI:
    """Create the FastAPI application and register its routes."""
    app_state = state or create_state()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if app_state.settings.auto_resume:
            app_state.runner.auto_resume()
        yield

    app = FastAPI(title="spo", lifespan=lifespan)
    app.state.spo = app_state
    _register_page_routes(app, app_state)
    _register_connection_routes(app, app_state)
    _register_job_routes(app, app_state)
    return app
