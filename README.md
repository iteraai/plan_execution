# Plan Execution

`plan_execution` is the public home for reusable agent skills and the shared
Python bridge that powers them.

## Structure

- `plan_execution/`: shared Python runtime for Itera auth, GraphQL requests,
  artifact writing, prototype media downloads, task snapshots, planned PR
  snapshots, and planned PR claiming
- `skills/`: thin skill wrappers and supporting documentation

The public skill script paths remain stable, but their implementations delegate
to the shared runtime package instead of duplicating auth and API logic.

## Install

Run `python3 install.py` to install the bundled skills for Codex.

Run `python3 install.py --target claude` to install the same bundled skills for
Claude Code.

Run `python3 install.py --target copilot` to install the same bundled skills as
GitHub Copilot project agent skills.

Run `python3 install.py --target cursor` to install the same bundled runtime
assets as Cursor project rules.

For project-scoped targets such as Copilot and Cursor, run the installer from
the client repository root or pass `--destination-root` explicitly.

Default install roots:

- Codex: `~/.codex/skills/<skill-name>`
- Claude Code: `~/.claude/skills/<skill-name>`
- GitHub Copilot: `.github/skills/<skill-name>` relative to the current working
  directory
- Cursor: `.cursor/rules/<skill-name>.mdc` plus `.cursor/rules/<skill-name>/`
  relative to the current working directory

The installer rewrites each installed `SKILL.md` and per-skill `README.md` so
the bundled script entrypoints point at the actual installed path for the
selected target. It also bundles the shared `plan_execution/` runtime under
each installed skill's `scripts/` directory so installed skills remain
self-contained.

Copilot installs are native agent skills. Install them from the root of the
client repository so Copilot cloud agent, Copilot CLI, and VS Code agent mode can
discover `.github/skills/<skill-name>/SKILL.md`. To install into a shared
open-standard skill directory instead, pass an explicit destination root such as
`--destination-root .agents/skills`.

Example from a client repository root:

`python3 /path/to/plan_execution/install.py --target copilot`

Cursor installs are generated as Agent Requested project rules so Cursor can
decide when to include them. Each generated `.mdc` rule references a colocated
asset bundle containing the original scripts and contracts. When installing from
outside the target project root, prefer an explicit destination such as:

`python3 /path/to/plan_execution/install.py --target cursor --destination-root /path/to/project/.cursor/rules`

Runtime artifact storage still defaults to `~/.codex/...` for backward
compatibility. Runtime auth is target-aware:

- Codex: `~/.codex/auth/plan_execution/iteraz.json`
- Claude Code: `~/.claude/auth/plan_execution/iteraz.json`
- Cursor: `~/.cursor/auth/plan_execution/iteraz.json`
- Copilot or other project-scoped installs: `${XDG_CONFIG_HOME:-~/.config}/plan_execution/auth/iteraz.json`

`--session-file`, `PLAN_EXECUTION_SESSION_FILE`, and
`PLAN_EXECUTION_AUTH_ROOT` can override the default.

## Available skills

- [`execute-approved-plan`](skills/execute-approved-plan/): start execution for the next dependency-ready planned pull request using a canonical task ID.
- [`download-task-specification`](skills/download-task-specification/): download the full task specification and coding context for a canonical task ID.
- [`download-pr-specification`](skills/download-pr-specification/): download the full build specification for a planned pull request within a canonical task.

## Available skill APIs

### `execute-approved-plan`

- `canonicalTaskId` input (for example `FRONTPAGE-42`)
- self-bootstrapped Itera login using `App: ITERAZ` and `Platform: WEB`
- stored refreshable session at the target-specific auth path
- `getNextReadyPlannedPullRequestForTask(canonicalTaskId)` query
- `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)` mutation
- explicit unavailable states and deterministic branch suggestion
- current execution state and planned-pull-request metadata

### `download-task-specification`

- `canonicalTaskId` input (for example `FRONTPAGE-42`)
- self-bootstrapped Itera login using `App: ITERAZ` and `Platform: WEB`
- stored refreshable session at the target-specific auth path
- `getIterationTaskByCanonicalId(canonicalId)` query
- raw task payload plus derived build context for coding
- default JSON artifact at `~/.codex/artifacts/plan_execution/specifications/tasks/<canonical-task-id-lower>.json`

### `download-pr-specification`

- `canonicalTaskId` plus `pullRequestPosition` or `plannedPullRequestId`
- self-bootstrapped Itera login using `App: ITERAZ` and `Platform: WEB`
- stored refreshable session at the target-specific auth path
- `getIterationTaskByCanonicalId(canonicalId)` query with full plan context
- selected planned-pull-request snapshot plus source task specification crosswalk
- default JSON artifact under `~/.codex/artifacts/plan_execution/specifications/planned_pull_requests/`

## Bundled runtime scripts

- `plan_execution/auth.py`
- `plan_execution/graphql_client.py`
- `plan_execution/artifacts.py`
- `plan_execution/tasks.py`
- `plan_execution/planned_prs.py`
- `plan_execution/bridge.py`
- `plan_execution/cli.py`

The files under `skills/*/scripts/` are backwards-compatible wrappers around
these modules.

## Plan execution flow at a glance

1. Refresh the stored session if the target-specific auth file exists.
2. If no valid session exists, bootstrap login with `sendEmailVerificationCode(email)` and `loginWithEmailMfa(identifier, code)`.
3. Complete MFA with TOTP, recovery code, or restricted-session enrollment when required.
4. Validate the authenticated session with `socialMe`.
5. Resolve the next dependency-ready planned pull request using `getNextReadyPlannedPullRequestForTask(canonicalTaskId)`, or resolve a specific planned PR by `plannedPullRequestId`.
6. If unavailable, return the explicit reason without claiming anything.
7. Claim the returned planned pull request with `claimPlannedPullRequestExecution(plannedPullRequestId, branchName)`.
8. Return a deterministic branch suggestion in the format `itera/<canonical-task-id-lower>/pr-<position+1>`.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
