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
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, session_file)
    os.chmod(session_file, stat.S_IRUSR | stat.S_IWUSR)


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


def main() -> int:
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
