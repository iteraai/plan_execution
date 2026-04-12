# execute-approved-plan

Engineer-facing public Codex skill to begin the next dependency-ready planned pull request from an approved Itera plan.

## Install

Run `python3 install.py` from the repository root.

This installs the skill into `~/.codex/skills/execute-approved-plan`.

## Input

- `canonicalTaskId` (required): canonical task ID such as `FRONTPAGE-42`.
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
10. Return suggested branch name, execution state, and a richer implementation context payload.

## Runtime entrypoint

Run:

```bash
python3 ~/.codex/skills/execute-approved-plan/scripts/execute_approved_plan.py \
  --canonical-task-id FRONTPAGE-42
```

## Failure modes

- `AUTH_REQUIRED`: a valid stored session is required and interactive login is disabled.
- `LOGIN_FAILED`: login or MFA enrollment could not be completed.
- `NO_READY_PR`: none available, task already claimed, not in approved state, or no approved plan.
- `UNAVAILABLE`: temporary service, task-contract, or claim issue.

## Output contract

Canonical contract in `input-contract.json`.

## Bundled scripts

- `scripts/auth_login.py`
- `scripts/auth_refresh.py`
- `scripts/graphql_client.py`
- `scripts/execute_approved_plan.py`
