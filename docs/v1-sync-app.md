# Sync Migration App v1 Spec

## Summary

- Build a local single-user web app at `127.0.0.1` with FastAPI, Jinja2, HTMX, HTMX SSE, and SQLite-backed state plus connection credentials.
- v1 implements bidirectional Spotify `<->` YouTube Music migration. Apple Music is deferred, but the architecture must stay service-generic and keep `apple_music` in the service model.
- Sync is one-off and resumable across restarts and day boundaries. Progress must persist after every source page fetch and every target mutation.
- Sync is non-destructive: never remove, unlike, unfollow, unsubscribe, or delete on the target. Preserve target-only content.
- v1 uses aggressive automatic merge and best-effort matching. There is no manual review queue.

## Architecture

- Server: FastAPI with REST endpoints and HTMX fragment responses.
- Live progress: Server-Sent Events for job updates. Do not use WebSockets.
- Runner: in-process background worker thread. Allow only one active job per target account and one active job per app process.
- Storage: use a fixed repo-local app-data directory at `./.spo-data/`, with `state.db`, `app.log`, and optionally `settings.toml` for non-secret bootstrap settings only.
- Credentials and tokens: store the Spotify client ID, pending PKCE verifier, Spotify OAuth tokens, and YouTube auth material in SQLite because they are mutable app-managed state. Do not use OS keyring and do not store credentials in `config.ini`.
- Security model: v1 accepts plaintext-at-rest secrets inside the repo-local app-data directory. Apply best-effort restrictive file permissions when creating the app-data directory and database, but do not implement platform-specific keychain or ACL logic.
- Modules: `web`, `sync`, `services`, `persistence`, `matching`.
- Service abstraction: `StreamingServiceAdapter` with concrete `SpotifyAdapter`, `YouTubeMusicAdapter`, and future `AppleMusicAdapter`.

## Public Interfaces and Types

- CLI entrypoint: `spo` starts the local app and auto-resumes resumable jobs. Keep `spo web` as a compatibility alias while the app has only one user-facing mode.
- UI pages: `/`, `/connections`, `/sync/new`, `/jobs/<job_id>`, `/history`.
- REST endpoints: `POST /api/connections/<service>`, `POST /api/connections/<service>/test`, `POST /api/jobs`, `POST /api/jobs/<job_id>/resume`, `POST /api/jobs/<job_id>/cancel`, `GET /api/jobs/<job_id>`, `GET /api/jobs/<job_id>/events`.
- Enums: `Service = spotify | ytmusic | apple_music`, `CollectionKind = playlist | saved_track | liked_track | saved_album | followed_artist | saved_podcast | saved_episode`, `JobStatus = draft | snapshotting | planning | applying | paused_rate_limit | paused_auth | completed | completed_with_warnings | failed | canceled`.
- Adapter contract methods: `authenticate()`, `get_account_identity()`, `list_collection(kind, cursor)`, `get_playlist_items(id, cursor)`, `search(kind, query, limit)`, `create_playlist()`, `add_playlist_items()`, `save_tracks()`, `like_tracks()`, `save_albums()`, `follow_artists()`, `save_podcasts()`, `save_episodes()`, `get_existing_state(kind, ids_or_queries)`.
- Canonical entity type: `CanonicalWork` with `kind`, `source_service`, `source_id`, `title`, `primary_creators`, `secondary_creators`, `container_title`, `duration_ms`, `year`, `explicit`, `external_ids`, `fingerprint`.

## Auth and Service Rules

- Spotify uses per-user developer app credentials only. The UI collects `client_id` and an optional redirect URI, then runs local Authorization Code with PKCE.
- Default Spotify redirect: `http://127.0.0.1:8899/callback/spotify`.
- YouTube Music auth uses browser-header import as the primary flow. Optional import of a pre-generated OAuth JSON is allowed, but v1 does not build Google OAuth client registration into the UI.
- If a settings file exists, it may contain only non-secret bootstrap options such as bind host, bind port, log level, and `auto_resume`. Service credentials must stay in SQLite.
- Apple Music shows as “planned” and disabled in the UI. Keep DB and interface compatibility, but no active Apple jobs in v1.

## Sync Semantics

- A sync job is directional: one source account, one target account, one immutable source snapshot, one resumable execution record.
- Default v1 scope includes all supported Spotify and YT collections: playlists, saved tracks, liked tracks where available, saved albums, followed or subscribed artists, saved podcasts, and saved episodes.
- Exclude music uploads, channels, audiobooks, and history/recommendation data.
- Spotify saved tracks map to canonical `saved_track`. YT `get_library_songs()` maps to `saved_track`. YT `get_liked_songs()` maps to `liked_track`.
- Spotify has no separate liked-track library surface in v1, so YT liked tracks syncing into Spotify are unioned into Spotify saved tracks.
- Spotify saved shows map to `saved_podcast`. Spotify saved episodes map to `saved_episode`. YT library podcasts and saved episodes map to the same canonical kinds.
- New target playlists preserve source order exactly.
- Existing merged playlists append only missing matched items in source order and never delete or reorder existing target-only items.
- Playlist duplicate handling is source-count aware: if source has `N` occurrences of a canonical item and target already has `M`, add `max(N-M, 0)` if the target service permits duplicates.
- Never remove anything from target collections.

