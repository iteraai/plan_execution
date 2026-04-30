from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "download-itera-diagnostics"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_itera_diagnostics

LOG_MEDIA_ID = "11111111-1111-4111-8111-111111111111"


def _session() -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "username": "admin",
            "account_email": "admin@example.com",
            "token": "access-token",
        },
        {"email": "admin@example.com", "profile": {"username": "admin"}},
    )


def _organization() -> dict[str, object]:
    return {
        "identifier": "acme",
        "name": "Acme",
        "domain": "acme.example",
        "createdAt": "2026-04-28T08:00:00Z",
        "viewerIsAdmin": True,
        "requireTotp": True,
        "mfaRequiredSince": "2026-04-01T00:00:00Z",
        "openAiTokenConfigured": True,
    }


def _project(project_id: str, title: str) -> dict[str, object]:
    return {
        "id": project_id,
        "title": title,
        "status": "ACTIVE",
        "repositoryProvider": "GITHUB",
        "organization": {
            "identifier": "acme",
            "name": "Acme",
            "viewerIsAdmin": True,
        },
    }


def _failure_entry(
    entry_id: str = "failure-1",
    *,
    project_id: str = "project-1",
    canonical_task_id: str = "ITERA-42",
    media_id: str = LOG_MEDIA_ID,
) -> dict[str, object]:
    return {
        "id": entry_id,
        "failureKind": "TASK_RUN",
        "organization": {
            "identifier": "acme",
            "name": "Acme",
            "viewerIsAdmin": True,
        },
        "projectId": project_id,
        "projectTitle": "Runtime",
        "taskId": "task-1",
        "taskCanonicalId": canonical_task_id,
        "taskName": "Fix startup",
        "taskPhase": "BUILDING",
        "summary": "Task run failed",
        "failureDetail": "Runtime command exited with 1.",
        "failedAt": "2026-04-28T09:15:00Z",
        "createdAt": "2026-04-28T09:12:00Z",
        "updatedAt": "2026-04-28T09:15:00Z",
        "logReference": {
            "kind": "LOG",
            "bucket": "ara-meet-media-staging",
            "key": f"task-runs/project/JSON/{media_id}",
        },
        "taskRun": {
            "id": "run-1",
            "phase": "ENGINEERING",
            "status": "FAILED",
            "triggerKind": "FOLLOW_UP_SUBMITTED",
            "triggerId": "trigger-1",
            "sourceKind": "MEMBER",
            "sourceActorId": "user-1",
            "traceId": "trace-1",
            "enqueuedAt": "2026-04-28T09:10:00Z",
            "processingStartedAt": "2026-04-28T09:12:00Z",
            "completedAt": "2026-04-28T09:15:00Z",
            "createdAt": "2026-04-28T09:10:00Z",
            "updatedAt": "2026-04-28T09:15:00Z",
        },
        "prototypeStartup": None,
    }


def _task() -> dict[str, object]:
    return {
        "id": "task-1",
        "canonicalId": "ITERA-42",
        "projectId": "project-1",
        "owner": {"username": "admin"},
        "name": "Fix startup",
        "contextProblem": "Startup fails.",
        "goalDescription": "Make diagnostics clear.",
        "successCriteria": "Task can be retried.",
        "outOfScope": "No mutations.",
        "phase": "BUILDING",
        "status": "FAILED",
        "productCodexSessionId": None,
        "engineeringCodexSessionId": None,
        "planningCodexSessionId": None,
        "createdAt": "2026-04-28T09:00:00Z",
        "updatedAt": "2026-04-28T09:15:00Z",
        "taskRuns": [],
        "currentHumanBlocker": None,
        "currentPlan": None,
    }


