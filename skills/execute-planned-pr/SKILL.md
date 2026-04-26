---
name: execute-planned-pr
description: Public self-contained skill that logs into Itera, claims one exact dependency-ready planned pull request by plannedPullRequestId, and returns implementation context for that PR.
---

# Execute Planned Pull Request

This skill is self-contained when installed. Its script entrypoints are thin wrappers around the bundled shared `plan_execution` Python runtime.

Use this skill for Itera web UI "Move to agent" prompts that include both `canonicalTaskId` and `plannedPullRequestId`. It claims exactly that planned PR, never the next ready PR.

## Install

Run `python3 install.py` from the repository root.

The installer copies this skill into `~/.codex/skills/execute-planned-pr`.

## Input Contract

See `input-contract.json`.

## Core Behavior

1. Run `python3 ~/.codex/skills/execute-planned-pr/scripts/execute_planned_pr.py --canonical-task-id <CANONICAL_TASK_ID> --planned-pull-request-id <PLANNED_PR_ID>`.
2. If the target-specific session file exists, refresh it with `refreshToken(refreshToken)`.
3. If no valid session exists, bootstrap login with:
   - `sendEmailVerificationCode(email)`
   - `loginWithEmailMfa(identifier, code)`
   - `completeEmailLoginWithTotp(challengeId, code)` or `completeEmailLoginWithRecoveryCode(challengeId, code)` when needed
   - `beginTotpEnrollment` and `confirmTotpEnrollment(code)` when the server requires first-time TOTP setup
4. Validate the authenticated session with `socialMe`.
5. Fetch task and plan context with `getIterationTaskByCanonicalId(canonicalId)`.
6. Locate the current plan entry whose `id` equals `plannedPullRequestId`.
7. Validate that the selected PR is startable: execution must still be `PLANNED`, it must not already be claimed, its plan state must be `READY_UNCLAIMED` when state is present, and all declared dependencies must be complete.
8. Build the branch name as `itera/<canonical-task-id-lower>/pr-<position+1>`.
9. Claim the exact PR with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`.
10. Resolve any referenced `prototypeCodeMedia` artifacts through `generateDownloadInformation(media)`, download them to `~/.codex/artifacts/plan_execution/claims/<canonical-task-id-lower>/pr-<position>/prototype_code_media/`, and annotate the returned implementation context with the local file paths.
11. Return JSON with status, task/PR identifiers, title and position, suggested branch name, execution state, implementation context, prototype implementation guidance, artifact paths, and prototype code media download metadata.

## Prototype Guardrails

- Downloaded prototype patches are required implementation input, not optional context.
- If the selected PR includes UI or UX work, the prototype must drive a pixel-perfect implementation of visuals and relevant interactions.
- Do not copy product logic, API contracts, data flow, or backend behavior from the prototype unless the written specifications separately require that work.

## Runtime Constraints

- `canonicalTaskId` and `plannedPullRequestId` are both required.
- This skill must not fall back to "next ready PR" selection.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- The default session file is target-specific: Codex uses `~/.codex/auth/plan_execution/iteraz.json`, Claude uses `~/.claude/auth/plan_execution/iteraz.json`, Cursor uses `~/.cursor/auth/plan_execution/iteraz.json`, and Copilot/other project-scoped installs use `${XDG_CONFIG_HOME:-~/.config}/plan_execution/auth/iteraz.json`.
- This skill is a client of GraphQL execution contracts; it is not a source of truth.

## Success and Error States

- `SUCCESS`: the exact requested planned PR was claimed and any downloadable prototype code media artifacts were resolved locally.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NOT_FOUND`: no iteration task exists for the canonical task ID.
- `NO_PLAN`: the task has no current approved plan.
- `PR_NOT_FOUND`: the requested planned pull request does not exist in the current plan.
- `UNAVAILABLE`: the requested PR exists but is not startable, already claimed, blocked, or the claim API rejected it.

## Runtime References

- `scripts/execute_planned_pr.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/bridge.py`
- `scripts/plan_execution/execute_planned_pr.py`
