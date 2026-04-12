from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "execute-approved-plan" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import execute_approved_plan


class ExecuteApprovedPlanTests(unittest.TestCase):
    def test_build_branch_name_uses_lowercase_canonical_id(self) -> None:
        branch_name = execute_approved_plan.build_branch_name("FRONTPAGE-42", 3)
        self.assertEqual(branch_name, "itera/frontpage-42/pr-4")

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_returns_no_ready_pr(
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
            "getNextReadyPlannedPullRequestForTask": {
                "iterationTask": {
                    "id": "task-1",
                    "canonicalId": "FRONTPAGE-42",
                    "status": "READY_TO_BUILD",
                },
                "plannedPullRequest": None,
                "unavailableReason": "already claimed",
            }
        }

        result = execute_approved_plan.run_execution("FRONTPAGE-42")

        self.assertEqual(result["status"], "NO_READY_PR")
        self.assertEqual(result["plan"]["unavailableReason"], "already claimed")

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_claims_next_ready_pr(
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
        execute_graphql.side_effect = [
            {
                "getNextReadyPlannedPullRequestForTask": {
                    "iterationTask": {
                        "id": "task-1",
                        "canonicalId": "FRONTPAGE-42",
                        "status": "READY_TO_BUILD",
                    },
                    "plannedPullRequest": {
                        "id": "pr-1",
                        "position": 0,
                        "title": "PR 1",
                        "goal": "Ship the slice",
                        "deploymentTargetLabel": "apps/itera",
                        "repositoryTarget": {
                            "provider": "GITHUB",
                            "owner": "iteraai",
                            "repoName": "Web",
                            "mainBranchName": "main",
                            "basePath": "",
                            "stableRepositoryId": "repo-1",
                        },
                        "execution": {
                            "status": "PLANNED",
                            "branchName": None,
                            "claimedByUser": None,
                        },
                    },
                    "unavailableReason": None,
                }
            },
            {
                "getIterationTask": {
                    "id": "task-1",
                    "canonicalId": "FRONTPAGE-42",
                    "name": "Frontpage rollout",
                    "goalDescription": "Build planned PR #1",
                    "successCriteria": "Pass all checks",
                    "outOfScope": "None",
                    "contextProblem": "none",
                    "currentPlan": {
                        "id": "plan-1",
                        "pullRequests": [
                            {
                                "id": "pr-1",
                                "position": 0,
                                "title": "PR 1",
                                "goal": "Ship the slice",
                                "deploymentTargetLabel": "apps/itera",
                                "allowedPathPrefixes": ["src"],
                                "mainTouchPoints": ["backend", "frontend"],
                                "modelsToCreate": ["m1"],
                                "newApiContracts": ["v1"],
                                "repositoryTarget": {
                                    "provider": "GITHUB",
                                    "owner": "iteraai",
                                    "repoName": "Web",
                                    "mainBranchName": "main",
                                    "basePath": "",
                                    "stableRepositoryId": "repo-1",
                                },
                            }
                        ],
                        "pullRequestDependencies": [],
                    },
                }
            },
            {
                "claimPlannedPullRequestExecution": {
                    "plannedPullRequest": {
                        "id": "pr-1",
                        "position": 0,
                        "title": "PR 1",
                        "goal": "Ship the slice",
                        "deploymentTargetLabel": "apps/itera",
                        "repositoryTarget": {
                            "provider": "GITHUB",
                            "owner": "iteraai",
                            "repoName": "Web",
                            "mainBranchName": "main",
                            "basePath": "",
                            "stableRepositoryId": "repo-1",
                        },
                        "execution": {
                            "status": "IMPLEMENTING",
                            "branchName": "itera/frontpage-42/pr-1",
                            "claimedByUser": {"username": "thor"},
                            "providerPullRequestNumber": None,
                            "providerPullRequestUrl": None,
                        },
                    }
                }
            },
        ]

        result = execute_approved_plan.run_execution("FRONTPAGE-42")

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(
            result["plan"]["suggestedBranchName"], "itera/frontpage-42/pr-1"
        )
        self.assertEqual(result["execution"]["executionState"], "IMPLEMENTING")
        self.assertEqual(
            result["implementationContext"]["selectedPlannedPullRequest"]["id"], "pr-1"
        )
        self.assertEqual(
            result["implementationContext"]["currentPlan"]["id"],
            "plan-1",
        )


if __name__ == "__main__":
    unittest.main()
