# Python Runtime Decisions

## Stable 3.14.3 vs 3.14 Beta

- Decision: target stable Python `3.14.3` or newer patch releases in the `3.14` line.
- Alternative rejected: continue supporting Python `3.14.0b2` with a local compatibility shim for `pydantic` and `fastapi`.
- Reasoning: the beta-only shim existed solely to bridge a temporary mismatch between the beta interpreter and upstream typing internals. Switching the project baseline to stable `3.14.3` removes that workaround and keeps the runtime requirement aligned with a release we can verify directly.
- Consequence: `pyproject.toml` now requires `>=3.14.3,<3.15`, the beta compatibility shim is removed, and local verification should run on a stable `3.14.3` interpreter rather than a `3.14` beta.
