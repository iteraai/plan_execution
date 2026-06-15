from __future__ import annotations

from dataclasses import dataclass
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import graphql_client

DEFAULT_LOGIN_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class WebLoginResult:
    session_payload: dict[str, Any]


class WebLoginError(RuntimeError):
    pass


class WebLoginState:
    def __init__(
        self,
        *,
        session_file: Path,
        config: graphql_client.GraphQLRequestConfig,
        email: str | None = None,
    ) -> None:
        self.session_file = session_file
        self.config = config
        self.email = email
        self.nonce = secrets.token_urlsafe(24)
        self.completed = threading.Event()
        self.lock = threading.Lock()
        self.result: WebLoginResult | None = None
        self.error: Exception | None = None
        self.challenge_id: str | None = None
        self.challenge_email: str | None = None
        self.challenge_username: str | None = None
        self.enrollment_token: str | None = None
        self.enrollment_email: str | None = None
        self.enrollment_username: str | None = None

    def mark_authenticated(self, session_payload: dict[str, Any]) -> None:
        with self.lock:
            self.result = WebLoginResult(session_payload=session_payload)
            self.error = None
            self.completed.set()

    def mark_error(self, error: Exception) -> None:
        with self.lock:
            if not self.completed.is_set():
                self.error = error


class LocalWebLoginServer:
    def __init__(
        self,
        *,
        session_file: Path,
        config: graphql_client.GraphQLRequestConfig,
        email: str | None = None,
    ) -> None:
        self.state = WebLoginState(
            session_file=session_file,
            config=config,
            email=email,
        )
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            self._build_handler(),
        )
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="plan-execution-auth-web",
            daemon=True,
        )

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/login?nonce={self.state.nonce}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def wait_for_result(self, *, timeout_seconds: int) -> dict[str, Any]:
        if not self.state.completed.wait(timeout_seconds):
            raise TimeoutError("Timed out waiting for browser login to complete")

        with self.state.lock:
            if self.state.error:
                raise WebLoginError(str(self.state.error)) from self.state.error
            if not self.state.result:
                raise WebLoginError("Browser login completed without a session")
            return self.state.result.session_payload

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            server_version = "PlanExecutionAuthWeb/1.0"

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                route = urlparse(self.path)
                if route.path != "/login":
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "not_found"},
                    )
                    return

                query = parse_qs(route.query)
                if query.get("nonce", [""])[0] != state.nonce:
                    self._write_json(
                        HTTPStatus.FORBIDDEN,
                        {"error": "invalid_login_link"},
                    )
                    return

                self._write_html(render_login_page(email=state.email or ""))

            def do_POST(self) -> None:
                route = urlparse(self.path)
                try:
                    payload = self._read_json()
                    if payload.get("nonce") != state.nonce:
                        self._write_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "invalid_login_link"},
                        )
                        return

                    if route.path == "/api/send-code":
                        self._handle_send_code(payload)
                        return
                    if route.path == "/api/login-email-code":
                        self._handle_login_email_code(payload)
                        return
                    if route.path == "/api/complete-totp":
                        self._handle_complete_totp(payload)
                        return
                    if route.path == "/api/begin-enrollment":
                        self._handle_begin_enrollment(payload)
                        return
                    if route.path == "/api/confirm-enrollment":
                        self._handle_confirm_enrollment(payload)
                        return

                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                except Exception as exc:
                    state.mark_error(exc)
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "login_failed", "message": str(exc)},
                    )

            def _handle_send_code(self, payload: dict[str, Any]) -> None:
                from . import auth

                email = require_string(payload, "email")
                response = auth._send_email_verification_code(  # noqa: SLF001
                    email,
                    config=state.config,
                )
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "sent": True,
                        "hasAccount": response.get("hasAccount"),
                    },
                )

            def _handle_login_email_code(self, payload: dict[str, Any]) -> None:
                from . import auth

                email = require_string(payload, "email")
                code = require_string(payload, "code")
                login_response = auth._login_with_email_mfa(  # noqa: SLF001
                    email,
                    code,
                    config=state.config,
                )
                status = str(login_response.get("status") or "")
                username = str(login_response.get("username") or "")
                if not status or not username:
                    raise WebLoginError("Email login returned incomplete data")

                if status == "AUTHENTICATED":
                    session_payload = auth.build_session(
                        account_email=email,
                        username=username,
                        token=require_response_string(login_response, "token"),
                        refresh_token=require_response_string(
                            login_response,
                            "refreshToken",
                        ),
                        graphql_url=state.config.graphql_url,
                        app_header=state.config.app_header,
                        platform_header=state.config.platform_header,
                    )
                    auth.write_session(state.session_file, session_payload)
                    state.mark_authenticated(session_payload)
                    self._write_json(
                        HTTPStatus.OK,
                        {
                            "status": "AUTHENTICATED",
                            "username": username,
                        },
                    )
                    return

                if status == "TOTP_REQUIRED":
                    challenge_id = require_response_string(
                        login_response,
                        "challengeId",
                    )
                    with state.lock:
                        state.challenge_id = challenge_id
                        state.challenge_email = email
                        state.challenge_username = username
                    self._write_json(
                        HTTPStatus.OK,
                        {
                            "status": "TOTP_REQUIRED",
                            "username": username,
                        },
                    )
                    return

                if status == "TOTP_ENROLLMENT_REQUIRED":
                    with state.lock:
                        state.enrollment_token = require_response_string(
                            login_response,
                            "token",
                        )
                        state.enrollment_email = email
                        state.enrollment_username = username
                    self._write_json(
                        HTTPStatus.OK,
                        {
                            "status": "TOTP_ENROLLMENT_REQUIRED",
                            "username": username,
                        },
                    )
                    return

                raise WebLoginError(f"Unsupported login status: {status}")

            def _handle_complete_totp(self, payload: dict[str, Any]) -> None:
                from . import auth

                code = require_string(payload, "code")
                method = str(payload.get("method") or "totp")
                with state.lock:
                    challenge_id = state.challenge_id
                    email = state.challenge_email
                    username = state.challenge_username
                if not challenge_id or not email or not username:
                    raise WebLoginError("No active TOTP challenge is available")

                if method == "recovery":
                    completed = auth._complete_email_login_with_recovery_code(  # noqa: SLF001
                        challenge_id,
                        code,
                        config=state.config,
                    )
                else:
                    completed = auth._complete_email_login_with_totp(  # noqa: SLF001
                        challenge_id,
                        code,
                        config=state.config,
                    )

                session_payload = auth.build_session(
                    account_email=email,
                    username=completed.get("username") or username,
                    token=require_response_string(completed, "token"),
                    refresh_token=require_response_string(completed, "refreshToken"),
                    graphql_url=state.config.graphql_url,
                    app_header=state.config.app_header,
                    platform_header=state.config.platform_header,
                )
                auth.write_session(state.session_file, session_payload)
                state.mark_authenticated(session_payload)
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "status": "AUTHENTICATED",
                        "username": session_payload["username"],
                    },
                )

            def _handle_begin_enrollment(self, payload: dict[str, Any]) -> None:
                del payload
                from . import auth

                with state.lock:
                    enrollment_token = state.enrollment_token
                if not enrollment_token:
                    raise WebLoginError("No active TOTP enrollment is available")

                enrollment = auth._begin_totp_enrollment(  # noqa: SLF001
                    enrollment_token,
                    config=state.config,
                )
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "secret": require_response_string(enrollment, "secret"),
                        "otpauthUri": require_response_string(
                            enrollment,
                            "otpauthUri",
                        ),
                    },
                )

            def _handle_confirm_enrollment(self, payload: dict[str, Any]) -> None:
                from . import auth

                code = require_string(payload, "code")
                with state.lock:
                    enrollment_token = state.enrollment_token
                    email = state.enrollment_email
                    username = state.enrollment_username
                if not enrollment_token or not email or not username:
                    raise WebLoginError("No active TOTP enrollment is available")

                confirmed = auth._confirm_totp_enrollment(  # noqa: SLF001
                    enrollment_token,
                    code,
                    config=state.config,
                )
                auth_payload = confirmed.get("auth")
                if not isinstance(auth_payload, dict):
                    raise WebLoginError("TOTP enrollment did not return auth tokens")

                session_payload = auth.build_session(
                    account_email=email,
                    username=username,
                    token=require_response_string(auth_payload, "token"),
                    refresh_token=require_response_string(
                        auth_payload,
                        "refreshToken",
                    ),
                    graphql_url=state.config.graphql_url,
                    app_header=state.config.app_header,
                    platform_header=state.config.platform_header,
                )
                auth.write_session(state.session_file, session_payload)
                state.mark_authenticated(session_payload)
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "status": "AUTHENTICATED",
                        "username": username,
                        "recoveryCodes": confirmed.get("recoveryCodes") or [],
                    },
                )

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError as exc:
                    raise WebLoginError("Request body must be valid JSON") from exc
                if not isinstance(payload, dict):
                    raise WebLoginError("Request body must be a JSON object")
                return payload

            def _write_html(self, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _write_json(
                self,
                status_code: HTTPStatus,
                payload: dict[str, Any],
            ) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        return Handler


def require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WebLoginError(f"Missing required field: {key}")
    return value.strip()


def require_response_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise WebLoginError(f"Login response did not include {key}")
    return value


def login_with_local_web_ui(
    *,
    session_file: Path,
    config: graphql_client.GraphQLRequestConfig,
    email: str | None = None,
    timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    try:
        server = LocalWebLoginServer(
            session_file=session_file,
            config=config,
            email=email,
        )
    except OSError as exc:
        raise WebLoginError(
            "Could not start the local browser login server on 127.0.0.1. "
            "If this environment blocks local sockets, rerun with "
            "PLAN_EXECUTION_LOGIN_MODE=terminal."
        ) from exc
    server.start()
    try:
        print(
            "Open this local Itera login URL in your browser:",
            file=sys.stderr,
        )
        print(server.url, file=sys.stderr)
        print(
            f"The login server will wait for {timeout_seconds // 60} minutes.",
            file=sys.stderr,
        )
        try:
            return server.wait_for_result(timeout_seconds=timeout_seconds)
        except TimeoutError as exc:
            raise WebLoginError(
                "Timed out waiting for browser login to complete. "
                "Rerun the command to get a fresh local login URL."
            ) from exc
    finally:
        server.stop()


def render_login_page(*, email: str) -> str:
    escaped_email = html.escape(email, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Itera Login</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #18212f;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px 16px;
      box-sizing: border-box;
    }}
    main {{
      width: min(480px, 100%);
      background: #ffffff;
      border: 1px solid #d9dee7;
      border-radius: 8px;
      box-shadow: 0 18px 50px rgba(24, 33, 47, 0.12);
      padding: 28px;
      box-sizing: border-box;
    }}
    h1 {{
      font-size: 24px;
      line-height: 1.2;
      margin: 0 0 8px;
    }}
    p {{
      margin: 0 0 20px;
      color: #506070;
      line-height: 1.45;
    }}
    label {{
      display: block;
      margin: 16px 0 6px;
      font-size: 13px;
      font-weight: 650;
      color: #2a3646;
    }}
    input, select {{
      width: 100%;
      min-height: 44px;
      border: 1px solid #b8c1cf;
      border-radius: 6px;
      padding: 0 12px;
      font-size: 16px;
      box-sizing: border-box;
      background: #fff;
      color: #18212f;
    }}
    button {{
      min-height: 44px;
      border: 0;
      border-radius: 6px;
      padding: 0 16px;
      background: #1f6feb;
      color: #fff;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: #eef2f7;
      color: #18212f;
    }}
    button:disabled {{
      opacity: 0.62;
      cursor: wait;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 20px;
    }}
    .panel {{
      display: none;
    }}
    .panel.active {{
      display: block;
    }}
    .status {{
      margin-top: 18px;
      min-height: 22px;
      color: #506070;
      font-size: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .error {{
      color: #b42318;
    }}
    .success {{
      color: #067647;
    }}
    .secret {{
      border: 1px solid #ccd4df;
      border-radius: 6px;
      padding: 12px;
      background: #f8fafc;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <main>
    <section id="emailPanel" class="panel active">
      <h1>Itera Login</h1>
      <p>Use this local page to authenticate the agent without putting login codes in the conversation.</p>
      <label for="email">Email</label>
      <input id="email" type="email" autocomplete="email" value="{escaped_email}">
      <div class="actions">
        <button id="sendCode">Send Verification Code</button>
      </div>
    </section>

    <section id="codePanel" class="panel">
      <h1>Email Verification</h1>
      <p>Enter the verification code sent to your email address.</p>
      <label for="emailCode">Verification code</label>
      <input id="emailCode" inputmode="numeric" autocomplete="one-time-code">
      <div class="actions">
        <button id="submitEmailCode">Continue</button>
        <button class="secondary" id="backToEmail">Back</button>
      </div>
    </section>

    <section id="totpPanel" class="panel">
      <h1>Two-Factor Authentication</h1>
      <p>Enter a TOTP code or choose recovery code.</p>
      <label for="totpMethod">Code type</label>
      <select id="totpMethod">
        <option value="totp">TOTP code</option>
        <option value="recovery">Recovery code</option>
      </select>
      <label for="totpCode">Code</label>
      <input id="totpCode" autocomplete="one-time-code">
      <div class="actions">
        <button id="submitTotp">Complete Login</button>
      </div>
    </section>

    <section id="enrollmentPanel" class="panel">
      <h1>Set Up Two-Factor Authentication</h1>
      <p>Add this secret to your authenticator app, then enter the first code.</p>
      <div id="enrollmentSecret" class="secret"></div>
      <label for="enrollmentCode">First TOTP code</label>
      <input id="enrollmentCode" inputmode="numeric" autocomplete="one-time-code">
      <div class="actions">
        <button id="confirmEnrollment">Confirm Setup</button>
      </div>
    </section>

    <section id="donePanel" class="panel">
      <h1>Authenticated</h1>
      <p>The local auth file has been updated. You can close this tab and return to the agent.</p>
      <div id="recoveryCodes" class="secret" style="display:none"></div>
    </section>

    <div id="status" class="status"></div>
  </main>

  <script>
    const nonce = new URLSearchParams(window.location.search).get("nonce");
    const statusEl = document.getElementById("status");
    const panels = {{
      email: document.getElementById("emailPanel"),
      code: document.getElementById("codePanel"),
      totp: document.getElementById("totpPanel"),
      enrollment: document.getElementById("enrollmentPanel"),
      done: document.getElementById("donePanel")
    }};

    function show(name) {{
      Object.values(panels).forEach((panel) => panel.classList.remove("active"));
      panels[name].classList.add("active");
      statusEl.textContent = "";
      statusEl.className = "status";
    }}

    function setStatus(message, kind = "") {{
      statusEl.textContent = message;
      statusEl.className = kind ? `status ${{kind}}` : "status";
    }}

    function email() {{
      return document.getElementById("email").value.trim();
    }}

    async function post(path, body) {{
      const response = await fetch(path, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ nonce, ...body }})
      }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || payload.error || "Login failed");
      }}
      return payload;
    }}

    async function withBusy(button, action) {{
      button.disabled = true;
      try {{
        await action();
      }} catch (error) {{
        setStatus(error.message, "error");
      }} finally {{
        button.disabled = false;
      }}
    }}

    document.getElementById("sendCode").addEventListener("click", (event) => {{
      withBusy(event.currentTarget, async () => {{
        if (!email()) throw new Error("Email is required");
        setStatus("Sending code...");
        await post("/api/send-code", {{ email: email() }});
        show("code");
        setStatus("Verification code sent.");
      }});
    }});

    document.getElementById("backToEmail").addEventListener("click", () => show("email"));

    document.getElementById("submitEmailCode").addEventListener("click", (event) => {{
      withBusy(event.currentTarget, async () => {{
        const code = document.getElementById("emailCode").value.trim();
        if (!code) throw new Error("Verification code is required");
        setStatus("Checking code...");
        const result = await post("/api/login-email-code", {{ email: email(), code }});
        if (result.status === "AUTHENTICATED") {{
          show("done");
          setStatus(`Authenticated as ${{result.username}}.`, "success");
        }} else if (result.status === "TOTP_REQUIRED") {{
          show("totp");
        }} else if (result.status === "TOTP_ENROLLMENT_REQUIRED") {{
          const enrollment = await post("/api/begin-enrollment", {{}});
          document.getElementById("enrollmentSecret").textContent =
            `Secret: ${{enrollment.secret}}\\n\\notpauthUri: ${{enrollment.otpauthUri}}`;
          show("enrollment");
        }} else {{
          throw new Error(`Unsupported login status: ${{result.status}}`);
        }}
      }});
    }});

    document.getElementById("submitTotp").addEventListener("click", (event) => {{
      withBusy(event.currentTarget, async () => {{
        const code = document.getElementById("totpCode").value.trim();
        const method = document.getElementById("totpMethod").value;
        if (!code) throw new Error("Code is required");
        const result = await post("/api/complete-totp", {{ code, method }});
        show("done");
        setStatus(`Authenticated as ${{result.username}}.`, "success");
      }});
    }});

    document.getElementById("confirmEnrollment").addEventListener("click", (event) => {{
      withBusy(event.currentTarget, async () => {{
        const code = document.getElementById("enrollmentCode").value.trim();
        if (!code) throw new Error("First TOTP code is required");
        const result = await post("/api/confirm-enrollment", {{ code }});
        if (Array.isArray(result.recoveryCodes) && result.recoveryCodes.length) {{
          const recoveryEl = document.getElementById("recoveryCodes");
          recoveryEl.style.display = "block";
          recoveryEl.textContent =
            "Recovery codes:\\n" + result.recoveryCodes.join("\\n");
        }}
        show("done");
        setStatus(`Authenticated as ${{result.username}}.`, "success");
      }});
    }});
  </script>
</body>
</html>
"""
