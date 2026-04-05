# YouTube Music Auth Decisions

## Guided OAuth vs Browser Header Scraping

- Decision: default to a guided Google device-flow OAuth connection for YouTube Music.
- Alternative rejected: ask users to paste raw OAuth JSON or have the app extract `music.youtube.com` headers/cookies directly from the browser.
- Reasoning: the current `ytmusicapi` OAuth flow can be driven by the app when the user provides a Google OAuth client ID and secret, while a normal local web app cannot read another site's browser cookies or authenticated request headers automatically.
- Fallback: keep manual browser-header import as an advanced option for users who already know how to export `ytmusicapi`-compatible headers.
