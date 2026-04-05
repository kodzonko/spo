# Linting Decisions

## Ruff Rule Scope

Option A was enforcing every rule from `select = ["ALL"]` immediately across source files, tests, and embedded templates.
Option B was keeping `ALL` as the baseline while explicitly ignoring rule families that currently create large amounts of mechanical churn without improving runtime behavior, and keeping the correctness-focused rules enabled.

This repository now uses option B because it lets Ruff catch concrete integration, safety, and framework issues without forcing hundreds of docstring, annotation, complexity, and exception-style edits while the codebase is still evolving.

## Test And Template Exceptions

Option A was applying the same Ruff expectations to pytest assertions, test fixture secrets, and long embedded HTML template lines.
Option B was using targeted per-file ignores for those cases while keeping the stricter rules elsewhere.

This repository now uses option B because bare `assert` statements are idiomatic in pytest, fixture-only credential strings are test data rather than deployed secrets, and wrapping long inline template fragments would make the template module harder to maintain.

## Dynamic SQL Updates

Option A was banning all dynamic SQL query assembly in the persistence layer.
Option B was allowing dynamic `UPDATE` fragments only after validating each column name against an explicit allow-list, and documenting the remaining Ruff false positive inline.

This repository now uses option B because `update_job` and `update_task` need partial updates, but the allow-lists keep the query surface bounded to known columns.

## Trailing Commas With Ruff Formatter

Option A was keeping `flake8-commas` enforcement rules like `COM812` and `COM819` enabled alongside `ruff format`.
Option B was letting `ruff format` own trailing-comma normalization and explicitly ignoring the conflicting lint rules.

This repository now uses option B because Ruff's formatter already adds and removes trailing commas consistently, so leaving `COM812` or `COM819` enabled only produces formatter-compatibility warnings without providing stronger guarantees.

## Magic Values And HTTP Status Codes

Option A was leaving comparison thresholds and HTTP status codes inline and silencing `PLR2004` where they appeared.
Option B was keeping Ruff's magic-value rule enabled, moving domain thresholds to named module constants, and using `requests.codes` for HTTP status comparisons.

This repository now uses option B because it makes matching heuristics explicit, keeps transport-layer status handling consistent across adapters and tests, and avoids weakening the lint rule globally.

## Sync Complexity Refactors

Option A was suppressing `C901` on orchestration methods like `_apply_playlists` once the control flow became branch-heavy.
Option B was extracting per-playlist, per-library-entity, and per-item helper methods so the top-level sync methods stay readable while the detailed branches remain explicit and testable.

This repository now uses option B because it keeps the orchestration path easy to follow, avoids normalizing lint suppressions for core sync code, and makes it easier to cover playlist edge cases such as mixed item kinds alongside library-collection match and skip flows.

## Job Execution Orchestration

Option A was keeping `run_job` as a single method that mixed setup, authentication persistence, per-collection dispatch, and terminal error handling.
Option B was moving those responsibilities into small private helpers coordinated by a lightweight job execution context.

This repository now uses option B because the main sync entry point stays readable under Ruff's statement limits, and setup or pause/fail paths can be exercised directly in integration-style tests without weakening the lint rules.

## Return-Heavy Route And Adapter Branches

Option A was suppressing `PLR0911` on route handlers and service methods that return from many branch-specific states.
Option B was consolidating those flows around a single response or page return while leaving the state-specific branches explicit.

This repository now uses option B because it keeps OAuth cleanup and collection-fetch behavior testable without normalizing lint suppressions, and it reduces the risk of one branch forgetting shared follow-up work like pagination or flow removal.
