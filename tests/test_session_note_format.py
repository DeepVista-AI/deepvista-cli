"""Tests for DV-817: session card title + turn-block formatting.

The session card is rendered in DeepVista's vistabase using the
``<accordion-plain>`` shortcode for each round, and the title is shown as the
list-row label. These tests pin the format so a regression in the CLI is
caught before it ships a wall of unwrapped turns to users.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime

from deepvista_cli import session_note as sn
from deepvista_cli.session_note import Turn


def test_default_title_is_human_readable() -> None:
    now = datetime(2026, 5, 25, 14, 32, tzinfo=UTC)
    title = sn.default_title("abcdef0123456789", "/Users/rj/Project/deepvista", now=now)
    assert title == "deepvista session · 2026-05-25 14:32"


def test_default_title_falls_back_when_cwd_unnamed() -> None:
    now = datetime(2026, 5, 25, 14, 32, tzinfo=UTC)
    title = sn.default_title("abcdef0123456789", "/", now=now)
    assert title.startswith("session · 2026-05-25 14:32")


def test_summarize_turn_wraps_in_accordion_plain() -> None:
    turn = Turn(
        user_text="Help me improve the session card UI",
        assistant_text="Sure, here is the plan",
        tool_counts=Counter({"Read": 3, "Edit": 1}),
        files_touched=["/foo/bar.py"],
    )
    now = datetime(2026, 5, 25, 14, 32, tzinfo=UTC)
    block = sn.summarize_turn(turn, 1, now=now)

    assert block.startswith("<accordion-plain>\n")
    assert block.rstrip().endswith("</accordion-plain>")

    # Head line: "Turn N · <preview from user text>"
    head_line = block.split("\n", 2)[1]
    assert head_line == "Turn 1 · Help me improve the session card UI"

    # Body keeps the existing structured fields.
    assert "**User:** Help me improve the session card UI" in block
    assert "**Assistant:** Sure, here is the plan" in block
    assert "**Tools:** Read(3), Edit(1)" in block
    assert "**Files touched:** `/foo/bar.py`" in block
    assert "_2026-05-25T14:32:00+00:00_" in block


def test_summarize_turn_head_falls_back_when_user_text_empty() -> None:
    turn = Turn(user_text="", assistant_text="Some output", tool_counts=Counter())
    block = sn.summarize_turn(turn, 7)
    head_line = block.split("\n", 2)[1]
    assert head_line == "Turn 7 · (no user text)"


def test_summarize_turn_head_truncates_long_user_text() -> None:
    long_text = "x" * 200
    turn = Turn(user_text=long_text, assistant_text="ok", tool_counts=Counter())
    block = sn.summarize_turn(turn, 1)
    head_line = block.split("\n", 2)[1]
    # "Turn 1 · " plus the truncated text — capped well under 200 chars
    assert head_line.startswith("Turn 1 · ")
    head_payload = head_line[len("Turn 1 · ") :]
    assert len(head_payload) <= sn.TURN_HEAD_CHAR_LIMIT
    assert head_payload.endswith("…")


def test_serialize_frontmatter_round_trips_summary() -> None:
    fm = {"agent": "claude-code", "summary": "First question text", "status": "active"}
    body = sn.serialize_frontmatter(fm, "## Turns\n\n")
    fm_back, _ = sn.parse_frontmatter(body)
    assert fm_back["summary"] == "First question text"
    # `summary` appears before `status` in the canonical order.
    assert body.index("summary:") < body.index("status:")


def test_append_turn_prepends_accordion_blocks() -> None:
    fm = sn.seed_frontmatter("sess-1", "/tmp/proj", "/tmp/t.jsonl")
    body = sn.build_initial_body(fm)

    t1 = Turn(user_text="First question", assistant_text="A1", tool_counts=Counter())
    body = sn.append_turn(body, sn.summarize_turn(t1, 1), {"turn_count": 1, "version": 1})

    t2 = Turn(user_text="Second question", assistant_text="A2", tool_counts=Counter())
    body = sn.append_turn(body, sn.summarize_turn(t2, 2), {"turn_count": 2, "version": 2})

    # Two accordion blocks, newest first.
    assert body.count("<accordion-plain>") == 2
    second_idx = body.index("Turn 2 · ")
    first_idx = body.index("Turn 1 · ")
    assert second_idx < first_idx


def test_summary_from_user_text_truncates_to_frontmatter_limit() -> None:
    short = sn.summary_from_user_text("Short prompt")
    assert short == "Short prompt"

    long_text = "x" * (sn.FRONTMATTER_SUMMARY_CHAR_LIMIT + 50)
    truncated = sn.summary_from_user_text(long_text)
    assert len(truncated) <= sn.FRONTMATTER_SUMMARY_CHAR_LIMIT
    assert truncated.endswith("…")


def test_summary_from_user_text_collapses_newlines() -> None:
    summary = sn.summary_from_user_text("line one\nline two")
    assert "\n" not in summary
    assert summary == "line one line two"


def test_summary_from_user_text_returns_empty_for_blank_input() -> None:
    assert sn.summary_from_user_text("") == ""
    assert sn.summary_from_user_text("   \n  ") == ""


def test_cap_body_size_splits_on_accordion_boundary(monkeypatch) -> None:
    monkeypatch.setattr(sn, "BODY_SIZE_CAP_BYTES", 3000)

    fm = sn.seed_frontmatter("sess-1", "/tmp/proj", "/tmp/t.jsonl")
    body = sn.build_initial_body(fm)
    for i in range(1, 11):
        turn = Turn(
            user_text=f"Question {i} " + "x" * 200,
            assistant_text=f"Answer {i} " + "y" * 200,
            tool_counts=Counter(),
        )
        body = sn.append_turn(body, sn.summarize_turn(turn, i), {"turn_count": i, "version": i})

    # Body stayed under the cap.
    assert len(body.encode("utf-8")) <= 3000

    # Newest turn (10) survives; oldest got trimmed.
    accordions = re.findall(r"<accordion-plain>", body)
    assert len(accordions) >= 1
    assert "Turn 10 · " in body
    assert "Turn 1 · " not in body
