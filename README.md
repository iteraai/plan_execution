# Plan Execution

`plan_execution` is the public home for reusable Codex skills and, later, a CLI that works with them.

## Structure

- `skills/`: skill definitions and supporting documentation

The repository starts as a public skills collection. CLI-related code can be added later without changing the current layout.

## Install

Run `python3 install.py`.

The installer copies `skills/execute-approved-plan/` into `~/.codex/skills/execute-approved-plan` so end users can use the skill without installing any other local skill.

## Available skills

- [`execute-approved-plan`](skills/execute-approved-plan/): start execution for the next dependency-ready planned pull request using a canonical task ID.

## Available skill APIs

### `execute-approved-plan`

- `canonicalTaskId` input (for example `FRONTPAGE-42`)
- self-bootstrapped Itera login using `App: ITERAZ` and `Platform: WEB`
- stored refreshable session at `~/.codex/auth/plan_execution/iteraz.json`
- `getNextReadyPlannedPullRequestForTask(canonicalTaskId)` query
- `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)` mutation
- explicit unavailable states and deterministic branch suggestion
- current execution state and planned-pull-request metadata

## Bundled runtime scripts

- `skills/execute-approved-plan/scripts/auth_login.py`
- `skills/execute-approved-plan/scripts/auth_refresh.py`
- `skills/execute-approved-plan/scripts/graphql_client.py`
- `skills/execute-approved-plan/scripts/execute_approved_plan.py`

## Plan execution flow at a glance

1. Refresh the stored session if `~/.codex/auth/plan_execution/iteraz.json` exists.
2. If no valid session exists, bootstrap login with `sendEmailVerificationCode(email)` and `loginWithEmailMfa(identifier, code)`.
3. Complete MFA with TOTP, recovery code, or restricted-session enrollment when required.
4. Validate the authenticated session with `socialMe`.
5. Resolve the next dependency-ready planned pull request using `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
6. If unavailable, return the explicit reason without claiming anything.
7. Claim the returned planned pull request with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`.
8. Return a deterministic branch suggestion in the format `itera/<canonical-task-id-lower>/pr-<position+1>`.
