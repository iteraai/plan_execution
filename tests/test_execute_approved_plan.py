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


def _prototype_reference(
    *,
    media_id: str | None = "media-123",
    handoff_artifact_id: str = "handoff-123",
    prototype_iteration_id: str = "iteration-123",
    checkpoint_id: str = "checkpoint-123",
) -> dict[str, object]:
    return {
        "prototypeHandoffArtifactId": handoff_artifact_id,
        "prototypeIterationId": prototype_iteration_id,
        "checkpointId": checkpoint_id,
        "prototypeCodeMedia": {"id": media_id} if media_id else None,
        "references": [{"source": "CHECKPOINT", "sourceId": checkpoint_id}],
    }


def _build_planned_pr_specification(
    specification_id: str,
    *,
    prototype_reference: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": specification_id,
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
        "prototypeReference": prototype_reference,
    }


def _build_next_ready_payload(
    *, specifications: list[dict[str, object]]
) -> dict[str, object]:
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
                "specifications": specifications,
                "deploymentTargetLabel": "skills",
                "repositoryTarget": {
                    "provider": "GITHUB",
                    "owner": "iteraai",
                    "repoName": "plan_execution",
                    "mainBranchName": "main",
                    "basePath": "",
                    "stableRepositoryId": "repo-1",
                },
                "execution": {
                    "status": "PLANNED",
                    "branchName": None,
                    "claimedByUser": None,
                    "providerPullRequestNumber": None,
                    "providerPullRequestUrl": None,
                },
            },
            "unavailableReason": None,
        }
    }


def _build_task_context_payload(
    *, specifications: list[dict[str, object]]
) -> dict[str, object]:
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
                        "specifications": specifications,
                        "deploymentTargetLabel": "skills",
                        "allowedPathPrefixes": ["skills", "tests"],
                        "mainTouchPoints": ["skills/download-pr-specification"],
                        "modelsToCreate": ["m1"],
                        "newApiContracts": ["v1"],
                        "repositoryTarget": {
                            "provider": "GITHUB",
                            "owner": "iteraai",
                            "repoName": "plan_execution",
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


def _build_claimed_pr_payload() -> dict[str, object]:
    return {
        "claimPlannedPullRequestExecution": {
            "plannedPullRequest": {
                "id": "pr-1",
                "position": 0,
                "title": "PR 1",
                "goal": "Ship the slice",
                "deploymentTargetLabel": "skills",
                "repositoryTarget": {
                    "provider": "GITHUB",
                    "owner": "iteraai",
                    "repoName": "plan_execution",
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


def _mock_http_response(payload: bytes) -> mock.MagicMock:
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = payload
    return response


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
        self.assertEqual(result["prototypeCodeArtifacts"], [])

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.request.urlopen")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_downloads_patch_into_implementation_context(
        self,
        execute_graphql: mock.Mock,
        urlopen: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        specifications = [
            _build_planned_pr_specification(
                "spec-1",
                prototype_reference=_prototype_reference(),
            )
        ]
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            _build_next_ready_payload(specifications=copy.deepcopy(specifications)),
            _build_task_context_payload(specifications=copy.deepcopy(specifications)),
            {
                "generateDownloadInformation": {
                    "url": "https://downloads.example/media-123"
                }
            },
            _build_claimed_pr_payload(),
        ]
        urlopen.return_value = _mock_http_response(b"diff --git a/skill b/skill\n")

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_root = Path(temp_dir)
            with mock.patch.object(
                execute_approved_plan,
                "DEFAULT_EXECUTION_OUTPUT_ROOT",
                artifact_root,
            ):
                result = execute_approved_plan.run_execution("FRONTPAGE-42")
                expected_patch = (
                    artifact_root
                    / "frontpage-42"
                    / "pr-1"
                    / "prototype-patches"
                    / "handoff-123.patch"
                )
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(
                    result["plan"]["suggestedBranchName"],
                    "itera/frontpage-42/pr-1",
                )
                self.assertTrue(expected_patch.exists())
                self.assertEqual(
                    expected_patch.read_bytes(),
                    b"diff --git a/skill b/skill\n",
                )
                artifact = result["implementationContext"]["prototypeCodeArtifacts"][0]
                self.assertEqual(artifact["downloadStatus"], "DOWNLOADED")
                self.assertEqual(artifact["localPath"], str(expected_patch))
                self.assertEqual(artifact["usedBySpecificationIds"], ["spec-1"])
                self.assertEqual(
                    result["prototypeCodeArtifacts"][0]["localPath"],
                    str(expected_patch),
                )

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_keeps_empty_artifact_list_without_prototype_media(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        specifications = [_build_planned_pr_specification("spec-1")]
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            _build_next_ready_payload(specifications=copy.deepcopy(specifications)),
            _build_task_context_payload(specifications=copy.deepcopy(specifications)),
            _build_claimed_pr_payload(),
        ]

        result = execute_approved_plan.run_execution("FRONTPAGE-42")

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["prototypeCodeArtifacts"], [])
        self.assertEqual(
            result["implementationContext"]["prototypeCodeArtifacts"],
            [],
        )
        self.assertEqual(execute_graphql.call_count, 3)

    @mock.patch("execute_approved_plan.ensure_authenticated_context")
    @mock.patch("execute_approved_plan.request.urlopen")
    @mock.patch("execute_approved_plan.graphql_client.execute_graphql")
    def test_run_execution_records_partial_download_failures_without_blocking_claim(
        self,
        execute_graphql: mock.Mock,
        urlopen: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        specifications = [
            _build_planned_pr_specification(
                "spec-1",
                prototype_reference=_prototype_reference(media_id="media-404"),
            )
        ]
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            _build_next_ready_payload(specifications=copy.deepcopy(specifications)),
            _build_task_context_payload(specifications=copy.deepcopy(specifications)),
            {
                "generateDownloadInformation": {
                    "url": "https://downloads.example/media-404"
                }
            },
            _build_claimed_pr_payload(),
        ]
        urlopen.side_effect = OSError("download failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                execute_approved_plan,
                "DEFAULT_EXECUTION_OUTPUT_ROOT",
                Path(temp_dir),
            ):
                result = execute_approved_plan.run_execution("FRONTPAGE-42")

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["execution"]["executionState"], "IMPLEMENTING")
        artifact = result["implementationContext"]["prototypeCodeArtifacts"][0]
        self.assertEqual(artifact["downloadStatus"], "DOWNLOAD_FAILED")
        self.assertIsNone(artifact["localPath"])
        self.assertEqual(artifact["error"], "download failed")


if __name__ == "__main__":
    unittest.main()
