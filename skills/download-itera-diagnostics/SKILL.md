---
name: download-itera-diagnostics
description: Public self-contained skill that downloads read-only Itera organization/project diagnostics for organization or project admins.
---

# Download Itera Diagnostics

This skill is self-contained when installed. Its script entrypoints are thin
wrappers around the bundled shared `plan_execution` Python runtime.

It logs the user into Itera with `App: ITERAZ`, persists a refreshable local
session, fetches read-only organization, project, failure review, task, and
retained-log diagnostics available to Itera organization/project admins, and
writes a local JSON artifact with a concise derived analysis.

## Install

Run `python3 install.py` from the repository root to choose an install target,
or pass a target flag such as `--codex`.

For Codex, the installer copies this skill into
`~/.codex/skills/download-itera-diagnostics`.

## Input Contract

See `input-contract.json`.

## Core behavior

1. Run `python3 ~/.codex/skills/download-itera-diagnostics/scripts/download_itera_diagnostics.py --organization-id <ORGANIZATION_ID>`.
2. If the target-specific session file exists, refresh it with `refreshToken(refreshToken)`.
3. If no valid session exists, bootstrap login with the same email, MFA, and TOTP enrollment flow used by the other plan execution skills.
4. Validate the authenticated session with `socialMe`.
5. Fetch `getOrganization(identifier)`.
6. If `canonicalTaskId` is provided, fetch `getIterationTaskByCanonicalId(canonicalId)`.
7. If `projectId` is provided, fetch `getProjectFailureReviewEntries(projectId, page, pageSize)` for that project. If `projectId` is omitted, fetch `getProjects(organizationId)` and then fetch one bounded failure review page for each project.
8. Inspect `itera.yaml` under `localRepoPath` and include parsed YAML when PyYAML is available, otherwise include redacted raw text with a parse note.
9. Redact obvious token-like keys from local `itera.yaml` data before writing the artifact.
10. By default, extract retained log media IDs from `LOG` references whose key matches the `JSON/<media-id>` pattern, resolve them with `generateDownloadInformation(media)`, and download the JSON files beside the diagnostics artifact.
11. Write the snapshot to `~/.codex/artifacts/plan_execution/diagnostics/<organization-id>/diagnostics.json` unless an explicit output path is provided.
12. Return the same snapshot as JSON with `analysis.likelyCause`, `confidence`, `evidence`, `recommendedNextSteps`, and `safetyNotes`.

## Runtime constraints

- `organizationId` is required for every invocation.
- `projectId`, `canonicalTaskId`, and `failureReviewEntryId` are optional filters.
- Failure review paging defaults to page `1` and page size `10`.
- Retained log downloads are enabled by default and can be disabled with `--no-retained-logs`.
- The GraphQL app context is fixed to `ITERAZ`.
- The GraphQL platform header is fixed to `WEB`.
- The default session file is target-specific: Codex uses `~/.codex/auth/plan_execution/iteraz.json`, Claude uses `~/.claude/auth/plan_execution/iteraz.json`, Cursor uses `~/.cursor/auth/plan_execution/iteraz.json`, and Copilot/other project-scoped installs use `${XDG_CONFIG_HOME:-~/.config}/plan_execution/auth/iteraz.json`.
- This skill only performs read-only diagnostics queries plus private media download URL resolution.

## Success and error states

- `SUCCESS`: the diagnostics snapshot was downloaded and written locally.
- `AUTH_REQUIRED`: interactive login is disabled and no valid stored session is available.
- `LOGIN_FAILED`: login, MFA challenge, or enrollment could not be completed.
- `NOT_FOUND`: the organization, canonical task, or requested failure review entry was not found.
- `FORBIDDEN`: the authenticated user cannot access the requested diagnostics scope.
- `UNAVAILABLE`: the API call failed, the local capture failed, or the snapshot could not be produced.

## Runtime References

- `scripts/download_itera_diagnostics.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/diagnostics.py`
