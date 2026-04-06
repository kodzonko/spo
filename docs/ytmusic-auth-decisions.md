# YouTube Music Auth Decisions

## Guided OAuth Only

- Decision: use a guided Google device-flow OAuth connection as the only YouTube Music auth flow.
- Alternative rejected: ask users to paste raw OAuth JSON, have the app extract `music.youtube.com` headers/cookies directly from the browser, or accept manual browser-header import.
- Reasoning: the current `ytmusicapi` OAuth flow can be driven by the app when the user provides a Google OAuth client ID and secret, while a normal local web app cannot read another site's browser cookies or authenticated request headers automatically. A single flow keeps the codebase simpler and avoids maintaining an auth path that cannot refresh tokens.

## OAuth Token Storage Shape

- Decision: persist only the OAuth token fields that `ytmusicapi` accepts and treat the SDK auth file as the source of truth when it already exists.
- Alternative rejected: store the raw Google token response verbatim in the auth file and overwrite any existing auth file from the database copy on each adapter construction.
- Reasoning: `ytmusicapi` expands the auth JSON directly into its `RefreshingToken` dataclass, so extra Google fields such as `refresh_token_expires_in` can break authentication. Preferring the auth file also preserves refreshed tokens that the SDK has already written locally instead of replacing them with stale database data.

## OAuth Failure Reporting

- Decision: translate `ytmusicapi` server-side OAuth 400 failures into a handled authentication error with an explicit upstream-limitation message.
- Alternative rejected: let the raw `YTMusicServerError` bubble up as a 500 during the connection flow, or keep retrying the device-code poll after the first authenticated library request already failed.
- Reasoning: current stable `ytmusicapi` still has open OAuth issues where YouTube Music returns `Request contains an invalid argument` for authenticated library requests even after Google consent succeeds. Reporting that as an application error is more accurate than a generic server crash and prevents the UI from getting stuck in a misleading follow-up state.

## Experimental OAuth Client Fallback

- Decision: for OAuth accounts, retry authentication with a short experimental client-profile sequence after the default `WEB_REMIX` profile fails, and persist the first profile that succeeds.
- Alternative rejected: pin the app to the draft `IOS_MUSIC` patch globally, or keep failing immediately on the first `WEB_REMIX` invalid-argument response.
- Reasoning: upstream discussion moved beyond the original `IOS_MUSIC` draft and indicates mixed results across `IOS_MUSIC`, `TVHTML5`, and different client versions. A local fallback sequence is the lowest-risk way to test those workarounds inside `spo` without patching site-packages or rewriting `ytmusicapi` parsing wholesale. This is intentionally experimental: it can unblock connection setup, but some later library operations may still depend on upstream response-shape support for the chosen profile.
