"""Click-level tests for `deepvista card comment` add / list / edit / delete (DV-1496)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli


class _StubCtxClient:
    """Minimal stand-in for the real client attached to ctx.obj._client."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def _pop(self, method: str, path: str, body: dict | None = None) -> Any:
        self.calls.append((method, path, body))
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for {method} {path}")
        return q.pop(0)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self._pop("POST", path, body)

    def delete(self, path: str, params: dict | None = None) -> Any:
        return self._pop("DELETE", path, params)


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubCtxClient) -> None:
    from deepvista_cli.client import http as http_module

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", lambda self, config: setattr(self, "config", config))
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body),
    )
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "delete",
        lambda self, path, params=None: stub.delete(path, params),
    )


def test_comment_add(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    stub.queue("/create_card_comment", {"id": "cmt-1", "card_id": "card-1", "comment": "hi"})

    result = CliRunner().invoke(cli, ["card", "comment", "add", "card-1", "--content", "hi"])

    assert result.exit_code == 0, result.output
    assert ("POST", "/create_card_comment", {"card_id": "card-1", "comment": "hi"}) in stub.calls


def test_comment_add_empty_is_rejected_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["card", "comment", "add", "card-1", "--content", "   "])

    assert result.exit_code == 3, result.output
    assert stub.calls == []  # never hit the API


def test_comment_add_dry_run_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["card", "comment", "add", "card-1", "--content", "hi", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dry_run"] is True
    assert stub.calls == []


def test_comment_list(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    stub.queue("/list_card_comments", [{"id": "cmt-1", "comment": "a"}, {"id": "cmt-2", "comment": "b"}])

    result = CliRunner().invoke(cli, ["card", "comment", "list", "card-1"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["count"] == 2
    assert ("POST", "/list_card_comments", {"card_id": "card-1"}) in stub.calls


def test_comment_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    stub.queue("/update_card_comment", {"id": "cmt-1", "comment": "edited"})

    result = CliRunner().invoke(cli, ["card", "comment", "edit", "cmt-1", "--content", "edited"])

    assert result.exit_code == 0, result.output
    assert ("POST", "/update_card_comment", {"comment_id": "cmt-1", "comment": "edited"}) in stub.calls


def test_comment_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCtxClient()
    _install_stub_client(monkeypatch, stub)
    stub.queue("/card_comments/cmt-1", {"success": True})

    result = CliRunner().invoke(cli, ["card", "comment", "delete", "cmt-1"])

    assert result.exit_code == 0, result.output
    assert ("DELETE", "/card_comments/cmt-1", None) in stub.calls
