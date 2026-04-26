# execute-approved-plan

Engineer-facing public Codex skill to begin the next dependency-ready planned pull request from an approved Itera plan and materialize any referenced prototype patch artifacts locally.

## Install

Run `python3 install.py` from the repository root.

This installs the skill into `~/.codex/skills/execute-approved-plan`.
The installed script entrypoints delegate to the bundled shared
`scripts/plan_execution/` runtime.

## Input

- `canonicalTaskId` (required): canonical task ID such as `FRONTPAGE-42`.
- Optional `plannedPullRequestId`: explicit Itera planned-pull-request ID to
  claim instead of the next dependency-ready item.
- The skill handles Itera login internally using `App: ITERAZ` and `Platform: WEB`.
- The stored session file is `~/.codex/auth/plan_execution/iteraz.json`.

## Flow

1. Refresh the stored Itera session if it already exists.
2. If no valid session exists, prompt for email and emailed verification code.
3. Complete MFA using TOTP, recovery code, or TOTP enrollment when required.
4. Validate the authenticated session with `socialMe`.
5. Read the next dependency-ready planned PR with `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
6. If no PR is available, return an explicit unavailable reason and exit.
7. Enrich context with `getIterationTask(taskId)` for full plan intent, dependencies, and repository target metadata.
8. Generate the branch name as `itera/<canonical-task-id-lower>/pr-<position+1>`.
9. Call `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)` to transition into `IMPLEMENTING` and bind the branch.
10. Resolve any referenced prototype code media artifacts, such as `.patch` files, through `generateDownloadInformation(media)`, download them into `~/.codex/artifacts/plan_execution/claims/<canonical-task-id-lower>/pr-<position>/prototype_code_media/`, and annotate the returned plan context with those local paths.
11. When a prototype patch is attached, emit explicit prototype implementation guidance that makes patch review mandatory before coding. If the PR includes UI or UX scope, the guidance must require a pixel-perfect UI implementation from the prototype while excluding prototype logic, API behavior, and backend behavior unless the written specs separately require them.
12. Return suggested branch name, execution state, richer implementation context payload, explicit prototype guidance, and prototype code media download metadata.

## Runtime entrypoint

Run:

```bash
python3 ~/.codex/skills/execute-approved-plan/scripts/execute_approved_plan.py \
  --canonical-task-id FRONTPAGE-42
```

## Failure modes

- `AUTH_REQUIRED`: a valid stored session is required and interactive login is disabled.
- `LOGIN_FAILED`: login or MFA enrollment could not be completed.
- `NOT_FOUND`: the canonical task ID does not resolve to an Itera task when a specific planned PR is requested.
- `NO_PLAN`: the task does not yet have a current plan when a specific planned PR is requested.
- `PR_NOT_FOUND`: the requested planned pull request is not in the current plan.
- `NO_READY_PR`: none available, task already claimed, not in approved state, or no approved plan.
- `UNAVAILABLE`: temporary service, task-contract, or claim issue.

## Output contract

Canonical contract in `input-contract.json`.

## Bundled runtime

- `scripts/execute_approved_plan.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/bridge.py`
