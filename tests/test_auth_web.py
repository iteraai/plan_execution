from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error, request
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plan_execution import auth_web, graphql_client


def _server_root(server: auth_web.LocalWebLoginServer) -> str:
    parsed = urlparse(server.url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _post_json(
    server: auth_web.LocalWebLoginServer,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    body = json.dumps({"nonce": server.state.nonce, **payload}).encode("utf-8")
    web_request = request.Request(
        f"{_server_root(server)}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(web_request, timeout=2) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


class AuthWebTests(unittest.TestCase):
    @mock.patch("plan_execution.auth._login_with_email_mfa")
    @mock.patch("plan_execution.auth._send_email_verification_code")
    def test_authenticated_email_login_writes_session_without_returning_tokens(
        self,
        send_email_verification_code: mock.Mock,
        login_with_email_mfa: mock.Mock,
    ) -> None:
        send_email_verification_code.return_value = {"hasAccount": True}
        login_with_email_mfa.return_value = {
            "status": "AUTHENTICATED",
            "challengeId": None,
            "token": "access-token",
            "refreshToken": "refresh-token",
            "username": "thor",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            server = auth_web.LocalWebLoginServer(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )
            server.start()
            try:
                send_response = _post_json(
                    server,
                    "/api/send-code",
                    {"email": "thor@example.com"},
                )
                login_response = _post_json(
                    server,
                    "/api/login-email-code",
                    {"email": "thor@example.com", "code": "123456"},
                )
                session_payload = server.wait_for_result(timeout_seconds=1)
            finally:
                server.stop()

        self.assertEqual(send_response, {"sent": True, "hasAccount": True})
        self.assertEqual(
            login_response,
            {"status": "AUTHENTICATED", "username": "thor"},
        )
        self.assertNotIn("access-token", json.dumps(login_response))
        self.assertNotIn("refresh-token", json.dumps(login_response))
        self.assertEqual(session_payload["token"], "access-token")
        self.assertEqual(session_payload["refresh_token"], "refresh-token")

    @mock.patch("plan_execution.auth._complete_email_login_with_totp")
    @mock.patch("plan_execution.auth._login_with_email_mfa")
    def test_totp_challenge_keeps_challenge_id_server_side(
        self,
        login_with_email_mfa: mock.Mock,
        complete_email_login_with_totp: mock.Mock,
    ) -> None:
        login_with_email_mfa.return_value = {
            "status": "TOTP_REQUIRED",
            "challengeId": "challenge-1",
            "token": None,
            "refreshToken": None,
            "username": "thor",
        }
        complete_email_login_with_totp.return_value = {
            "token": "access-token",
            "refreshToken": "refresh-token",
            "username": "thor",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            server = auth_web.LocalWebLoginServer(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )
            server.start()
            try:
                challenge_response = _post_json(
                    server,
                    "/api/login-email-code",
                    {"email": "thor@example.com", "code": "123456"},
                )
                login_response = _post_json(
                    server,
                    "/api/complete-totp",
                    {"code": "654321", "method": "totp"},
                )
                session_payload = server.wait_for_result(timeout_seconds=1)
            finally:
                server.stop()

        self.assertEqual(
            challenge_response,
            {"status": "TOTP_REQUIRED", "username": "thor"},
        )
        self.assertNotIn("challenge-1", json.dumps(challenge_response))
        self.assertEqual(
            login_response,
            {"status": "AUTHENTICATED", "username": "thor"},
        )
        complete_email_login_with_totp.assert_called_once()
        self.assertEqual(session_payload["token"], "access-token")

    @mock.patch("plan_execution.auth._confirm_totp_enrollment")
    @mock.patch("plan_execution.auth._begin_totp_enrollment")
    @mock.patch("plan_execution.auth._login_with_email_mfa")
    def test_totp_enrollment_keeps_restricted_token_server_side(
        self,
        login_with_email_mfa: mock.Mock,
        begin_totp_enrollment: mock.Mock,
        confirm_totp_enrollment: mock.Mock,
    ) -> None:
        login_with_email_mfa.return_value = {
            "status": "TOTP_ENROLLMENT_REQUIRED",
            "challengeId": None,
            "token": "restricted-token",
            "refreshToken": "restricted-refresh-token",
            "username": "thor",
        }
        begin_totp_enrollment.return_value = {
            "secret": "VERY-SECRET",
            "otpauthUri": "otpauth://totp/Itera:thor?secret=VERY-SECRET",
        }
        confirm_totp_enrollment.return_value = {
            "recoveryCodes": ["code-one", "code-two"],
            "auth": {
                "token": "access-token",
                "refreshToken": "refresh-token",
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            server = auth_web.LocalWebLoginServer(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )
            server.start()
            try:
                enrollment_required_response = _post_json(
                    server,
                    "/api/login-email-code",
                    {"email": "thor@example.com", "code": "123456"},
                )
                enrollment_response = _post_json(
                    server,
                    "/api/begin-enrollment",
                    {},
                )
                login_response = _post_json(
                    server,
                    "/api/confirm-enrollment",
                    {"code": "654321"},
                )
                session_payload = server.wait_for_result(timeout_seconds=1)
            finally:
                server.stop()

        self.assertEqual(
            enrollment_required_response,
            {"status": "TOTP_ENROLLMENT_REQUIRED", "username": "thor"},
        )
        self.assertNotIn("restricted-token", json.dumps(enrollment_required_response))
        self.assertEqual(enrollment_response["secret"], "VERY-SECRET")
        self.assertNotIn("access-token", json.dumps(login_response))
        self.assertNotIn("refresh-token", json.dumps(login_response))
        self.assertEqual(login_response["status"], "AUTHENTICATED")
        self.assertEqual(login_response["recoveryCodes"], ["code-one", "code-two"])
        self.assertEqual(session_payload["token"], "access-token")

    @mock.patch("plan_execution.auth._send_email_verification_code")
    def test_post_rejects_invalid_nonce(
        self,
        send_email_verification_code: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = auth_web.LocalWebLoginServer(
                session_file=Path(temp_dir) / "iteraz.json",
                config=graphql_client.GraphQLRequestConfig(),
            )
            server.start()
            try:
                body = json.dumps(
                    {"nonce": "wrong", "email": "thor@example.com"}
                ).encode("utf-8")
                web_request = request.Request(
                    f"{_server_root(server)}/api/send-code",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(error.HTTPError) as error_context:
                    request.urlopen(web_request, timeout=2)
            finally:
                server.stop()

        self.assertEqual(error_context.exception.code, 403)
        send_email_verification_code.assert_not_called()


if __name__ == "__main__":
    unittest.main()
