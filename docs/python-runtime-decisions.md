# Python Runtime Decisions

## Validated Python 3.13 vs Python 3.14 Beta

- Decision: pin local development and CI to Python `3.13` for now.
- Alternative rejected: require Python `3.14` immediately.
- Reasoning: the current `uv`-provisioned `3.14` interpreter resolves to `3.14.0b2` in this environment, and the FastAPI/Pydantic stack crashes during import on that beta runtime before tests can start.
- Consequence: the repository now keeps `pyproject.toml`, `.python-version`, `README.md`, and lint/test CI aligned on `3.13` until a stable `3.14` toolchain is available and verified against the project.
