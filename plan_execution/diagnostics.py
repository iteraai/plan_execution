#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from . import auth as auth_login
from . import auth as auth_refresh
from . import artifacts
from . import graphql_client

GET_ORGANIZATION_QUERY = """
query GetOrganization($organizationId: OrganizationID!) {
  getOrganization(identifier: $organizationId) {
    identifier
    name
    domain
    createdAt
    viewerIsAdmin
    requireTotp
    mfaRequiredSince
    openAiTokenConfigured
  }
}
""".strip()
GET_PROJECTS_QUERY = """
query GetProjects($organizationId: OrganizationID!) {
  getProjects(organizationId: $organizationId) {
    id
    title
    status
    repositoryProvider
    organization {
      identifier
      name
      viewerIsAdmin
    }
  }
}
""".strip()
GET_PROJECT_FAILURE_REVIEW_ENTRIES_QUERY = """
query GetProjectFailureReviewEntries(
  $projectId: ProjectID!
  $page: Int
  $pageSize: Int
) {
  getProjectFailureReviewEntries(
    projectId: $projectId
    page: $page
    pageSize: $pageSize
  ) {
    id
    failureKind
    organization {
      identifier
      name
      viewerIsAdmin
    }
    projectId
    projectTitle
    taskId
    taskCanonicalId
    taskName
    taskPhase
    summary
    failureDetail
    failedAt
    createdAt
    updatedAt
    logReference {
      kind
      bucket
      key
    }
    taskRun {
      id
      phase
      status
      triggerKind
      triggerId
      sourceKind
      sourceActorId
      traceId
      enqueuedAt
      processingStartedAt
      completedAt
      createdAt
      updatedAt
    }
    prototypeStartup {
      sessionId
      prototypeId
      status
      sourceActorId
      createdAt
      updatedAt
    }
  }
}
""".strip()
GET_ITERATION_TASK_BY_CANONICAL_ID_QUERY = """
query GetIterationTaskByCanonicalId($canonicalId: IterationTaskCanonicalID!) {
  getIterationTaskByCanonicalId(canonicalId: $canonicalId) {
    id
    canonicalId
    projectId
    owner {
      username
    }
    name
    contextProblem
    goalDescription
    successCriteria
    outOfScope
    phase
    status
    productCodexSessionId
    engineeringCodexSessionId
    planningCodexSessionId
    createdAt
    updatedAt
    taskRuns {
      id
      phase
      status
      trigger {
        kind
        id
      }
      source {
        kind
        actorId
      }
      traceId
      enqueuedAt
      processingStartedAt
      completedAt
      summary
      createdAt
      updatedAt
      artifactReferences {
        kind
        bucket
        key
      }
    }
    currentHumanBlocker {
      kind
      phase
      taskRunId
      questionIds
      specificationIds
    }
    currentPlan {
      id
      taskRunId
      createdAt
      updatedAt
      pullRequests {
        id
        position
        title
        state
        deploymentTargetLabel
        execution {
          status
          branchName
          claimedByUser {
            username
          }
          providerPullRequestNumber
          providerPullRequestUrl
        }
      }
    }
  }
}
""".strip()
GENERATE_DOWNLOAD_INFORMATION_MUTATION = """
mutation GenerateDownloadInformation($mediaId: MediaID!) {
  generateDownloadInformation(media: $mediaId) {
    url
    expiration
  }
}
""".strip()
DEFAULT_OUTPUT_ROOT = (
    Path.home() / ".codex" / "artifacts" / "plan_execution" / "diagnostics"
)
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
RETAINED_LOGS_DIRNAME = "retained_logs"
REDACTED_SECRET_VALUE = "[REDACTED]"
SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|credential|authorization|api[_-]?key|"
    r"private[_-]?key|access[_-]?key|refresh[_-]?key)",
    re.IGNORECASE,
)
RAW_SECRET_LINE_PATTERN = re.compile(
    r"^(\s*(?:-\s*)?[^#:\n=]*"
    r"(?:token|secret|password|credential|authorization|api[_-]?key|"
    r"private[_-]?key|access[_-]?key|refresh[_-]?key)"
    r"[^:\n=]*\s*[:=]\s*)(.+)$",
    re.IGNORECASE,
)
JSON_MEDIA_LOG_KEY_PATTERN = re.compile(
    r"(?:^|/)JSON/" r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


class AuthRequiredError(RuntimeError):
    pass


class PermissionDeniedError(RuntimeError):
    pass


def _sanitize_path_part(value: str) -> str:
    sanitized = []
    for character in value:
        if character.isalnum() or character in {"-", "_", "."}:
            sanitized.append(character)
        else:
            sanitized.append("-")
    return "".join(sanitized).strip("-") or "organization"


def default_output_file(organization_id: str) -> Path:
    return (
        DEFAULT_OUTPUT_ROOT / _sanitize_path_part(organization_id) / "diagnostics.json"
    )


def write_json_artifact(output_file: Path, payload: dict[str, Any]) -> None:
    artifacts.write_json_artifact(
        output_file, payload, protect_file=auth_refresh.protect_local_file
    )


def write_binary_artifact(output_file: Path, payload: bytes) -> None:
    artifacts.write_binary_artifact(
        output_file, payload, protect_file=auth_refresh.protect_local_file
    )


def _error_text(exc: graphql_client.GraphQLError) -> str:
    parts = [str(exc)]
    if exc.errors is not None:
        try:
            parts.append(json.dumps(exc.errors))
        except TypeError:
            parts.append(str(exc.errors))
    return " ".join(parts).lower()


def _is_forbidden_graphql_error(exc: graphql_client.GraphQLError) -> bool:
    if exc.status_code in {401, 403}:
        return True
    text = _error_text(exc)
    return any(
        signal in text
        for signal in (
            "forbidden",
            "permission",
            "not authorized",
            "unauthorized",
            "not allowed",
            "requires admin",
        )
    )


def _is_not_found_graphql_error(exc: graphql_client.GraphQLError) -> bool:
    text = _error_text(exc)
    return any(signal in text for signal in ("not found", "does not exist", "missing"))


def ensure_authenticated_context(
    *,
    session_file: Path,
    config: graphql_client.GraphQLRequestConfig,
    interactive: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if session_file.exists():
        try:
            payload = auth_refresh.refresh_session_file(session_file, config=config)
            social_me = auth_refresh.fetch_social_me(payload["token"], config=config)
            return payload, social_me
        except Exception as exc:
            print(
                f"Stored Itera session could not be refreshed: {exc}",
                file=sys.stderr,
            )

    if not interactive:
        raise AuthRequiredError("A valid Itera session is required")

    payload = auth_login.login_interactively(session_file=session_file, config=config)
    social_me = auth_refresh.fetch_social_me(payload["token"], config=config)
    return payload, social_me


def _redact_value(value: Any, *, parent_sensitive: bool = False) -> Any:
    if parent_sensitive:
        return REDACTED_SECRET_VALUE
    if isinstance(value, dict):
        return {
            key: _redact_value(
                nested_value,
                parent_sensitive=SENSITIVE_KEY_PATTERN.search(str(key)) is not None,
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_raw_text(text: str) -> str:
    redacted_lines = []
    for line in text.splitlines():
        match = RAW_SECRET_LINE_PATTERN.match(line)
        if match is None:
            redacted_lines.append(line)
            continue
        redacted_lines.append(f"{match.group(1)}{REDACTED_SECRET_VALUE}")
    return "\n".join(redacted_lines)


def _load_yaml_module() -> Any | None:
    try:
        import yaml  # type: ignore[import-untyped]
    except Exception:
        return None
    return yaml


def inspect_local_itera_yaml(local_repo_path: Path) -> dict[str, Any]:
    repo_path = local_repo_path.expanduser()
    itera_yaml_path = repo_path / "itera.yaml"
    result: dict[str, Any] = {
        "localRepoPath": str(repo_path),
        "path": str(itera_yaml_path),
        "exists": itera_yaml_path.is_file(),
    }
    if not itera_yaml_path.is_file():
        return result

    raw_text = itera_yaml_path.read_text()
    yaml_module = _load_yaml_module()
    if yaml_module is None:
        result.update(
            {
                "parseMode": "raw",
                "rawText": _redact_raw_text(raw_text),
                "parseError": "PyYAML is not installed; captured redacted raw text.",
            }
        )
        return result

    try:
        parsed_yaml = yaml_module.safe_load(raw_text)
    except Exception as exc:
        result.update(
            {
                "parseMode": "pyyaml-error",
                "rawText": _redact_raw_text(raw_text),
                "parseError": str(exc),
            }
        )
        return result

    result.update(
        {
            "parseMode": "pyyaml",
            "parsedYaml": _redact_value(parsed_yaml),
            "parseError": None,
        }
    )
    return result


def _parse_s3_bucket_and_key(media_url: str) -> tuple[str, str] | None:
    parsed_url = urllib_parse.urlparse(media_url)
    if parsed_url.scheme not in {"http", "https"}:
        return None

    host = parsed_url.netloc.strip().lower()
    path = urllib_parse.unquote(parsed_url.path.lstrip("/"))
    if not host or not path:
        return None

    if host.endswith(".s3.amazonaws.com"):
        bucket = host[: -len(".s3.amazonaws.com")]
        return (bucket, path) if bucket else None

    if ".s3." in host:
        bucket = host.split(".s3.", 1)[0]
        return (bucket, path) if bucket else None

    if host == "s3.amazonaws.com" or host.startswith("s3."):
        bucket, _, key = path.partition("/")
        return (bucket, key) if bucket and key else None

    return None


def _download_private_media_bytes(media_url: str, *, timeout_seconds: float) -> bytes:
    media_request = urllib_request.Request(media_url, method="GET")
    try:
        with urllib_request.urlopen(media_request, timeout=timeout_seconds) as response:
            return response.read()
    except urllib_error.HTTPError as exc:
        if exc.code not in {401, 403}:
            raise
    except urllib_error.URLError:
        pass

    bucket_and_key = _parse_s3_bucket_and_key(media_url)
    if bucket_and_key is None:
        raise RuntimeError(
            "Retained log media URL is not directly readable and is not a supported S3 URL"
        )

    try:
        import boto3
    except Exception as exc:  # pragma: no cover - dependency/environment failure
        raise RuntimeError(
            "Retained log media URL requires private access and boto3 is unavailable for S3 fallback"
        ) from exc

    bucket, key = bucket_and_key
    s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _extract_log_media_id(log_reference: dict[str, Any] | None) -> str | None:
    if not isinstance(log_reference, dict):
        return None
    if str(log_reference.get("kind") or "").upper() != "LOG":
        return None
    key = log_reference.get("key")
    if not isinstance(key, str):
        return None
    match = JSON_MEDIA_LOG_KEY_PATTERN.search(key.strip())
    return match.group(1) if match is not None else None


def _generate_download_information(
    media_id: str,
    *,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> tuple[str | None, str | None]:
    response = graphql_client.execute_graphql(
        GENERATE_DOWNLOAD_INFORMATION_MUTATION,
        {"mediaId": media_id},
        token=token,
        config=config,
    )
    download_information = response.get("generateDownloadInformation") or {}
    return (
        download_information.get("url"),
        download_information.get("expiration"),
    )


def _retained_log_output_root(diagnostics_path: Path) -> Path:
    return diagnostics_path.parent / RETAINED_LOGS_DIRNAME


def _brief_failure_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "failureKind": entry.get("failureKind"),
        "projectId": entry.get("projectId"),
        "projectTitle": entry.get("projectTitle"),
        "taskCanonicalId": entry.get("taskCanonicalId"),
        "taskName": entry.get("taskName"),
        "summary": entry.get("summary"),
        "failedAt": entry.get("failedAt"),
    }


def _collect_retained_log_media(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    collected_media: dict[str, dict[str, Any]] = {}
    for entry in entries:
        log_reference = entry.get("logReference")
        media_id = _extract_log_media_id(log_reference)
        if media_id is None:
            continue

        collected_entry = collected_media.setdefault(
            media_id,
            {
                "mediaId": media_id,
                "logReference": log_reference,
                "sourceEntries": [],
            },
        )
        collected_entry["sourceEntries"].append(_brief_failure_entry(entry))
    return collected_media


def _download_retained_log_artifacts(
    entries: list[dict[str, Any]],
    *,
    diagnostics_path: Path,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    collected_media = _collect_retained_log_media(entries)
    if not collected_media:
        return []

    output_root = _retained_log_output_root(diagnostics_path)
    downloads: list[dict[str, Any]] = []
    for media_id, collected_entry in sorted(collected_media.items()):
        local_file: str | None = None
        error_message: str | None = None
        download_status = "SKIPPED"
        download_information_expiration: str | None = None

        media_file = output_root / f"{media_id}.json"
        try:
            download_url, download_information_expiration = (
                _generate_download_information(
                    media_id,
                    token=token,
                    config=config,
                )
            )
            if not download_url:
                raise RuntimeError(
                    "generateDownloadInformation returned no download URL"
                )
            if not media_file.exists():
                payload_bytes = _download_private_media_bytes(
                    download_url,
                    timeout_seconds=timeout_seconds,
                )
                write_binary_artifact(media_file, payload_bytes)
            local_file = str(media_file)
            download_status = "DOWNLOADED"
        except graphql_client.GraphQLError as exc:
            if _is_forbidden_graphql_error(exc):
                raise PermissionDeniedError(str(exc)) from exc
            error_message = str(exc)
            download_status = "FAILED"
        except Exception as exc:
            error_message = str(exc)
            download_status = "FAILED"

        downloads.append(
            {
                "mediaId": media_id,
                "downloadStatus": download_status,
                "downloadInformationExpiration": download_information_expiration,
                "localFile": local_file,
                "error": error_message,
                "logReference": collected_entry["logReference"],
                "sourceEntries": collected_entry["sourceEntries"],
            }
        )

    return downloads


def _fetch_organization(
    organization_id: str,
    *,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any] | None:
    return graphql_client.execute_graphql(
        GET_ORGANIZATION_QUERY,
        {"organizationId": organization_id},
        token=token,
        config=config,
    ).get("getOrganization")


def _fetch_projects(
    organization_id: str,
    *,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> list[dict[str, Any]]:
    return (
        graphql_client.execute_graphql(
            GET_PROJECTS_QUERY,
            {"organizationId": organization_id},
            token=token,
            config=config,
        ).get("getProjects")
        or []
    )


def _fetch_project_failure_review_entries(
    project_id: str,
    *,
    page: int,
    page_size: int,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> list[dict[str, Any]]:
    return (
        graphql_client.execute_graphql(
            GET_PROJECT_FAILURE_REVIEW_ENTRIES_QUERY,
            {"projectId": project_id, "page": page, "pageSize": page_size},
            token=token,
            config=config,
        ).get("getProjectFailureReviewEntries")
        or []
    )


def _fetch_iteration_task_by_canonical_id(
    canonical_task_id: str,
    *,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any] | None:
    return graphql_client.execute_graphql(
        GET_ITERATION_TASK_BY_CANONICAL_ID_QUERY,
        {"canonicalId": canonical_task_id},
        token=token,
        config=config,
    ).get("getIterationTaskByCanonicalId")


def _find_project(
    projects: list[dict[str, Any]],
    project_id: str,
) -> dict[str, Any] | None:
    for project in projects:
        if str(project.get("id") or "") == project_id:
            return project
    return None


def _project_ids(projects: list[dict[str, Any]]) -> set[str]:
    return {str(project.get("id")) for project in projects if project.get("id")}


def _task_is_in_requested_scope(
    task: dict[str, Any],
    *,
    project_id: str | None,
    projects: list[dict[str, Any]],
) -> bool:
    task_project_id = str(task.get("projectId") or "")
    if not task_project_id:
        return False
    if project_id:
        return task_project_id == project_id
    return task_project_id in _project_ids(projects)


def _fetch_failure_review_sets(
    *,
    projects: list[dict[str, Any]],
    project_id: str | None,
    page: int,
    page_size: int,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if project_id is not None:
        project = _find_project(projects, project_id)
        entries = _fetch_project_failure_review_entries(
            project_id,
            page=page,
            page_size=page_size,
            token=token,
            config=config,
        )
        return projects, [
            {"projectId": project_id, "project": project, "entries": entries}
        ]

    failure_review_sets: list[dict[str, Any]] = []
    for project in projects:
        fetched_project_id = project.get("id")
        if not fetched_project_id:
            continue
        entries = _fetch_project_failure_review_entries(
            str(fetched_project_id),
            page=page,
            page_size=page_size,
            token=token,
            config=config,
        )
        failure_review_sets.append(
            {
                "projectId": fetched_project_id,
                "project": project,
                "entries": entries,
            }
        )
    return projects, failure_review_sets


def _flatten_failure_review_entries(
    failure_review_sets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for failure_review_set in failure_review_sets:
        entries.extend(failure_review_set.get("entries") or [])
    return entries


def _matching_failure_review_entries(
    entries: list[dict[str, Any]],
    *,
    canonical_task_id: str | None,
    failure_review_entry_id: str | None,
) -> list[dict[str, Any]]:
    if failure_review_entry_id:
        return [
            entry
            for entry in entries
            if str(entry.get("id") or "") == failure_review_entry_id
        ]

    if canonical_task_id:
        return [
            entry
            for entry in entries
            if str(entry.get("taskCanonicalId") or "").upper()
            == canonical_task_id.upper()
        ]

    return entries


def _count_by_field(entries: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(field) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _latest_failure_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entries:
        return None
    return max(
        entries,
        key=lambda entry: str(
            entry.get("failedAt")
            or entry.get("updatedAt")
            or entry.get("createdAt")
            or ""
        ),
    )


def _build_likely_cause(
    *,
    matching_entries: list[dict[str, Any]],
    task: dict[str, Any] | None,
    canonical_task_id: str | None,
) -> tuple[str, float]:
    latest_entry = _latest_failure_entry(matching_entries)
    if latest_entry is not None:
        summary = latest_entry.get("summary") or latest_entry.get("failureDetail")
        failure_kind = str(latest_entry.get("failureKind") or "failure").replace(
            "_", " "
        )
        if str(latest_entry.get("failureKind") or "").upper() == "PROTOTYPE_STARTUP":
            return (f"Prototype startup failure: {summary or failure_kind}", 0.84)
        task_run = latest_entry.get("taskRun") or {}
        phase = task_run.get("phase") or latest_entry.get("taskPhase")
        if phase:
            return (
                f"Task run failure during {phase}: {summary or failure_kind}",
                0.82,
            )
        return (f"Retained failure review entry: {summary or failure_kind}", 0.76)

    if task is not None and canonical_task_id:
        return (
            f"No retained failure entry was found in the requested page for {canonical_task_id}.",
            0.48,
        )

    return (
        "No retained failure review entries were found in the requested scope.",
        0.44,
    )


def _build_analysis(
    *,
    organization: dict[str, Any],
    projects: list[dict[str, Any]],
    failure_review_sets: list[dict[str, Any]],
    all_entries: list[dict[str, Any]],
    matching_entries: list[dict[str, Any]],
    task: dict[str, Any] | None,
    local_itera_yaml: dict[str, Any],
    retained_log_downloads: list[dict[str, Any]],
    organization_id: str,
    project_id: str | None,
    canonical_task_id: str | None,
    failure_review_entry_id: str | None,
    page: int,
    page_size: int,
    include_retained_logs: bool,
) -> dict[str, Any]:
    likely_cause, confidence = _build_likely_cause(
        matching_entries=matching_entries,
        task=task,
        canonical_task_id=canonical_task_id,
    )
    evidence = [
        f"Loaded organization {organization.get('name') or organization_id}.",
        f"Fetched {len(all_entries)} failure review entr"
        f"{'y' if len(all_entries) == 1 else 'ies'} from page {page} "
        f"with pageSize {page_size}.",
    ]
    if project_id:
        evidence.append(f"Used project-scoped failure review for project {project_id}.")
    else:
        evidence.append(
            f"Collected project-scoped failure reviews across {len(projects)} organization project(s)."
        )
    if canonical_task_id:
        evidence.append(
            f"Matched {len(matching_entries)} failure entr"
            f"{'y' if len(matching_entries) == 1 else 'ies'} for canonical task "
            f"{canonical_task_id}."
        )
    if failure_review_entry_id:
        evidence.append(f"Requested failure review entry {failure_review_entry_id}.")
    if task is not None:
        evidence.append(
            f"Task {task.get('canonicalId')} is {task.get('status')} in phase {task.get('phase')}."
        )
    if local_itera_yaml.get("exists"):
        evidence.append(
            f"Captured local itera.yaml using {local_itera_yaml.get('parseMode')} mode with token-like keys redacted."
        )
    if include_retained_logs:
        downloaded_count = len(
            [
                download
                for download in retained_log_downloads
                if download.get("downloadStatus") == "DOWNLOADED"
            ]
        )
        failed_count = len(
            [
                download
                for download in retained_log_downloads
                if download.get("downloadStatus") == "FAILED"
            ]
        )
        evidence.append(
            f"Resolved {downloaded_count} retained log download(s); {failed_count} failed."
        )
    else:
        evidence.append("Retained log downloads were disabled by input.")

    recommended_next_steps = [
        "Open any downloaded retained log JSON files referenced in retainedLogDownloads.",
        "Compare the failure entry phase, status, traceId, and failureDetail with the task run history.",
        "Verify project runtime configuration and required secrets before retrying the task or prototype startup.",
    ]
    if not matching_entries and (canonical_task_id or failure_review_entry_id):
        recommended_next_steps.insert(
            0,
            "Increase pageSize or choose a later page if the requested failure is older than the current failure review page.",
        )

    return {
        "likelyCause": likely_cause,
        "confidence": confidence,
        "evidence": evidence,
        "recommendedNextSteps": recommended_next_steps,
        "safetyNotes": [
            "Only read-only Itera GraphQL queries were used.",
            "The local itera.yaml capture redacts obvious token-like keys.",
            "Retained log files can contain sensitive diagnostics; keep generated artifacts local and private.",
        ],
        "counts": {
            "projectsQueried": len(failure_review_sets),
            "failureEntries": len(all_entries),
            "matchingFailureEntries": len(matching_entries),
            "failureKind": _count_by_field(all_entries, "failureKind"),
            "taskPhase": _count_by_field(all_entries, "taskPhase"),
        },
    }


def _viewer_from_session(session_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": session_payload.get("username"),
        "email": session_payload.get("account_email"),
    }


def _error_result(
    *,
    status: str,
    message: str,
    organization_id: str,
    project_id: str | None,
    canonical_task_id: str | None,
    failure_review_entry_id: str | None,
    viewer: dict[str, Any] | None = None,
    social_me: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "organizationId": organization_id,
        "projectId": project_id,
        "canonicalTaskId": canonical_task_id,
        "failureReviewEntryId": failure_review_entry_id,
        "message": message,
        "diagnosticsFile": None,
        "organization": None,
        "projects": None,
        "failureReview": None,
        "task": None,
        "localRepository": None,
        "retainedLogDownloads": None,
        "analysis": None,
        "viewer": viewer,
        "socialMe": social_me,
    }


def _normalize_positive_integer(value: int, *, name: str) -> int:
    if value < 1:
        raise ValueError(f"{name} must be greater than or equal to 1")
    return value


def run_download(
    organization_id: str,
    *,
    project_id: str | None = None,
    canonical_task_id: str | None = None,
    failure_review_entry_id: str | None = None,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_retained_logs: bool = True,
    local_repo_path: Path | None = None,
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    interactive: bool = True,
    output_file: Path | None = None,
) -> dict[str, Any]:
    try:
        normalized_page = _normalize_positive_integer(page, name="page")
        normalized_page_size = _normalize_positive_integer(
            page_size,
            name="pageSize",
        )
    except ValueError as exc:
        return _error_result(
            status="UNAVAILABLE",
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
        )

    request_config = config or graphql_client.GraphQLRequestConfig()
    diagnostics_path = (
        output_file or default_output_file(organization_id)
    ).expanduser()

    try:
        session_payload, social_me = ensure_authenticated_context(
            session_file=session_file,
            config=request_config,
            interactive=interactive,
        )
    except AuthRequiredError as exc:
        return _error_result(
            status="AUTH_REQUIRED",
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
        )
    except Exception as exc:
        return _error_result(
            status="LOGIN_FAILED",
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
        )

    viewer = _viewer_from_session(session_payload)

    try:
        organization = _fetch_organization(
            organization_id,
            token=session_payload["token"],
            config=request_config,
        )
        if organization is None:
            return _error_result(
                status="NOT_FOUND",
                message="No organization was found for the organizationId",
                organization_id=organization_id,
                project_id=project_id,
                canonical_task_id=canonical_task_id,
                failure_review_entry_id=failure_review_entry_id,
                viewer=viewer,
                social_me=social_me,
            )

        projects = _fetch_projects(
            organization_id,
            token=session_payload["token"],
            config=request_config,
        )
        if project_id and _find_project(projects, project_id) is None:
            return _error_result(
                status="NOT_FOUND",
                message=(
                    "No project matched projectId in the requested organization scope"
                ),
                organization_id=organization_id,
                project_id=project_id,
                canonical_task_id=canonical_task_id,
                failure_review_entry_id=failure_review_entry_id,
                viewer=viewer,
                social_me=social_me,
            )

        task = None
        if canonical_task_id:
            task = _fetch_iteration_task_by_canonical_id(
                canonical_task_id,
                token=session_payload["token"],
                config=request_config,
            )
            if task is None:
                return _error_result(
                    status="NOT_FOUND",
                    message="No iteration task was found for the canonicalTaskId",
                    organization_id=organization_id,
                    project_id=project_id,
                    canonical_task_id=canonical_task_id,
                    failure_review_entry_id=failure_review_entry_id,
                    viewer=viewer,
                    social_me=social_me,
                )
            if not _task_is_in_requested_scope(
                task,
                project_id=project_id,
                projects=projects,
            ):
                return _error_result(
                    status="NOT_FOUND",
                    message=(
                        "No iteration task matched canonicalTaskId in the requested "
                        "project or organization scope"
                    ),
                    organization_id=organization_id,
                    project_id=project_id,
                    canonical_task_id=canonical_task_id,
                    failure_review_entry_id=failure_review_entry_id,
                    viewer=viewer,
                    social_me=social_me,
                )

        projects, failure_review_sets = _fetch_failure_review_sets(
            projects=projects,
            project_id=project_id,
            page=normalized_page,
            page_size=normalized_page_size,
            token=session_payload["token"],
            config=request_config,
        )
        all_entries = _flatten_failure_review_entries(failure_review_sets)
        matching_entries = _matching_failure_review_entries(
            all_entries,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
        )
        if failure_review_entry_id and not matching_entries:
            return _error_result(
                status="NOT_FOUND",
                message=(
                    "No failure review entry matched failureReviewEntryId in the fetched page scope"
                ),
                organization_id=organization_id,
                project_id=project_id,
                canonical_task_id=canonical_task_id,
                failure_review_entry_id=failure_review_entry_id,
                viewer=viewer,
                social_me=social_me,
            )

        local_itera_yaml = inspect_local_itera_yaml(local_repo_path or Path.cwd())
        entries_for_log_download = matching_entries
        retained_log_downloads = (
            _download_retained_log_artifacts(
                entries_for_log_download,
                diagnostics_path=diagnostics_path,
                token=session_payload["token"],
                config=request_config,
                timeout_seconds=30.0,
            )
            if include_retained_logs
            else []
        )
        analysis = _build_analysis(
            organization=organization,
            projects=projects,
            failure_review_sets=failure_review_sets,
            all_entries=all_entries,
            matching_entries=matching_entries,
            task=task,
            local_itera_yaml=local_itera_yaml,
            retained_log_downloads=retained_log_downloads,
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
            page=normalized_page,
            page_size=normalized_page_size,
            include_retained_logs=include_retained_logs,
        )
        result = {
            "status": "SUCCESS",
            "organizationId": organization_id,
            "projectId": project_id,
            "canonicalTaskId": canonical_task_id,
            "failureReviewEntryId": failure_review_entry_id,
            "downloadedAt": auth_refresh.utc_now(),
            "message": "Downloaded Itera diagnostics snapshot",
            "diagnosticsFile": str(diagnostics_path),
            "inputs": {
                "organizationId": organization_id,
                "projectId": project_id,
                "canonicalTaskId": canonical_task_id,
                "failureReviewEntryId": failure_review_entry_id,
                "page": normalized_page,
                "pageSize": normalized_page_size,
                "includeRetainedLogs": include_retained_logs,
                "localRepoPath": str((local_repo_path or Path.cwd()).expanduser()),
            },
            "viewer": viewer,
            "socialMe": social_me,
            "organization": organization,
            "projects": projects,
            "failureReview": {
                "scope": "PROJECT" if project_id else "ORGANIZATION_PROJECTS",
                "page": normalized_page,
                "pageSize": normalized_page_size,
                "projectSets": failure_review_sets,
                "entries": all_entries,
                "matchingEntries": matching_entries,
            },
            "task": task,
            "localRepository": {
                "path": str((local_repo_path or Path.cwd()).expanduser()),
                "iteraYaml": local_itera_yaml,
            },
            "retainedLogDownloads": retained_log_downloads,
            "analysis": analysis,
        }
        write_json_artifact(diagnostics_path, result)
        return result
    except PermissionDeniedError as exc:
        return _error_result(
            status="FORBIDDEN",
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
            viewer=viewer,
            social_me=social_me,
        )
    except graphql_client.GraphQLError as exc:
        if _is_forbidden_graphql_error(exc):
            status = "FORBIDDEN"
        elif _is_not_found_graphql_error(exc):
            status = "NOT_FOUND"
        else:
            status = "UNAVAILABLE"
        return _error_result(
            status=status,
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
            viewer=viewer,
            social_me=social_me,
        )
    except Exception as exc:
        return _error_result(
            status="UNAVAILABLE",
            message=str(exc),
            organization_id=organization_id,
            project_id=project_id,
            canonical_task_id=canonical_task_id,
            failure_review_entry_id=failure_review_entry_id,
            viewer=viewer,
            social_me=social_me,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download read-only Itera organization/project diagnostics."
    )
    parser.add_argument(
        "--organization-id",
        required=True,
        help="Itera organization identifier.",
    )
    parser.add_argument("--project-id", help="Optional project ID to inspect.")
    parser.add_argument(
        "--canonical-task-id",
        help="Optional canonical Itera task ID such as FRONTPAGE-42.",
    )
    parser.add_argument(
        "--failure-review-entry-id",
        help="Optional failure review entry ID to focus on.",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=DEFAULT_PAGE,
        help="Failure review page to fetch. Defaults to 1.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Failure review page size. Defaults to 10.",
    )
    parser.add_argument(
        "--include-retained-logs",
        dest="include_retained_logs",
        action="store_true",
        default=True,
        help="Resolve and download retained log artifacts. Enabled by default.",
    )
    parser.add_argument(
        "--no-retained-logs",
        dest="include_retained_logs",
        action="store_false",
        help="Skip retained log downloads.",
    )
    parser.add_argument(
        "--local-repo-path",
        default=".",
        help="Local repository path to inspect for itera.yaml. Defaults to current directory.",
    )
    parser.add_argument(
        "--session-file",
        default=str(auth_refresh.DEFAULT_SESSION_FILE),
        help="Path to the stored auth JSON.",
    )
    parser.add_argument(
        "--graphql-url",
        default=graphql_client.DEFAULT_GRAPHQL_URL,
        help="Itera GraphQL URL. Defaults to https://api.iteradev.ai/graphql/.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional explicit JSON artifact path.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt for login if a valid stored session is unavailable.",
    )
    args = parser.parse_args()

    config = graphql_client.GraphQLRequestConfig(graphql_url=args.graphql_url)
    result = run_download(
        args.organization_id,
        project_id=args.project_id,
        canonical_task_id=args.canonical_task_id,
        failure_review_entry_id=args.failure_review_entry_id,
        page=args.page,
        page_size=args.page_size,
        include_retained_logs=args.include_retained_logs,
        local_repo_path=Path(args.local_repo_path).expanduser(),
        session_file=auth_refresh.expand_session_file(args.session_file),
        config=config,
        interactive=not args.no_prompt,
        output_file=Path(args.output_file).expanduser() if args.output_file else None,
    )
    print(json.dumps(result, indent=2))
    return (
        0
        if result["status"]
        in {"SUCCESS", "AUTH_REQUIRED", "NOT_FOUND", "FORBIDDEN", "UNAVAILABLE"}
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "UNAVAILABLE", "message": str(exc)}, indent=2))
        raise SystemExit(1)
