from __future__ import annotations

import contextlib
import io
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

import auth_login
import graphql_client


class AuthLoginTests(unittest.TestCase):
    @mock.patch("auth_login.auth_refresh.write_session")
    @mock.patch("auth_login.graphql_client.execute_graphql")
    @mock.patch("auth_login._prompt_value")
    def test_login_interactively_supports_authenticated_response(
        self,
        prompt_value: mock.Mock,
        execute_graphql: mock.Mock,
        write_session: mock.Mock,
    ) -> None:
        prompt_value.side_effect = ["thor@example.com", "123456"]
        execute_graphql.side_effect = [
            {"sendEmailVerificationCode": {"hasAccount": True}},
            {
                "loginWithEmailMfa": {
                    "status": "AUTHENTICATED",
                    "challengeId": None,
                    "token": "access-token",
                    "refreshToken": "refresh-token",
                    "username": "thor",
                }
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            session = auth_login.login_interactively(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )

        self.assertEqual(session["account_email"], "thor@example.com")
        self.assertEqual(session["username"], "thor")
        self.assertEqual(session["token"], "access-token")
        write_session.assert_called_once()

    @mock.patch("auth_login.auth_refresh.write_session")
    @mock.patch("auth_login.graphql_client.execute_graphql")
    @mock.patch("auth_login._prompt_value")
    def test_login_interactively_supports_totp_challenge(
        self,
        prompt_value: mock.Mock,
        execute_graphql: mock.Mock,
        write_session: mock.Mock,
    ) -> None:
        prompt_value.side_effect = [
            "thor@example.com",
            "123456",
            "654321",
        ]
        execute_graphql.side_effect = [
            {"sendEmailVerificationCode": {"hasAccount": True}},
            {
                "loginWithEmailMfa": {
                    "status": "TOTP_REQUIRED",
                    "challengeId": "challenge-1",
                    "token": None,
                    "refreshToken": None,
                    "username": "thor",
                }
            },
            {
                "completeEmailLoginWithTotp": {
                    "token": "access-token",
                    "refreshToken": "refresh-token",
                    "username": "thor",
                }
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            session = auth_login.login_interactively(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )

        self.assertEqual(session["token"], "access-token")
        write_session.assert_called_once()

    @mock.patch("auth_login.auth_refresh.write_session")
    @mock.patch("auth_login.graphql_client.execute_graphql")
    @mock.patch("auth_login._prompt_value")
    def test_login_interactively_enrollment_does_not_log_secrets(
        self,
        prompt_value: mock.Mock,
        execute_graphql: mock.Mock,
        write_session: mock.Mock,
    ) -> None:
        prompt_value.side_effect = [
            "thor@example.com",
            "123456",
            "654321",
        ]
        execute_graphql.side_effect = [
            {"sendEmailVerificationCode": {"hasAccount": True}},
            {
                "loginWithEmailMfa": {
                    "status": "TOTP_ENROLLMENT_REQUIRED",
                    "challengeId": None,
                    "token": "restricted-token",
                    "refreshToken": "restricted-refresh-token",
                    "username": "thor",
                }
            },
            {
                "beginTotpEnrollment": {
                    "secret": "VERY-SECRET",
                    "otpauthUri": "otpauth://totp/Itera:thor?secret=VERY-SECRET",
                }
            },
            {
                "confirmTotpEnrollment": {
                    "recoveryCodes": ["code-one", "code-two"],
                    "auth": {
                        "token": "access-token",
                        "refreshToken": "refresh-token",
                    },
                }
            },
        ]

        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            with contextlib.redirect_stderr(stderr):
                session = auth_login.login_interactively(
                    session_file=Path(temp_dir) / "iteraz.json",
                    config=graphql_client.GraphQLRequestConfig(),
                )

        self.assertEqual(session["token"], "access-token")
        self.assertEqual(session["refresh_token"], "refresh-token")
        self.assertIn(
            "TOTP enrollment is required for this account.", stderr.getvalue()
        )
        self.assertIn("intentionally not printed by this tool", stderr.getvalue())
        self.assertNotIn("VERY-SECRET", stderr.getvalue())
        self.assertNotIn(
            "otpauth://totp/Itera:thor?secret=VERY-SECRET", stderr.getvalue()
        )
        self.assertNotIn("code-one", stderr.getvalue())
        self.assertNotIn("code-two", stderr.getvalue())
        write_session.assert_called_once()

    def test_auth_login_script_copies_stay_in_sync(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        canonical = (
            repo_root / "skills" / "execute-approved-plan" / "scripts" / "auth_login.py"
        ).read_text()

        self.assertEqual(
            canonical,
            (
                repo_root
                / "skills"
                / "download-task-specification"
                / "scripts"
                / "auth_login.py"
            ).read_text(),
        )
        self.assertEqual(
            canonical,
            (
                repo_root
                / "skills"
                / "download-pr-specification"
                / "scripts"
                / "auth_login.py"
            ).read_text(),
        )


if __name__ == "__main__":
    unittest.main()
