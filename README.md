# Plan Execution

`plan_execution` is the home for reusable skills and, later, a CLI that works with them.

## Structure

- `skills/`: skill definitions and supporting documentation

The repository starts as a skills collection. CLI-related code can be added later without changing the current layout.

## Available skills

- [`execute-approved-plan`](skills/execute-approved-plan/): start execution for the next dependency-ready planned pull request using a canonical task ID.

## Available skill APIs

### `execute-approved-plan`

- `canonicalTaskId` input (for example `FRONTPAGE-42`)
- `getNextReadyPlannedPullRequestForTask(canonicalTaskId)` query
- optional claim via `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`
- explicit unavailable states and deterministic branch suggestion
- current execution state and planned-pull-request metadata

## Plan execution flow at a glance

1. Authenticate with existing Itera login flows (`social-graph-api-auth`).
2. Resolve the next dependency-ready planned pull request using `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
3. If unavailable (not ready, claimed, not in `PLANNED`, task not found), return a clear reason.
4. Claim the returned planned pull request with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`.
5. Return a deterministic branch suggestion and current execution state.
