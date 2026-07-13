"""Tests for exponential-backoff retry on transient network errors (DV-1529).

A single `ConnectError`/`TimeoutException` used to be immediately fatal
(`sys.exit(EXIT_NETWORK_ERROR)`), which killed an hours-long `tasks run` poll
loop on one network blip. The client now retries with backoff first.
"""

from __future__ import annotations

import types

import httpx
import pytest

import deepvista_cli.client.http as http_module
from deepvista_cli.client.http import NETWORK_RETRY_ATTEMPTS, DeepVistaClient
from deepvista_cli.config import EXIT_NETWORK_ERROR, CLIConfig


def _patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.client.origin as origin_mod

    monkeypatch.setattr(http_module, "get_valid_token", lambda _path: types.SimpleNamespace(access_token="tok-123"))
    monkeypatch.setattr(origin_mod, "build_origin", lambda: {})


def _response(status_code: int = 200, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_body or {}, request=httpx.Request("GET", "https://api.test/x"))


class _FlakyClient:
    """Stand-in for `httpx.Client` whose method raises N times, then succeeds."""

    def __init__(self, fail_times: int, exc: Exception | None = None) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.exc = exc or httpx.TimeoutException("timed out")

    def get(self, path: str, headers=None, params=None) -> httpx.Response:  # noqa: ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _response(json_body={"ok": True})

    def post(self, path: str, headers=None, json=None) -> httpx.Response:  # noqa: A002, ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _response(json_body={"success": True})


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_module.time, "sleep", lambda _seconds: None)


def test_get_retries_transient_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig())
    fake = _FlakyClient(fail_times=NETWORK_RETRY_ATTEMPTS - 1)
    monkeypatch.setattr(client, "_get_client", lambda: fake)

    result = client.get("/x")

    assert result == {"ok": True}
    assert fake.calls == NETWORK_RETRY_ATTEMPTS


def test_get_exhausts_retries_then_exits_with_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig())
    fake = _FlakyClient(fail_times=NETWORK_RETRY_ATTEMPTS + 5, exc=httpx.ConnectError("refused"))
    monkeypatch.setattr(client, "_get_client", lambda: fake)

    with pytest.raises(SystemExit) as exc_info:
        client.get("/x")

    assert exc_info.value.code == EXIT_NETWORK_ERROR
    assert fake.calls == NETWORK_RETRY_ATTEMPTS


def test_post_nofatal_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig())
    fake = _FlakyClient(fail_times=1)
    monkeypatch.setattr(client, "_get_client", lambda: fake)

    result = client.post_nofatal("/x")

    assert result["success"] is True
    assert fake.calls == 2


def test_post_nofatal_exhausts_retries_then_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_auth(monkeypatch)
    client = DeepVistaClient(CLIConfig())
    fake = _FlakyClient(fail_times=NETWORK_RETRY_ATTEMPTS + 5)
    monkeypatch.setattr(client, "_get_client", lambda: fake)

    with pytest.raises(SystemExit) as exc_info:
        client.post_nofatal("/x")

    assert exc_info.value.code == EXIT_NETWORK_ERROR
    assert fake.calls == NETWORK_RETRY_ATTEMPTS
