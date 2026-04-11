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
