# Runtime Storage Decisions

## Fixed Repo-Local Storage vs Configurable App-Data Paths

- Decision: store runtime state in `./.spo-data/` under the repository root.
- Alternative rejected: allow `SPO_DATA_DIR`, platform-specific app-data directories, or a configurable `app_data_dir` in `settings.toml`.
- Reasoning: the app is developed and run from this repository, so a repo-local path is predictable, easy to inspect, and keeps cleanup, backups, and auth debugging tied to the checkout in use.
- Consequence: runtime files are no longer relocatable through config and must stay ignored in Git.
