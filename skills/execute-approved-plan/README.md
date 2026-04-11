# execute-approved-plan

Engineer-facing Codex skill to begin the next dependency-ready planned pull request from an approved Itera plan.

## Input

- `canonicalTaskId` (required): canonical task ID such as `FRONTPAGE-42`.
- Uses existing Itera auth helpers from [`social-graph-api-auth`](/Users/jpellat/.codex/skills/social-graph-api-auth/SKILL.md).

## Flow

1. Authenticate with existing Itera login flow.
2. Read the next dependency-ready planned PR with `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
3. If no PR is available (task unavailable, no plan, no dependency-ready PR, already claimed), return an explicit unavailable reason and exit.
4. Call `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)` to transition into `IMPLEMENTING` and bind branch.
5. Return suggested branch name, execution state, and selected planned-pull-request metadata.

## Failure modes

- `NO_READY_PR`: none available, task already claimed, not in approved state, or no approved plan.
- `AUTH_REQUIRED`: social-graph auth helper missing/expired.
- `UNAVAILABLE`: temporary service or validation issue.

## Output contract

Canonical contract in `input-contract.json`.

## Related touch points

- `/Users/jpellat/.codex/worktrees/3229/plan_execution/README.md`
- `/Users/jpellat/.codex/worktrees/3229/plan_execution/skills/README.md`
- `/Users/jpellat/.codex/workspaces/3229/plan_execution/skills/execute-approved-plan/README.md`
