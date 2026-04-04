# spo

`spo` is a local, single-user web app for migrating library data between Spotify and YouTube Music. It runs entirely on your machine: no hosted backend, no shared account model, no remote state.

The current app is aimed at one-off or occasional migrations. It snapshots the source library, applies changes to the target, and resumes interrupted jobs from local state.

## Requirements

- Python `3.13`
- [`uv`](https://docs.astral.sh/uv/)
- A Spotify developer app for your own account
- YouTube Music auth material in `ytmusicapi`-compatible headers JSON or OAuth JSON form

## Install and Run

```bash
git clone git@github.com:kodzonko/spo.git
cd spo
uv sync
uv run spo web
```

Open [http://127.0.0.1:8899](http://127.0.0.1:8899).

Useful overrides:

```bash
SPO_DATA_DIR=$PWD/.spo-data uv run spo web --host 127.0.0.1 --port 8899
```

`SPO_DATA_DIR` controls where the app keeps its database, logs, and local auth files. Without it, `spo` uses the platform app-data directory.

## How to Use It

1. Go to `Connections`.
2. Connect Spotify by pasting your app `client_id` and `client_secret`.
3. In your Spotify app settings, allow the redirect URI shown by `spo`. The default is `http://127.0.0.1:8899/callback/spotify`.
4. Connect YouTube Music by pasting either headers JSON or OAuth JSON.
5. Go to `New Sync`, choose source and target accounts, select the collection types, and create the job.
6. Watch progress on the job page. Jobs can be resumed after restarts, auth fixes, and rate-limit pauses.

## What It Syncs

The v1 app is for Spotify `<->` YouTube Music only. Apple Music is modeled in the codebase but not implemented in the UI.

Collections currently handled:

- playlists
- saved tracks
- liked tracks where the source exposes them separately
- saved albums
- followed artists
- saved podcasts
- saved episodes

## Caveats

- The app is non-destructive on the target side. It creates or appends, but does not delete, unlike, unfollow, or clean up target-only content.
- Matching is automatic and best-effort. There is no manual review queue in v1, so unresolved items are skipped and reported as warnings.
- Spotify auth depends on your own developer app. In Spotify development mode, only allowlisted users can authorize it, so this is not a shared multi-user deployment.
- YouTube Music support uses `ytmusicapi`, which relies on unofficial auth flows. Browser-header auth can expire when your Google session changes.
- Some writes are intentionally unsupported in v1. If the target service cannot write a selected collection, the job finishes with warnings and skips that part.
- Spotify has no separate "liked songs" write surface here; syncing YouTube Music liked tracks into Spotify lands them in Spotify saved tracks.
- Credentials and tokens are stored locally in the app data directory, not in the OS keychain. Treat that directory as sensitive.
- Only one active job runs per app process.

## Local State

`spo` stores runtime data locally:

- `state.db`: accounts, credentials, jobs, progress
- `app.log`: application log
- `auth/`: auxiliary auth files for providers that need them
- `settings.toml`: optional non-secret settings such as bind host, bind port, log level, and `auto_resume`

Default location depends on the OS. Override it with `SPO_DATA_DIR` if you want a predictable path for backups, testing, or cleanup.
