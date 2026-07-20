"""Tests for `deepvista card upload` (DV-1650) and the binary --content-file guard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.main import cli

# Valid PNG magic followed by bytes that are not valid UTF-8.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\xff\xfe" * 8


class _StubClient:
    """Records POST bodies and presigned PUTs driven by `card upload`."""

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.posts: list[tuple[str, dict | None]] = []
        self.puts: list[tuple[str, bytes, dict[str, str]]] = []

    def queue(self, path: str, response: Any) -> None:
        self.responses.setdefault(path, []).append(response)

    def post(self, path: str, body: dict | None = None) -> Any:
        self.posts.append((path, body))
        q = self.responses.get(path)
        if not q:
            raise AssertionError(f"no response queued for POST {path}")
        return q.pop(0)

    def put_bytes(self, url: str, data: bytes, headers: dict[str, str]) -> None:
        self.puts.append((url, data, headers))


def _install_stub_client(monkeypatch: pytest.MonkeyPatch, stub: _StubClient) -> None:
    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(
        DeepVistaClient,
        "post",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body),
    )
    monkeypatch.setattr(
        DeepVistaClient,
        "put_bytes",
        lambda self, url, data, headers: stub.put_bytes(url, data, headers),
    )


def test_card_upload_puts_bytes_and_reports_file_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "screenshot.png"
    png.write_bytes(PNG_BYTES)

    stub = _StubClient()
    stub.queue(
        "/attachments/signed-upload-url",
        {
            "signedUrl": "https://storage.example/put?sig=abc",
            "gcsPath": "user-1/attachments/x.png",
            "gsUrl": "gs://bucket/user-1/attachments/x.png",
            "headers": {"Content-Type": "image/png"},
        },
    )
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["card", "upload", str(png)])
    assert result.exit_code == 0, result.output

    path, body = stub.posts[0]
    assert path == "/attachments/signed-upload-url"
    assert body == {"file_name": "screenshot.png", "file_size": len(PNG_BYTES), "content_type": "image/png"}

    url, data, headers = stub.puts[0]
    assert url == "https://storage.example/put?sig=abc"
    assert data == PNG_BYTES
    assert headers == {"Content-Type": "image/png"}

    payload = json.loads(result.output)
    assert payload["url"] == "gs://bucket/user-1/attachments/x.png"
    assert payload["file_type"] == "image/png"


def test_card_upload_rejects_oversize_before_any_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.commands.card as card_module

    big = tmp_path / "big.bin"
    big.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(card_module, "MAX_UPLOAD_BYTES", 16)

    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["card", "upload", str(big)])
    assert result.exit_code == 3
    assert stub.posts == []
    assert stub.puts == []


def test_card_upload_dry_run_makes_no_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(PNG_BYTES)

    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(cli, ["card", "upload", str(png), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert stub.posts == []
    assert stub.puts == []
    assert json.loads(result.output)["dry_run"] is True


def test_card_create_content_file_binary_points_at_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Binary --content-file fails with guidance instead of a UnicodeDecodeError traceback."""
    png = tmp_path / "shot.png"
    png.write_bytes(PNG_BYTES)

    stub = _StubClient()
    _install_stub_client(monkeypatch, stub)

    result = CliRunner().invoke(
        cli, ["card", "create", "--type", "file", "--title", "shot", "--content-file", str(png)]
    )
    assert result.exit_code == 3
    assert "card upload" in result.output
    assert stub.posts == []
