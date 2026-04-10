"""Build origin metadata for chat sessions.

Detects the calling AI agent (Claude Code, OpenCode, etc.) from
environment variables and collects machine info so the backend can
track where chats originate from.
"""

from __future__ import annotations

import os
import platform
import re

from deepvista_cli import __version__


def _detect_agent_tool() -> tuple[str, str | None]:
    """Detect the AI agent tool running the CLI from environment variables.

    Returns (tool_name, tool_version).
    """
    # Claude Code: sets CLAUDECODE=1 and CLAUDE_CODE_EXECPATH containing version
    if os.environ.get("CLAUDECODE") == "1":
        version = None
        exec_path = os.environ.get("CLAUDE_CODE_EXECPATH", "")
        # Extract version from path like /Users/x/.local/share/claude/versions/2.1.100
        m = re.search(r"/versions/(\d[\d.]+\d)", exec_path)
        if m:
            version = m.group(1)
        return ("claude-code", version)

    # OpenCode: check for OPENCODE env var or opencode in PATH hint
    if os.environ.get("OPENCODE"):
        return ("opencode", os.environ.get("OPENCODE_VERSION"))

    # Cursor: sets CURSOR=1
    if os.environ.get("CURSOR"):
        return ("cursor", os.environ.get("CURSOR_VERSION"))

    # Fallback: direct CLI usage
    return ("deepvista-cli", __version__)


def _machine_description() -> str:
    """Human-readable machine description."""
    node = platform.node()
    system = platform.system()
    machine = platform.machine()
    return f"{node} ({system} {machine})"


def build_origin() -> dict[str, str | bool]:
    """Build the origin metadata dict for /imagine requests."""
    tool, tool_version = _detect_agent_tool()
    origin: dict[str, str | bool] = {
        "tool": tool,
        "machine": _machine_description(),
        "is_logged_in": True,  # CLI requires auth, always true here
    }
    if tool_version:
        origin["tool_version"] = tool_version

    # Model: check common env vars set by AI agents
    model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("CLAUDE_MODEL")
    if model:
        origin["model"] = model

    return origin
