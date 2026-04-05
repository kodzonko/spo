# spo

`spo` is a local app for migrating music library between Spotify and YouTube Music.

## Requirements

- Python `3.13`
- Astral's [`uv`](https://docs.astral.sh/uv/)
- A Spotify developer app for your own account
- YouTube Music auth material in `ytmusicapi`-compatible headers JSON or OAuth JSON form

## Install and Run

```bash
git clone git@github.com:kodzonko/spo.git
cd spo
uv sync
uv run spo
```

Open [http://127.0.0.1:8899](http://127.0.0.1:8899).

`spo` keeps its database, logs, local auth files, and optional `settings.toml` in `./.spo-data/` at the repository root.

## How to Use It

1. Go to `Connections`.
2. Connect Spotify by pasting your app `client_id` and `client_secret`.
3. In your Spotify app settings, allow the redirect URI shown by `spo`. The default is `http://127.0.0.1:8899/callback/spotify`.
4. Connect YouTube Music by pasting either headers JSON or OAuth JSON.
5. Go to `New Sync`, choose source and target accounts, select the collection types, and create the job.
6. Watch progress on the job page. Jobs can be resumed after restarts, auth fixes, and rate-limit pauses.

## What It Syncs

The v1 app is for Spotify `<->` YouTube Music only.

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
- Matching is automatic and best-effort. There is no manual review queue, so unresolved items are skipped and reported as warnings.
- Spotify has no separate "liked songs" write surface here; syncing YouTube Music liked tracks into Spotify lands them in Spotify saved tracks.
- Credentials and tokens are stored locally in `./.spo-data/`. Treat that directory as sensitive.
