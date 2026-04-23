"""Session-scoped conversation notes.

One DeepVista note per Claude Code (or equivalent) session. A note's body is
YAML-ish frontmatter plus an append-only list of turn blocks; each `session-tick`
re-parses the transcript JSONL, extracts the newest turn(s), and rewrites the
body with an incremented ``turn_count`` / ``version``.

Design is deliberately minimal for M1:
  - No backend schema change: versions are implicit in ``turn_count`` + body
    history lines. Server-side audit table comes in M2 (DV-449 §5).
  - Session → note mapping is cached at ``$XDG_STATE_HOME/deepvista/sessions/``.
    On cache miss we fall back to listing recent notes and client-side matching
    on the ``cc-session:<id>`` tag.

See DV-449 for the full design.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_TAG_PREFIX = "cc-session:"
AGENT_TAG_PREFIX = "agent:"
PROJECT_TAG_PREFIX = "project:"
DEFAULT_AGENT = "claude-code"
FRONTMATTER_FENCE = "---"
TURN_HEADING_RE = re.compile(r"^### Turn (\d+) · ")
SUMMARY_CHAR_LIMIT = 400
BODY_SIZE_CAP_BYTES = 50_000


# ---------------------------------------------------------------------------
# State cache — maps session_id to note_id + last-processed turn index
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "deepvista" / "sessions"


def state_path(session_id: str) -> Path:
    return _state_dir() / f"{session_id}.json"


def load_state(session_id: str) -> dict[str, Any]:
    path = state_path(session_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(session_id: str, state: dict[str, Any]) -> None:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Frontmatter (YAML-ish, but we parse only a flat key/value subset)
# ---------------------------------------------------------------------------


def parse_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """Split a body into (frontmatter dict, remaining markdown).

    Supports a flat ``key: value`` subset. Lists and nested maps are kept as
    raw strings — we only round-trip what we write, and we write scalars +
    JSON-encoded dicts.
    """
    if not body.startswith(FRONTMATTER_FENCE + "\n"):
        return {}, body
    try:
        _, fm, rest = body.split(FRONTMATTER_FENCE + "\n", 2)
    except ValueError:
        return {}, body
    data: dict[str, Any] = {}
    for line in fm.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data, rest.lstrip("\n")


def serialize_frontmatter(fm: dict[str, Any], rest: str) -> str:
    ordered_keys = [
        "agent",
        "agent_version",
        "cc_session_id",
        "project_dir",
        "git_branch",
        "git_commit",
        "git_dirty",
        "started_at",
        "updated_at",
        "turn_count",
        "version",
        "transcript_path",
        "tools_used",
        "status",
    ]
    lines = [FRONTMATTER_FENCE]
    seen: set[str] = set()
    for key in ordered_keys:
        if key in fm:
            lines.append(f"{key}: {_fmt_value(fm[key])}")
            seen.add(key)
    for key, value in fm.items():
        if key not in seen:
            lines.append(f"{key}: {_fmt_value(value)}")
    lines.append(FRONTMATTER_FENCE)
    lines.append("")
    return "\n".join(lines) + rest


def _fmt_value(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"), sort_keys=isinstance(value, dict))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Transcript parsing — extract turns from Claude Code JSONL
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One user→assistant turn pulled from the transcript."""

    user_text: str = ""
    assistant_text: str = ""
    tool_counts: Counter[str] = field(default_factory=Counter)
    files_touched: list[str] = field(default_factory=list)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return " ".join(p for p in parts if p).strip()
    return ""


def _tool_use(content: Any) -> list[tuple[str, dict]]:
    """Extract (tool_name, tool_input) pairs from an assistant content list."""
    out: list[tuple[str, dict]] = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            name = block.get("name") or "unknown"
            tin = block.get("input") or {}
            out.append((name, tin if isinstance(tin, dict) else {}))
    return out


def parse_transcript(path: str | Path) -> list[Turn]:
    """Parse a Claude Code JSONL transcript into Turn records.

    A new Turn starts on each user message. Subsequent assistant messages +
    their tool_use blocks are attached to that turn until the next user
    message.
    """
    turns: list[Turn] = []
    current: Turn | None = None
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = entry.get("role")
                content_raw = entry.get("content")
                if not role:
                    msg = entry.get("message") or {}
                    role = msg.get("role")
                    content_raw = msg.get("content")
                if not role:
                    continue
                if role == "user":
                    text = _extract_text(content_raw)
                    if not text:
                        continue
                    current = Turn(user_text=text)
                    turns.append(current)
                elif role == "assistant" and current is not None:
                    current.assistant_text = (
                        (current.assistant_text + "\n" + _extract_text(content_raw)).strip()
                        if current.assistant_text
                        else _extract_text(content_raw)
                    )
                    for name, tin in _tool_use(content_raw):
                        current.tool_counts[name] += 1
                        fp = _file_from_tool_input(name, tin)
                        if fp and fp not in current.files_touched:
                            current.files_touched.append(fp)
    except OSError:
        pass
    return turns


