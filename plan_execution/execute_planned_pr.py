#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import auth as auth_refresh
from . import bridge
from . import graphql_client

build_branch_name = bridge.build_branch_name
ensure_authenticated_context = bridge.ensure_authenticated_context


def run_execution(
    canonical_task_id: str,
    planned_pull_request_id: str,
    *,
    session_file: Path = auth_refresh.DEFAULT_SESSION_FILE,
    config: graphql_client.GraphQLRequestConfig | None = None,
    interactive: bool = True,
) -> dict[str, Any]:
    return bridge.run_planned_pr_execution(
        canonical_task_id,
        planned_pull_request_id,
        session_file=session_file,
        config=config,
        interactive=interactive,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim one exact dependency-ready Itera planned pull request."
    )
    parser.add_argument(
        "--canonical-task-id",
        required=True,
        help="Canonical Itera task ID such as FRONTPAGE-42.",
    )
    parser.add_argument(
        "--planned-pull-request-id",
        required=True,
        help="Exact Itera planned pull request ID to claim.",
    )
    parser.add_argument(
        "--session-file",
        default=str(auth_refresh.DEFAULT_SESSION_FILE),
        help="Path to the stored auth JSON.",
    )
    parser.add_argument(
        "--graphql-url",
        default=graphql_client.DEFAULT_GRAPHQL_URL,
        help="Itera GraphQL URL. Defaults to https://api.iteradev.ai/graphql/.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt for login if a valid stored session is unavailable.",
    )
    args = parser.parse_args()

    config = graphql_client.GraphQLRequestConfig(graphql_url=args.graphql_url)
    result = run_execution(
        args.canonical_task_id,
        args.planned_pull_request_id,
        session_file=auth_refresh.expand_session_file(args.session_file),
        config=config,
        interactive=not args.no_prompt,
    )
    print(json.dumps(result, indent=2))
    return (
        0
        if result["status"]
        in {
            "SUCCESS",
            "AUTH_REQUIRED",
            "NOT_FOUND",
            "NO_PLAN",
            "PR_NOT_FOUND",
            "UNAVAILABLE",
        }
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(json.dumps({"status": "UNAVAILABLE", "message": str(exc)}, indent=2))
        raise SystemExit(1)
