# download-itera-diagnostics

Admin-facing public Codex skill to fetch read-only Itera organization/project
diagnostics, failure review entries, local `itera.yaml` context, and retained
log artifacts.

## Install

Run `python3 install.py` from the repository root to choose an install target,
or pass a target flag such as `--codex`.

For Codex, this installs the skill into
`~/.codex/skills/download-itera-diagnostics`.
The installed script entrypoints delegate to the bundled shared
`scripts/plan_execution/` runtime.

## Input

- `organizationId` (required): Itera organization identifier.
- Optional `projectId`: inspect one project. If omitted, the skill lists
  organization projects and fetches a bounded failure review page for each one.
- Optional `canonicalTaskId`: include task context and focus analysis/log
  downloads on matching failure entries.
- Optional `failureReviewEntryId`: focus diagnostics on one fetched failure
  review entry.
- Optional `page` and `pageSize`: failure review paging, defaulting to `1` and
  `10`.
- Optional `includeRetainedLogs`: defaults to `true`.
- Optional `localRepoPath`: repository path to inspect for `itera.yaml`,
  defaulting to the current directory.
- Optional `outputFile`: explicit JSON artifact path.

## Runtime entrypoint

Run:

```bash
python3 ~/.codex/skills/download-itera-diagnostics/scripts/download_itera_diagnostics.py \
  --organization-id acme \
  --project-id project-123 \
  --canonical-task-id ITERA-42
```

Use `--no-prompt` when automation should fail with `AUTH_REQUIRED` instead of
starting interactive login. Use `--no-retained-logs` to skip retained log media
resolution.

## Output

By default, the skill writes:

`~/.codex/artifacts/plan_execution/diagnostics/<organization-id>/diagnostics.json`

The JSON includes viewer metadata, organization/project context, fetched failure
review entries, optional task context, redacted local `itera.yaml` data,
retained log download metadata, and a concise derived `analysis` object.

## Failure modes

- `AUTH_REQUIRED`: a valid stored session is required and interactive login is disabled.
- `LOGIN_FAILED`: login or MFA enrollment could not be completed.
- `NOT_FOUND`: the requested organization, task, or failure review entry was not found.
- `FORBIDDEN`: the authenticated user lacks admin/elevated access to the diagnostics scope.
- `UNAVAILABLE`: temporary service, contract, local parsing, or local write issue.

## Bundled runtime

- `scripts/download_itera_diagnostics.py`
- `scripts/plan_execution/auth.py`
- `scripts/plan_execution/graphql_client.py`
- `scripts/plan_execution/artifacts.py`
- `scripts/plan_execution/diagnostics.py`
