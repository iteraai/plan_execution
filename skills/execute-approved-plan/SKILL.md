---
name: execute-approved-plan
description: Public self-contained skill that logs into Itera, resolves the next dependency-ready planned pull request for a canonical task ID, and claims it.
---

# Execute Approved Plan

This skill is self-contained when installed. Its script entrypoints are thin wrappers around the bundled shared `plan_execution` Python runtime.

It logs the user into Itera with `App: ITERAZ`, persists a refreshable local session, fetches the next dependency-ready planned pull request, claims it, downloads referenced prototype code media artifacts, and returns the deterministic branch suggestion plus execution state.

## Install

Run `python3 install.py` from the repository root to choose an install target,
or pass a target flag such as `--codex`.

For Codex, the installer copies this skill into
`~/.codex/skills/execute-approved-plan`.

## Input Contract

See `input-contract.json`.

## Core behavior

1. Run `python3 ~/.codex/skills/execute-approved-plan/scripts/execute_approved_plan.py --canonical-task-id <CANONICAL_TASK_ID>`. To claim a specific plan entry instead of the next ready one, add `--planned-pull-request-id <ID>`.
2. If the target-specific session file exists, refresh it with `refreshToken(refreshToken)`.
3. If no valid session exists, bootstrap login with:
   - `sendEmailVerificationCode(email)`
   - `loginWithEmailMfa(identifier, code)`
   - `completeEmailLoginWithTotp(challengeId, code)` or `completeEmailLoginWithRecoveryCode(challengeId, code)` when needed
   - `beginTotpEnrollment` and `confirmTotpEnrollment(code)` when the server requires first-time TOTP setup
4. Validate the authenticated session with `socialMe`.
5. Call `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
6. If a PR is ready, optionally enrich context with `getIterationTask(taskId)` so downstream execution has full plan context.
7. If no ready planned pull request exists, surface the unavailable reason and stop.
8. Build the branch name as `itera/<canonical-task-id-lower>/pr-<position+1>`.
9. Claim the PR with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`.
10. Resolve any referenced `prototypeCodeMedia` artifacts through `generateDownloadInformation(media)`, download them to `~/.codex/artifacts/plan_execution/claims/<canonical-task-id-lower>/pr-<position>/prototype_code_media/`, and annotate the returned implementation context with the local file paths.
11. When a prototype patch is attached, return explicit `prototypeImplementationGuidance` that makes patch review mandatory before coding. If the PR includes UI or UX scope, the guidance must say to treat written specs and non-canvas prototype app changes as the visual source of truth and match product UI pixel-perfect for UI details and relevant UX. It must also say to never build a Canvas page or `/itera/canvas` route from the prototype, to use prototype canvas files only as state/variant reference material, and to exclude prototype logic, APIs, and backend behavior unless separately specified.
12. Return the claimed execution details, suggested branch name, `implementationContext`, explicit prototype guidance, and prototype code media download metadata as JSON.

## Prototype guardrails

- Downloaded prototype patches are required implementation input, not optional context.
- If the selected PR includes UI or UX work, written specs and non-canvas prototype app changes must drive a pixel-perfect implementation of visuals and relevant interactions.
- Never build a Canvas page or `/itera/canvas` route in the target app from a prototype patch.
- Use prototype canvas files, fixtures, manifests, and `/itera/canvas` contents only to understand component states and variants.
- Treat everything outside the prototype canvas as the primary source of truth for product UI and behavior.
- Do not copy product logic, API contracts, data flow, or backend behavior from the prototype unless the written specifications separately require that work.

## Runtime constraints

- Canonical task ID input is required for every invocation.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- The default session file is target-specific: Codex uses `~/.codex/auth/plan_execution/iteraz.json`, Claude uses `~/.claude/auth/plan_execution/iteraz.json`, Cursor uses `~/.cursor/auth/plan_execution/iteraz.json`, and Copilot/other project-scoped installs use `${XDG_CONFIG_HOME:-~/.config}/plan_execution/auth/iteraz.json`.
- This skill is a client of GraphQL execution contracts; it is not a source of truth.
- Execution states are limited to `PLANNED`, `IMPLEMENTING`, `IN_REVIEW`, and `MERGED` for v1.

## Success and error states

- `SUCCESS`: claim was created, branch suggestion is returned, and any downloadable prototype code media artifacts were resolved locally.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NO_READY_PR`: there is no dependency-ready planned pull request.
- `NOT_FOUND`: no iteration task exists for the canonical task ID when selecting a specific planned PR.
- `NO_PLAN`: the task has no current approved plan when selecting a specific planned PR.
- `PR_NOT_FOUND`: the requested planned pull request does not exist in the current plan.
- `UNAVAILABLE`: the next or selected item is not startable at the moment (already claimed or otherwise blocked).

## Runtime References

- `scripts/execute_approved_plan.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/bridge.py`
