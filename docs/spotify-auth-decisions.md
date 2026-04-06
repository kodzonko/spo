# Spotify Auth Decisions

## PKCE vs Client Secret

- Decision: use Spotify Authorization Code with PKCE for `spo` connections.
- Alternative rejected: ask users to paste a Spotify app client secret and run the confidential-client authorization code flow.
- Reasoning: `spo` is a local single-user migration tool that runs against the operator's own accounts. PKCE keeps the same Spotify user-library scopes and refresh-token behavior needed by the app while avoiding storage of a Spotify client secret on disk.
- Consequence: Spotify connections require only a Spotify developer app `client_id` plus a registered local redirect URI. `spo` stores the PKCE verifier only while the authorization callback is pending, then persists the resulting tokens for later refreshes. There is no client-secret fallback path in the app code.
