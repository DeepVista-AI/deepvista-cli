"""Unit tests for deepvista_cli.session_note (DV-449).

Run with: ``uv run python -m unittest tests.test_session_note``.

Tests cover:
- Frontmatter round-trip (parse → serialize).
- Transcript JSONL parser (flat {role, content} and nested {message: {…}} formats).
- Turn summary rendering.
- Body append ordering (newest turn first).
- State cache read/write isolation via ``XDG_STATE_HOME`` override.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from deepvista_cli import session_note as sn


class FrontmatterTests(unittest.TestCase):
    def test_round_trip_scalar_and_dict(self) -> None:
        fm = {
            "agent": "claude-code",
            "cc_session_id": "abc-123",
            "turn_count": 3,
            "tools_used": {"Read": 2, "Edit": 1},
            "git_dirty": True,
        }
        rest = "## Session summary\n\nbody\n"
        body = sn.serialize_frontmatter(fm, rest)
        parsed, tail = sn.parse_frontmatter(body)
        self.assertEqual(parsed["agent"], "claude-code")
        self.assertEqual(parsed["cc_session_id"], "abc-123")
        self.assertEqual(parsed["turn_count"], "3")  # flat string parse — caller re-casts
        self.assertEqual(parsed["git_dirty"], "true")
        self.assertEqual(json.loads(parsed["tools_used"]), {"Edit": 1, "Read": 2})
        self.assertEqual(tail, rest)

    def test_parse_body_with_no_frontmatter(self) -> None:
        fm, rest = sn.parse_frontmatter("# hello\nbody\n")
        self.assertEqual(fm, {})
        self.assertEqual(rest, "# hello\nbody\n")


class TranscriptParseTests(unittest.TestCase):
    def _write_jsonl(self, entries: list[dict]) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return path

    def test_flat_format(self) -> None:
        path = self._write_jsonl(
            [
                {"role": "user", "content": "hi there"},
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "second turn"},
                {"role": "assistant", "content": "response 2"},
            ]
        )
        turns = sn.parse_transcript(path)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].user_text, "hi there")
        self.assertEqual(turns[0].assistant_text, "hello")
        self.assertEqual(turns[1].user_text, "second turn")
        Path(path).unlink()

    def test_nested_format_with_tool_use(self) -> None:
        path = self._write_jsonl(
            [
                {"message": {"role": "user", "content": [{"type": "text", "text": "edit foo.py"}]}},
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "on it"},
                            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/repo/foo.py"}},
                            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/repo/foo.py"}},
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ],
                    }
                },
            ]
        )
        turns = sn.parse_transcript(path)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].user_text, "edit foo.py")
        self.assertEqual(turns[0].assistant_text, "on it")
        self.assertEqual(turns[0].tool_counts["Edit"], 2)
        self.assertEqual(turns[0].tool_counts["Bash"], 1)
        self.assertEqual(turns[0].files_touched, ["/repo/foo.py"])
        Path(path).unlink()

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(sn.parse_transcript("/nonexistent/path.jsonl"), [])


class SummarizeTurnTests(unittest.TestCase):
    def test_renders_all_sections(self) -> None:
        turn = sn.Turn(user_text="hello world", assistant_text="hi", tool_counts=Counter({"Read": 2}))
        turn.files_touched = ["/repo/a.py"]
        out = sn.summarize_turn(turn, index=1)
        self.assertIn("### Turn 1 ·", out)
        self.assertIn("**User:** hello world", out)
        self.assertIn("**Assistant:** hi", out)
        self.assertIn("Read(2)", out)
        self.assertIn("`/repo/a.py`", out)

    def test_truncates_long_text(self) -> None:
        turn = sn.Turn(user_text="x" * 10_000, assistant_text="y" * 10_000)
        out = sn.summarize_turn(turn, index=2)
        self.assertIn("…", out)


class BodyAppendTests(unittest.TestCase):
    def test_appends_turn_newest_first(self) -> None:
        body = sn.build_initial_body({"agent": "claude-code", "turn_count": 0})
        body = sn.append_turn(body, "### Turn 1 · 2026-04-23T00:00:00+00:00\n**User:** a\n", {"turn_count": 1})
        body = sn.append_turn(body, "### Turn 2 · 2026-04-23T00:01:00+00:00\n**User:** b\n", {"turn_count": 2})
        t2 = body.index("### Turn 2")
        t1 = body.index("### Turn 1")
        self.assertLess(t2, t1, "newest turn should appear first under ## Turns")
        fm, _ = sn.parse_frontmatter(body)
        self.assertEqual(fm["turn_count"], "2")


class StateCacheTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            os.environ["XDG_STATE_HOME"] = d
            try:
                sn.save_state("sess-1", {"note_id": "n1", "last_turn_index": 3})
                self.assertEqual(sn.load_state("sess-1"), {"note_id": "n1", "last_turn_index": 3})
                self.assertEqual(sn.load_state("sess-missing"), {})
            finally:
                del os.environ["XDG_STATE_HOME"]


class SeedFrontmatterTests(unittest.TestCase):
    def test_has_required_keys(self) -> None:
        fm = sn.seed_frontmatter("sess-x", "/tmp/proj", "/tmp/t.jsonl")
        for key in ("agent", "cc_session_id", "project_dir", "started_at", "turn_count", "version", "status"):
            self.assertIn(key, fm)
        self.assertEqual(fm["cc_session_id"], "sess-x")
        self.assertEqual(fm["status"], "active")


if __name__ == "__main__":
    unittest.main()
