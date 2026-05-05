from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "download-pr-specification"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_pr_specification


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


def _build_task_payload() -> dict[str, object]:
    return {
        "id": "task-1",
        "canonicalId": "FRONTPAGE-42",
        "owner": {"username": "thor"},
        "projectId": "project-1",
        "initialIntent": "Build the PR context downloader",
        "name": "Download PR context",
        "contextProblem": "Agents need PR-specific build context.",
        "goalDescription": "Ship a PR specification downloader.",
        "successCriteria": "Agents can import the PR snapshot.",
        "outOfScope": "No mutations.",
        "phase": "READY_TO_BUILD",
        "status": "READY_TO_BUILD",
        "productCodexSessionId": None,
        "engineeringCodexSessionId": None,
        "planningCodexSessionId": None,
        "createdAt": "2026-04-15T08:00:00Z",
        "updatedAt": "2026-04-15T08:05:00Z",
        "repositorySnapshots": [
            {
                "id": "snapshot-1",
                "position": 0,
                "commitSha": "abc123",
                "repositoryConfiguration": {
                    "provider": "GITHUB",
                    "owner": "iteraai",
                    "repoName": "plan_execution",
                    "mainBranchName": "main",
                    "basePath": "",
                    "stableRepositoryId": "repo-1",
                    "providerMetadata": None,
                },
            }
        ],
        "freeformInputs": [],
        "taskRuns": [
            {
                "id": "run-1",
                "taskId": "task-1",
                "phase": "PLANNING",
                "status": "FINISHED",
                "trigger": {"kind": "TASK_CREATED", "id": None},
                "source": {"kind": "MEMBER", "actorId": "thor"},
                "traceId": None,
                "enqueuedAt": "2026-04-15T08:00:00Z",
                "processingStartedAt": "2026-04-15T08:01:00Z",
                "completedAt": "2026-04-15T08:02:00Z",
                "summary": "Planned the work.",
                "createdAt": "2026-04-15T08:00:00Z",
                "updatedAt": "2026-04-15T08:02:00Z",
                "artifactReferences": [],
                "prototypeHandoffArtifact": None,
                "questions": [],
                "specifications": [],
            }
        ],
        "questions": [
            {
                "id": "question-1",
                "taskRunId": "run-1",
                "category": "TECHNICAL",
                "target": "cli",
                "question": "Should the PR context include dependencies?",
                "suggestedAnswers": ["Yes"],
                "answer": "",
                "answeredByUserId": None,
                "answeredAt": None,
            }
        ],
        "specifications": [
            {
                "id": "spec-1",
                "taskRunId": "run-1",
                "questionId": None,
                "category": "TECHNICAL",
                "type": "API_CONTRACT",
                "typeLabel": "API Contract",
                "customTypeLabel": None,
                "title": "Use task specs in the selected PR snapshot",
                "deltaExplanation": "PR context should preserve upstream task intent.",
                "before": "PR specs have no upstream detail.",
                "after": "Selected PR specs include source task spec data.",
                "target": "planned-pr",
                "rule": "Selected PR specs should preserve task intent.",
                "status": "ACCEPTED",
                "answer": None,
                "answeredByUserId": None,
                "answeredAt": None,
                "reviewFeedback": None,
                "reviewedByUserId": None,
                "reviewedAt": None,
                "originalProposalId": None,
                "inferredFromPrecedent": False,
                "prototypeReference": None,
            }
        ],
        "currentHumanBlocker": None,
        "jiraWorkItemLink": None,
        "linkedPrototypeIteration": None,
        "currentPlan": {
            "id": "plan-1",
            "taskRunId": "run-1",
            "createdAt": "2026-04-15T08:00:00Z",
            "updatedAt": "2026-04-15T08:02:00Z",
            "pullRequests": [
                {
                    "id": "pr-1",
                    "position": 0,
                    "title": "PR 1",
                    "goal": "Prepare the shared runtime helpers",
                    "repositoryTarget": {
                        "provider": "GITHUB",
                        "owner": "iteraai",
                        "repoName": "plan_execution",
                        "mainBranchName": "main",
                        "basePath": "",
                        "stableRepositoryId": "repo-1",
                    },
                    "deploymentTargetLabel": "skill",
                    "allowedPathPrefixes": ["skills"],
                    "mainTouchPoints": ["skills/execute-approved-plan"],
                    "modelsToCreate": [],
                    "newApiContracts": ["execute-approved-plan"],
                    "specifications": [],
                    "state": "MERGED",
                    "execution": {
                        "status": "MERGED",
                        "branchName": "itera/frontpage-42/pr-1",
                        "manualEvidenceOverride": None,
                        "claimedByUser": {"username": "thor"},
                        "providerPullRequestNumber": 11,
                        "providerPullRequestUrl": "https://github.com/iteraai/plan_execution/pull/11",
                    },
                },
                {
                    "id": "pr-2",
                    "position": 1,
                    "title": "PR 2",
                    "goal": "Ship the PR downloader",
                    "repositoryTarget": {
                        "provider": "GITHUB",
                        "owner": "iteraai",
                        "repoName": "plan_execution",
                        "mainBranchName": "main",
                        "basePath": "",
                        "stableRepositoryId": "repo-1",
                    },
                    "deploymentTargetLabel": "skill",
                    "allowedPathPrefixes": ["skills", "tests"],
                    "mainTouchPoints": ["skills/download-pr-specification"],
                    "modelsToCreate": [],
                    "newApiContracts": ["download-pr-specification"],
                    "specifications": [
                        {
                            "id": "plan-spec-1",
                            "sourceTaskSpecificationId": "spec-1",
                            "type": "API_CONTRACT",
                            "typeLabel": "API Contract",
                            "customTypeLabel": None,
                            "title": "Crosswalk upstream task specs",
                            "deltaExplanation": "Preserve upstream task detail in the selected PR.",
                            "before": "PR specs lose task context.",
                            "after": "Selected PR specs include task context.",
                            "target": "selected-pr",
                            "rule": "Selected PR context should preserve source task specs.",
                            "inferredFromPrecedent": False,
                            "prototypeReference": None,
                        }
                    ],
                    "state": "READY_UNCLAIMED",
                    "execution": {
                        "status": "PLANNED",
                        "branchName": None,
                        "manualEvidenceOverride": None,
                        "claimedByUser": None,
                        "providerPullRequestNumber": None,
                        "providerPullRequestUrl": None,
                    },
                },
            ],
            "pullRequestDependencies": [
                {
                    "id": "dependency-1",
                    "pullRequestId": "pr-2",
                    "dependsOnPullRequestId": "pr-1",
                }
            ],
        },
    }


class DownloadPrSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        download_pr_specification.auth_refresh._warned_about_windows_permission_fallback = (
            False
        )

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    @mock.patch("download_pr_specification._download_private_media_bytes")
    def test_run_download_downloads_prototype_media_via_download_information(
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
        task_payload = _build_task_payload()
        task_payload["specifications"][0]["type"] = "USER_UI"
        task_payload["specifications"][0]["typeLabel"] = "User UI"
        task_payload["specifications"][0]["title"] = "Match the dashboard UI"
        task_payload["specifications"][0][
            "prototypeReference"
        ] = _build_prototype_reference()
        task_payload["currentPlan"]["pullRequests"][1]["specifications"][0][
            "type"
        ] = "USER_UI"
        task_payload["currentPlan"]["pullRequests"][1]["specifications"][0][
            "typeLabel"
        ] = "User UI"
        task_payload["currentPlan"]["pullRequests"][1]["specifications"][0][
            "title"
        ] = "Match the dashboard UI"
        task_payload["currentPlan"]["pullRequests"][1]["specifications"][0][
            "prototypeReference"
        ] = _build_prototype_reference()

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getIterationTaskByCanonicalId" in query:
                return {"getIterationTaskByCanonicalId": task_payload}
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
            output_file = Path(temp_dir) / "pr.json"
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=output_file,
            )

            self.assertEqual(result["status"], "SUCCESS")
            download_private_media_bytes.assert_called_once_with(
                "https://downloads.example.com/media-123?signature=abc",
                timeout_seconds=30.0,
            )
            self.assertEqual(
                result["prototypeCodeMediaDownloads"][0][
                    "downloadInformationExpiration"
                ],
                "2026-04-21T00:00:00Z",
            )
            self.assertTrue(
                Path(result["prototypeCodeMediaDownloads"][0]["localFile"]).exists()
            )
            self.assertTrue(
                result["prototypeCodeMediaDownloads"][0][
                    "mustReviewBeforeImplementation"
                ]
            )
            self.assertEqual(
                result["plannedPullRequest"]["specifications"][0]["prototypeReference"][
                    "prototypeCodeMediaLocalFile"
                ],
                result["prototypeCodeMediaDownloads"][0]["localFile"],
            )
            self.assertTrue(
                result["prototypeImplementationGuidance"][
                    "requiresPixelPerfectUiImplementation"
                ]
            )
            self.assertIn(
                "pixel-perfect",
                result["prototypeImplementationGuidance"]["instructionSummary"],
            )
            self.assertIn(
                "Never build a Canvas page",
                result["prototypeImplementationGuidance"]["instructionSummary"],
            )
            self.assertIn(
                "Use prototype canvas files, fixtures, and manifests only to understand component states and variants.",
                result["prototypeImplementationGuidance"]["requirements"],
            )
            self.assertIn(
                "Never build a Canvas page",
                result["prototypeCodeMediaDownloads"][0]["usageSummary"],
            )

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_selects_pr_and_crosswalks_source_specs(
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
            "getIterationTaskByCanonicalId": _build_task_payload()
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "pr.json"
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=output_file,
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["plannedPullRequest"]["id"], "pr-2")
            self.assertEqual(
                result["buildContext"]["sourceTaskSpecifications"][0]["id"],
                "spec-1",
            )
            self.assertEqual(
                result["buildContext"]["dependencyContext"]["dependsOn"][0]["id"],
                "pr-1",
            )
            self.assertEqual(result["snapshotFile"], str(output_file))
            self.assertTrue(output_file.exists())
            if os.name != "nt":
                mode = stat.S_IMODE(output_file.stat().st_mode)
                self.assertEqual(
                    mode,
                    download_pr_specification.auth_refresh.PRIVATE_FILE_MODE,
                )

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_returns_pr_not_found(
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
            "getIterationTaskByCanonicalId": _build_task_payload()
        }

        result = download_pr_specification.run_download(
            "FRONTPAGE-42",
            pull_request_position=3,
        )

        self.assertEqual(result["status"], "PR_NOT_FOUND")
        self.assertIsNone(result["plannedPullRequest"])

    @mock.patch("download_pr_specification.auth_refresh.os.chmod")
    def test_write_json_artifact_notices_inherited_windows_acls(
        self,
        chmod: mock.Mock,
    ) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "pr.json"
            with contextlib.redirect_stderr(stderr):
                with mock.patch(
                    "download_pr_specification.auth_refresh.is_windows_platform",
                    return_value=True,
                ):
                    download_pr_specification.write_json_artifact(
                        output_file,
                        {"canonicalTaskId": "FRONTPAGE-42", "pullRequestId": "pr-2"},
                    )
            self.assertTrue(output_file.exists())

        chmod.assert_not_called()
        self.assertEqual(
            stderr.getvalue().count(
                download_pr_specification.auth_refresh.WINDOWS_PERMISSION_FALLBACK_WARNING
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
