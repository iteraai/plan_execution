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
from .planned_prs import GET_ITERATION_TASK_BY_CANONICAL_ID_QUERY

GET_NEXT_READY_PLANNED_PULL_REQUEST_QUERY = """
query GetNextReadyPlannedPullRequestForTask($canonicalTaskId: IterationTaskCanonicalID!) {
  getNextReadyPlannedPullRequestForTask(canonicalTaskId: $canonicalTaskId) {
    iterationTask {
      id
      canonicalId
      status
    }
    unavailableReason
      plannedPullRequest {
        id
        position
        title
        goal
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
        deploymentTargetLabel
        repositoryTarget {
          provider
          owner
        repoName
        mainBranchName
        basePath
        stableRepositoryId
      }
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
""".strip()
GET_ITERATION_TASK_CONTEXT_QUERY = """
query GetIterationTaskContext($taskId: IterationTaskID!) {
  getIterationTask(taskId: $taskId) {
    id
    canonicalId
    status
    name
    goalDescription
    successCriteria
    outOfScope
    contextProblem
    currentPlan {
      id
      pullRequests {
        id
        position
                            title
                            goal
                            deploymentTargetLabel
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
                            allowedPathPrefixes
                            mainTouchPoints
                            modelsToCreate
                            newApiContracts
                            repositoryTarget {
          provider
          owner
          repoName
          mainBranchName
          basePath
          stableRepositoryId
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
CLAIM_PLANNED_PULL_REQUEST_EXECUTION_MUTATION = """
mutation ClaimPlannedPullRequestExecution(
  $plannedPullRequestId: IterationPlanPullRequestID!
  $branchName: String!
) {
  claimPlannedPullRequestExecution(
    plannedPullRequestId: $plannedPullRequestId
    branchName: $branchName
  ) {
    plannedPullRequest {
      id
      position
      title
      goal
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
      deploymentTargetLabel
      repositoryTarget {
        provider
        owner
        repoName
        mainBranchName
        basePath
        stableRepositoryId
      }
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
""".strip()
GENERATE_DOWNLOAD_INFORMATION_MUTATION = """
mutation GenerateDownloadInformation($mediaId: MediaID!) {
  generateDownloadInformation(media: $mediaId) {
    url
    expiration
  }
}
""".strip()
DEFAULT_OUTPUT_ROOT = Path.home() / ".codex" / "artifacts" / "plan_execution" / "claims"
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


def build_branch_name(canonical_task_id: str, position: int) -> str:
    return f"itera/{canonical_task_id.lower()}/pr-{position + 1}"


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


def _build_prototype_guidance_for_pull_request(
    planned_pull_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not planned_pull_request:
        return None

    specifications = planned_pull_request.get("specifications") or []
    prototype_patch_media_ids, prototype_patch_local_files, download_errors = (
        _collect_prototype_patch_details(specifications)
    )
    if not prototype_patch_media_ids:
        return None

    ui_scope_signals = _collect_ui_scope_signals(
        specifications,
        context_values=[
            planned_pull_request.get("title"),
            planned_pull_request.get("goal"),
            planned_pull_request.get("deploymentTargetLabel"),
            *(planned_pull_request.get("allowedPathPrefixes") or []),
            *(planned_pull_request.get("mainTouchPoints") or []),
        ],
    )
    return {
        "scope": "PLANNED_PULL_REQUEST",
        "plannedPullRequestId": planned_pull_request.get("id"),
        "plannedPullRequestPosition": planned_pull_request.get("position"),
        "plannedPullRequestTitle": planned_pull_request.get("title"),
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


def _sanitize_filename_part(value: str) -> str:
    sanitized = []
    for character in value:
        if character.isalnum() or character in {"-", "_"}:
            sanitized.append(character)
        else:
            sanitized.append("-")
    return "".join(sanitized).strip("-") or "planned-pull-request"


def _claim_artifact_root(
    canonical_task_id: str, planned_pull_request: dict[str, Any] | None
) -> Path:
    output_root = DEFAULT_OUTPUT_ROOT / canonical_task_id.strip().lower()
    if (
        planned_pull_request is not None
        and planned_pull_request.get("position") is not None
    ):
        position = int(planned_pull_request["position"]) + 1
        return output_root / f"pr-{position}"
    if planned_pull_request is not None and planned_pull_request.get("id"):
        return output_root / _sanitize_filename_part(str(planned_pull_request["id"]))
    return output_root / "planned-pull-request"


def write_binary_artifact(output_file: Path, payload: bytes) -> None:
    artifacts.write_binary_artifact(
        output_file, payload, protect_file=auth_refresh.protect_local_file
    )


def _prototype_code_media_output_root(artifact_root: Path) -> Path:
    return artifact_root / PROTOTYPE_CODE_MEDIA_DIRNAME


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


def _collect_prototype_code_media_from_pull_request(
    collected_media: dict[str, dict[str, Any]],
    *,
    planned_pull_request: dict[str, Any],
    source_kind: str,
) -> None:
    for specification in planned_pull_request.get("specifications") or []:
        prototype_reference = specification.get("prototypeReference")
        if isinstance(prototype_reference, dict):
            _register_prototype_code_media_reference(
                collected_media,
                prototype_reference=prototype_reference,
                source_location={
                    "kind": source_kind,
                    "plannedPullRequestId": planned_pull_request.get("id"),
                    "plannedPullRequestPosition": planned_pull_request.get("position"),
                    "plannedPullRequestTitle": planned_pull_request.get("title"),
                    "specificationId": specification.get("id"),
                    "title": specification.get("title"),
                    "target": specification.get("target"),
                },
            )


def _download_prototype_code_media_artifacts(
    *,
    canonical_task_id: str,
    full_iteration_task_context: dict[str, Any] | None,
    selected_pull_request: dict[str, Any] | None,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    collected_media: dict[str, dict[str, Any]] = {}

    current_plan = (full_iteration_task_context or {}).get("currentPlan") or {}
    for planned_pull_request in current_plan.get("pullRequests") or []:
        _collect_prototype_code_media_from_pull_request(
            collected_media,
            planned_pull_request=planned_pull_request,
            source_kind="CURRENT_PLAN_PULL_REQUEST_SPECIFICATION",
        )

    if selected_pull_request is not None:
        _collect_prototype_code_media_from_pull_request(
            collected_media,
            planned_pull_request=selected_pull_request,
            source_kind="SELECTED_PULL_REQUEST_SPECIFICATION",
        )

    if not collected_media:
        return []

    output_root = _prototype_code_media_output_root(
        _claim_artifact_root(canonical_task_id, selected_pull_request)
    )
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


def _extract_execution(planned_pull_request: dict[str, Any] | None) -> dict[str, Any]:
    execution = (planned_pull_request or {}).get("execution") or {}
    claimed_by = execution.get("claimedByUser") or {}
    return {
        "executionState": execution.get("status"),
        "claimedBy": claimed_by.get("username"),
        "claimedAt": None,
        "branchName": execution.get("branchName"),
        "providerPullRequestNumber": execution.get("providerPullRequestNumber"),
        "providerPullRequestUrl": execution.get("providerPullRequestUrl"),
    }


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


def _build_pull_request_summary(
    planned_pull_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not planned_pull_request:
        return None
    repository_target = planned_pull_request.get("repositoryTarget") or {}
    summary = {
        "id": planned_pull_request.get("id"),
        "position": planned_pull_request.get("position"),
        "title": planned_pull_request.get("title"),
        "goal": planned_pull_request.get("goal"),
        "specifications": planned_pull_request.get("specifications"),
        "deploymentTargetLabel": planned_pull_request.get("deploymentTargetLabel"),
        "allowedPathPrefixes": planned_pull_request.get("allowedPathPrefixes"),
        "mainTouchPoints": planned_pull_request.get("mainTouchPoints"),
        "modelsToCreate": planned_pull_request.get("modelsToCreate"),
        "newApiContracts": planned_pull_request.get("newApiContracts"),
        "repositoryTarget": repository_target,
        "remoteRepositoryUrl": _build_remote_repo_url(repository_target),
        "prototypeImplementationGuidance": _build_prototype_guidance_for_pull_request(
            planned_pull_request
        ),
    }
    return summary


def _get_iteration_task_context(
    *, task_id: str, token: str, config: graphql_client.GraphQLRequestConfig
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = graphql_client.execute_graphql(
            GET_ITERATION_TASK_CONTEXT_QUERY,
            {"taskId": task_id},
            token=token,
            config=config,
        )
        return response.get("getIterationTask"), None
    except graphql_client.GraphQLError as exc:
        return None, str(exc)


def _dependency_context(
    current_plan: dict[str, Any] | None, selected_pull_request_id: str | None
) -> dict[str, Any] | None:
    if not current_plan:
        return None
    dependencies = current_plan.get("pullRequestDependencies") or []
    depends_on = [
        dependency
        for dependency in dependencies
        if dependency.get("pullRequestId") == selected_pull_request_id
    ]
    blocks = [
        dependency
        for dependency in dependencies
        if dependency.get("dependsOnPullRequestId") == selected_pull_request_id
    ]
    return {
        "forSelectedPullRequest": {
            "dependsOn": depends_on,
            "blocks": blocks,
        },
        "allDependencies": dependencies,
    }


def _find_selected_pull_request_in_plan(
    current_plan: dict[str, Any] | None, selected_pull_request: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not current_plan or not selected_pull_request:
        return None
    selected_pull_request_id = selected_pull_request.get("id")
    for planned_pull_request in current_plan.get("pullRequests") or []:
        if planned_pull_request.get("id") == selected_pull_request_id:
            return planned_pull_request
    return None


def _build_implementation_context(
    full_iteration_task_context: dict[str, Any] | None,
    selected_pull_request: dict[str, Any] | None,
    context_error: str | None = None,
) -> dict[str, Any] | None:
    if not full_iteration_task_context and not selected_pull_request:
        return None

    current_plan = (full_iteration_task_context or {}).get("currentPlan") or {}
    selected_from_plan = _find_selected_pull_request_in_plan(
        current_plan, selected_pull_request
    )
    selected = selected_from_plan or selected_pull_request
    selected_id = selected.get("id") if selected else None

    summarized_pull_requests = []
    for planned_pull_request in current_plan.get("pullRequests") or []:
        summary = _build_pull_request_summary(planned_pull_request)
        if summary is not None:
            summarized_pull_requests.append(summary)

    return {
        "contextError": context_error,
        "iterationTaskContext": full_iteration_task_context,
        "selectedPlannedPullRequest": _build_pull_request_summary(selected),
        "prototypeImplementationGuidance": _build_prototype_guidance_for_pull_request(
            selected
        ),
        "currentPlan": {
            "id": current_plan.get("id") if current_plan else None,
            "pullRequests": summarized_pull_requests,
            "dependencyContext": _dependency_context(current_plan, selected_id),
        },
        "repositoryHints": {
            "suggestedBasePath": (
                selected.get("repositoryTarget", {}).get("basePath")
                if selected
                else None
            ),
            "suggestedStableRepositoryId": (
                selected.get("repositoryTarget", {}).get("stableRepositoryId")
                if selected
                else None
            ),
        },
    }


def _select_pull_request_by_id(
    task: dict[str, Any],
    planned_pull_request_id: str,
) -> dict[str, Any] | None:
    current_plan = task.get("currentPlan") or {}
    for planned_pull_request in current_plan.get("pullRequests") or []:
        if planned_pull_request.get("id") == planned_pull_request_id:
            return planned_pull_request
    return None


def _pull_request_lookup(
    current_plan: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not current_plan:
        return {}
    return {
        planned_pull_request["id"]: planned_pull_request
        for planned_pull_request in current_plan.get("pullRequests") or []
        if planned_pull_request.get("id")
    }


def _is_dependency_satisfied(planned_pull_request: dict[str, Any]) -> bool:
    state = str(planned_pull_request.get("state") or "").upper()
    execution_state = str(
        (planned_pull_request.get("execution") or {}).get("status") or ""
    ).upper()
    return state in {"MERGED", "DONE"} or execution_state in {"MERGED", "DONE"}


def _planned_pull_request_unavailable_reason(
    current_plan: dict[str, Any] | None,
    planned_pull_request: dict[str, Any],
) -> str | None:
    current_execution = (planned_pull_request.get("execution") or {}).get("status")
    if current_execution and current_execution != "PLANNED":
        return f"Planned pull request is already in execution state {current_execution}"

    claimed_by = (planned_pull_request.get("execution") or {}).get("claimedByUser")
    if claimed_by:
        username = claimed_by.get("username") if isinstance(claimed_by, dict) else None
        return (
            f"Planned pull request is already claimed by {username}"
            if username
            else "Planned pull request is already claimed"
        )

    state = planned_pull_request.get("state")
    if state and state != "READY_UNCLAIMED":
        return f"Planned pull request is not dependency-ready; current state is {state}"

    pull_requests_by_id = _pull_request_lookup(current_plan)
    blocking_dependencies = []
    selected_pull_request_id = planned_pull_request.get("id")
    for dependency in (current_plan or {}).get("pullRequestDependencies") or []:
        if dependency.get("pullRequestId") != selected_pull_request_id:
            continue
        upstream = pull_requests_by_id.get(dependency.get("dependsOnPullRequestId"))
        if upstream is None or not _is_dependency_satisfied(upstream):
            blocking_dependencies.append(dependency)

    if blocking_dependencies:
        dependency_ids = ", ".join(
            str(dependency.get("dependsOnPullRequestId"))
            for dependency in blocking_dependencies
        )
        return f"Planned pull request is blocked by unfinished dependencies: {dependency_ids}"

    return None


def _run_specific_execution(
    canonical_task_id: str,
    planned_pull_request_id: str,
    *,
    session_payload: dict[str, Any],
    social_me: dict[str, Any],
    request_config: graphql_client.GraphQLRequestConfig,
    validate_startable: bool = False,
) -> dict[str, Any]:
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
            "plannedPullRequestId": planned_pull_request_id,
            "message": str(exc),
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    if task is None:
        return {
            "status": "NOT_FOUND",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "message": "No iteration task was found for the canonical task ID",
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": "No iteration task was found for the canonical task ID",
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    current_plan = task.get("currentPlan")
    if current_plan is None:
        return {
            "status": "NO_PLAN",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "message": "The task does not have a current plan",
            "iterationTask": task,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": "The task does not have a current plan",
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": _build_implementation_context(task, None),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    planned_pull_request = _select_pull_request_by_id(task, planned_pull_request_id)
    if planned_pull_request is None:
        return {
            "status": "PR_NOT_FOUND",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "message": f"No current plan entry matched planned pull request ID {planned_pull_request_id}",
            "iterationTask": task,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": f"No current plan entry matched planned pull request ID {planned_pull_request_id}",
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": _build_implementation_context(task, None),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    unavailable_reason = (
        _planned_pull_request_unavailable_reason(current_plan, planned_pull_request)
        if validate_startable
        else None
    )
    if unavailable_reason is None:
        current_execution = (planned_pull_request.get("execution") or {}).get("status")
        if current_execution and current_execution != "PLANNED":
            unavailable_reason = (
                f"Planned pull request is already in execution state {current_execution}"
            )

    if unavailable_reason:
        prototype_code_media_downloads = _download_prototype_code_media_artifacts(
            canonical_task_id=canonical_task_id,
            full_iteration_task_context=task,
            selected_pull_request=planned_pull_request,
            token=session_payload["token"],
            config=request_config,
            timeout_seconds=30.0,
        )
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "plannedPullRequestTitle": planned_pull_request.get("title"),
            "plannedPullRequestPosition": planned_pull_request.get("position"),
            "message": unavailable_reason,
            "iterationTask": task,
            "plan": {
                "plannedPullRequest": planned_pull_request,
                "unavailableReason": unavailable_reason,
                "suggestedBranchName": None,
            },
            "execution": _extract_execution(planned_pull_request),
            "implementationContext": _build_implementation_context(
                task, planned_pull_request
            ),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": prototype_code_media_downloads,
            "artifactPaths": [
                download["localFile"]
                for download in prototype_code_media_downloads
                if download.get("localFile")
            ],
        }

    branch_name = build_branch_name(
        canonical_task_id, int(planned_pull_request["position"])
    )
    try:
        claimed_pull_request = graphql_client.execute_graphql(
            CLAIM_PLANNED_PULL_REQUEST_EXECUTION_MUTATION,
            {
                "plannedPullRequestId": planned_pull_request["id"],
                "branchName": branch_name,
            },
            token=session_payload["token"],
            config=request_config,
        )["claimPlannedPullRequestExecution"]["plannedPullRequest"]
    except graphql_client.GraphQLError as exc:
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "message": str(exc),
            "iterationTask": task,
            "plan": {
                "plannedPullRequest": planned_pull_request,
                "unavailableReason": str(exc),
                "suggestedBranchName": branch_name,
            },
            "execution": _extract_execution(planned_pull_request),
            "implementationContext": _build_implementation_context(
                task, planned_pull_request
            ),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    prototype_code_media_downloads = _download_prototype_code_media_artifacts(
        canonical_task_id=canonical_task_id,
        full_iteration_task_context=task,
        selected_pull_request=claimed_pull_request,
        token=session_payload["token"],
        config=request_config,
        timeout_seconds=30.0,
    )
    implementation_context = _build_implementation_context(task, claimed_pull_request)
    return {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "plannedPullRequestId": planned_pull_request_id,
        "plannedPullRequestTitle": claimed_pull_request.get("title"),
        "plannedPullRequestPosition": claimed_pull_request.get("position"),
        "suggestedBranchName": branch_name,
        "message": (
            "Claimed the selected planned pull request and prototype code media artifacts"
            if prototype_code_media_downloads
            else "Claimed the selected planned pull request"
        ),
        "iterationTask": task,
        "plan": {
            "plannedPullRequest": claimed_pull_request,
            "unavailableReason": None,
            "suggestedBranchName": branch_name,
        },
        "execution": _extract_execution(claimed_pull_request),
        "implementationContext": implementation_context,
        "prototypeImplementationGuidance": (
            implementation_context.get("prototypeImplementationGuidance")
            if implementation_context is not None
            else None
        ),
        "viewer": {
            "username": session_payload["username"],
            "email": session_payload["account_email"],
        },
        "socialMe": social_me,
        "prototypeCodeMediaDownloads": prototype_code_media_downloads,
        "artifactPaths": [
            download["localFile"]
            for download in prototype_code_media_downloads
            if download.get("localFile")
        ],
    }


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
                f"Stored Itera session could not be refreshed: {exc}", file=sys.stderr
            )

    if not interactive:
        raise AuthRequiredError("A valid Itera session is required")

    payload = auth_login.login_interactively(session_file=session_file, config=config)
    social_me = auth_refresh.fetch_social_me(payload["token"], config=config)
    return payload, social_me


def run_execution(
    canonical_task_id: str,
    *,
    planned_pull_request_id: str | None = None,
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    interactive: bool = True,
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
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "prototypeCodeMediaDownloads": [],
        }
    except Exception as exc:
        return {
            "status": "LOGIN_FAILED",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "prototypeCodeMediaDownloads": [],
        }

    if planned_pull_request_id:
        return _run_specific_execution(
            canonical_task_id,
            planned_pull_request_id,
            session_payload=session_payload,
            social_me=social_me,
            request_config=request_config,
        )

    try:
        next_ready = graphql_client.execute_graphql(
            GET_NEXT_READY_PLANNED_PULL_REQUEST_QUERY,
            {"canonicalTaskId": canonical_task_id},
            token=session_payload["token"],
            config=request_config,
        )["getNextReadyPlannedPullRequestForTask"]
    except graphql_client.GraphQLError as exc:
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
        }

    iteration_task = next_ready["iterationTask"]
    planned_pull_request = next_ready.get("plannedPullRequest")
    unavailable_reason = next_ready.get("unavailableReason")
    full_iteration_task_context = None
    full_context_error = None
    if planned_pull_request and iteration_task and iteration_task.get("id"):
        full_iteration_task_context, full_context_error = _get_iteration_task_context(
            task_id=iteration_task["id"],
            token=session_payload["token"],
            config=request_config,
        )

    if not planned_pull_request:
        return {
            "status": "NO_READY_PR",
            "canonicalTaskId": canonical_task_id,
            "message": unavailable_reason
            or "No dependency-ready planned pull request is available",
            "iterationTask": iteration_task,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": unavailable_reason,
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": [],
        }

    if unavailable_reason:
        prototype_code_media_downloads = _download_prototype_code_media_artifacts(
            canonical_task_id=canonical_task_id,
            full_iteration_task_context=full_iteration_task_context,
            selected_pull_request=planned_pull_request,
            token=session_payload["token"],
            config=request_config,
            timeout_seconds=30.0,
        )
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "message": unavailable_reason,
            "iterationTask": iteration_task,
            "plan": {
                "plannedPullRequest": planned_pull_request,
                "unavailableReason": unavailable_reason,
                "suggestedBranchName": None,
            },
            "execution": _extract_execution(planned_pull_request),
            "implementationContext": _build_implementation_context(
                full_iteration_task_context,
                planned_pull_request,
                full_context_error,
            ),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": prototype_code_media_downloads,
        }

    current_execution = (planned_pull_request.get("execution") or {}).get("status")
    if current_execution and current_execution != "PLANNED":
        prototype_code_media_downloads = _download_prototype_code_media_artifacts(
            canonical_task_id=canonical_task_id,
            full_iteration_task_context=full_iteration_task_context,
            selected_pull_request=planned_pull_request,
            token=session_payload["token"],
            config=request_config,
            timeout_seconds=30.0,
        )
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "message": f"Planned pull request is already in execution state {current_execution}",
            "iterationTask": iteration_task,
            "plan": {
                "plannedPullRequest": planned_pull_request,
                "unavailableReason": f"Planned pull request is already in execution state {current_execution}",
                "suggestedBranchName": None,
            },
            "execution": _extract_execution(planned_pull_request),
            "implementationContext": _build_implementation_context(
                full_iteration_task_context,
                planned_pull_request,
                full_context_error,
            ),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": prototype_code_media_downloads,
        }

    branch_name = build_branch_name(
        canonical_task_id, int(planned_pull_request["position"])
    )

    try:
        claimed_pull_request = graphql_client.execute_graphql(
            CLAIM_PLANNED_PULL_REQUEST_EXECUTION_MUTATION,
            {
                "plannedPullRequestId": planned_pull_request["id"],
                "branchName": branch_name,
            },
            token=session_payload["token"],
            config=request_config,
        )["claimPlannedPullRequestExecution"]["plannedPullRequest"]
    except graphql_client.GraphQLError as exc:
        prototype_code_media_downloads = _download_prototype_code_media_artifacts(
            canonical_task_id=canonical_task_id,
            full_iteration_task_context=full_iteration_task_context,
            selected_pull_request=planned_pull_request,
            token=session_payload["token"],
            config=request_config,
            timeout_seconds=30.0,
        )
        return {
            "status": "UNAVAILABLE",
            "canonicalTaskId": canonical_task_id,
            "message": str(exc),
            "iterationTask": iteration_task,
            "plan": {
                "plannedPullRequest": planned_pull_request,
                "unavailableReason": str(exc),
                "suggestedBranchName": branch_name,
            },
            "execution": _extract_execution(planned_pull_request),
            "implementationContext": _build_implementation_context(
                full_iteration_task_context,
                planned_pull_request,
                full_context_error,
            ),
            "viewer": {
                "username": session_payload["username"],
                "email": session_payload["account_email"],
            },
            "socialMe": social_me,
            "prototypeCodeMediaDownloads": prototype_code_media_downloads,
        }

    prototype_code_media_downloads = _download_prototype_code_media_artifacts(
        canonical_task_id=canonical_task_id,
        full_iteration_task_context=full_iteration_task_context,
        selected_pull_request=claimed_pull_request,
        token=session_payload["token"],
        config=request_config,
        timeout_seconds=30.0,
    )
    implementation_context = _build_implementation_context(
        full_iteration_task_context,
        claimed_pull_request,
        full_context_error,
    )
    return {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "message": (
            "Claimed the next dependency-ready planned pull request and prototype code media artifacts"
            if prototype_code_media_downloads
            else "Claimed the next dependency-ready planned pull request"
        ),
        "iterationTask": iteration_task,
        "plan": {
            "plannedPullRequest": claimed_pull_request,
            "unavailableReason": None,
            "suggestedBranchName": branch_name,
        },
        "execution": _extract_execution(claimed_pull_request),
        "implementationContext": implementation_context,
        "prototypeImplementationGuidance": (
            implementation_context.get("prototypeImplementationGuidance")
            if implementation_context is not None
            else None
        ),
        "viewer": {
            "username": session_payload["username"],
            "email": session_payload["account_email"],
        },
        "socialMe": social_me,
        "prototypeCodeMediaDownloads": prototype_code_media_downloads,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim the next dependency-ready planned pull request for a canonical Itera task ID."
    )
    parser.add_argument(
        "--canonical-task-id",
        required=True,
        help="Canonical Itera task ID such as FRONTPAGE-42.",
    )
    parser.add_argument(
        "--planned-pull-request-id",
        help=(
            "Optional explicit Itera planned pull request ID. When omitted, "
            "the next dependency-ready planned pull request is claimed."
        ),
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
        "--no-prompt",
        action="store_true",
        help="Do not prompt for login if a valid stored session is unavailable.",
    )
    args = parser.parse_args()

    config = graphql_client.GraphQLRequestConfig(graphql_url=args.graphql_url)
    result = run_execution(
        args.canonical_task_id,
        planned_pull_request_id=args.planned_pull_request_id,
        session_file=auth_refresh.expand_session_file(args.session_file),
        config=config,
        interactive=not args.no_prompt,
    )
    print(json.dumps(result, indent=2))
    return (
        0
        if result["status"]
        in {"SUCCESS", "NO_READY_PR", "UNAVAILABLE", "AUTH_REQUIRED"}
        else 1
    )


def run_planned_pr_execution(
    canonical_task_id: str,
    planned_pull_request_id: str,
    *,
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    interactive: bool = True,
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
            "plannedPullRequestId": planned_pull_request_id,
            "message": str(exc),
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }
    except Exception as exc:
        return {
            "status": "LOGIN_FAILED",
            "canonicalTaskId": canonical_task_id,
            "plannedPullRequestId": planned_pull_request_id,
            "message": str(exc),
            "iterationTask": None,
            "plan": {
                "plannedPullRequest": None,
                "unavailableReason": str(exc),
                "suggestedBranchName": None,
            },
            "execution": None,
            "implementationContext": None,
            "prototypeCodeMediaDownloads": [],
            "artifactPaths": [],
        }

    return _run_specific_execution(
        canonical_task_id,
        planned_pull_request_id,
        session_payload=session_payload,
        social_me=social_me,
        request_config=request_config,
        validate_startable=True,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "LOGIN_FAILED", "message": str(exc)}, indent=2))
        raise SystemExit(1)
