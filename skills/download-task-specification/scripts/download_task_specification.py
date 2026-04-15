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
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=output_file.parent,
        prefix=f"{output_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, output_file)
    os.chmod(output_file, stat.S_IRUSR | stat.S_IWUSR)


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
    result = {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "downloadedAt": auth_refresh.utc_now(),
        "message": "Downloaded full iteration task specification snapshot",
        "snapshotFile": str(snapshot_path),
        "task": task,
        "buildContext": _build_build_context(task),
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
