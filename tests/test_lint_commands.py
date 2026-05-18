"""Tests for `deepvista lint`, focused on the DV-724 skills-refresh check."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from deepvista_cli.commands import lint as lint_module
from deepvista_cli.main import cli

# ---------------------------------------------------------------------------
# _parse_time_range
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, seconds, canonical",
    [
        ("30s", 30, "30s"),
        ("5m", 300, "5m"),
        ("1h", 3600, "1h"),
        ("4h", 4 * 3600, "4h"),
        ("1d", 86400, "1d"),
        ("7d", 7 * 86400, "7d"),
        ("2w", 14 * 86400, "2w"),
        ("  1D ", 86400, "1d"),  # whitespace + uppercase tolerated
    ],
)
def test_parse_time_range_accepts_supported_units(raw: str, seconds: int, canonical: str) -> None:
    s, c = lint_module._parse_time_range(raw)
    assert s == seconds
    assert c == canonical


@pytest.mark.parametrize("raw", ["", "abc", "1", "1y", "-1h", "0d", "1.5d", "h1"])
def test_parse_time_range_rejects_garbage(raw: str) -> None:
    import click

    with pytest.raises(click.BadParameter):
        lint_module._parse_time_range(raw)


# ---------------------------------------------------------------------------
# _resolve_cutoff
# ---------------------------------------------------------------------------


def test_resolve_cutoff_produces_iso_z_timestamp() -> None:
    fixed = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
    out = lint_module._resolve_cutoff(86400, now=fixed)
    assert out == "2026-05-17T12:00:00Z"


def test_resolve_cutoff_default_now_returns_well_formed_iso() -> None:
    out = lint_module._resolve_cutoff(3600)
    # 2026-05-18T07:13:36Z style
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", out)


# ---------------------------------------------------------------------------
# _resolve_checks — write-check semantics
# ---------------------------------------------------------------------------


def test_resolve_checks_all_excludes_write_checks() -> None:
    result = lint_module._resolve_checks(())
    assert "skills-refresh" not in result
    # The other documented checks still come through.
    for ro in ("duplicates", "contradictions", "stale", "orphans", "missing-refs", "gaps"):
        assert ro in result


def test_resolve_checks_all_plus_skills_refresh_keeps_explicit_write() -> None:
    result = lint_module._resolve_checks(("all", "skills-refresh"))
    assert result[-1] == "skills-refresh"
    assert result.count("skills-refresh") == 1


def test_resolve_checks_preserves_caller_order_and_dedupes() -> None:
    result = lint_module._resolve_checks(("stale", "duplicates", "stale"))
    assert result == ["stale", "duplicates"]


# ---------------------------------------------------------------------------
# _build_prompt — cutoff templating
# ---------------------------------------------------------------------------


def test_build_prompt_templates_cutoff_into_skills_refresh() -> None:
    prompt = lint_module._build_prompt(["skills-refresh"], fix=False, cutoff_iso="2026-05-17T12:00:00Z", window="1d")
    assert "2026-05-17T12:00:00Z" in prompt
    assert "last 1d" in prompt
    # Read-only suffix is appended even though this is a write check —
    # the write-confirmation lives in the CLI gate, not in the prompt body.


def test_build_prompt_asserts_when_skills_refresh_missing_cutoff() -> None:
    with pytest.raises(AssertionError):
        lint_module._build_prompt(["skills-refresh"], fix=False, cutoff_iso=None, window=None)


# ---------------------------------------------------------------------------
# CLI integration — dry-run + validation
# ---------------------------------------------------------------------------


def test_cli_dry_run_includes_resolved_cutoff() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--check", "skills-refresh", "--time-range", "1d", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["checks"] == ["skills-refresh"]
    assert payload["time_range"]["window"] == "1d"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", payload["time_range"]["cutoff_iso"])
    # The cutoff must also be embedded in the prompt itself.
    assert payload["time_range"]["cutoff_iso"] in payload["payload"]["user_instruction"]


def test_cli_skills_refresh_requires_time_range() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["lint", "--check", "skills-refresh", "--dry-run"])
    assert result.exit_code != 0
    combined = result.output + (result.stderr or "")
    assert "--time-range" in combined


def test_cli_bad_time_range_is_rejected() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--check", "skills-refresh", "--time-range", "1y", "--dry-run"],
    )
    assert result.exit_code != 0
    combined = result.output + (result.stderr or "")
    assert "--time-range" in combined


def test_cli_time_range_without_skills_refresh_warns_and_continues() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--check", "duplicates", "--time-range", "1d", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    # The warning is written to stderr; click's CliRunner merges by default.
    assert "--time-range is only used by --check skills-refresh" in (result.output + (result.stderr or ""))


def test_cli_default_all_does_not_pick_up_skills_refresh() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["lint", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "skills-refresh" not in payload["checks"]


def test_cli_write_check_prompts_without_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `-y`, `skills-refresh` must hit the confirmation gate before streaming."""
    calls: list[tuple[str, dict]] = []

    def fake_stream_sse(self, path, body):  # type: ignore[no-untyped-def]
        calls.append((path, body))
        return iter([])

    from deepvista_cli.client import http as http_module

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(http_module.DeepVistaClient, "stream_sse", fake_stream_sse)

    runner = CliRunner()
    # No -y, no stdin input → click.confirm aborts with non-zero exit.
    result = runner.invoke(
        cli,
        ["lint", "--check", "skills-refresh", "--time-range", "1d"],
        input="n\n",
    )
    assert result.exit_code != 0, result.output
    assert calls == [], "stream_sse must not be called when the user declines the write gate"
    assert "skill" in result.output.lower()


def test_cli_write_check_streams_with_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_stream_sse(self, path, body):  # type: ignore[no-untyped-def]
        calls.append((path, body))
        yield {"type": "done"}

    from deepvista_cli.client import http as http_module

    def fake_init(self, config):  # type: ignore[no-untyped-def]
        self.config = config

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", fake_init)
    monkeypatch.setattr(http_module.DeepVistaClient, "stream_sse", fake_stream_sse)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["lint", "--check", "skills-refresh", "--time-range", "1d", "-y"],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    path, body = calls[0]
    assert path == "/imagine"
    assert "skills-refresh" in body["user_instruction"]
    # The dry-run-style cutoff must appear in the streamed instruction too.
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["user_instruction"])