## Matching and Merge Strategy

- Normalize strings with lowercase, Unicode fold, punctuation stripping, whitespace collapse, `feat./ft./featuring` removal, and `&`/`and` equivalence.
- Album mismatch is a soft penalty, not a blocker.
- Featured-artist mismatch is acceptable when title and primary creator align.
- Matching order: external IDs first when available, then weighted fuzzy score over title, primary creator or show, duration, container title, year, and explicitness.
- Auto-accept a candidate if score `>= 0.80`, or if score `>= 0.65` and the gap to the next candidate is `>= 0.10`. Otherwise mark unresolved.
- Playlist merge is aggressive: exact normalized title match merges automatically; otherwise merge into the highest-scoring fuzzy title candidate `>= 0.85`; otherwise create a new playlist.
- Search fallback for tracks and episodes: full query, then title + primary creator, then title-only.
- Spotify search must request at most 10 results per query.
- If an episode cannot be matched but its podcast or show can, save or subscribe the show and log the episode as unresolved.

## Persistence Model

- `accounts`: service, remote_account_id, display_name, auth_status, created_at, updated_at.
- `service_credentials`: account_id, credential_type, payload_json, schema_version, created_at, updated_at, last_validated_at.
- `jobs`: source_account_id, target_account_id, scope_json, status, phase, started_at, finished_at, last_error, progress counters, resume_token.
- `source_entities`: job_id, collection_kind, source_id, parent_source_id, canonical_payload, order_index, page_cursor, fingerprint, snapshot_hash.
- `entity_mappings`: source_service, target_service, source_fingerprint, target_id, target_kind, confidence, match_method, last_verified_at.
- `tasks`: job_id, action, collection_kind, source_entity_id, target_entity_id, payload_json, state, attempt_count, cooldown_until, last_error.
- `events`: job_id, level, message, detail_json, created_at.
- `service_cooldowns`: account_id, operation, cooldown_until, reason, vendor_hint.
- `service_credentials.payload_json` stores service-specific auth material such as the Spotify client ID, pending PKCE verifier, OAuth tokens, or imported YouTube headers and OAuth blobs. Keep this separated from `accounts` so reconnect, rotation, and schema migration do not rewrite account identity rows.
- Resume logic must read unfinished `tasks` and pending snapshot cursors instead of recomputing finished work.

## UI Behavior

- `Connections` shows service cards, auth health, remote account identity, and reconnect actions.
- `New Sync` lets the user choose source, target, and included collection kinds.
- `Job Detail` shows phase, per-collection counts, current operation, unresolved items, last vendor error, cooldown countdown, and final summary.
- Live updates use SSE plus HTMX fragment refresh where aggregate counters need rerendering.
- On startup, incomplete jobs appear first and auto-resume if credentials are valid and cooldowns have expired.

## Test Plan

- Unit tests for normalization and scoring, including album mismatch acceptance and featured-artist acceptance.
- Unit tests for playlist duplicate counting, aggressive merge selection, and non-deletion guarantees.
- Adapter contract tests with mocked Spotify and YT responses for pagination, auth errors, `429` handling, and batch-size limits.
- SQLite integration test proving an interrupted job resumes without repeating already committed mutations.
- Integration test proving partial manual migration on the target is adopted instead of recreated.
- Integration test proving a rate-limited job enters `paused_rate_limit`, persists cooldown, and resumes without resetting progress.
- Acceptance tests for Spotify `->` YT and YT `->` Spotify across playlists, tracks, albums, artists, podcasts, and episodes.
- Acceptance test proving unresolved items are reported and skipped without failing the whole job unless auth or schema errors block progress.

## Assumptions and External Constraints

- Spotify constraints to honor: development-mode apps are allowlisted and unsuitable as a shared multi-user app, rate limits are enforced in a rolling 30-second window, `429` includes `Retry-After`, playlist add is max 100 items/request, and search currently maxes at 10 results.
- YouTube Music in v1 relies on `ytmusicapi`, not an official public library API. Browser-header auth is supported, headers remain valid while the browser session remains valid, and the required library and playlist operations exist in current docs.
- Apple Music is deferred because MusicKit web auth requires a developer token plus in-browser user authorization. Keep the abstraction ready, but do not implement Apple flows in v1.
- Storing credentials outside OS keyrings is an explicit v1 tradeoff for portability and implementation simplicity. If stronger local-at-rest protection is needed later, add optional passphrase-based encryption as a future enhancement rather than changing the default storage model now.
