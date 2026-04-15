---
name: download-pr-specification
description: Public self-contained skill that downloads the full build specification for a planned pull request within a canonical task.
---

# Download Planned Pull Request Specification

This skill is self-contained. It does not depend on any other local skill or
pre-existing auth helper.

It logs the user into Itera with `App: ITERAZ`, persists a refreshable local
session, fetches the full iteration task payload for a canonical task ID,
selects one planned pull request, enriches it with source task specifications
and dependency context, and writes the snapshot to a local JSON artifact that
agents can import while implementing.

## Install

Run `python3 install.py` from the repository root.

The installer copies this skill into `~/.codex/skills/download-pr-specification`.

## Input Contract

See `input-contract.json`.

## Core behavior

1. Run `python3 ~/.codex/skills/download-pr-specification/scripts/download_pr_specification.py --canonical-task-id <CANONICAL_TASK_ID> --pull-request-position <N>` or provide `--planned-pull-request-id`.
2. If the session file exists at `~/.codex/auth/plan_execution/iteraz.json`, refresh it with `refreshToken(refreshToken)`.
3. If no valid session exists, bootstrap login with:
   - `sendEmailVerificationCode(email)`
   - `loginWithEmailMfa(identifier, code)`
   - `completeEmailLoginWithTotp(challengeId, code)` or `completeEmailLoginWithRecoveryCode(challengeId, code)` when needed
   - `beginTotpEnrollment` and `confirmTotpEnrollment(code)` when the server requires first-time TOTP setup
4. Validate the authenticated session with `socialMe`.
5. Call `getIterationTaskByCanonicalId(canonicalId)`.
6. Resolve the selected planned pull request by human position or Itera planned-pull-request ID.
7. Build an implementation snapshot that includes the selected pull request, repository target, dependency context, and source task specification crosswalk.
8. Write the full snapshot to `~/.codex/artifacts/plan_execution/specifications/planned_pull_requests/<canonical-task-id-lower>/pr-<position>.json` unless an explicit output path is provided.
9. Return the same snapshot as JSON, including the artifact path for later imports.

## Runtime constraints

- Canonical task ID input is required for every invocation.
- Exactly one planned pull request selector is required: `pullRequestPosition` or `plannedPullRequestId`.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- This skill is a client of GraphQL execution contracts; it is not a source of truth.

## Success and error states

- `SUCCESS`: the planned-pull-request snapshot was downloaded and written locally.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NOT_FOUND`: no iteration task exists for the canonical task ID.
- `NO_PLAN`: the task has no current approved plan to select from.
- `PR_NOT_FOUND`: the requested planned pull request does not exist in the current plan.
- `UNAVAILABLE`: the API call failed or the snapshot could not be produced.

## References

- `scripts/auth_login.py`
- `scripts/auth_refresh.py`
- `scripts/graphql_client.py`
- `scripts/download_pr_specification.py`
