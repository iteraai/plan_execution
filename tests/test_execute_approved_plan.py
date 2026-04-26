from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "execute-approved-plan" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import execute_approved_plan


def _build_prototype_reference(media_id: str = "media-123") -> dict[str, object]:
    return {
        "prototypeHandoffArtifactId": "handoff-1",
        "prototypeIterationId": "prototype-1",
        "checkpointId": "checkpoint-1",
        "prototypeCodeMedia": {
            "id": media_id,
            "type": "PATCH",
            "status": "COMPLETED",
        },
        "references": [],
    }


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
    @mock.patch("execute_approved_plan._download_private_media_bytes")
    def test_run_execution_downloads_prototype_media_via_download_information(
        self,
        download_private_media_bytes: mock.Mock,
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
        download_private_media_bytes.return_value = b"diff --git a/foo b/foo\n"
        selected_specification = {
            "id": "spec-1",
            "sourceTaskSpecificationId": "task-spec-1",
            "type": "USER_UI",
            "typeLabel": "User UI",
            "customTypeLabel": "Custom spec",
            "title": "Match the prototype dashboard UI",
            "deltaExplanation": "Explain delta",
            "before": "Before",
            "after": "After",
            "target": "Target",
            "rule": "Rule",
            "inferredFromPrecedent": False,
            "prototypeReference": _build_prototype_reference(),
        }

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getNextReadyPlannedPullRequestForTask" in query:
                return {
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
                            "specifications": [copy.deepcopy(selected_specification)],
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
                            "execution": {
                                "status": "PLANNED",
                                "branchName": None,
                                "claimedByUser": None,
                            },
                        },
                        "unavailableReason": None,
                    }
                }
            if "query GetIterationTaskContext" in query:
                return {
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
                                    "specifications": [
                                        copy.deepcopy(selected_specification)
                                    ],
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
                }
            if "claimPlannedPullRequestExecution" in query:
                return {
                    "claimPlannedPullRequestExecution": {
                        "plannedPullRequest": {
                            "id": "pr-1",
                            "position": 0,
                            "title": "PR 1",
                            "goal": "Ship the slice",
                            "deploymentTargetLabel": "apps/itera",
                            "allowedPathPrefixes": ["src"],
                            "mainTouchPoints": ["backend", "frontend"],
                            "modelsToCreate": ["m1"],
                            "newApiContracts": ["v1"],
                            "specifications": [copy.deepcopy(selected_specification)],
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
                }
            if "generateDownloadInformation" in query:
                self.assertEqual(variables, {"mediaId": "media-123"})
                return {
                    "generateDownloadInformation": {
                        "url": "https://downloads.example.com/media-123?signature=abc",
                        "expiration": "2026-04-21T00:00:00Z",
                    }
                }
            self.fail(f"Unexpected GraphQL query: {query}")

        execute_graphql.side_effect = graphql_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                execute_approved_plan,
                "DEFAULT_OUTPUT_ROOT",
                Path(temp_dir),
            ):
                result = execute_approved_plan.run_execution("FRONTPAGE-42")
                self.assertTrue(
                    Path(result["prototypeCodeMediaDownloads"][0]["localFile"]).exists()
                )

        self.assertEqual(result["status"], "SUCCESS")
        download_private_media_bytes.assert_called_once_with(
            "https://downloads.example.com/media-123?signature=abc",
            timeout_seconds=30.0,
        )
        self.assertEqual(
            result["prototypeCodeMediaDownloads"][0]["downloadInformationExpiration"],
            "2026-04-21T00:00:00Z",
        )
        self.assertTrue(
            result["prototypeCodeMediaDownloads"][0]["mustReviewBeforeImplementation"]
        )
        self.assertEqual(
            result["implementationContext"]["selectedPlannedPullRequest"][
                "specifications"
            ][0]["prototypeReference"]["prototypeCodeMediaLocalFile"],
            result["prototypeCodeMediaDownloads"][0]["localFile"],
        )
        self.assertTrue(
            result["implementationContext"]["selectedPlannedPullRequest"][
                "prototypeImplementationGuidance"
            ]["requiresPixelPerfectUiImplementation"]
        )
        self.assertIn(
            "pixel-perfect",
            result["prototypeImplementationGuidance"]["instructionSummary"],
        )

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
                        "specifications": [
                            {
                                "id": "spec-1",
                                "sourceTaskSpecificationId": "task-spec-1",
                                "type": "CUSTOM",
                                "typeLabel": "Custom",
                                "customTypeLabel": "Custom spec",
                                "title": "Spec title",
                                "deltaExplanation": "Explain delta",
                                "before": "Before",
                                "after": "After",
                                "target": "Target",
                                "rule": "Rule",
                                "inferredFromPrecedent": False,
                            },
                        ],
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
                                "specifications": [
                                    {
                                        "id": "spec-1",
                                        "sourceTaskSpecificationId": "task-spec-1",
                                        "type": "CUSTOM",
                                        "typeLabel": "Custom",
                                        "customTypeLabel": "Custom spec",
                                        "title": "Spec title",
                                        "deltaExplanation": "Explain delta",
                                        "before": "Before",
                                        "after": "After",
                                        "target": "Target",
                                        "rule": "Rule",
                                        "inferredFromPrecedent": False,
                                    },
                                ],
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
            result["implementationContext"]["selectedPlannedPullRequest"][
                "specifications"
            ],
            [
                {
                    "id": "spec-1",
                    "sourceTaskSpecificationId": "task-spec-1",
                    "type": "CUSTOM",
                    "typeLabel": "Custom",
                    "customTypeLabel": "Custom spec",
                    "title": "Spec title",
                    "deltaExplanation": "Explain delta",
                    "before": "Before",
                    "after": "After",
                    "target": "Target",
                    "rule": "Rule",
                    "inferredFromPrecedent": False,
                },
            ],
        )
        self.assertEqual(
            result["implementationContext"]["currentPlan"]["id"],
            "plan-1",
        )

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_claims_specific_planned_pr(
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
        planned_pull_request = {
            "id": "pr-2",
            "position": 1,
            "title": "PR 2",
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
            "execution": {
                "status": "PLANNED",
                "branchName": None,
                "claimedByUser": None,
            },
        }

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
                    "getIterationTaskByCanonicalId": {
                        "id": "task-1",
                        "canonicalId": "FRONTPAGE-42",
                        "status": "READY_TO_BUILD",
                        "currentPlan": {
                            "id": "plan-1",
                            "pullRequests": [copy.deepcopy(planned_pull_request)],
                            "pullRequestDependencies": [],
                        },
                    }
                }
            if "claimPlannedPullRequestExecution" in query:
                self.assertEqual(
                    variables,
                    {
                        "plannedPullRequestId": "pr-2",
                        "branchName": "itera/frontpage-42/pr-2",
                    },
                )
                claimed = copy.deepcopy(planned_pull_request)
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

        result = execute_approved_plan.run_execution(
            "FRONTPAGE-42",
            planned_pull_request_id="pr-2",
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(
            result["plan"]["suggestedBranchName"], "itera/frontpage-42/pr-2"
        )
        self.assertEqual(result["execution"]["executionState"], "IMPLEMENTING")


if __name__ == "__main__":
    unittest.main()
