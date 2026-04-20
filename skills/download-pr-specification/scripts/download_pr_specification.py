#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import auth_login
import auth_refresh
import graphql_client

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
            f"{prefix} This work has UI/UX signals, so treat the prototype as the visual "
            "source of truth and match it pixel-perfect for layout, spacing, sizing, "
            "typography, states, responsive behavior, and relevant interactions. Do not "
            "copy logic, data flow, APIs, or backend behavior from the prototype unless "
            "the written specifications explicitly require that work."
        )

    return (
        f"{prefix} Treat it as required implementation context. If this work includes UI "
        "or UX scope, use the prototype as the visual source of truth for pixel-perfect "
        "implementation and do not copy prototype logic, APIs, or backend behavior unless "
        "the written specifications explicitly require that work."
    )


def _selected_pull_request_prototype_specifications(
    selected_pull_request: dict[str, Any],
) -> list[dict[str, Any]]:
    specifications: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_specification(specification: dict[str, Any] | None) -> None:
        if not isinstance(specification, dict):
            return
        key = str(specification.get("id") or id(specification))
        if key in seen_ids:
            return
        seen_ids.add(key)
        specifications.append(specification)

    for specification in selected_pull_request.get("specifications") or []:
        add_specification(specification)
        add_specification(specification.get("sourceTaskSpecification"))

    return specifications


def _build_selected_pull_request_prototype_guidance(
    selected_pull_request: dict[str, Any],
) -> dict[str, Any] | None:
    relevant_specifications = _selected_pull_request_prototype_specifications(
        selected_pull_request
    )
    prototype_patch_media_ids, prototype_patch_local_files, download_errors = (
        _collect_prototype_patch_details(relevant_specifications)
    )
    if not prototype_patch_media_ids:
        return None

    ui_scope_signals = _collect_ui_scope_signals(
        relevant_specifications,
        context_values=[
            selected_pull_request.get("title"),
            selected_pull_request.get("goal"),
            selected_pull_request.get("deploymentTargetLabel"),
            *(selected_pull_request.get("allowedPathPrefixes") or []),
            *(selected_pull_request.get("mainTouchPoints") or []),
        ],
    )
    return {
        "scope": "SELECTED_PLANNED_PULL_REQUEST",
        "plannedPullRequestId": selected_pull_request.get("id"),
        "plannedPullRequestPosition": selected_pull_request.get("position"),
        "plannedPullRequestTitle": selected_pull_request.get("title"),
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
            "When the work includes UI or UX scope, copy the prototype pixel-perfect for layout, spacing, sizing, typography, states, responsive behavior, and relevant interactions.",
            "Use the prototype only for UI/UX guidance unless the written specs explicitly say otherwise; do not inherit its business logic, data flow, API contracts, or backend behavior.",
        ],
    }


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
        _build_selected_pull_request_prototype_guidance(enriched)
    )
    return enriched


def _select_planned_pull_request(
    pull_requests: list[dict[str, Any]],
    *,
    planned_pull_request_id: str | None,
    pull_request_position: int | None,
) -> dict[str, Any] | None:
    if planned_pull_request_id:
        for planned_pull_request in pull_requests:
            if planned_pull_request.get("id") == planned_pull_request_id:
                return planned_pull_request

    if pull_request_position is not None:
        expected_position = pull_request_position - 1
        for planned_pull_request in pull_requests:
            if planned_pull_request.get("position") == expected_position:
                return planned_pull_request

    return None


def _brief_pull_request(planned_pull_request: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": planned_pull_request.get("id"),
        "position": planned_pull_request.get("position"),
        "title": planned_pull_request.get("title"),
        "goal": planned_pull_request.get("goal"),
        "state": planned_pull_request.get("state"),
        "deploymentTargetLabel": planned_pull_request.get("deploymentTargetLabel"),
        "allowedPathPrefixes": planned_pull_request.get("allowedPathPrefixes"),
        "mainTouchPoints": planned_pull_request.get("mainTouchPoints"),
        "modelsToCreate": planned_pull_request.get("modelsToCreate"),
        "newApiContracts": planned_pull_request.get("newApiContracts"),
        "repositoryTarget": planned_pull_request.get("repositoryTarget") or {},
        "remoteRepositoryUrl": planned_pull_request.get("remoteRepositoryUrl"),
        "execution": planned_pull_request.get("execution"),
        "prototypeImplementationGuidance": planned_pull_request.get(
            "prototypeImplementationGuidance"
        ),
    }


