# execute-planned-pr

Engineer-facing public Codex skill for claiming one exact dependency-ready Itera planned pull request from a per-PR "Move to agent" prompt.

## Quick Start

Install:

`python3 install.py --codex --skill execute-planned-pr`

Run:

`python3 ~/.codex/skills/execute-planned-pr/scripts/execute_planned_pr.py --canonical-task-id FRONTPAGE-42 --planned-pull-request-id <PLANNED_PR_ID>`

Use `--no-prompt` in automation when an interactive Itera login is not allowed. In that mode the command returns `AUTH_REQUIRED` if no refreshable stored session is available.

Interactive login starts a short-lived local browser UI on `127.0.0.1` and
prints a one-time URL. The user enters email verification, TOTP, recovery, or
enrollment codes in that page, and the runtime writes the normal local session
file. Set `PLAN_EXECUTION_LOGIN_MODE=terminal` to use the legacy prompt flow.

## Behavior

The command refreshes or bootstraps Itera auth, fetches the task's current plan by canonical task ID, finds the planned PR by exact ID, validates that it is startable, builds `itera/<canonical-task-id-lower>/pr-<position+1>`, claims that PR, and returns implementation context as JSON.

It does not select the next ready planned PR. Use `execute-approved-plan` for that workflow.

Prototype patches referenced by the selected PR are downloaded and returned as mandatory implementation inputs. For UI/UX PRs, treat written specs and non-canvas prototype app changes as the visual source of truth. Never build a Canvas page or `/itera/canvas` route from the prototype; use prototype canvas files only to understand component states and variants. Do not copy prototype logic/API/backend behavior unless the specs separately require it.
