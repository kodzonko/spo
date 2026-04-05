# Workflow Trigger Decisions

## Decision

Use the same trigger policy across all GitHub Actions workflows:

- run on pushes to any branch
- run on pull request creation and reopen events
- run when commits are pushed to an open or draft pull request
- run when a pull request is moved between draft and ready-for-review states
- allow manual runs through `workflow_dispatch`

## Reasoning

Option A was mixing workflow-specific trigger rules such as `push` on `master` in one workflow and broader triggers in another.
Option B was standardizing all workflows on the same branch and pull request trigger policy.

This repository now uses option B because CI behavior should not depend on which workflow is being evaluated. Standardizing the trigger block avoids gaps where one workflow runs for a pull request update and another does not.

## Manual Dispatch Branch Selection

Option A was trying to define a custom `workflow_dispatch` input whose branch choices are generated dynamically in workflow YAML.
Option B was relying on GitHub Actions' native `Run workflow` branch selector, which already presents the available branches dynamically for manual runs.

This repository now uses option B because GitHub Actions does not support dynamically generated `workflow_dispatch` choice inputs in workflow YAML. The native branch selector is the supported way to choose the target branch for a manual run.