def _build_dependency_context(
    current_plan: dict[str, Any],
    *,
    selected_pull_request: dict[str, Any],
    enriched_pull_requests_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected_pull_request_id = selected_pull_request["id"]
    dependencies = current_plan.get("pullRequestDependencies") or []
    depends_on_edges = [
        dependency
        for dependency in dependencies
        if dependency.get("pullRequestId") == selected_pull_request_id
    ]
    blocked_by_edges = [
        dependency
        for dependency in dependencies
        if dependency.get("dependsOnPullRequestId") == selected_pull_request_id
    ]

    depends_on_pull_requests = []
    for dependency in depends_on_edges:
        upstream = enriched_pull_requests_by_id.get(
            dependency.get("dependsOnPullRequestId")
        )
        if upstream is not None:
            depends_on_pull_requests.append(_brief_pull_request(upstream))

    blocked_pull_requests = []
    for dependency in blocked_by_edges:
        downstream = enriched_pull_requests_by_id.get(dependency.get("pullRequestId"))
        if downstream is not None:
            blocked_pull_requests.append(_brief_pull_request(downstream))

    return {
        "dependsOn": depends_on_pull_requests,
        "blocks": blocked_pull_requests,
        "edgesForSelectedPullRequest": {
            "dependsOn": depends_on_edges,
            "blocks": blocked_by_edges,
        },
        "allDependencies": dependencies,
    }


def _build_repository_hints(
    task: dict[str, Any],
    selected_pull_request: dict[str, Any],
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

    repository_hints.append(
        {
            "source": "SELECTED_PLANNED_PULL_REQUEST",
            "plannedPullRequestId": selected_pull_request.get("id"),
            "plannedPullRequestPosition": selected_pull_request.get("position"),
            "deploymentTargetLabel": selected_pull_request.get("deploymentTargetLabel"),
            "repositoryTarget": selected_pull_request.get("repositoryTarget") or {},
            "remoteRepositoryUrl": selected_pull_request.get("remoteRepositoryUrl"),
        }
    )
    return repository_hints


def _sanitize_filename_part(value: str) -> str:
    sanitized = []
    for character in value:
        if character.isalnum() or character in {"-", "_"}:
            sanitized.append(character)
        else:
            sanitized.append("-")
    return "".join(sanitized).strip("-") or "planned-pull-request"


def default_output_file(
    canonical_task_id: str,
    *,
    selected_pull_request: dict[str, Any] | None = None,
    planned_pull_request_id: str | None = None,
) -> Path:
    pull_request_directory = (
        DEFAULT_OUTPUT_ROOT / "planned_pull_requests" / canonical_task_id.lower()
    )
    if (
        selected_pull_request is not None
        and selected_pull_request.get("position") is not None
    ):
        position = int(selected_pull_request["position"]) + 1
        return pull_request_directory / f"pr-{position}.json"
    if planned_pull_request_id:
        return (
            pull_request_directory
            / f"{_sanitize_filename_part(planned_pull_request_id)}.json"
        )
    return pull_request_directory / "planned-pull-request.json"


def write_json_artifact(output_file: Path, payload: dict[str, Any]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=output_file.parent,
        prefix=f"{output_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        auth_refresh.protect_local_file(temp_path)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, output_file)
    auth_refresh.protect_local_file(output_file)


def write_binary_artifact(output_file: Path, payload: bytes) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=output_file.parent,
        prefix=f"{output_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        auth_refresh.protect_local_file(temp_path)
        handle.write(payload)
    os.replace(temp_path, output_file)
    auth_refresh.protect_local_file(output_file)


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


def _collect_prototype_code_media_from_selected_pull_request(
    selected_pull_request: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    collected_media: dict[str, dict[str, Any]] = {}

    for specification in selected_pull_request.get("specifications") or []:
        prototype_reference = specification.get("prototypeReference")
        if isinstance(prototype_reference, dict):
            _register_prototype_code_media_reference(
                collected_media,
                prototype_reference=prototype_reference,
                source_location={
                    "kind": "SELECTED_PLANNED_PULL_REQUEST_SPECIFICATION",
                    "plannedPullRequestId": selected_pull_request.get("id"),
                    "plannedPullRequestPosition": selected_pull_request.get("position"),
                    "plannedPullRequestTitle": selected_pull_request.get("title"),
                    "specificationId": specification.get("id"),
                    "title": specification.get("title"),
                    "target": specification.get("target"),
                },
            )

        source_task_specification = specification.get("sourceTaskSpecification")
        if not isinstance(source_task_specification, dict):
            continue
        source_prototype_reference = source_task_specification.get("prototypeReference")
        if isinstance(source_prototype_reference, dict):
            _register_prototype_code_media_reference(
                collected_media,
                prototype_reference=source_prototype_reference,
                source_location={
                    "kind": "SOURCE_TASK_SPECIFICATION",
                    "plannedPullRequestId": selected_pull_request.get("id"),
                    "plannedPullRequestPosition": selected_pull_request.get("position"),
                    "plannedPullRequestTitle": selected_pull_request.get("title"),
                    "specificationId": source_task_specification.get("id"),
                    "title": source_task_specification.get("title"),
                    "target": source_task_specification.get("target"),
                },
            )

    return collected_media


def _download_prototype_code_media_artifacts(
    selected_pull_request: dict[str, Any],
    *,
    snapshot_path: Path,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    collected_media = _collect_prototype_code_media_from_selected_pull_request(
        selected_pull_request
    )
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
                    "associated work includes UI or UX scope, use it as the pixel-perfect "
                    "visual reference and do not copy logic or backend behavior from it."
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
    planned_pull_request_id: str | None = None,
    pull_request_position: int | None = None,
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
            "plannedPullRequest": None,
            "buildContext": None,
        }
    except Exception as exc:
        return {
            "status": "LOGIN_FAILED",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "snapshotFile": None,
            "task": None,
            "plannedPullRequest": None,
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
            "plannedPullRequest": None,
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
            "plannedPullRequest": None,
            "buildContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
        }

    current_plan = task.get("currentPlan")
    if current_plan is None:
        return {
            "status": "NO_PLAN",
            "canonicalTaskId": canonical_task_id,
            "message": "The task does not have a current plan",
            "snapshotFile": None,
            "task": task,
            "plannedPullRequest": None,
            "buildContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
        }

    task_specifications_by_id = _task_specs_by_id(task)
    enriched_pull_requests = [
        _enrich_planned_pull_request(
            planned_pull_request,
            task_specifications_by_id=task_specifications_by_id,
        )
        for planned_pull_request in current_plan.get("pullRequests") or []
    ]
    enriched_pull_requests_by_id = {
        planned_pull_request["id"]: planned_pull_request
        for planned_pull_request in enriched_pull_requests
        if planned_pull_request.get("id")
    }
    selected_pull_request = _select_planned_pull_request(
        enriched_pull_requests,
        planned_pull_request_id=planned_pull_request_id,
        pull_request_position=pull_request_position,
    )

    if selected_pull_request is None:
        selector_description = (
            f"planned pull request ID {planned_pull_request_id}"
            if planned_pull_request_id
            else f"planned pull request position {pull_request_position}"
        )
        return {
            "status": "PR_NOT_FOUND",
            "canonicalTaskId": canonical_task_id,
            "message": f"No current plan entry matched {selector_description}",
            "snapshotFile": None,
            "task": task,
            "plannedPullRequest": None,
            "buildContext": {
                "availablePullRequests": [
                    _brief_pull_request(planned_pull_request)
                    for planned_pull_request in enriched_pull_requests
                ]
            },
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
        }

    source_task_specification_ids = [
        specification.get("sourceTaskSpecificationId")
        for specification in selected_pull_request.get("specifications") or []
        if specification.get("sourceTaskSpecificationId")
    ]
    source_task_specifications = [
        task_specifications_by_id[source_task_specification_id]
        for source_task_specification_id in source_task_specification_ids
        if source_task_specification_id in task_specifications_by_id
    ]

    snapshot_path = (
        output_file
        or default_output_file(
            canonical_task_id,
            selected_pull_request=selected_pull_request,
            planned_pull_request_id=planned_pull_request_id,
        )
    ).expanduser()
    prototype_code_media_downloads = _download_prototype_code_media_artifacts(
        selected_pull_request,
        snapshot_path=snapshot_path,
        token=session_payload["token"],
        config=request_config,
        timeout_seconds=30.0,
    )
    selected_pull_request["prototypeImplementationGuidance"] = (
        _build_selected_pull_request_prototype_guidance(selected_pull_request)
    )
    prototype_implementation_guidance = selected_pull_request.get(
        "prototypeImplementationGuidance"
    )
    result = {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "requestedPullRequestPosition": pull_request_position,
        "requestedPlannedPullRequestId": planned_pull_request_id,
        "downloadedAt": auth_refresh.utc_now(),
        "message": (
            "Downloaded full planned pull request specification snapshot and prototype code media artifacts"
            if prototype_code_media_downloads
            else "Downloaded full planned pull request specification snapshot"
        ),
        "snapshotFile": str(snapshot_path),
        "task": task,
        "plannedPullRequest": selected_pull_request,
        "buildContext": {
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
            },
            "selectedPlannedPullRequest": selected_pull_request,
            "sourceTaskSpecifications": source_task_specifications,
            "dependencyContext": _build_dependency_context(
                current_plan,
                selected_pull_request=selected_pull_request,
                enriched_pull_requests_by_id=enriched_pull_requests_by_id,
            ),
            "repositoryHints": _build_repository_hints(task, selected_pull_request),
            "openQuestions": [
                question
                for question in task.get("questions") or []
                if not (question.get("answer") or "").strip()
            ],
            "acceptedTaskSpecifications": [
                specification
                for specification in task.get("specifications") or []
                if specification.get("status") == "ACCEPTED"
            ],
            "latestTaskRunsByPhase": _build_latest_task_runs_by_phase(
                task.get("taskRuns") or []
            ),
            "currentHumanBlocker": task.get("currentHumanBlocker"),
            "prototypeImplementationGuidance": prototype_implementation_guidance,
        },
        "prototypeImplementationGuidance": prototype_implementation_guidance,
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
        description=(
            "Download the full Itera planned pull request specification for a canonical task ID."
        )
    )
    parser.add_argument(
        "--canonical-task-id",
        required=True,
        help="Canonical Itera task ID such as FRONTPAGE-42.",
    )
    selector_group = parser.add_mutually_exclusive_group(required=True)
    selector_group.add_argument(
        "--pull-request-position",
        type=int,
        help="1-based planned pull request position inside the current plan.",
    )
    selector_group.add_argument(
        "--planned-pull-request-id",
        help="Explicit Itera planned pull request ID.",
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

    if args.pull_request_position is not None and args.pull_request_position < 1:
        raise ValueError("--pull-request-position must be greater than or equal to 1")

    config = graphql_client.GraphQLRequestConfig(graphql_url=args.graphql_url)
    result = run_download(
        args.canonical_task_id,
        planned_pull_request_id=args.planned_pull_request_id,
        pull_request_position=args.pull_request_position,
        session_file=auth_refresh.expand_session_file(args.session_file),
        config=config,
        interactive=not args.no_prompt,
        output_file=Path(args.output_file).expanduser() if args.output_file else None,
    )
    print(json.dumps(result, indent=2))
    return (
        0
        if result["status"]
        in {
            "SUCCESS",
            "NOT_FOUND",
            "NO_PLAN",
            "PR_NOT_FOUND",
            "UNAVAILABLE",
            "AUTH_REQUIRED",
        }
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "UNAVAILABLE", "message": str(exc)}, indent=2))
        raise SystemExit(1)
