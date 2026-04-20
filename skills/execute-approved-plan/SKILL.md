---
name: execute-approved-plan
description: Public self-contained skill that logs into Itera, resolves the next dependency-ready planned pull request for a canonical task ID, and claims it.
---

# Execute Approved Plan

This skill is self-contained. It does not depend on any other local skill or pre-existing auth helper.

It logs the user into Itera with `App: ITERAZ`, persists a refreshable local session, fetches the next dependency-ready planned pull request, claims it, downloads referenced prototype code media artifacts, and returns the deterministic branch suggestion plus execution state.

## Install

Run `python3 install.py` from the repository root.

The installer copies this skill into `~/.codex/skills/execute-approved-plan`.

## Input Contract

See `input-contract.json`.

## Core behavior

1. Run `python3 ~/.codex/skills/execute-approved-plan/scripts/execute_approved_plan.py --canonical-task-id <CANONICAL_TASK_ID>`.
2. If the session file exists at `~/.codex/auth/plan_execution/iteraz.json`, refresh it with `refreshToken(refreshToken)`.
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
10. Download any referenced `prototypeCodeMedia` artifacts, such as `.patch` files, to `~/.codex/artifacts/plan_execution/claims/<canonical-task-id-lower>/pr-<position>/prototype_code_media/` and annotate the returned implementation context with the local file paths.
11. Return the claimed execution details, suggested branch name, `implementationContext`, and prototype code media download metadata as JSON.

## Runtime constraints

- Canonical task ID input is required for every invocation.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- This skill is a client of GraphQL execution contracts; it is not a source of truth.
- Execution states are limited to `PLANNED`, `IMPLEMENTING`, `IN_REVIEW`, and `MERGED` for v1.

## Success and error states

- `SUCCESS`: claim was created, branch suggestion is returned, and any downloadable prototype code media artifacts were resolved locally.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NO_READY_PR`: there is no dependency-ready planned pull request.
- `UNAVAILABLE`: the next item is not startable at the moment (already claimed or otherwise blocked).

## References

- `scripts/auth_login.py`
- `scripts/auth_refresh.py`
- `scripts/graphql_client.py`
- `scripts/execute_approved_plan.py`
