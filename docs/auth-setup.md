# Auth Setup

This guide matches the current auth flows implemented in `spo`:

- Spotify: Authorization Code with PKCE
- YouTube Music: Google device flow with your own OAuth client
- YouTube Music fallback: manual browser-header import

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

### Recommended: Google device flow

Use this when you want the cleanest supported setup for authenticated library access.

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project, or select an existing personal project.
3. Open `APIs & Services` -> `Library`.
4. Enable `YouTube Data API v3`.
5. Open `Google Auth Platform` and configure the OAuth consent screen.
6. Set the app name, support email, audience, and contact email.
7. If you choose `External` and leave the app in testing, add your own Google account as a test user. For a personal one-user setup, that is enough.
8. Open `APIs & Services` -> `Credentials`.
9. Create an `OAuth client ID`.
10. Choose `TVs and Limited Input devices` as the application type.
11. Create the client and copy both the `Client ID` and `Client Secret`.
12. Return to `spo` -> `Connections`.
13. Paste those values into the YouTube Music form.
14. Click `Connect YouTube Music`.
15. `spo` will open a page showing a Google verification URL and a user code.
16. Open that URL, sign in with the Google account that owns the target YouTube Music library, enter the code, and approve access.
17. Keep the `spo` page open until it reports completion.

Notes:

- This flow does not need a redirect URI.
- `spo` stores the resulting token locally so later sync runs can reuse it.

### Fallback: browser headers

Use this only if you already know how to export `ytmusicapi` browser headers, or if you want to avoid Google Cloud setup.

1. Sign in to [music.youtube.com](https://music.youtube.com/) with the Google account you want `spo` to use.
2. Open the browser developer tools and switch to the `Network` tab.
3. Trigger an authenticated request on the site. The easiest option is to open Library or scroll until a `POST` request to `/browse` appears.
4. Copy the request headers as described in the [`ytmusicapi` browser-auth guide](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html).
5. Convert the copied headers into a JSON object if your browser exported them in another format.
6. Return to `spo` -> `Connections`.
7. Expand `Advanced: paste browser headers instead`.
8. Paste the JSON into `Headers JSON`.
9. Click `Save browser headers`.

The JSON should match the shape expected by `ytmusicapi`, for example:

```json
{
  "Accept": "*/*",
  "Authorization": "PASTE_AUTHORIZATION",
  "Content-Type": "application/json",
  "X-Goog-AuthUser": "0",
  "x-origin": "https://music.youtube.com",
  "Cookie": "PASTE_COOKIE"
}
```

## References

- Spotify apps: <https://developer.spotify.com/documentation/web-api/concepts/apps>
- Spotify redirect URIs: <https://developer.spotify.com/documentation/web-api/concepts/redirect_uri>
- Spotify PKCE flow: <https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow>
- YouTube Music auth overview: <https://ytmusicapi.readthedocs.io/en/stable/setup/>
- YouTube Music OAuth setup: <https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html>
- YouTube Music browser auth: <https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html>
- Google device flow: <https://developers.google.com/youtube/v3/guides/auth/devices>
- Google OAuth consent screen: <https://developers.google.com/workspace/guides/configure-oauth-consent>
