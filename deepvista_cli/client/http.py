"""HTTP client that handles auth headers and auto-refresh.

Every request includes:
  - Authorization: Bearer <jwt>
  - Content-Type: application/json

Token refresh is transparent — if the access token is expired, the client
refreshes it before the request and saves the new tokens.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import Iterator
from typing import Any, NoReturn

import click
import httpx

from deepvista_cli import __version__
from deepvista_cli.auth.tokens import get_valid_token
from deepvista_cli.config import EXIT_API_ERROR, EXIT_AUTH_ERROR, EXIT_NETWORK_ERROR, CLIConfig, credentials_path

logger = logging.getLogger(__name__)


class DeepVistaClient:
    """HTTP client for the DeepVista backend API."""

    def __init__(self, config: CLIConfig) -> None:
        self.config = config
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.api_url,
                timeout=30,
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        """Build auth headers, auto-refreshing token if needed.

        Auth: Authorization: Bearer <jwt> (from login).
        Origin: X-DeepVista-Origin: <json> (agent/machine metadata).
        """
        from deepvista_cli.client.origin import build_origin

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": f"deepvista-cli/{__version__}",
            "X-DeepVista-Origin": json.dumps(build_origin(), separators=(",", ":")),
        }

        # Scope every authenticated request to the CLI's working project.
        # When unset, the header is omitted and the backend resolves the
        # caller's default project (unchanged legacy behavior). Resolved from
        # --project / DEEPVISTA_PROJECT_ID / profile project_id (see config).
        if self.config.project_id:
            headers["X-Project-Id"] = self.config.project_id

        # JWT auth (from per-profile credentials file)
        tokens = get_valid_token(credentials_path(self.config.profile))
        if tokens is not None and tokens.access_token:
            headers["Authorization"] = f"Bearer {tokens.access_token}"
            return headers

        # No user identity — must login first.
        click.echo(
            json.dumps(
                {
                    "error": {
                        "code": 2,
                        "message": "Not authenticated. Run: deepvista auth login",
                    }
                }
            ),
            err=True,
        )
        sys.exit(EXIT_AUTH_ERROR)

    def _log_request(self, method: str, path: str, body: Any = None) -> None:
        if self.config.verbose:
            click.echo(f">>> {method} {self.config.api_url}{path}", err=True)
            if body:
                click.echo(f">>> Body: {json.dumps(body, default=str)}", err=True)

    def _log_response(self, resp: httpx.Response) -> None:
        if self.config.verbose:
            click.echo(f"<<< {resp.status_code}", err=True)

    def _handle_network_error(self, exc: httpx.ConnectError | httpx.TimeoutException) -> NoReturn:
        """Handle network-level errors with structured output."""
        if isinstance(exc, httpx.ConnectError):
            msg = f"Cannot connect to {self.config.api_url}"
            detail = str(exc)
        else:
            msg = f"Request timed out to {self.config.api_url}"
            detail = str(exc)
        err = {"error": {"code": EXIT_NETWORK_ERROR, "message": msg, "detail": detail}}
        click.echo(json.dumps(err, indent=2), err=True)
        sys.exit(EXIT_NETWORK_ERROR)

    def _handle_error(self, resp: httpx.Response) -> None:
        """Handle non-2xx responses with structured error output."""
        try:
            body = resp.json()
            detail = body.get("detail", body.get("message", resp.text))
        except Exception:
            detail = resp.text

        err = {"error": {"code": EXIT_API_ERROR, "message": f"API error ({resp.status_code})", "detail": str(detail)}}
        click.echo(json.dumps(err, indent=2), err=True)
        sys.exit(EXIT_API_ERROR)

    # -- Public request methods -----------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Unified request method with network error handling."""
        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)
        self._log_request(method, path, body)
        if self.config.dry_run:
            click.echo(
                json.dumps(
                    {"dry_run": True, "method": method, "path": path, "body": body, "params": params}, default=str
                ),
                err=True,
            )
            sys.exit(0)

        with self._lock:
            try:
                client = self._get_client()
                if method == "GET":
                    resp = client.get(path, headers=headers, params=params)
                elif method == "POST":
                    resp = client.post(path, headers=headers, json=body or {})
                elif method == "PATCH":
                    resp = client.patch(path, headers=headers, json=body or {})
                elif method == "DELETE":
                    resp = client.delete(path, headers=headers, params=params)
                else:
                    raise ValueError(f"Unsupported method: {method}")
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                self._handle_network_error(exc)

            self._log_response(resp)
            if resp.status_code >= 400:
                self._handle_error(resp)
            return resp.json()

    def get(self, path: str, params: dict | None = None, extra_headers: dict[str, str] | None = None) -> Any:
        """HTTP GET, returns parsed JSON."""
        return self._request("GET", path, params=params, extra_headers=extra_headers)

    def post(self, path: str, body: dict | None = None, extra_headers: dict[str, str] | None = None) -> Any:
        """HTTP POST, returns parsed JSON."""
        return self._request("POST", path, body=body, extra_headers=extra_headers)

    def post_nofatal(self, path: str, body: dict | None = None, extra_headers: dict[str, str] | None = None) -> Any:
        """HTTP POST that returns the parsed response body for both success and API errors.

        Unlike post(), 4xx/5xx responses are returned as-is (the server's JSON body) rather
        than printed to stderr and raised as SystemExit. Network errors still raise SystemExit.
        """
        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)
        self._log_request("POST", path, body)
        if self.config.dry_run:
            click.echo(
                json.dumps({"dry_run": True, "method": "POST", "path": path, "body": body}, default=str),
                err=True,
            )
            sys.exit(0)
        with self._lock:
            try:
                client = self._get_client()
                resp = client.post(path, headers=headers, json=body or {})
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                self._handle_network_error(exc)
            self._log_response(resp)
            try:
                data = resp.json()
                if isinstance(data, dict):
                    data["_status_code"] = resp.status_code
                return data
            except Exception:
                return {"error": resp.text, "status_code": resp.status_code, "_status_code": resp.status_code}

    def patch(self, path: str, body: dict | None = None) -> Any:
        """HTTP PATCH, returns parsed JSON."""
        return self._request("PATCH", path, body=body)

    def delete(self, path: str, params: dict | None = None) -> Any:
        """HTTP DELETE, returns parsed JSON."""
        return self._request("DELETE", path, params=params)

    def stream_sse(self, path: str, body: dict | None = None) -> Iterator[dict]:
        """POST with SSE streaming. Yields parsed JSON events as NDJSON."""
        headers = self._auth_headers()
        headers["Accept"] = "text/event-stream"
        self._log_request("POST (SSE)", path, body)
        if self.config.dry_run:
            click.echo(
                json.dumps({"dry_run": True, "method": "POST_SSE", "path": path, "body": body}, default=str),
                err=True,
            )
            sys.exit(0)

        client = self._get_client()

        try:
            with client.stream("POST", path, json=body or {}, headers=headers, timeout=300) as resp:
                self._log_response(resp)
                if resp.status_code >= 400:
                    resp.read()
                    self._handle_error(resp)

                buffer = ""
                for chunk in resp.iter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                return
                            try:
                                yield json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.debug("Skipping non-JSON SSE line: %s", data_str)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            self._handle_network_error(exc)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
