#!/usr/bin/env python3

from __future__ import annotations

import argparse
from getpass import getpass
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import auth_refresh
import graphql_client

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

    return auth_refresh.build_session(
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
    _begin_totp_enrollment(restricted_token, config=config)
    print("TOTP enrollment is required for this account.", file=sys.stderr)
    print(
        "Set up this account in your authenticator app using a trusted local "
        "workflow, then enter the first TOTP code below. The enrollment secret, "
        "otpauth URI, and recovery codes are intentionally not printed by this "
        "tool.",
        file=sys.stderr,
    )

    code = _prompt_value("First TOTP code", secret=True)
    confirmed = _confirm_totp_enrollment(restricted_token, code, config=config)
    auth = confirmed.get("auth")
    if not auth:
        raise RuntimeError("TOTP enrollment did not return upgraded auth tokens")

    if confirmed.get("recoveryCodes"):
        print(
            "Recovery codes were generated for this account, but they are "
            "intentionally not printed by this tool.",
            file=sys.stderr,
        )

    return auth_refresh.build_session(
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
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
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
        session_payload = auth_refresh.build_session(
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

    auth_refresh.write_session(session_file, session_payload)
    return session_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap or refresh the public plan_execution Itera login."
    )
    parser.add_argument("--email", help="Prefill the Itera email address for login.")
    parser.add_argument(
        "--session-file",
        default=str(auth_refresh.DEFAULT_SESSION_FILE),
        help="Path to the stored auth JSON.",
    )
    args = parser.parse_args()

    session_file = auth_refresh.expand_session_file(args.session_file)
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"login failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
