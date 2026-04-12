#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import auth_login
import auth_refresh
import graphql_client

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


class AuthRequiredError(RuntimeError):
    pass


def build_branch_name(canonical_task_id: str, position: int) -> str:
    return f"itera/{canonical_task_id.lower()}/pr-{position + 1}"


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
        "deploymentTargetLabel": planned_pull_request.get("deploymentTargetLabel"),
        "allowedPathPrefixes": planned_pull_request.get("allowedPathPrefixes"),
        "mainTouchPoints": planned_pull_request.get("mainTouchPoints"),
        "modelsToCreate": planned_pull_request.get("modelsToCreate"),
        "newApiContracts": planned_pull_request.get("newApiContracts"),
        "repositoryTarget": repository_target,
        "remoteRepositoryUrl": _build_remote_repo_url(repository_target),
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

    current_plan = (full_iteration_task_context or {}).get("currentPlan")
    selected_from_plan = _find_selected_pull_request_in_plan(
        current_plan, selected_pull_request
    )
    selected = selected_from_plan or selected_pull_request
    selected_id = selected.get("id") if selected else None

    summarized_pull_requests = []
    for planned_pull_request in (current_plan.get("pullRequests") or []):
        summary = _build_pull_request_summary(planned_pull_request)
        if summary is not None:
            summarized_pull_requests.append(summary)

    return {
        "contextError": context_error,
        "iterationTaskContext": full_iteration_task_context,
        "selectedPlannedPullRequest": _build_pull_request_summary(selected),
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
        }

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
        }

    if unavailable_reason:
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
        }

    current_execution = (planned_pull_request.get("execution") or {}).get("status")
    if current_execution and current_execution != "PLANNED":
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
        }

    return {
        "status": "SUCCESS",
        "canonicalTaskId": canonical_task_id,
        "message": "Claimed the next dependency-ready planned pull request",
        "iterationTask": iteration_task,
        "plan": {
            "plannedPullRequest": claimed_pull_request,
            "unavailableReason": None,
            "suggestedBranchName": branch_name,
        },
        "execution": _extract_execution(claimed_pull_request),
        "implementationContext": _build_implementation_context(
            full_iteration_task_context,
            claimed_pull_request,
            full_context_error,
        ),
        "viewer": {
            "username": session_payload["username"],
            "email": session_payload["account_email"],
        },
        "socialMe": social_me,
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "LOGIN_FAILED", "message": str(exc)}, indent=2))
        raise SystemExit(1)
