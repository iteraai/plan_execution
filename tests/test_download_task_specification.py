from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "download-task-specification"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_task_specification


def _build_task_payload() -> dict[str, object]:
    return {
        "id": "task-1",
        "canonicalId": "FRONTPAGE-42",
        "owner": {"username": "thor"},
        "projectId": "project-1",
        "initialIntent": "Build the task context downloader",
        "name": "Download task context",
        "contextProblem": "Agents need durable coding context.",
        "goalDescription": "Ship a task specification downloader.",
        "successCriteria": "Agents can import a JSON snapshot.",
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
                "question": "Should the skill write a file?",
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
                "title": "Write a durable JSON snapshot",
                "deltaExplanation": "Agents need durable imports.",
                "before": "No snapshot file exists.",
                "after": "A durable JSON artifact is written.",
                "target": "skill-output",
                "rule": "The task snapshot must be readable by downstream agents.",
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
                    "goal": "Ship the downloader",
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
                    "mainTouchPoints": ["skills", "install.py"],
                    "modelsToCreate": [],
                    "newApiContracts": ["download-task-specification"],
                    "specifications": [
                        {
                            "id": "plan-spec-1",
                            "sourceTaskSpecificationId": "spec-1",
                            "type": "API_CONTRACT",
                            "typeLabel": "API Contract",
                            "customTypeLabel": None,
                            "title": "Use the accepted task spec",
                            "deltaExplanation": "Carry task intent to the PR.",
                            "before": "No PR spec crosswalk exists.",
                            "after": "PR specs point back to task specs.",
                            "target": "planned-pr",
                            "rule": "PR specs should preserve source task specs.",
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
                }
            ],
            "pullRequestDependencies": [],
        },
    }


class DownloadTaskSpecificationTests(unittest.TestCase):
    @mock.patch("download_task_specification.ensure_authenticated_context")
    @mock.patch("download_task_specification.graphql_client.execute_graphql")
    def test_run_download_writes_snapshot_and_build_context(
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
            output_file = Path(temp_dir) / "task.json"
            result = download_task_specification.run_download(
                "FRONTPAGE-42",
                output_file=output_file,
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["snapshotFile"], str(output_file))
            self.assertTrue(output_file.exists())
            self.assertEqual(
                result["buildContext"]["currentPlan"]["pullRequests"][0][
                    "remoteRepositoryUrl"
                ],
                "https://github.com/iteraai/plan_execution",
            )
            self.assertEqual(
                result["buildContext"]["specificationSummary"]["byStatus"]["ACCEPTED"],
                1,
            )
            self.assertEqual(
                len(result["buildContext"]["questionSummary"]["openQuestions"]),
                1,
            )

    @mock.patch("download_task_specification.ensure_authenticated_context")
    @mock.patch("download_task_specification.graphql_client.execute_graphql")
    def test_run_download_returns_not_found(
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
        execute_graphql.return_value = {"getIterationTaskByCanonicalId": None}

        result = download_task_specification.run_download("FRONTPAGE-42")

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertIsNone(result["snapshotFile"])


if __name__ == "__main__":
    unittest.main()
