#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request

DEFAULT_GRAPHQL_URL = os.environ.get(
    "ITERA_GRAPHQL_URL", "https://api.iteradev.ai/graphql/"
)
DEFAULT_APP_HEADER = "ITERAZ"
DEFAULT_PLATFORM_HEADER = "WEB"
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("ITERA_GRAPHQL_TIMEOUT_SECONDS", "30"))


@dataclass(frozen=True)
class GraphQLRequestConfig:
    graphql_url: str = DEFAULT_GRAPHQL_URL
    app_header: str = DEFAULT_APP_HEADER
    platform_header: str = DEFAULT_PLATFORM_HEADER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class GraphQLError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        errors: Any = None,
        payload: Any = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors
        self.payload = payload
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "errors": self.errors,
            "statusCode": self.status_code,
        }


def execute_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    config: GraphQLRequestConfig | None = None,
) -> dict[str, Any]:
    request_config = config or GraphQLRequestConfig()
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "App": request_config.app_header,
        "Platform": request_config.platform_header,
    }
    if token:
        headers["Authorization"] = f"Token {token}"

    graphql_request = request.Request(
        request_config.graphql_url,
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(
            graphql_request, timeout=request_config.timeout_seconds
        ) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            response_payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            response_payload = None
        raise GraphQLError(
            f"GraphQL request failed with HTTP {exc.code}",
            errors=(
                (response_payload or {}).get("errors")
                if isinstance(response_payload, dict)
                else None
            ),
            payload=response_payload,
            status_code=exc.code,
        ) from exc
    except error.URLError as exc:
        raise GraphQLError(f"GraphQL request failed: {exc.reason}") from exc

    if response_payload.get("errors"):
        raise GraphQLError(
            "GraphQL returned errors",
            errors=response_payload["errors"],
            payload=response_payload,
        )

    if "data" not in response_payload:
        raise GraphQLError(
            "GraphQL response was missing data", payload=response_payload
        )

    return response_payload["data"]