class DownloadIteraDiagnosticsTests(unittest.TestCase):
    @mock.patch("download_itera_diagnostics.ensure_authenticated_context")
    @mock.patch("download_itera_diagnostics.graphql_client.execute_graphql")
    def test_run_download_writes_successful_project_diagnostics(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = _session()

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getOrganization" in query:
                self.assertEqual(variables, {"organizationId": "acme"})
                return {"getOrganization": _organization()}
            if "getIterationTaskByCanonicalId" in query:
                self.assertEqual(variables, {"canonicalId": "ITERA-42"})
                return {"getIterationTaskByCanonicalId": _task()}
            if "getProjectFailureReviewEntries" in query:
                self.assertEqual(
                    variables,
                    {"projectId": "project-1", "page": 2, "pageSize": 25},
                )
                return {"getProjectFailureReviewEntries": [_failure_entry()]}
            self.fail(f"Unexpected GraphQL query: {query}")

        execute_graphql.side_effect = graphql_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "diagnostics.json"
            result = download_itera_diagnostics.run_download(
                "acme",
                project_id="project-1",
                canonical_task_id="ITERA-42",
                page=2,
                page_size=25,
                include_retained_logs=False,
                output_file=output_file,
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["diagnosticsFile"], str(output_file))
            self.assertTrue(output_file.exists())
            self.assertEqual(result["failureReview"]["scope"], "PROJECT")
            self.assertEqual(len(result["failureReview"]["entries"]), 1)
            self.assertEqual(len(result["failureReview"]["matchingEntries"]), 1)
            self.assertEqual(result["task"]["canonicalId"], "ITERA-42")

    @mock.patch("download_itera_diagnostics.ensure_authenticated_context")
    @mock.patch("download_itera_diagnostics.graphql_client.execute_graphql")
    def test_run_download_collects_failure_entries_for_each_org_project(
        self,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = _session()
        project_entries = {
            "project-1": [_failure_entry("failure-1", project_id="project-1")],
            "project-2": [
                _failure_entry(
                    "failure-2",
                    project_id="project-2",
                    canonical_task_id="ITERA-99",
                )
            ],
        }

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getOrganization" in query:
                return {"getOrganization": _organization()}
            if "getProjects" in query:
                self.assertEqual(variables, {"organizationId": "acme"})
                return {
                    "getProjects": [
                        _project("project-1", "Runtime"),
                        _project("project-2", "Prototype"),
                    ]
                }
            if "getProjectFailureReviewEntries" in query:
                self.assertEqual(variables["page"], 1)
                self.assertEqual(variables["pageSize"], 10)
                return {
                    "getProjectFailureReviewEntries": project_entries[
                        str(variables["projectId"])
                    ]
                }
            self.fail(f"Unexpected GraphQL query: {query}")

        execute_graphql.side_effect = graphql_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            result = download_itera_diagnostics.run_download(
                "acme",
                include_retained_logs=False,
                output_file=Path(temp_dir) / "diagnostics.json",
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["failureReview"]["scope"], "ORGANIZATION_PROJECTS")
            self.assertEqual(len(result["projects"]), 2)
            self.assertEqual(len(result["failureReview"]["projectSets"]), 2)
            self.assertEqual(len(result["failureReview"]["entries"]), 2)

    def test_inspect_local_itera_yaml_redacts_token_like_values(self) -> None:
        class FakeYaml:
            @staticmethod
            def safe_load(raw_text: str) -> dict[str, object]:
                self.assertIn("apiToken", raw_text)
                return {
                    "apiToken": "secret-token",
                    "nested": {"refresh_token": "refresh-secret"},
                    "visible": "keep-me",
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            (repo_path / "itera.yaml").write_text(
                "\n".join(
                    [
                        "apiToken: secret-token",
                        "nested:",
                        "  refresh_token: refresh-secret",
                        "visible: keep-me",
                    ]
                )
                + "\n"
            )

            with mock.patch(
                "download_itera_diagnostics._load_yaml_module",
                return_value=FakeYaml,
            ):
                result = download_itera_diagnostics.inspect_local_itera_yaml(repo_path)

            serialized = json.dumps(result)
            self.assertEqual(result["parseMode"], "pyyaml")
            self.assertIn("keep-me", serialized)
            self.assertNotIn("secret-token", serialized)
            self.assertNotIn("refresh-secret", serialized)
            self.assertEqual(result["parsedYaml"]["apiToken"], "[REDACTED]")

    @mock.patch("download_itera_diagnostics.ensure_authenticated_context")
    @mock.patch("download_itera_diagnostics.graphql_client.execute_graphql")
    @mock.patch("download_itera_diagnostics._download_private_media_bytes")
    def test_run_download_downloads_retained_log_artifact(
        self,
        download_private_media_bytes: mock.Mock,
        execute_graphql: mock.Mock,
        ensure_authenticated_context: mock.Mock,
    ) -> None:
        ensure_authenticated_context.return_value = _session()
        download_private_media_bytes.return_value = b'{"status":"failed"}\n'

        def graphql_side_effect(
            query: str,
            variables: dict[str, object] | None = None,
            *,
            token: str | None = None,
            config: object | None = None,
        ) -> dict[str, object]:
            del token, config
            if "getOrganization" in query:
                return {"getOrganization": _organization()}
            if "getProjectFailureReviewEntries" in query:
                return {"getProjectFailureReviewEntries": [_failure_entry()]}
            if "generateDownloadInformation" in query:
                self.assertEqual(variables, {"mediaId": LOG_MEDIA_ID})
                return {
                    "generateDownloadInformation": {
                        "url": f"https://downloads.example.com/{LOG_MEDIA_ID}.json",
                        "expiration": "2026-04-29T00:00:00Z",
                    }
                }
            self.fail(f"Unexpected GraphQL query: {query}")

        execute_graphql.side_effect = graphql_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "diagnostics.json"
            result = download_itera_diagnostics.run_download(
                "acme",
                project_id="project-1",
                output_file=output_file,
            )

            self.assertEqual(result["status"], "SUCCESS")
            download_private_media_bytes.assert_called_once_with(
                f"https://downloads.example.com/{LOG_MEDIA_ID}.json",
                timeout_seconds=30.0,
            )
            download = result["retainedLogDownloads"][0]
            self.assertEqual(download["downloadStatus"], "DOWNLOADED")
            self.assertEqual(
                download["downloadInformationExpiration"],
                "2026-04-29T00:00:00Z",
            )
            self.assertTrue(Path(download["localFile"]).exists())
            self.assertEqual(
                Path(download["localFile"]).parent,
                output_file.parent / "retained_logs",
            )

    def test_run_download_returns_auth_required_without_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = download_itera_diagnostics.run_download(
                "acme",
                session_file=Path(temp_dir) / "missing-session.json",
                interactive=False,
            )

        self.assertEqual(result["status"], "AUTH_REQUIRED")
        self.assertIsNone(result["diagnosticsFile"])
        self.assertIn("valid Itera session", result["message"])


if __name__ == "__main__":
    unittest.main()
