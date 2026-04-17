from __future__ import annotations

import contextlib
import io
import os
import copy
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
                        _build_planned_pr_specification("plan-spec-1"),
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
    source_task_specification_id: str = "spec-1",
) -> dict[str, object]:
    return {
        "id": specification_id,
        "sourceTaskSpecificationId": source_task_specification_id,
        "type": "API_CONTRACT",
        "typeLabel": "API Contract",
        "customTypeLabel": None,
        "title": f"Spec {specification_id}",
        "deltaExplanation": "Preserve upstream task detail in the selected PR.",
        "before": "PR specs lose task context.",
        "after": "Selected PR specs include task context.",
        "target": "selected-pr",
        "rule": "Selected PR context should preserve source task specs.",
        "inferredFromPrecedent": False,
        "prototypeReference": prototype_reference,
    }


def _set_selected_pr_specifications(
    task_payload: dict[str, object], specifications: list[dict[str, object]]
) -> dict[str, object]:
    selected_pull_request = task_payload["currentPlan"]["pullRequests"][1]
    selected_pull_request["specifications"] = specifications
    return task_payload


def _mock_http_response(payload: bytes) -> mock.MagicMock:
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = payload
    return response


class DownloadPrSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        download_pr_specification.auth_refresh._warned_about_windows_permission_fallback = (
            False
        )

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.request.urlopen")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_downloads_single_prototype_patch(
        self,
        execute_graphql: mock.Mock,
        urlopen: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        task_payload = _set_selected_pr_specifications(
            copy.deepcopy(_build_task_payload()),
            [
                _build_planned_pr_specification(
                    "plan-spec-1",
                    prototype_reference=_prototype_reference(),
                )
            ],
        )
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            {"getIterationTaskByCanonicalId": task_payload},
            {"generateDownloadInformation": {"url": "https://downloads.example/media-123"}},
        ]
        urlopen.return_value = _mock_http_response(b"diff --git a/ui b/ui\n")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "pr.json"
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=output_file,
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["plannedPullRequest"]["id"], "pr-2")
            self.assertEqual(len(result["prototypeCodeArtifacts"]), 1)
            artifact = result["prototypeCodeArtifacts"][0]
            expected_patch = (
                output_file.parent
                / "pr.artifacts"
                / "prototype-patches"
                / "handoff-123.patch"
            )
            self.assertEqual(artifact["mediaId"], "media-123")
            self.assertEqual(artifact["downloadStatus"], "DOWNLOADED")
            self.assertEqual(artifact["usedBySpecificationIds"], ["plan-spec-1"])
            self.assertEqual(artifact["localPath"], str(expected_patch))
            self.assertTrue(expected_patch.exists())
            self.assertEqual(
                expected_patch.read_bytes(),
                b"diff --git a/ui b/ui\n",
            )
            self.assertEqual(
                result["buildContext"]["prototypeCodeArtifacts"][0]["localPath"],
                str(expected_patch),
            )

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.request.urlopen")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_deduplicates_shared_media_ids(
        self,
        execute_graphql: mock.Mock,
        urlopen: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        shared_reference = _prototype_reference(
            media_id="media-555",
            handoff_artifact_id="handoff-555",
        )
        task_payload = _set_selected_pr_specifications(
            copy.deepcopy(_build_task_payload()),
            [
                _build_planned_pr_specification(
                    "plan-spec-1",
                    prototype_reference=shared_reference,
                ),
                _build_planned_pr_specification(
                    "plan-spec-2",
                    prototype_reference=shared_reference,
                    source_task_specification_id="spec-1",
                ),
            ],
        )
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            {"getIterationTaskByCanonicalId": task_payload},
            {"generateDownloadInformation": {"url": "https://downloads.example/media-555"}},
        ]
        urlopen.return_value = _mock_http_response(b"patch payload")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=Path(temp_dir) / "pr.json",
            )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["prototypeCodeArtifacts"]), 1)
        artifact = result["prototypeCodeArtifacts"][0]
        self.assertEqual(
            artifact["usedBySpecificationIds"],
            ["plan-spec-1", "plan-spec-2"],
        )
        self.assertEqual(artifact["downloadStatus"], "DOWNLOADED")
        self.assertEqual(execute_graphql.call_count, 2)
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_returns_empty_artifact_list_without_prototype_media(
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
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=Path(temp_dir) / "pr.json",
            )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["prototypeCodeArtifacts"], [])
        self.assertEqual(result["buildContext"]["prototypeCodeArtifacts"], [])
        self.assertEqual(execute_graphql.call_count, 1)

    @mock.patch("download_pr_specification.ensure_authenticated_context")
    @mock.patch("download_pr_specification.request.urlopen")
    @mock.patch("download_pr_specification.graphql_client.execute_graphql")
    def test_run_download_records_partial_download_failures(
        self,
        execute_graphql: mock.Mock,
        urlopen: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        task_payload = _set_selected_pr_specifications(
            copy.deepcopy(_build_task_payload()),
            [
                _build_planned_pr_specification(
                    "plan-spec-1",
                    prototype_reference=_prototype_reference(media_id="media-404"),
                )
            ],
        )
        ensure_authenticated_context.return_value = (
            {
                "username": "thor",
                "account_email": "thor@example.com",
                "token": "access-token",
            },
            {"email": "thor@example.com"},
        )
        execute_graphql.side_effect = [
            {"getIterationTaskByCanonicalId": task_payload},
            {"generateDownloadInformation": {"url": "https://downloads.example/media-404"}},
        ]
        urlopen.side_effect = OSError("download failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = download_pr_specification.run_download(
                "FRONTPAGE-42",
                pull_request_position=2,
                output_file=Path(temp_dir) / "pr.json",
            )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["prototypeCodeArtifacts"]), 1)
        artifact = result["prototypeCodeArtifacts"][0]
        self.assertEqual(artifact["downloadStatus"], "DOWNLOAD_FAILED")
        self.assertIsNone(artifact["localPath"])
        self.assertEqual(artifact["error"], "download failed")

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
        self.assertEqual(result["prototypeCodeArtifacts"], [])

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
