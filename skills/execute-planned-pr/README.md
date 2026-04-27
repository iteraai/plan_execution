# execute-planned-pr

Engineer-facing public Codex skill for claiming one exact dependency-ready Itera planned pull request from a per-PR "Move to agent" prompt.

## Quick Start

Install:

`python3 install.py --codex --skill execute-planned-pr`

Run:

`python3 ~/.codex/skills/execute-planned-pr/scripts/execute_planned_pr.py --canonical-task-id FRONTPAGE-42 --planned-pull-request-id <PLANNED_PR_ID>`

Use `--no-prompt` in automation when an interactive Itera login is not allowed. In that mode the command returns `AUTH_REQUIRED` if no refreshable stored session is available.

## Behavior

The command refreshes or bootstraps Itera auth, fetches the task's current plan by canonical task ID, finds the planned PR by exact ID, validates that it is startable, builds `itera/<canonical-task-id-lower>/pr-<position+1>`, claims that PR, and returns implementation context as JSON.

It does not select the next ready planned PR. Use `execute-approved-plan` for that workflow.

Prototype patches referenced by the selected PR are downloaded and returned as mandatory implementation inputs. For UI/UX PRs, treat the prototype as the visual source of truth and do not copy prototype logic/API/backend behavior unless the specs separately require it.
