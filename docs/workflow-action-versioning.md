# Workflow Action Versioning

## Decision

Pin GitHub Actions to commit SHAs and annotate each pin with the corresponding stable release tag.

## Reasoning

Option A was floating major tags such as `actions/checkout@v6`.
Option B was pinned commit SHAs annotated with stable release tags such as `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2`.

This repository now uses option B because it satisfies workflow security linters, makes upgrades auditable, and keeps each workflow run reproducible while still tracking current stable releases through intentional maintenance updates.

## Related CI Tooling Choice

Option A was changing the lint workflow from `mypy` to `ty`.
Option B was keeping `mypy` as the workflow type checker and restoring the missing dev dependency.

This repository now uses option B because the existing README, workflow, and `[tool.mypy]` configuration already standardize on `mypy`, so the smallest coherent fix is to keep that toolchain aligned.
