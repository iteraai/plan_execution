from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "execute-planned-pr" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import execute_planned_pr


def _planned_pull_request(
    pull_request_id: str,
    *,
    position: int,
    state: str = "READY_UNCLAIMED",
    execution_status: str = "PLANNED",
) -> dict[str, object]:
    return {
        "id": pull_request_id,
        "position": position,
        "title": f"PR {position + 1}",
        "goal": "Ship the selected slice",
        "specifications": [],
        "deploymentTargetLabel": "apps/itera",
        "allowedPathPrefixes": ["src"],
        "mainTouchPoints": ["backend"],
        "modelsToCreate": [],
        "newApiContracts": [],
        "repositoryTarget": {
            "provider": "GITHUB",
            "owner": "iteraai",
            "repoName": "Web",
            "mainBranchName": "main",
            "basePath": "",
            "stableRepositoryId": "repo-1",
        },
        "state": state,
        "execution": {
            "status": execution_status,
            "branchName": None,
            "claimedByUser": None,
            "providerPullRequestNumber": None,
            "providerPullRequestUrl": None,
        },
    }


def _task_payload(
    pull_requests: list[dict[str, object]],
    *,
    dependencies: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "task-1",
        "canonicalId": "FRONTPAGE-42",
        "status": "READY_TO_BUILD",
        "currentPlan": {
            "id": "plan-1",
            "pullRequests": pull_requests,
            "pullRequestDependencies": dependencies or [],
        },
    }


class ExecutePlannedPrTests(unittest.TestCase):
    def test_build_branch_name_uses_lowercase_canonical_id(self) -> None:
        branch_name = execute_planned_pr.build_branch_name("FRONTPAGE-42", 1)
        self.assertEqual(branch_name, "itera/frontpage-42/pr-2")

    @mock.patch("execute_planned_pr.bridge.ensure_authenticated_context")
    @mock.patch("execute_planned_pr.graphql_client.execute_graphql")
    def test_run_execution_claims_exact_requested_pr(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        upstream = _planned_pull_request(
            "pr-1",
            position=0,
            state="MERGED",
            execution_status="MERGED",
        )
        selected = _planned_pull_request("pr-2", position=1)

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getIterationTaskByCanonicalId" in query:
                return {
                    "getIterationTaskByCanonicalId": _task_payload(
                        [upstream, selected],
                        dependencies=[
                            {
                                "id": "dependency-1",
                                "pullRequestId": "pr-2",
                                "dependsOnPullRequestId": "pr-1",
                            }
                        ],
                    )
                }
            if "claimPlannedPullRequestExecution" in query:
                self.assertEqual(
                    variables,
                    {
                        "plannedPullRequestId": "pr-2",
                        "branchName": "itera/frontpage-42/pr-2",
                    },
                )
                claimed = dict(selected)
                claimed["execution"] = {
                    "status": "IMPLEMENTING",
                    "branchName": "itera/frontpage-42/pr-2",
                    "claimedByUser": {"username": "thor"},
                    "providerPullRequestNumber": None,
                    "providerPullRequestUrl": None,
                }
                return {
                    "claimPlannedPullRequestExecution": {
                        "plannedPullRequest": claimed,
                    }
                }
            self.fail(f"Unexpected GraphQL query: {query}")

        execute_graphql.side_effect = graphql_side_effect

        result = execute_planned_pr.run_execution("FRONTPAGE-42", "pr-2")

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["plannedPullRequestId"], "pr-2")
        self.assertEqual(result["plannedPullRequestTitle"], "PR 2")
        self.assertEqual(result["plannedPullRequestPosition"], 1)
        self.assertEqual(result["suggestedBranchName"], "itera/frontpage-42/pr-2")
        self.assertEqual(result["execution"]["executionState"], "IMPLEMENTING")
        self.assertEqual(
            result["implementationContext"]["selectedPlannedPullRequest"]["id"],
            "pr-2",
        )

    @mock.patch("execute_planned_pr.bridge.ensure_authenticated_context")
    @mock.patch("execute_planned_pr.graphql_client.execute_graphql")
    def test_run_execution_returns_pr_not_found_for_missing_id(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.return_value = {
            "getIterationTaskByCanonicalId": _task_payload(
                [_planned_pull_request("pr-1", position=0)]
            )
        }

        result = execute_planned_pr.run_execution("FRONTPAGE-42", "missing-pr")

        self.assertEqual(result["status"], "PR_NOT_FOUND")
        self.assertEqual(result["plannedPullRequestId"], "missing-pr")
        self.assertIsNone(result["plan"]["plannedPullRequest"])

    @mock.patch("execute_planned_pr.bridge.ensure_authenticated_context")
    @mock.patch("execute_planned_pr.graphql_client.execute_graphql")
    def test_run_execution_returns_unavailable_for_not_ready_pr(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.return_value = {
            "getIterationTaskByCanonicalId": _task_payload(
                [
                    _planned_pull_request("pr-1", position=0),
                    _planned_pull_request(
                        "pr-2",
                        position=1,
                        state="WAITING_ON_DEPENDENCY",
                    ),
                ],
                dependencies=[
                    {
                        "id": "dependency-1",
                        "pullRequestId": "pr-2",
                        "dependsOnPullRequestId": "pr-1",
                    }
                ],
            )
        }

        result = execute_planned_pr.run_execution("FRONTPAGE-42", "pr-2")

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIn("not dependency-ready", result["message"])
        self.assertIsNone(result["plan"]["suggestedBranchName"])
        self.assertEqual(execute_graphql.call_count, 1)


if __name__ == "__main__":
    unittest.main()
