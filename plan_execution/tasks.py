#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from . import auth as auth_login
from . import auth as auth_refresh
from . import artifacts
from . import graphql_client

GET_ITERATION_TASK_BY_CANONICAL_ID_QUERY = """
query GetIterationTaskByCanonicalId($canonicalId: IterationTaskCanonicalID!) {
  getIterationTaskByCanonicalId(canonicalId: $canonicalId) {
    id
    canonicalId
    owner {
      username
    }
    projectId
    initialIntent
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
    repositorySnapshots {
      id
      position
      commitSha
      repositoryConfiguration {
        provider
        owner
        repoName
        mainBranchName
        basePath
        stableRepositoryId
        providerMetadata
      }
    }
    freeformInputs {
      id
      phase
      text
      createdAt
    }
    taskRuns {
      id
      taskId
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
      prototypeHandoffArtifact {
        id
        kind
        prototypeIterationId
        checkpointId
        previousCheckpointId
        replacedTaskRunId
        conversationDelta {
          id
          role
          content
          createdAt
        }
        codeChangeDelta {
          id
          createdAt
          changeType
          commit {
            sha
            parentSha
            message
            committedAt
            author
            authorHandle
          }
        }
      }
      questions {
        id
        taskRunId
        category
        target
        question
        suggestedAnswers
        answer
        answeredByUserId
        answeredAt
      }
      specifications {
        id
        taskRunId
        questionId
        category
        type
        typeLabel
        customTypeLabel
        title
        deltaExplanation
        before
        after
        target
        rule
        status
        answer
        answeredByUserId
        answeredAt
        reviewFeedback
        reviewedByUserId
        reviewedAt
        originalProposalId
        inferredFromPrecedent
        prototypeReference {
          prototypeHandoffArtifactId
          prototypeIterationId
          checkpointId
          prototypeCodeMedia {
            id
            type
            status
          }
          references {
            source
            sourceId
          }
        }
      }
    }
    questions {
      id
      taskRunId
      category
      target
      question
      suggestedAnswers
      answer
      answeredByUserId
      answeredAt
    }
    specifications {
      id
      taskRunId
      questionId
      category
      type
      typeLabel
      customTypeLabel
      title
      deltaExplanation
      before
      after
      target
      rule
      status
      answer
      answeredByUserId
      answeredAt
      reviewFeedback
      reviewedByUserId
      reviewedAt
      originalProposalId
      inferredFromPrecedent
      prototypeReference {
        prototypeHandoffArtifactId
        prototypeIterationId
        checkpointId
        prototypeCodeMedia {
          id
          type
          status
        }
        references {
          source
          sourceId
        }
      }
    }
    currentHumanBlocker {
      kind
      phase
      taskRunId
      questionIds
      specificationIds
    }
    jiraWorkItemLink {
      workItemKey
      summary
      statusName
      browseUrl
    }
    linkedPrototypeIteration {
      id
      status
      active
      activeAt
      lastSubmittedCheckpoint {
        id
        createdAt
        latestMessageId
        latestCodeChangeEventId
      }
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
        goal
        repositoryTarget {
          provider
          owner
          repoName
          mainBranchName
          basePath
          stableRepositoryId
        }
        deploymentTargetLabel
        allowedPathPrefixes
        mainTouchPoints
        modelsToCreate
        newApiContracts
        specifications {
          id
          sourceTaskSpecificationId
          type
          typeLabel
          customTypeLabel
          title
          deltaExplanation
          before
          after
          target
          rule
          inferredFromPrecedent
          prototypeReference {
            prototypeHandoffArtifactId
            prototypeIterationId
            checkpointId
            prototypeCodeMedia {
              id
              type
              status
            }
            references {
              source
              sourceId
            }
          }
        }
        state
        execution {
          status
          branchName
          manualEvidenceOverride
          claimedByUser {
            username
          }
          providerPullRequestNumber
          providerPullRequestUrl
        }
      }
      pullRequestDependencies {
        id
        pullRequestId
        dependsOnPullRequestId
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
    Path.home() / ".codex" / "artifacts" / "plan_execution" / "specifications"
)
PROTOTYPE_CODE_MEDIA_DIRNAME = "prototype_code_media"
MEDIA_FILE_SUFFIX_BY_TYPE = {
    "PATCH": ".patch",
}
UI_SPECIFICATION_TYPE_KEYS = {"USER_UI", "USER_EXPERIENCE"}
UI_TEXT_SIGNAL_KEYWORDS = (
    "ui",
    "user ui",
    "user interface",
    "ux",
    "user experience",
    "frontend",
    "front end",
    "pixel perfect",
    "visual",
    "layout",
    "spacing",
    "typography",
    "responsive",
    "interaction",
)


class AuthRequiredError(RuntimeError):
    pass


def _build_remote_repo_url(repository_target: dict[str, Any] | None) -> str | None:
    if not repository_target:
        return None
    provider = str(repository_target.get("provider", "")).upper()
    owner = repository_target.get("owner")
    repo_name = repository_target.get("repoName")
    if not owner or not repo_name:
        return None
    if provider == "GITHUB":
        return f"https://github.com/{owner}/{repo_name}"
    if provider == "GITLAB":
        return f"https://gitlab.com/{owner}/{repo_name}"
    return None


def _count_by_field(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(field) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _task_specs_by_id(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        specification["id"]: specification
        for specification in task.get("specifications") or []
        if specification.get("id")
    }


def _normalize_signal_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.lower().replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


def _has_ui_text_signal(values: list[Any]) -> bool:
    for value in values:
        normalized = _normalize_signal_text(value)
        if not normalized:
            continue
        padded = f" {normalized} "
        for keyword in UI_TEXT_SIGNAL_KEYWORDS:
            if f" {keyword} " in padded:
                return True
    return False


def _collect_prototype_patch_details(
    specifications: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    media_ids: set[str] = set()
    local_files: set[str] = set()
    download_errors: set[str] = set()

    for specification in specifications:
        prototype_reference = specification.get("prototypeReference") or {}
        prototype_code_media = prototype_reference.get("prototypeCodeMedia") or {}
        if str(prototype_code_media.get("type") or "").upper() != "PATCH":
            continue
        media_id = prototype_code_media.get("id")
        if media_id:
            media_ids.add(str(media_id))
        local_file = prototype_reference.get("prototypeCodeMediaLocalFile")
        if local_file:
            local_files.add(str(local_file))
        download_error = prototype_reference.get("prototypeCodeMediaDownloadError")
        if download_error:
            download_errors.add(str(download_error))

    return sorted(media_ids), sorted(local_files), sorted(download_errors)


def _collect_ui_scope_signals(
    specifications: list[dict[str, Any]],
    *,
    context_values: list[Any] | None = None,
) -> list[str]:
    signals: list[str] = []
    specification_types = {
        str(specification.get("type") or "").upper() for specification in specifications
    }
    matched_ui_types = UI_SPECIFICATION_TYPE_KEYS & specification_types
    if "USER_UI" in matched_ui_types:
        signals.append("SPECIFICATION_TYPE_USER_UI")
    if "USER_EXPERIENCE" in matched_ui_types:
        signals.append("SPECIFICATION_TYPE_USER_EXPERIENCE")

    specification_text_values: list[Any] = []
    for specification in specifications:
        specification_text_values.extend(
            [
                specification.get("typeLabel"),
                specification.get("customTypeLabel"),
                specification.get("title"),
                specification.get("deltaExplanation"),
                specification.get("before"),
                specification.get("after"),
                specification.get("target"),
                specification.get("rule"),
            ]
        )
    if _has_ui_text_signal(specification_text_values):
        signals.append("SPECIFICATION_TEXT_UI_KEYWORDS")
    if context_values and _has_ui_text_signal(context_values):
        signals.append("CONTEXT_UI_KEYWORDS")
    return signals


def _build_prototype_patch_instruction_summary(
    *,
    has_local_files: bool,
    is_ui_or_ux_scope: bool,
) -> str:
    if not has_local_files:
        prefix = "Mandatory: resolve the prototype patch download failure before implementation."
    else:
        prefix = "Mandatory: open the downloaded prototype patch before writing code."

    if is_ui_or_ux_scope:
        return (
            f"{prefix} This work has UI/UX signals, so treat written specs and the "
            "non-canvas prototype app changes as the visual source of truth and match "
            "product UI pixel-perfect for layout, spacing, sizing, typography, states, "
            "responsive behavior, and relevant interactions. Never build a Canvas page "
            "or `/itera/canvas` route from the prototype; use prototype canvas files only "
            "to understand component states and variants. Do not copy logic, data flow, "
            "APIs, or backend behavior from the prototype unless the written "
            "specifications explicitly require that work."
        )

    return (
        f"{prefix} Treat it as required implementation context. If this work includes UI "
        "or UX scope, use written specs and non-canvas prototype app changes as the "
        "visual source of truth for pixel-perfect implementation. Never build a Canvas "
        "page or `/itera/canvas` route from the prototype; use prototype canvas files "
        "only to understand component states and variants. Do not copy prototype logic, "
        "APIs, or backend behavior unless the written specifications explicitly require "
        "that work."
    )


def _build_specification_prototype_guidance(
    *,
    scope: str,
    specifications: list[dict[str, Any]],
    scope_metadata: dict[str, Any] | None = None,
    context_values: list[Any] | None = None,
) -> dict[str, Any] | None:
    prototype_patch_media_ids, prototype_patch_local_files, download_errors = (
        _collect_prototype_patch_details(specifications)
    )
    if not prototype_patch_media_ids:
        return None

    ui_scope_signals = _collect_ui_scope_signals(
        specifications,
        context_values=context_values,
    )
    guidance = {
        "scope": scope,
        "requiresPrototypePatchReview": True,
        "requiresPixelPerfectUiImplementation": bool(ui_scope_signals),
        "uiScopeSignals": ui_scope_signals,
        "prototypePatchMediaIds": prototype_patch_media_ids,
        "prototypePatchLocalFiles": prototype_patch_local_files,
        "prototypePatchDownloadErrors": download_errors,
        "instructionSummary": _build_prototype_patch_instruction_summary(
            has_local_files=bool(prototype_patch_local_files),
            is_ui_or_ux_scope=bool(ui_scope_signals),
        ),
        "requirements": [
            "Do not start implementation until every referenced prototype patch has been downloaded or the download failure has been resolved.",
            "Open the downloaded prototype patch before editing code and keep it visible while implementing the affected slice.",
            "When the work includes UI or UX scope, match the non-canvas prototype product UI pixel-perfect for layout, spacing, sizing, typography, states, responsive behavior, and relevant interactions.",
            "Never build a Canvas page or `/itera/canvas` route in the target app from a prototype patch; prototype canvas code is not part of the production deliverable.",
            "Use prototype canvas files, fixtures, and manifests only to understand component states and variants.",
            "Treat written specifications and non-canvas prototype app changes as the source of truth; do not let canvas-only fixtures, mocks, routes, manifests, or helpers define product behavior or scope.",
            "Use the prototype only for UI/UX guidance unless the written specs explicitly say otherwise; do not inherit its business logic, data flow, API contracts, or backend behavior.",
        ],
    }
    if scope_metadata:
        guidance.update(scope_metadata)
    return guidance


def _enrich_planned_pull_request(
    planned_pull_request: dict[str, Any],
    *,
    task_specifications_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(planned_pull_request)
    repository_target = planned_pull_request.get("repositoryTarget") or {}
    enriched["remoteRepositoryUrl"] = _build_remote_repo_url(repository_target)

    enriched_specifications = []
    for specification in planned_pull_request.get("specifications") or []:
        enriched_specification = dict(specification)
        source_task_specification_id = specification.get("sourceTaskSpecificationId")
        if source_task_specification_id:
            enriched_specification["sourceTaskSpecification"] = (
                task_specifications_by_id.get(source_task_specification_id)
            )
        enriched_specifications.append(enriched_specification)
    enriched["specifications"] = enriched_specifications
    enriched["prototypeImplementationGuidance"] = (
        _build_specification_prototype_guidance(
            scope="PLANNED_PULL_REQUEST",
            specifications=enriched_specifications,
            scope_metadata={
                "plannedPullRequestId": planned_pull_request.get("id"),
                "plannedPullRequestPosition": planned_pull_request.get("position"),
                "plannedPullRequestTitle": planned_pull_request.get("title"),
            },
            context_values=[
                planned_pull_request.get("title"),
                planned_pull_request.get("goal"),
                planned_pull_request.get("deploymentTargetLabel"),
                *(planned_pull_request.get("allowedPathPrefixes") or []),
                *(planned_pull_request.get("mainTouchPoints") or []),
            ],
        )
    )
    return enriched


def _latest_timestamp(task_run: dict[str, Any]) -> str:
    return (
        task_run.get("completedAt")
        or task_run.get("updatedAt")
        or task_run.get("processingStartedAt")
        or task_run.get("enqueuedAt")
        or task_run.get("createdAt")
        or ""
    )


def _build_latest_task_runs_by_phase(
    task_runs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest_by_phase: dict[str, dict[str, Any]] = {}
    for task_run in task_runs:
        phase = task_run.get("phase")
        if not phase:
            continue
        current = latest_by_phase.get(phase)
        if current is None or _latest_timestamp(task_run) >= _latest_timestamp(current):
            latest_by_phase[phase] = task_run
    return latest_by_phase


def _build_repository_hints(
    task: dict[str, Any],
    enriched_pull_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    repository_hints: list[dict[str, Any]] = []

    for snapshot in task.get("repositorySnapshots") or []:
        repository_configuration = snapshot.get("repositoryConfiguration") or {}
        repository_hints.append(
            {
                "source": "TASK_REPOSITORY_SNAPSHOT",
                "position": snapshot.get("position"),
                "commitSha": snapshot.get("commitSha"),
                "repositoryTarget": repository_configuration,
                "remoteRepositoryUrl": _build_remote_repo_url(repository_configuration),
            }
        )

    for planned_pull_request in enriched_pull_requests:
        repository_hints.append(
            {
                "source": "PLANNED_PULL_REQUEST",
                "plannedPullRequestId": planned_pull_request.get("id"),
                "plannedPullRequestPosition": planned_pull_request.get("position"),
                "deploymentTargetLabel": planned_pull_request.get(
                    "deploymentTargetLabel"
                ),
                "repositoryTarget": planned_pull_request.get("repositoryTarget") or {},
                "remoteRepositoryUrl": planned_pull_request.get("remoteRepositoryUrl"),
            }
        )

    return repository_hints


def _build_build_context(task: dict[str, Any]) -> dict[str, Any]:
    task_specifications = task.get("specifications") or []
    questions = task.get("questions") or []
    task_specifications_by_id = _task_specs_by_id(task)
    current_plan = task.get("currentPlan") or {}
    enriched_pull_requests = [
        _enrich_planned_pull_request(
            planned_pull_request,
            task_specifications_by_id=task_specifications_by_id,
        )
        for planned_pull_request in current_plan.get("pullRequests") or []
    ]
    task_level_prototype_guidance = _build_specification_prototype_guidance(
        scope="TASK_SPECIFICATIONS",
        specifications=task_specifications,
        scope_metadata={
            "canonicalTaskId": task.get("canonicalId"),
            "taskName": task.get("name"),
        },
        context_values=[
            task.get("name"),
            task.get("goalDescription"),
            task.get("successCriteria"),
            task.get("contextProblem"),
        ],
    )
    planned_pull_request_prototype_guidance = [
        planned_pull_request["prototypeImplementationGuidance"]
        for planned_pull_request in enriched_pull_requests
        if planned_pull_request.get("prototypeImplementationGuidance") is not None
    ]

    return {
        "taskSummary": {
            "id": task.get("id"),
            "canonicalId": task.get("canonicalId"),
            "name": task.get("name"),
            "phase": task.get("phase"),
            "status": task.get("status"),
            "goalDescription": task.get("goalDescription"),
            "successCriteria": task.get("successCriteria"),
            "outOfScope": task.get("outOfScope"),
            "contextProblem": task.get("contextProblem"),
            "ownerUsername": (task.get("owner") or {}).get("username"),
            "jiraWorkItemLink": task.get("jiraWorkItemLink"),
        },
        "repositoryHints": _build_repository_hints(task, enriched_pull_requests),
        "questionSummary": {
            "byCategory": _count_by_field(questions, "category"),
            "openQuestions": [
                question
                for question in questions
                if not (question.get("answer") or "").strip()
            ],
            "answeredQuestions": [
                question
                for question in questions
                if (question.get("answer") or "").strip()
            ],
        },
        "specificationSummary": {
            "byStatus": _count_by_field(task_specifications, "status"),
            "acceptedSpecifications": [
                specification
                for specification in task_specifications
                if specification.get("status") == "ACCEPTED"
            ],
            "nonAcceptedSpecifications": [
                specification
                for specification in task_specifications
                if specification.get("status") != "ACCEPTED"
            ],
        },
        "latestTaskRunsByPhase": _build_latest_task_runs_by_phase(
            task.get("taskRuns") or []
        ),
        "currentHumanBlocker": task.get("currentHumanBlocker"),
        "prototypeImplementationGuidance": {
            "taskSpecifications": task_level_prototype_guidance,
            "plannedPullRequests": planned_pull_request_prototype_guidance,
        },
        "currentPlan": {
            "id": current_plan.get("id"),
            "taskRunId": current_plan.get("taskRunId"),
            "createdAt": current_plan.get("createdAt"),
            "updatedAt": current_plan.get("updatedAt"),
            "pullRequests": enriched_pull_requests,
            "pullRequestDependencies": current_plan.get("pullRequestDependencies")
            or [],
        },
    }


def default_output_file(canonical_task_id: str) -> Path:
    return DEFAULT_OUTPUT_ROOT / "tasks" / f"{canonical_task_id.strip().lower()}.json"


def write_json_artifact(output_file: Path, payload: dict[str, Any]) -> None:
    artifacts.write_json_artifact(
        output_file, payload, protect_file=auth_refresh.protect_local_file
    )


def write_binary_artifact(output_file: Path, payload: bytes) -> None:
    artifacts.write_binary_artifact(
        output_file, payload, protect_file=auth_refresh.protect_local_file
    )


def _prototype_code_media_output_root(snapshot_path: Path) -> Path:
    return snapshot_path.parent / snapshot_path.stem / PROTOTYPE_CODE_MEDIA_DIRNAME


def _media_file_suffix(media_type: str | None) -> str:
    normalized_media_type = str(media_type or "").upper()
    return MEDIA_FILE_SUFFIX_BY_TYPE.get(normalized_media_type, ".bin")


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
            "Prototype code media URL is not directly readable and is not a supported S3 URL"
        )

    try:
        import boto3
    except Exception as exc:  # pragma: no cover - dependency/environment failure
        raise RuntimeError(
            "Prototype code media URL requires private access and boto3 is unavailable for S3 fallback"
        ) from exc

    bucket, key = bucket_and_key
    s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


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


def _register_prototype_code_media_reference(
    collected_media: dict[str, dict[str, Any]],
    *,
    prototype_reference: dict[str, Any],
    source_location: dict[str, Any],
) -> None:
    prototype_code_media = prototype_reference.get("prototypeCodeMedia")
    if not isinstance(prototype_code_media, dict):
        return

    media_id = prototype_code_media.get("id")
    if not media_id:
        return

    collected_entry = collected_media.setdefault(
        media_id,
        {
            "media": prototype_code_media,
            "prototypeReferences": [],
            "sourceLocations": [],
        },
    )
    collected_entry["prototypeReferences"].append(prototype_reference)
    collected_entry["sourceLocations"].append(source_location)


def _collect_prototype_code_media(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    collected_media: dict[str, dict[str, Any]] = {}

    for specification in task.get("specifications") or []:
        prototype_reference = specification.get("prototypeReference")
        if isinstance(prototype_reference, dict):
            _register_prototype_code_media_reference(
                collected_media,
                prototype_reference=prototype_reference,
                source_location={
                    "kind": "TASK_SPECIFICATION",
                    "specificationId": specification.get("id"),
                    "title": specification.get("title"),
                    "target": specification.get("target"),
                },
            )

    for task_run in task.get("taskRuns") or []:
        for specification in task_run.get("specifications") or []:
            prototype_reference = specification.get("prototypeReference")
            if isinstance(prototype_reference, dict):
                _register_prototype_code_media_reference(
                    collected_media,
                    prototype_reference=prototype_reference,
                    source_location={
                        "kind": "TASK_RUN_SPECIFICATION",
                        "taskRunId": task_run.get("id"),
                        "phase": task_run.get("phase"),
                        "specificationId": specification.get("id"),
                        "title": specification.get("title"),
                        "target": specification.get("target"),
                    },
                )

    current_plan = task.get("currentPlan") or {}
    for planned_pull_request in current_plan.get("pullRequests") or []:
        for specification in planned_pull_request.get("specifications") or []:
            prototype_reference = specification.get("prototypeReference")
            if isinstance(prototype_reference, dict):
                _register_prototype_code_media_reference(
                    collected_media,
                    prototype_reference=prototype_reference,
                    source_location={
                        "kind": "PLANNED_PULL_REQUEST_SPECIFICATION",
                        "plannedPullRequestId": planned_pull_request.get("id"),
                        "plannedPullRequestPosition": planned_pull_request.get(
                            "position"
                        ),
                        "plannedPullRequestTitle": planned_pull_request.get("title"),
                        "specificationId": specification.get("id"),
                        "title": specification.get("title"),
                        "target": specification.get("target"),
                    },
                )

    return collected_media


def _download_prototype_code_media_artifacts(
    task: dict[str, Any],
    *,
    snapshot_path: Path,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    collected_media = _collect_prototype_code_media(task)
    if not collected_media:
        return []

    output_root = _prototype_code_media_output_root(snapshot_path)
    downloads: list[dict[str, Any]] = []

    for media_id, collected_entry in sorted(collected_media.items()):
        media = collected_entry["media"]
        local_file: str | None = None
        error_message: str | None = None
        download_status = "SKIPPED"
        download_information_expiration: str | None = None

        if str(media.get("status") or "").upper() == "COMPLETED":
            media_file = (
                output_root / f"{media_id}{_media_file_suffix(media.get('type'))}"
            )
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
            except Exception as exc:
                error_message = str(exc)
                download_status = "FAILED"

        for prototype_reference in collected_entry["prototypeReferences"]:
            if local_file is not None:
                prototype_reference["prototypeCodeMediaLocalFile"] = local_file
            if error_message is not None:
                prototype_reference["prototypeCodeMediaDownloadError"] = error_message

        downloads.append(
            {
                "mediaId": media_id,
                "mediaType": media.get("type"),
                "mediaStatus": media.get("status"),
                "downloadStatus": download_status,
                "downloadInformationExpiration": download_information_expiration,
                "localFile": local_file,
                "error": error_message,
                "mustReviewBeforeImplementation": True,
                "usageSummary": (
                    "Mandatory: inspect this prototype patch before implementation. If the "
                    "associated work includes UI or UX scope, use written specs and "
                    "non-canvas prototype app changes as the pixel-perfect visual "
                    "reference. Never build a Canvas page or `/itera/canvas` route from "
                    "the prototype; canvas files are only a reference for component "
                    "states and variants. Do not copy logic or backend behavior from it."
                ),
                "sourceLocations": collected_entry["sourceLocations"],
            }
        )

    return downloads


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


def run_download(
    canonical_task_id: str,
    *,
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    interactive: bool = True,
    output_file: Path | None = None,
) -> dict[str, Any]:
    request_config = config or graphql_client.GraphQLRequestConfig()

    try:
        session_payload, social_me = ensure_authenticated_context(
            session_file=session_file,
            config=request_config,
            interactive=interactive,
        )
    except AuthRequiredError as exc:
        return {
            "status": "AUTH_REQUIRED",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "snapshotFile": None,
            "task": None,
            "buildContext": None,
        }
    except Exception as exc:
        return {
            "status": "LOGIN_FAILED",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "snapshotFile": None,
            "task": None,
            "buildContext": None,
        }

    try:
        task = graphql_client.execute_graphql(
            GET_ITERATION_TASK_BY_CANONICAL_ID_QUERY,
            {"canonicalId": canonical_task_id},
            token=session_payload["token"],
            config=request_config,
        ).get("getIterationTaskByCanonicalId")
    except graphql_client.GraphQLError as exc:
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "snapshotFile": None,
            "task": None,
            "buildContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
        }

    if task is None:
        return {
            "status": "NOT_FOUND",
            "canonicalTaskId": canonical_task_id,
            "message": "No iteration task was found for the canonical task ID",
            "snapshotFile": None,
            "task": None,
            "buildContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
        }

    snapshot_path = (output_file or default_output_file(canonical_task_id)).expanduser()
    prototype_code_media_downloads = _download_prototype_code_media_artifacts(
        task,
        snapshot_path=snapshot_path,
        token=session_payload["token"],
        config=request_config,
        timeout_seconds=30.0,
    )
    build_context = _build_build_context(task)
    result = {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "downloadedAt": auth_refresh.utc_now(),
        "message": (
            "Downloaded full iteration task specification snapshot and prototype code media artifacts"
            if prototype_code_media_downloads
            else "Downloaded full iteration task specification snapshot"
        ),
        "snapshotFile": str(snapshot_path),
        "task": task,
        "buildContext": build_context,
        "prototypeImplementationGuidance": build_context[
            "prototypeImplementationGuidance"
        ],
        "prototypeCodeMediaDownloads": prototype_code_media_downloads,
        "viewer": {
            "username": session_payload["username"],
            "email": session_payload["account_email"],
        },
        "socialMe": social_me,
    }
    write_json_artifact(snapshot_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download the full Itera task specification for a canonical task ID."
    )
    parser.add_argument(
        "--canonical-task-id",
        required=True,
        help="Canonical Itera task ID such as FRONTPAGE-42.",
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
        args.canonical_task_id,
        session_file=auth_refresh.expand_session_file(args.session_file),
        config=config,
        interactive=not args.no_prompt,
        output_file=Path(args.output_file).expanduser() if args.output_file else None,
    )
    print(json.dumps(result, indent=2))
    return (
        0
        if result["status"] in {"SUCCESS", "NOT_FOUND", "UNAVAILABLE", "AUTH_REQUIRED"}
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "UNAVAILABLE", "message": str(exc)}, indent=2))
        raise SystemExit(1)
