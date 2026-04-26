#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import graphql_client

DEFAULT_SESSION_FILE = (
    Path.home() / ".codex" / "auth" / "plan_execution" / "iteraz.json"
)
REFRESH_TOKEN_MUTATION = """
mutation RefreshToken($refreshToken: String!) {
  refreshToken(refreshToken: $refreshToken) {
    token
    refreshToken
  }
}
""".strip()
SOCIAL_ME_QUERY = """
query SocialMe {
  socialMe {
    email
    identifier
    profile {
      username
    }
  }
}
""".strip()
REQUIRED_SESSION_KEYS = {
    "account_email",
    "username",
    "graphql_url",
    "app_header",
    "platform_header",
    "token",
    "refresh_token",
    "rotated_at",
}
PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
WINDOWS_PERMISSION_FALLBACK_WARNING = (
    "Windows local file protection falls back to inherited directory ACLs; "
    "this script does not rewrite Windows ACLs, so token and artifact privacy "
    "depends on the parent directory permissions."
)
_warned_about_windows_permission_fallback = False
auth_refresh = sys.modules[__name__]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def expand_session_file(path: str | Path | None = None) -> Path:
    if path is None:
        return DEFAULT_SESSION_FILE
    return Path(path).expanduser()


def load_session(session_file: Path = DEFAULT_SESSION_FILE) -> dict[str, Any]:
    payload = json.loads(session_file.read_text())
    missing_keys = sorted(REQUIRED_SESSION_KEYS - payload.keys())
    if missing_keys:
        raise ValueError(f"Session file is missing keys: {', '.join(missing_keys)}")
    return payload


def warn_about_windows_permission_fallback() -> None:
    global _warned_about_windows_permission_fallback
    if _warned_about_windows_permission_fallback:
        return
    print(WINDOWS_PERMISSION_FALLBACK_WARNING, file=sys.stderr)
    _warned_about_windows_permission_fallback = True


def is_windows_platform() -> bool:
    return os.name == "nt"


def protect_local_file(path: Path) -> None:
    """Restrict a local file as much as this platform can reliably support."""
    if is_windows_platform():
        warn_about_windows_permission_fallback()
        return
    os.chmod(path, PRIVATE_FILE_MODE)


def write_session(session_file: Path, payload: dict[str, Any]) -> None:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=session_file.parent,
        prefix=f"{session_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        protect_local_file(temp_path)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, session_file)
    protect_local_file(session_file)


def build_session(
    *,
    account_email: str,
    username: str,
    token: str,
    refresh_token: str,
    graphql_url: str = graphql_client.DEFAULT_GRAPHQL_URL,
    app_header: str = graphql_client.DEFAULT_APP_HEADER,
    platform_header: str = graphql_client.DEFAULT_PLATFORM_HEADER,
) -> dict[str, Any]:
    return {
        "account_email": account_email,
        "username": username,
        "graphql_url": graphql_url,
        "app_header": app_header,
        "platform_header": platform_header,
        "token": token,
        "refresh_token": refresh_token,
        "rotated_at": utc_now(),
    }


def get_config_from_session(
    payload: dict[str, Any],
) -> graphql_client.GraphQLRequestConfig:
    return graphql_client.GraphQLRequestConfig(
        graphql_url=payload["graphql_url"],
        app_header=payload["app_header"],
        platform_header=payload["platform_header"],
    )


def refresh_session(
    payload: dict[str, Any],
    *,
    config: graphql_client.GraphQLRequestConfig | None = None,
) -> dict[str, Any]:
    request_config = config or get_config_from_session(payload)
    refreshed = graphql_client.execute_graphql(
        REFRESH_TOKEN_MUTATION,
        {"refreshToken": payload["refresh_token"]},
        config=request_config,
    )["refreshToken"]
    payload["token"] = refreshed["token"]
    payload["refresh_token"] = refreshed["refreshToken"]
    payload["graphql_url"] = request_config.graphql_url
    payload["app_header"] = request_config.app_header
    payload["platform_header"] = request_config.platform_header
    payload["rotated_at"] = utc_now()
    return payload


def refresh_session_file(
    session_file: Path = DEFAULT_SESSION_FILE,
    *,
    config: graphql_client.GraphQLRequestConfig | None = None,
) -> dict[str, Any]:
    payload = load_session(session_file)
    refreshed_payload = refresh_session(payload, config=config)
    write_session(session_file, refreshed_payload)
    return refreshed_payload


def fetch_social_me(
    token: str,
    *,
    config: graphql_client.GraphQLRequestConfig | None = None,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        SOCIAL_ME_QUERY,
        token=token,
        config=config,
    )["socialMe"]


