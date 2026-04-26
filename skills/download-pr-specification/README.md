# download-pr-specification

Engineer-facing public Codex skill to fetch the full build specification for one
planned pull request within an Itera task.

## Install

Run `python3 install.py` from the repository root.

This installs the skill into `~/.codex/skills/download-pr-specification`.
The installed script entrypoints delegate to the bundled shared
`scripts/plan_execution/` runtime.

## Input

- `canonicalTaskId` (required): canonical task ID such as `FRONTPAGE-42`.
- Exactly one planned pull request selector:
  - `pullRequestPosition`: 1-based human position inside the approved plan.
  - `plannedPullRequestId`: explicit Itera planned-pull-request ID.
- Optional `outputFile`: explicit JSON artifact path. If omitted, the skill
  writes to `~/.codex/artifacts/plan_execution/specifications/planned_pull_requests/<canonical-task-id-lower>/`.
- The skill handles Itera login internally using `App: ITERAZ` and `Platform: WEB`.
- The stored session file is target-specific:
  - Codex: `~/.codex/auth/plan_execution/iteraz.json`
  - Claude: `~/.claude/auth/plan_execution/iteraz.json`
  - Cursor: `~/.cursor/auth/plan_execution/iteraz.json`
  - Copilot or other project-scoped installs: `${XDG_CONFIG_HOME:-~/.config}/plan_execution/auth/iteraz.json`

## Flow

1. Refresh the stored Itera session if it already exists.
2. If no valid session exists, prompt for email and emailed verification code.
3. Complete MFA using TOTP, recovery code, or TOTP enrollment when required.
4. Validate the authenticated session with `socialMe`.
5. Read the full task payload using `getIterationTaskByCanonicalId(canonicalId)`.
6. Resolve the selected planned pull request from the task’s current plan.
7. Derive build-oriented context such as source task specifications, dependency
   relationships, open questions, accepted task specifications, and repository hints.
8. When the selected planned PR or its source task specifications include
   prototype code media, download those artifacts beside the snapshot and
   annotate the returned context with the local file paths.
9. When a prototype patch is attached, emit explicit prototype implementation
   guidance that makes patch review mandatory before coding. If the selected PR
   includes UI or UX scope, the guidance must require a pixel-perfect UI
   implementation from the prototype while excluding prototype logic, API
   behavior, and backend behavior unless the written specs separately require
   them.
10. Write the full snapshot to a local JSON artifact so downstream agents can
   import it directly.
11. Return the same snapshot as structured JSON on stdout.

## Runtime entrypoint

Run:

```bash
python3 ~/.codex/skills/download-pr-specification/scripts/download_pr_specification.py \
  --canonical-task-id FRONTPAGE-42 \
  --pull-request-position 1
```

## Failure modes

- `AUTH_REQUIRED`: a valid stored session is required and interactive login is disabled.
- `LOGIN_FAILED`: login or MFA enrollment could not be completed.
- `NOT_FOUND`: the canonical task ID does not resolve to an Itera task.
- `NO_PLAN`: the task does not yet have a current plan.
- `PR_NOT_FOUND`: the selected planned pull request is not in the current plan.
- `UNAVAILABLE`: temporary service, contract, or local write issue.

## Output contract

Canonical contract in `input-contract.json`.

## Bundled runtime

- `scripts/download_pr_specification.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/planned_prs.py`
