# Auth Setup

This guide matches the current auth flows implemented in `spo`:

- Spotify: Authorization Code with PKCE
- YouTube Music: Google device flow with your own OAuth client

## Spotify

Use this when connecting your own Spotify account to `spo`.

1. Start `spo` with `uv run spo` and open `Connections`.
2. Note the Spotify redirect URI shown by the app. The default is `http://127.0.0.1:8899/callback/spotify`.
3. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
4. Create a new app.
5. Open the app settings.
6. Add the exact redirect URI from `spo`.
7. Keep the IP-literal form if you use the default local callback. Use `http://127.0.0.1:8899/callback/spotify`, not `http://localhost:8899/callback/spotify`.
8. Save the app settings.
9. Copy the app `Client ID`.
10. Return to `spo` and paste that value into the Spotify `Client ID` field.
11. Leave `Redirect URI` blank unless you intentionally changed it in `spo`. The blank field uses the app default.
12. Click `Connect Spotify`.
13. Sign in to Spotify, approve access, and wait for the callback to return to `spo`.

Notes:

- `spo` uses PKCE, so you do not need a Spotify `Client Secret`.
- The redirect URI must match exactly between Spotify and the value used by `spo`.

## YouTube Music

### Enable the YouTube Data API

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project, or select an existing personal project.
3. Open `APIs & Services` -> `Library`.
4. Search for `YouTube Data API v3` and enable it.

### Configure the OAuth consent screen

1. Open `Google Auth Platform` -> `Branding` (or `APIs & Services` -> `OAuth consent screen` in the classic view) and configure the consent screen.
2. Set the app name, support email, audience, and contact email.
3. If you choose `External` and leave the app in testing, add your own Google account as a test user under `Google Auth Platform` -> `Audience`. For a personal one-user setup, that is enough.

### Create OAuth credentials

1. Open `Google Auth Platform` -> `Clients` (or `APIs & Services` -> `Credentials` in the classic view).
2. Click `Create Client` (or `Create Credentials` -> `OAuth client ID`).
3. Set the application type to **`TVs and Limited Input devices`**. This is required because `spo` uses the [Google device authorization flow](https://developers.google.com/youtube/v3/guides/auth/devices). Do not choose `Web application`, `Desktop app`, or any other type — only `TVs and Limited Input devices` supports the device code grant.
4. Name the client (e.g. `spo`) and create it.
5. Copy both the `Client ID` and `Client Secret`.

### Connect in spo

1. Start `spo` with `uv run spo` and open `Connections`.
2. Paste the `Client ID` and `Client Secret` into the YouTube Music form.
3. Click `Connect YouTube Music`.
4. `spo` will open a page showing a Google verification URL and a user code.
5. Open that URL, sign in with the Google account that owns the target YouTube Music library, enter the code, and approve access.
6. Keep the `spo` page open until it reports completion.

Notes:

- This flow does not need a redirect URI. The fields for redirect URIs and JavaScript origins that appear for other client types do not apply here.
- `spo` stores the resulting token locally so later sync runs can reuse it.
- `spo` also tries a small experimental fallback sequence of alternate YouTube client profiles for OAuth accounts. This is based on current upstream `ytmusicapi` discussion around `IOS_MUSIC` and `TVHTML5` workarounds. The fallback can help the initial connection succeed, but some library endpoints may still depend on upstream parser support for those profiles.
- If Google consent succeeds but `spo` reports that YouTube Music rejected the authenticated library request with `Request contains an invalid argument`, the setup is most likely correct and you are hitting a current upstream `ytmusicapi` OAuth limitation rather than a bad client ID or secret.

## References

- Spotify apps: <https://developer.spotify.com/documentation/web-api/concepts/apps>
- Spotify redirect URIs: <https://developer.spotify.com/documentation/web-api/concepts/redirect_uri>
- Spotify PKCE flow: <https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow>
- YouTube Music auth overview: <https://ytmusicapi.readthedocs.io/en/stable/setup/>
- YouTube Music OAuth setup: <https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html>
- Google device flow: <https://developers.google.com/youtube/v3/guides/auth/devices>
- Google OAuth consent screen: <https://developers.google.com/workspace/guides/configure-oauth-consent>
