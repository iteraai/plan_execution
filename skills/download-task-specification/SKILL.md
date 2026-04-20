---
name: download-task-specification
description: Public self-contained skill that downloads the full Itera task specification and coding context for a canonical task ID.
---

# Download Task Specification

This skill is self-contained. It does not depend on any other local skill or
pre-existing auth helper.

It logs the user into Itera with `App: ITERAZ`, persists a refreshable local
session, fetches the full iteration task payload for a canonical task ID,
enriches it with build-oriented context, and writes the snapshot to a local JSON
artifact that agents can import while implementing.

## Install

Run `python3 install.py` from the repository root.

The installer copies this skill into `~/.codex/skills/download-task-specification`.

## Input Contract

See `input-contract.json`.

## Core behavior

1. Run `python3 ~/.codex/skills/download-task-specification/scripts/download_task_specification.py --canonical-task-id <CANONICAL_TASK_ID>`.
2. If the session file exists at `~/.codex/auth/plan_execution/iteraz.json`, refresh it with `refreshToken(refreshToken)`.
3. If no valid session exists, bootstrap login with:
   - `sendEmailVerificationCode(email)`
   - `loginWithEmailMfa(identifier, code)`
   - `completeEmailLoginWithTotp(challengeId, code)` or `completeEmailLoginWithRecoveryCode(challengeId, code)` when needed
   - `beginTotpEnrollment` and `confirmTotpEnrollment(code)` when the server requires first-time TOTP setup
4. Validate the authenticated session with `socialMe`.
5. Call `getIterationTaskByCanonicalId(canonicalId)`.
6. Build a coding-oriented context payload with task specifications, questions, runs, repository hints, and current plan data.
7. When a task or planned PR specification includes `prototypeCodeMedia`, download that private media artifact to a local file next to the task snapshot and record the local path in the JSON output.
8. Write the full snapshot to `~/.codex/artifacts/plan_execution/specifications/tasks/<canonical-task-id-lower>.json` unless an explicit output path is provided.
9. Return the same snapshot as JSON, including the artifact path for later imports.

## Runtime constraints

- Canonical task ID input is required for every invocation.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- This skill is a client of GraphQL execution contracts; it is not a source of truth.

## Success and error states

- `SUCCESS`: the task snapshot was downloaded and written locally, along with any downloadable prototype code media artifacts.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NOT_FOUND`: no iteration task exists for the canonical task ID.
- `UNAVAILABLE`: the API call failed or the snapshot could not be produced.

## References

- `scripts/auth_login.py`
- `scripts/auth_refresh.py`
- `scripts/graphql_client.py`
- `scripts/download_task_specification.py`
