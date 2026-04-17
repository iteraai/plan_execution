from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "execute-approved-plan" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import auth_refresh


class AuthRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_refresh._warned_about_windows_permission_fallback = False

    @unittest.skipIf(
        os.name == "nt",
        "POSIX chmod semantics are not available on Windows.",
    )
    def test_write_session_sets_0600_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "iteraz.json"
            payload = auth_refresh.build_session(
                account_email="thor@example.com",
                username="thor",
                token="token-1",
                refresh_token="refresh-1",
            )

            auth_refresh.write_session(session_file, payload)

            mode = stat.S_IMODE(session_file.stat().st_mode)
            self.assertEqual(mode, auth_refresh.PRIVATE_FILE_MODE)

    @mock.patch("auth_refresh.warnings.warn")
    @mock.patch("auth_refresh.os.chmod")
    def test_write_session_warns_about_inherited_windows_acls(
        self,
        chmod: mock.Mock,
        warn: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "iteraz.json"
            payload = auth_refresh.build_session(
                account_email="thor@example.com",
                username="thor",
                token="token-1",
                refresh_token="refresh-1",
            )

            with mock.patch("auth_refresh.is_windows_platform", return_value=True):
                auth_refresh.write_session(session_file, payload)

        chmod.assert_not_called()
        warn.assert_called_once()
        self.assertEqual(
            warn.call_args.args[0],
            auth_refresh.WINDOWS_PERMISSION_FALLBACK_WARNING,
        )
        self.assertIs(warn.call_args.args[1], RuntimeWarning)

    @mock.patch("auth_refresh.graphql_client.execute_graphql")
    def test_refresh_session_rotates_tokens(self, execute_graphql: mock.Mock) -> None:
        execute_graphql.return_value = {
            "refreshToken": {
                "token": "token-2",
                "refreshToken": "refresh-2",
            }
        }
        payload = auth_refresh.build_session(
            account_email="thor@example.com",
            username="thor",
            token="token-1",
            refresh_token="refresh-1",
        )

        refreshed = auth_refresh.refresh_session(payload)

        self.assertEqual(refreshed["token"], "token-2")
        self.assertEqual(refreshed["refresh_token"], "refresh-2")


if __name__ == "__main__":
    unittest.main()
