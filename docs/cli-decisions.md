# CLI Decisions

## Root Command vs Subcommand

- Prefer `spo` over `spo web` as the primary end-user entrypoint.
- Reasoning: the application currently exposes a single user-facing mode, so requiring a subcommand adds friction without adding clarity.
- Compatibility: keep `spo web` working as an alias so existing scripts and habits do not break.
