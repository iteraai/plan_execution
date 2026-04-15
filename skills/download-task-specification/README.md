# download-task-specification

Engineer-facing public Codex skill to fetch the full Itera task specification
and coding context for a canonical task ID.

## Install

Run `python3 install.py` from the repository root.

This installs the skill into `~/.codex/skills/download-task-specification`.

## Input

- `canonicalTaskId` (required): canonical task ID such as `FRONTPAGE-42`.
- Optional `outputFile`: explicit JSON artifact path. If omitted, the skill
  writes to `~/.codex/artifacts/plan_execution/specifications/tasks/<canonical-task-id-lower>.json`.
- The skill handles Itera login internally using `App: ITERAZ` and `Platform: WEB`.
- The stored session file is `~/.codex/auth/plan_execution/iteraz.json`.

## Flow

1. Refresh the stored Itera session if it already exists.
2. If no valid session exists, prompt for email and emailed verification code.
3. Complete MFA using TOTP, recovery code, or TOTP enrollment when required.
4. Validate the authenticated session with `socialMe`.
5. Read the full task payload using `getIterationTaskByCanonicalId(canonicalId)`.
6. Derive build-oriented context such as repository hints, latest task runs,
   open questions, accepted specifications, and the enriched current plan.
7. Write the full snapshot to a local JSON artifact so downstream agents can
   import it directly.
8. Return the same snapshot as structured JSON on stdout.

## Runtime entrypoint

Run:

```bash
python3 ~/.codex/skills/download-task-specification/scripts/download_task_specification.py \
  --canonical-task-id FRONTPAGE-42
```

## Failure modes

- `AUTH_REQUIRED`: a valid stored session is required and interactive login is disabled.
- `LOGIN_FAILED`: login or MFA enrollment could not be completed.
- `NOT_FOUND`: the canonical task ID does not resolve to an Itera task.
- `UNAVAILABLE`: temporary service, contract, or local write issue.

## Output contract

Canonical contract in `input-contract.json`.

## Bundled scripts

- `scripts/auth_login.py`
- `scripts/auth_refresh.py`
- `scripts/graphql_client.py`
- `scripts/download_task_specification.py`
