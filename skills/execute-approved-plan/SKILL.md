---
name: execute-approved-plan
description: Claim the next dependency-ready planned pull request for a canonical Itera task using the approved-plan execution contracts.
---

# Execute Approved Plan

This skill claims the next dependency-ready planned pull request for an iteration task using its canonical task ID.

Use cases:

- Start execution in the approved-planning phase using human-friendly task IDs.
- Resolve dependency readiness without client-side plan graph traversal.
- Bind branch ownership before provider pull request creation.

## Input Contract

See [`input-contract.json`](./input-contract.json).

## Core behavior

1. Refresh Itera auth token via the existing auth helper.
2. Call `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`.
3. If no PR is returned (or the selection is unavailable), stop and surface the reason.
4. If the returned PR is unavailable, return a clear unavailable message.
5. Claim the PR with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)` to support webhook-based state transitions.
6. Return the claimed execution details and a deterministic branch suggestion.

## Runtime constraints

- Canonical task ID input is required for every invocation.
- Implementation scope is `plan_execution` only (`README.md` and `skills/*`).
- This skill is a client of GraphQL execution contracts; it should not become a second source of truth.
- Execution states are limited to `PLANNED`, `IMPLEMENTING`, `IN_REVIEW`, and `MERGED` for v1.

## Success and error states

- `SUCCESS`: claim was created and branch suggestion is returned.
- `NO_READY_PR`: there is no dependency-ready planned pull request.
- `UNAVAILABLE`: the next item is not startable at the moment (already claimed or otherwise blocked).
- `AUTH_REQUIRED`: token refresh or auth helper failure.

## References

- [`/Users/jpellat/.codex/skills/social-graph-api-auth/SKILL.md`](/Users/jpellat/.codex/skills/social-graph-api-auth/SKILL.md): required login flow.
- [input contract](./input-contract.json)
- [README](/Users/jpellat/.codex/worktrees/3229/plan_execution/README.md)
