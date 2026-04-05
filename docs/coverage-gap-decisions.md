# Coverage Gap Decisions

## Adapter Coverage Focus

Option A was raising the coverage percentage with tests aimed mostly at abstract base classes and tiny helpers.
Option B was prioritizing direct tests around Spotify and YouTube Music adapter behavior, including credential validation, token refresh, payload normalization, search filtering, and API batching.

This repository now uses option B because the adapter layer is both the least-covered and the highest-risk boundary for real sync jobs. The new tests are unit-level because these branches depend on third-party SDK behavior and network-backed auth flows, which are impractical to cover reliably with local end-to-end tests alone.
