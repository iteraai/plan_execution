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

    @mock.patch("auth_refresh.os.chmod")
    def test_write_session_notices_inherited_windows_acls_without_blocking_write(
        self,
        chmod: mock.Mock,
    ) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            session_file = Path(temp_dir) / "iteraz.json"
            payload = auth_refresh.build_session(
                account_email="thor@example.com",
                username="thor",
                token="token-1",
                refresh_token="refresh-1",
            )

            with contextlib.redirect_stderr(stderr):
                with mock.patch("auth_refresh.is_windows_platform", return_value=True):
                    auth_refresh.write_session(session_file, payload)

            self.assertTrue(session_file.exists())
        chmod.assert_not_called()
        self.assertEqual(
            stderr.getvalue().count(auth_refresh.WINDOWS_PERMISSION_FALLBACK_WARNING),
            1,
        )

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

    def test_default_auth_root_uses_agent_specific_locations(self) -> None:
        home = Path.home()
        self.assertEqual(
            auth_refresh.default_auth_root_for_target("codex"),
            home / ".codex" / "auth" / "plan_execution",
        )
        self.assertEqual(
            auth_refresh.default_auth_root_for_target("claude"),
            home / ".claude" / "auth" / "plan_execution",
        )
        self.assertEqual(
            auth_refresh.default_auth_root_for_target("cursor"),
            home / ".cursor" / "auth" / "plan_execution",
        )

    def test_default_auth_root_for_copilot_uses_neutral_config_home(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/config-home"}):
            self.assertEqual(
                auth_refresh.default_auth_root_for_target("copilot"),
                Path("/tmp/config-home") / "plan_execution" / "auth",
            )


if __name__ == "__main__":
    unittest.main()
