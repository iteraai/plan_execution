#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any
from urllib import request

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
DEFAULT_OUTPUT_ROOT = (
    Path.home() / ".codex" / "artifacts" / "plan_execution" / "specifications"
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
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        handle.write(payload)
    os.replace(temp_path, output_file)
    os.chmod(output_file, stat.S_IRUSR | stat.S_IWUSR)


def _prototype_patch_artifact_directory(snapshot_path: Path) -> Path:
    return snapshot_path.parent / f"{snapshot_path.stem}.artifacts" / "prototype-patches"


def _merge_reference_provenance(
    destination: dict[str, Any], prototype_reference: dict[str, Any]
) -> None:
    for field_name in (
        "prototypeHandoffArtifactId",
        "prototypeIterationId",
        "checkpointId",
    ):
        if destination.get(field_name) is None and prototype_reference.get(field_name):
            destination[field_name] = prototype_reference.get(field_name)

    existing_references = destination.setdefault("references", [])
    for reference in prototype_reference.get("references") or []:
        if reference not in existing_references:
            existing_references.append(reference)


def _prototype_patch_filename(artifact: dict[str, Any]) -> str:
    preferred_id = (
        artifact.get("prototypeHandoffArtifactId")
        or artifact.get("mediaId")
        or "prototype-code-artifact"
    )
    return f"{_sanitize_filename_part(str(preferred_id))}.patch"


def _build_prototype_code_artifacts(
    specifications: list[dict[str, Any]],
    *,
    artifact_directory: Path,
    token: str,
    config: graphql_client.GraphQLRequestConfig,
) -> list[dict[str, Any]]:
    prototype_code_artifacts: list[dict[str, Any]] = []
    artifacts_by_media_id: dict[str, dict[str, Any]] = {}

    for specification in specifications:
        prototype_reference = specification.get("prototypeReference") or {}
        if not prototype_reference:
            continue

        specification_id = specification.get("id")
        prototype_code_media = prototype_reference.get("prototypeCodeMedia") or {}
        media_id = prototype_code_media.get("id")
        if not media_id:
            prototype_code_artifacts.append(
                {
                    "mediaId": None,
                    "prototypeHandoffArtifactId": prototype_reference.get(
                        "prototypeHandoffArtifactId"
                    ),
                    "prototypeIterationId": prototype_reference.get(
                        "prototypeIterationId"
                    ),
                    "checkpointId": prototype_reference.get("checkpointId"),
                    "references": list(prototype_reference.get("references") or []),
                    "usedBySpecificationIds": (
                        [specification_id] if specification_id else []
                    ),
                    "downloadStatus": "MISSING_MEDIA",
                    "localPath": None,
                    "downloadUrl": None,
                    "error": "prototypeReference.prototypeCodeMedia.id was not present",
                }
            )
            continue

        artifact = artifacts_by_media_id.get(media_id)
        if artifact is None:
            artifact = {
                "mediaId": media_id,
                "prototypeHandoffArtifactId": prototype_reference.get(
                    "prototypeHandoffArtifactId"
                ),
                "prototypeIterationId": prototype_reference.get(
                    "prototypeIterationId"
                ),
                "checkpointId": prototype_reference.get("checkpointId"),
                "references": list(prototype_reference.get("references") or []),
                "usedBySpecificationIds": [],
                "downloadStatus": "DOWNLOAD_FAILED",
                "localPath": None,
                "downloadUrl": None,
                "error": None,
            }
            artifacts_by_media_id[media_id] = artifact
            prototype_code_artifacts.append(artifact)
        else:
            _merge_reference_provenance(artifact, prototype_reference)

        if (
            specification_id
            and specification_id not in artifact["usedBySpecificationIds"]
        ):
            artifact["usedBySpecificationIds"].append(specification_id)

    for artifact in prototype_code_artifacts:
        media_id = artifact.get("mediaId")
        if not media_id:
            continue

        try:
            download_url = graphql_client.generate_download_information(
                str(media_id),
                token=token,
                config=config,
            )
            with request.urlopen(download_url, timeout=config.timeout_seconds) as response:
                payload = response.read()
            local_path = artifact_directory / _prototype_patch_filename(artifact)
            write_binary_artifact(local_path, payload)
            artifact["downloadStatus"] = "DOWNLOADED"
            artifact["localPath"] = str(local_path)
            artifact["error"] = None
        except Exception as exc:
            artifact["downloadStatus"] = "DOWNLOAD_FAILED"
            artifact["localPath"] = None
            artifact["error"] = str(exc)

    return prototype_code_artifacts


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
    prototype_code_artifacts: list[dict[str, Any]] = []

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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
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
    prototype_code_artifacts = _build_prototype_code_artifacts(
        selected_pull_request.get("specifications") or [],
        artifact_directory=_prototype_patch_artifact_directory(snapshot_path),
        token=session_payload["token"],
        config=request_config,
    )
    result = {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "requestedPullRequestPosition": pull_request_position,
        "requestedPlannedPullRequestId": planned_pull_request_id,
        "downloadedAt": auth_refresh.utc_now(),
        "message": "Downloaded full planned pull request specification snapshot",
        "snapshotFile": str(snapshot_path),
        "task": task,
        "plannedPullRequest": selected_pull_request,
        "prototypeCodeArtifacts": prototype_code_artifacts,
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
            "prototypeCodeArtifacts": prototype_code_artifacts,
        },
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