def refresh_main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the public plan_execution Itera session."
    )
    parser.add_argument(
        "--session-file",
        default=str(DEFAULT_SESSION_FILE),
        help="Path to the stored auth JSON.",
    )
    parser.add_argument(
        "--print-access-token",
        action="store_true",
        help="Print only the refreshed access token.",
    )
    parser.add_argument(
        "--print-refresh-token",
        action="store_true",
        help="Print only the refreshed refresh token.",
    )
    args = parser.parse_args()

    session_file = expand_session_file(args.session_file)
    payload = refresh_session_file(session_file)

    if args.print_access_token:
        print(payload["token"])
        return 0

    if args.print_refresh_token:
        print(payload["refresh_token"])
        return 0

    print(
        json.dumps(
            {
                "session_file": str(session_file),
                "account_email": payload["account_email"],
                "username": payload["username"],
                "graphql_url": payload["graphql_url"],
                "app_header": payload["app_header"],
                "platform_header": payload["platform_header"],
                "rotated_at": payload["rotated_at"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
SEND_EMAIL_VERIFICATION_CODE_MUTATION = """
mutation SendEmailVerificationCode($email: String!) {
  sendEmailVerificationCode(email: $email) {
    hasAccount
  }
}
""".strip()
LOGIN_WITH_EMAIL_MFA_MUTATION = """
mutation LoginWithEmailMfa($identifier: String!, $code: String!) {
  loginWithEmailMfa(identifier: $identifier, code: $code) {
    status
    challengeId
    token
    refreshToken
    username
  }
}
""".strip()
COMPLETE_EMAIL_LOGIN_WITH_TOTP_MUTATION = """
mutation CompleteEmailLoginWithTotp($challengeId: String!, $code: String!) {
  completeEmailLoginWithTotp(challengeId: $challengeId, code: $code) {
    token
    refreshToken
    username
  }
}
""".strip()
COMPLETE_EMAIL_LOGIN_WITH_RECOVERY_CODE_MUTATION = """
mutation CompleteEmailLoginWithRecoveryCode($challengeId: String!, $code: String!) {
  completeEmailLoginWithRecoveryCode(challengeId: $challengeId, code: $code) {
    token
    refreshToken
    username
  }
}
""".strip()
BEGIN_TOTP_ENROLLMENT_MUTATION = """
mutation BeginTotpEnrollment {
  beginTotpEnrollment {
    secret
    otpauthUri
  }
}
""".strip()
CONFIRM_TOTP_ENROLLMENT_MUTATION = """
mutation ConfirmTotpEnrollment($code: String!) {
  confirmTotpEnrollment(code: $code) {
    recoveryCodes
    auth {
      token
      refreshToken
    }
  }
}
""".strip()


def _prompt_value(
    prompt_text: str, *, secret: bool = False, allow_empty: bool = False
) -> str:
    while True:
        if secret:
            value = getpass(f"{prompt_text}: ")
        else:
            print(f"{prompt_text}: ", end="", file=sys.stderr, flush=True)
            value = input()
        value = value.strip()
        if value or allow_empty:
            return value
        print("A value is required.", file=sys.stderr)


def _open_sensitive_display():
    candidate_paths = ("CONOUT$",) if os.name == "nt" else ("/dev/tty",)
    for candidate_path in candidate_paths:
        try:
            return open(candidate_path, "w", encoding="utf-8")
        except OSError:
            continue
    raise RuntimeError(
        "TOTP enrollment requires an interactive terminal so enrollment details "
        "can be shown without writing them to stdout or stderr."
    )


def _write_sensitive_lines(lines: list[str]) -> None:
    with _open_sensitive_display() as display:
        for line in lines:
            print(line, file=display)
        display.flush()


def _send_email_verification_code(
    email: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        SEND_EMAIL_VERIFICATION_CODE_MUTATION,
        {"email": email},
        config=config,
    )["sendEmailVerificationCode"]


def _login_with_email_mfa(
    email: str,
    code: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        LOGIN_WITH_EMAIL_MFA_MUTATION,
        {"identifier": email, "code": code},
        config=config,
    )["loginWithEmailMfa"]


def _complete_email_login_with_totp(
    challenge_id: str,
    code: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        COMPLETE_EMAIL_LOGIN_WITH_TOTP_MUTATION,
        {"challengeId": challenge_id, "code": code},
        config=config,
    )["completeEmailLoginWithTotp"]


def _complete_email_login_with_recovery_code(
    challenge_id: str,
    code: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        COMPLETE_EMAIL_LOGIN_WITH_RECOVERY_CODE_MUTATION,
        {"challengeId": challenge_id, "code": code},
        config=config,
    )["completeEmailLoginWithRecoveryCode"]


def _begin_totp_enrollment(
    token: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        BEGIN_TOTP_ENROLLMENT_MUTATION,
        token=token,
        config=config,
    )["beginTotpEnrollment"]


def _confirm_totp_enrollment(
    token: str,
    code: str,
    *,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    return graphql_client.execute_graphql(
        CONFIRM_TOTP_ENROLLMENT_MUTATION,
        {"code": code},
        token=token,
        config=config,
    )["confirmTotpEnrollment"]


def _complete_totp_challenge(
    *,
    challenge_id: str,
    email: str,
    username: str,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    totp_code = _prompt_value(
        "TOTP code (leave blank to use a recovery code)", secret=True, allow_empty=True
    )
    if totp_code:
        completed = _complete_email_login_with_totp(
            challenge_id, totp_code, config=config
        )
    else:
        recovery_code = _prompt_value("Recovery code", secret=True)
        completed = _complete_email_login_with_recovery_code(
            challenge_id,
            recovery_code,
            config=config,
        )

    return build_session(
        account_email=email,
        username=completed["username"] or username,
        token=completed["token"],
        refresh_token=completed["refreshToken"],
        graphql_url=config.graphql_url,
        app_header=config.app_header,
        platform_header=config.platform_header,
    )


def _complete_totp_enrollment(
    *,
    restricted_token: str,
    email: str,
    username: str,
    config: graphql_client.GraphQLRequestConfig,
) -> dict[str, Any]:
    enrollment = _begin_totp_enrollment(restricted_token, config=config)
    print("TOTP enrollment is required for this account.", file=sys.stderr)
    print(
        "The enrollment secret and recovery codes will be shown only in your "
        "interactive terminal, not in stdout or stderr logs.",
        file=sys.stderr,
    )
    _write_sensitive_lines(
        [
            "TOTP enrollment details:",
            f"Secret: {enrollment['secret']}",
            f"otpauthUri: {enrollment['otpauthUri']}",
            "Store these values securely before continuing.",
        ]
    )

    code = _prompt_value("First TOTP code", secret=True)
    confirmed = _confirm_totp_enrollment(restricted_token, code, config=config)
    auth = confirmed.get("auth")
    if not auth:
        raise RuntimeError("TOTP enrollment did not return upgraded auth tokens")

    if confirmed.get("recoveryCodes"):
        _write_sensitive_lines(
            [
                "Recovery codes:",
                *confirmed["recoveryCodes"],
                "Store these codes securely.",
            ]
        )

    return build_session(
        account_email=email,
        username=username,
        token=auth["token"],
        refresh_token=auth["refreshToken"],
        graphql_url=config.graphql_url,
        app_header=config.app_header,
        platform_header=config.platform_header,
    )


def login_interactively(
    *,
    session_file: Path = DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    request_config = config or graphql_client.GraphQLRequestConfig()
    account_email = email or _prompt_value("Itera email")
    _send_email_verification_code(account_email, config=request_config)
    email_code = _prompt_value("Email verification code", secret=True)
    login_response = _login_with_email_mfa(
        account_email, email_code, config=request_config
    )

    status = login_response["status"]
    if status == "AUTHENTICATED":
        session_payload = build_session(
            account_email=account_email,
            username=login_response["username"],
            token=login_response["token"],
            refresh_token=login_response["refreshToken"],
            graphql_url=request_config.graphql_url,
            app_header=request_config.app_header,
            platform_header=request_config.platform_header,
        )
    elif status == "TOTP_REQUIRED":
        challenge_id = login_response.get("challengeId")
        if not challenge_id:
            raise RuntimeError("TOTP login challenge was missing a challengeId")
        session_payload = _complete_totp_challenge(
            challenge_id=challenge_id,
            email=account_email,
            username=login_response["username"],
            config=request_config,
        )
    elif status == "TOTP_ENROLLMENT_REQUIRED":
        if not login_response.get("token") or not login_response.get("refreshToken"):
            raise RuntimeError(
                "Restricted enrollment login did not return session tokens"
            )
        session_payload = _complete_totp_enrollment(
            restricted_token=login_response["token"],
            email=account_email,
            username=login_response["username"],
            config=request_config,
        )
    else:
        raise RuntimeError(f"Unsupported login status: {status}")

    write_session(session_file, session_payload)
    return session_payload


def login_main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap or refresh the public plan_execution Itera login."
    )
    parser.add_argument("--email", help="Prefill the Itera email address for login.")
    parser.add_argument(
        "--session-file",
        default=str(DEFAULT_SESSION_FILE),
        help="Path to the stored auth JSON.",
    )
    args = parser.parse_args()

    session_file = expand_session_file(args.session_file)
    session_payload = login_interactively(session_file=session_file, email=args.email)
    print(
        json.dumps(
            {
                "session_file": str(session_file),
                "account_email": session_payload["account_email"],
                "username": session_payload["username"],
                "graphql_url": session_payload["graphql_url"],
                "app_header": session_payload["app_header"],
                "platform_header": session_payload["platform_header"],
                "rotated_at": session_payload["rotated_at"],
            }
        )
    )
    return 0


def main() -> int:
    return refresh_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"login failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
