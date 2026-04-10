"""Build origin metadata for chat sessions.

Detects the calling AI agent (Claude Code, OpenCode, Cursor, etc.) from
environment variables — with a process-tree fallback — and collects machine
info so the backend can track where chats originate from.

Everything is computed once per process via ``@functools.lru_cache`` on
``build_origin()``.
"""

from __future__ import annotations

import functools
import logging
import os
import platform
import re
import subprocess

from deepvista_cli import __version__

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent detection — env vars (fast, reliable, preferred)
# ---------------------------------------------------------------------------


def _detect_from_env() -> tuple[str, str | None] | None:
    """Try to identify the agent from well-known environment variables.

    Returns ``(tool_name, tool_version)`` or ``None`` if nothing matched.
    """
    # Claude Code: sets CLAUDECODE=1, version embedded in CLAUDE_CODE_EXECPATH
    if os.environ.get("CLAUDECODE") == "1":
        version = None
        exec_path = os.environ.get("CLAUDE_CODE_EXECPATH", "")
        m = re.search(r"/versions/(\d[\d.]+\d)", exec_path)
        if m:
            version = m.group(1)
        return ("claude-code", version)

    # OpenCode: sets OPENCODE=1
    if os.environ.get("OPENCODE"):
        return ("opencode", os.environ.get("OPENCODE_VERSION"))

    # Cursor: sets CURSOR=1
    if os.environ.get("CURSOR"):
        return ("cursor", os.environ.get("CURSOR_VERSION"))

    # Windsurf (Codeium): sets WINDSURF=1
    if os.environ.get("WINDSURF"):
        return ("windsurf", os.environ.get("WINDSURF_VERSION"))

    # Cline (VS Code extension): sets CLINE=1
    if os.environ.get("CLINE"):
        return ("cline", os.environ.get("CLINE_VERSION"))

    # Aider: sets AIDER=1
    if os.environ.get("AIDER"):
        return ("aider", os.environ.get("AIDER_VERSION"))

    # GitHub Copilot CLI
    if os.environ.get("GITHUB_COPILOT"):
        return ("github-copilot", os.environ.get("GITHUB_COPILOT_VERSION"))

    # Generic "some agent is driving us" but we don't know which one
    if os.environ.get("AGENT"):
        return None  # fall through to process-tree detection

    return None


# ---------------------------------------------------------------------------
# Agent detection — process-tree fallback (heavier, best-effort)
# ---------------------------------------------------------------------------

# Map of substrings found in process names / cmdlines → tool names.
_PROCESS_HINTS: dict[str, str] = {
    "claude": "claude-code",
    "opencode": "opencode",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "cline": "cline",
    "aider": "aider",
    "copilot": "github-copilot",
    "codex": "codex-cli",
}


def _detect_from_process_tree() -> tuple[str, str | None] | None:
    """Walk the parent process chain looking for a recognisable agent.

    Uses *psutil* (already a project dependency).  Returns ``None`` on any
    failure — this is strictly best-effort.
    """
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        return None

    try:
        pid = os.getppid()
        for _ in range(8):  # walk at most 8 levels
            proc = psutil.Process(pid)
            name_lower = proc.name().lower()
            cmdline_str = " ".join(proc.cmdline()[:3]).lower()
            haystack = f"{name_lower} {cmdline_str}"

            for hint, tool in _PROCESS_HINTS.items():
                if hint in haystack:
                    return (tool, None)

            pid = proc.ppid()
            if pid <= 1:
                break
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        log.debug("process-tree agent detection failed", exc_info=True)

    return None


# ---------------------------------------------------------------------------
# Public: combined detection
# ---------------------------------------------------------------------------


def _detect_agent_tool() -> tuple[str, str | None]:
    """Detect the AI agent driving the CLI.

    Strategy: check environment variables first (cheap, explicit), then fall
    back to walking the process tree (heavier, heuristic).  If neither
    succeeds, assume direct CLI usage.
    """
    result = _detect_from_env()
    if result is not None:
        return result

    result = _detect_from_process_tree()
    if result is not None:
        return result

    return ("deepvista-cli", __version__)


def _native_arch() -> str:
    """Return the real hardware architecture, bypassing emulation layers.

    On macOS under Rosetta 2, ``platform.machine()`` and even child-process
    ``uname -m`` return ``x86_64``.  We detect Rosetta via
    ``sysctl.proc_translated`` and escape with ``arch -arm64e``.

    On Windows under ARM emulation, ``platform.machine()`` may return
    ``AMD64`` — we check ``PROCESSOR_ARCHITEW6432`` for the native arch.

    Linux is straightforward: ``platform.machine()`` is reliable.
    """
    system = platform.system()
    machine = platform.machine()

    if system == "Darwin" and machine == "x86_64":
        try:
            translated = subprocess.run(  # noqa: S603
                ["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if translated.returncode == 0 and translated.stdout.strip() == "1":
                native = subprocess.run(  # noqa: S603
                    ["/usr/bin/arch", "-arm64e", "/usr/bin/uname", "-m"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if native.returncode == 0 and native.stdout.strip():
                    return native.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass

    if system == "Windows" and machine == "AMD64":
        # PROCESSOR_ARCHITEW6432 is set when a 32/64-bit process runs on ARM64
        native = os.environ.get("PROCESSOR_ARCHITEW6432", "")
        if native.upper() == "ARM64":
            return "ARM64"

    return machine


_ARCH_LABELS: dict[str, str] = {
    "arm64": "Apple Silicon",
    "aarch64": "ARM64",
    "ARM64": "ARM64",
    "x86_64": "Intel",
    "AMD64": "Intel",
}

_OS_LABELS: dict[str, str] = {
    "Darwin": "macOS",
    "Linux": "Linux",
    "Windows": "Windows",
}


def _machine_description() -> str:
    """Human-readable device label: ``hostname · OS · chip``."""
    hostname = platform.node()
    system = _OS_LABELS.get(platform.system(), platform.system())
    arch = _native_arch()
    chip = _ARCH_LABELS.get(arch, arch)
    return f"{hostname} · {system} · {chip}"


@functools.lru_cache(maxsize=1)
def build_origin() -> dict[str, str | bool]:
    """Build the origin metadata dict for /imagine requests.

    Cached for the lifetime of the process — agent detection and machine
    info won't change mid-session.
    """
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
