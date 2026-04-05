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
Option B was extracting per-playlist and per-item helper methods so the top-level sync method stays readable while the detailed branches remain explicit and testable.

This repository now uses option B because it keeps the orchestration path easy to follow, avoids normalizing lint suppressions for core sync code, and makes it easier to cover playlist edge cases such as mixed item kinds.
