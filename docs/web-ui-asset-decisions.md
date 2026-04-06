# Web UI Asset Decisions

## Explicit Empty Icon Declarations vs Placeholder Icon Files

Option A was adding placeholder `favicon.ico` and Apple touch icon files just to silence default browser probes.

Option B was declaring empty `data:,` icons in the shared HTML template and returning `204 No Content` on the common icon probe routes.

This repository now uses option B because the web app intentionally has no branding assets, the shared template makes that choice explicit, and the compatibility routes prevent noisy `404 Not Found` logs from browsers that still probe icon paths on their own.