def _file_from_tool_input(name: str, tin: dict) -> str | None:
    if name in {"Read", "Edit", "Write", "NotebookEdit"}:
        fp = tin.get("file_path") or tin.get("path")
        if isinstance(fp, str):
            return fp
    return None


# ---------------------------------------------------------------------------
# Heuristic turn summary
# ---------------------------------------------------------------------------


def summarize_turn(turn: Turn, index: int, now: datetime | None = None) -> str:
    ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    user = _truncate(turn.user_text, SUMMARY_CHAR_LIMIT)
    assistant = _truncate(turn.assistant_text, SUMMARY_CHAR_LIMIT) or "_(no assistant output)_"
    tool_pairs = (
        turn.tool_counts.most_common()
        if isinstance(turn.tool_counts, Counter)
        else sorted(turn.tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    tools = ", ".join(f"{k}({v})" for k, v in tool_pairs) or "_(none)_"
    files = ", ".join(f"`{p}`" for p in turn.files_touched[:8]) or "_(none)_"
    return (
        f"### Turn {index} · {ts}\n"
        f"**User:** {user}\n\n"
        f"**Assistant:** {assistant}\n\n"
        f"**Tools:** {tools}\n\n"
        f"**Files touched:** {files}\n"
    )


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Body building
# ---------------------------------------------------------------------------


def _body_skeleton() -> str:
    return "## Session summary\n\n_(pending — filled at session-finalize)_\n\n## Turns\n\n"


def build_initial_body(fm: dict[str, Any]) -> str:
    return serialize_frontmatter(fm, _body_skeleton())


def append_turn(existing_body: str, turn_block: str, new_fm_updates: dict[str, Any]) -> str:
    """Merge a new turn into an existing body, returning the rewritten body.

    Frontmatter is updated in-place with ``new_fm_updates``. The turn block is
    prepended inside ``## Turns`` so newest turn is first.
    """
    fm, rest = parse_frontmatter(existing_body)
    fm.update(new_fm_updates)

    if "## Turns" not in rest:
        rest = rest.rstrip() + "\n\n## Turns\n\n" + turn_block.strip() + "\n"
    else:
        head, _, tail = rest.partition("## Turns")
        tail_body = tail.split("\n", 1)[1] if "\n" in tail else ""
        rest = f"{head}## Turns\n\n{turn_block.strip()}\n\n{tail_body.lstrip()}"

    body = serialize_frontmatter(fm, rest)
    return _cap_body_size(body)


def _cap_body_size(body: str) -> str:
    if len(body.encode("utf-8")) <= BODY_SIZE_CAP_BYTES:
        return body
    fm, rest = parse_frontmatter(body)
    head, _, tail = rest.partition("## Turns")
    tail = tail.split("\n", 1)[1] if "\n" in tail else ""
    turn_blocks = re.split(r"(?=^### Turn \d+ · )", tail, flags=re.MULTILINE)
    turn_blocks = [b for b in turn_blocks if b.strip()]
    kept: list[str] = []
    size = len(serialize_frontmatter(fm, head + "## Turns\n\n").encode("utf-8"))
    for block in turn_blocks:
        if size + len(block.encode("utf-8")) > BODY_SIZE_CAP_BYTES:
            break
        kept.append(block)
        size += len(block.encode("utf-8"))
    new_rest = head + "## Turns\n\n" + "".join(kept)
    return serialize_frontmatter(fm, new_rest)


# ---------------------------------------------------------------------------
# Environment probe — git branch/commit, project dir
# ---------------------------------------------------------------------------


def probe_git(cwd: str | Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, args in (
        ("git_branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("git_commit", ["git", "rev-parse", "--short", "HEAD"]),
    ):
        try:
            result = subprocess.run(  # noqa: S603
                args, cwd=str(cwd), capture_output=True, text=True, timeout=2, check=False
            )
            if result.returncode == 0:
                out[key] = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"], cwd=str(cwd), capture_output=True, text=True, timeout=2, check=False
        )
        if result.returncode == 0:
            out["git_dirty"] = "true" if result.stdout.strip() else "false"
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def seed_frontmatter(
    session_id: str,
    cwd: str,
    transcript: str,
    agent: str = DEFAULT_AGENT,
    agent_version: str | None = None,
) -> dict[str, Any]:
    fm: dict[str, Any] = {
        "agent": agent,
        "cc_session_id": session_id,
        "project_dir": cwd,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "turn_count": 0,
        "version": 1,
        "transcript_path": transcript,
        "status": "active",
    }
    if agent_version:
        fm["agent_version"] = agent_version
    fm.update(probe_git(cwd))
    return fm


def session_tags(session_id: str, agent: str, cwd: str) -> list[str]:
    project = Path(cwd).name
    return [
        f"{SESSION_TAG_PREFIX}{session_id}",
        f"{AGENT_TAG_PREFIX}{agent}",
        f"{PROJECT_TAG_PREFIX}{project}",
        "session-note",
    ]


def default_title(session_id: str, cwd: str) -> str:
    project = Path(cwd).name or "session"
    return f"{project} · {session_id[:8]}"
