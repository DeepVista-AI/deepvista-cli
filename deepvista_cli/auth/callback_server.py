"""Local HTTP callback server for interactive CLI login.

Flow:
  1. Start a single-use HTTP server on 127.0.0.1 (random port)
  2. Open browser to /cli?callback_url=http://127.0.0.1:PORT/callback&state=STATE
  3. User authenticates in browser
  4. Frontend POSTs tokens back to the callback_url
  5. Server validates state, extracts tokens, shuts down
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import click

from deepvista_cli.auth.tokens import TokenSet, _extract_issuer, save_tokens

_TIMEOUT_SECONDS = 120  # max wait for browser callback


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handle the POST /callback from the browser."""

    # Shared state — set by the parent before starting the server.
    expected_state: str = ""
    result: TokenSet | None = None
    error: str | None = None

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/callback":
            self._respond(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._respond(400, {"error": "invalid json"})
            return

        # CSRF check
        if payload.get("state") != self.expected_state:
            self._respond(403, {"error": "state mismatch"})
            return

        if "access_token" not in payload:
            self._respond(400, {"error": "missing access_token"})
            return

        user = payload.get("user", {})
        access_token = payload["access_token"]
        _CallbackHandler.result = TokenSet(
            access_token=access_token,
            refresh_token=payload.get("refresh_token", ""),
            expires_at=float(payload.get("expires_at", time.time() + 3600)),
            user_id=user.get("id", ""),
            email=user.get("email", ""),
            issuer=_extract_issuer(access_token) or "",
            api_key=payload.get("api_key", ""),
        )

        self._respond(200, {"status": "ok"})

        # Shut down in a separate thread to avoid deadlock
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight from browser."""
        self._respond(204, None, cors=True)

    def _respond(self, code: int, body: dict | None, *, cors: bool = False) -> None:
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body is not None:
            self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default stderr logging."""


def login_with_callback(
    auth_url: str = "https://app.deepvista.ai",
    credentials_path: Path | None = None,
) -> TokenSet:
    """Run the local-callback login flow.

    Starts a localhost HTTP server, opens the browser, and waits for the
    frontend to POST tokens back. Tokens never touch shell history.
    """
    state = secrets.token_urlsafe(32)
    _CallbackHandler.expected_state = state
    _CallbackHandler.result = None
    _CallbackHandler.error = None

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]
    callback_url = f"http://127.0.0.1:{port}/callback"

    login_url = f"{auth_url}/cli?callback_url={callback_url}&state={state}"

    click.echo("", err=True)
    click.echo("  Opening browser to authenticate...", err=True)
    click.echo("  If the browser doesn't open, visit:", err=True)
    click.echo(f"  {login_url}", err=True)
    click.echo("", err=True)
    click.echo("  Waiting for authentication...", err=True)

    webbrowser.open(login_url)

    # Serve with timeout
    server.timeout = _TIMEOUT_SECONDS
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    server_thread.join(timeout=_TIMEOUT_SECONDS)
    server.shutdown()

    if _CallbackHandler.result is None:
        raise click.ClickException(
            "Login timed out. No response received from the browser.\n"
            "  Try again, or visit the web app and use: deepvista auth login --code XXXX-XXXX"
        )

    tokens = _CallbackHandler.result
    save_tokens(tokens, credentials_path)
    return tokens
