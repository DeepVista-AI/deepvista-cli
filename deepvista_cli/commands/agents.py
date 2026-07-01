"""deepvista agents — register and manage AI agents connected to DeepVista.

Each registered agent (Claude Code, OpenClaw, Cursor, etc.) gets a persistent
identity with config, soul, and memory stored in DeepVista.

Agent IDs are stored locally at ~/.config/deepvista/agents/<agent_type>.json
so the CLI knows which agent it's running inside.
"""

from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path

import click

from deepvista_cli import agent_catalog
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import build_origin, detect_agent_tool
from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.output.formatter import format_output, output_error

AGENT_COLUMNS = ["id", "name", "agent_type", "agent_role", "status", "last_heartbeat_at", "updated_at"]
AGENTS_DIR = CONFIG_DIR / "agents"

# DV-832: agent_role is open-text. We provide a default but do not
# enforce a closed set — the product list (sales, marketing, product,
# engineering, hiring, content, misc, …) may change.
DEFAULT_AGENT_ROLE = "misc"

# Backend error codes (mirror of ai/chat_service/routers/agents.py constants).
# Surfaced via the JSON response body so the CLI can recover programmatically
# instead of bailing on the user.
ERROR_CODE_AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
ERROR_CODE_AGENT_ALREADY_REGISTERED = "AGENT_ALREADY_REGISTERED"

# Friendly labels for auto-generated agent names. Matches the agent_type choices
# below; anything missing falls back to the raw type string.
_AGENT_TYPE_LABELS = {
    "claude-code": "Claude Code",
    "opencode": "OpenCode",
    "openclaw": "OpenClaw",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "cline": "Cline",
    "aider": "Aider",
    "github-copilot": "GitHub Copilot",
    "deepvista-cli": "DeepVista CLI",
}


# ---------------------------------------------------------------------------
# Local agent ID storage
# ---------------------------------------------------------------------------


def _agent_id_path(agent_type: str, agent_role: str | None = None, project_id: str | None = None) -> Path:
    """Path to the local agent registration file for a given (type, role[, project]).

    DV-832: cache key is ``<type>__<role>.json`` so a single machine can host
    multiple roles. When ``project_id`` is supplied the key becomes
    ``<type>__<role>__<project_id>.json`` so a machine can also host the same
    role for multiple projects without one overwriting the other. When
    ``agent_role`` is omitted we fall back to the legacy ``<type>.json``
    filename for read-only adoption — see ``_load_agent_id``.
    """
    if agent_role and project_id:
        return AGENTS_DIR / f"{agent_type}__{agent_role}__{project_id}.json"
    if agent_role:
        return AGENTS_DIR / f"{agent_type}__{agent_role}.json"
    return AGENTS_DIR / f"{agent_type}.json"


def _save_agent_id(
    agent_type: str,
    agent_id: str,
    agent_role: str = DEFAULT_AGENT_ROLE,
    project_id: str | None = None,
    project_name: str | None = None,
) -> None:
    """Persist agent ID locally after registration."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _agent_id_path(agent_type, agent_role, project_id)
    data: dict = {"agent_id": agent_id, "agent_type": agent_type, "agent_role": agent_role}
    if project_id:
        data["project_id"] = project_id
    if project_name:
        data["project_name"] = project_name
    path.write_text(_json.dumps(data))
    os.chmod(path, 0o600)


def _load_agent_id(
    agent_type: str,
    agent_role: str | None = None,
    project_id: str | None = None,
) -> str | None:
    """Load locally stored agent ID for a given (type, [role], [project_id]).

    Resolution order:
    1. Exact ``<type>__<role>__<project_id>.json`` when both role and project_id given.
    2. ``<type>__<role>.json`` when only role given (DV-832).
    3. Most-recently-modified file matching the type (no role/project filter).

    When ``project_id`` is supplied without a role the scan is filtered to
    files whose JSON content has a matching ``project_id``.
    Migrates the legacy ``<type>.json`` file on first read by treating it as
    the ``misc`` role.
    """
    if agent_role and project_id:
        # Prefer the project-keyed file; fall back to the role-only file (old
        # registrations that pre-date project_id storage).
        for path in [
            _agent_id_path(agent_type, agent_role, project_id),
            _agent_id_path(agent_type, agent_role),
        ]:
            if not path.exists():
                continue
            try:
                data = _json.loads(path.read_text())
                stored_project = data.get("project_id")
                # Accept role-only files only when their project_id matches or is absent.
                if stored_project and stored_project != project_id:
                    continue
                if aid := data.get("agent_id"):
                    return aid
            except (_json.JSONDecodeError, KeyError):
                continue
        return None

    if agent_role:
        # Any project for this role — prefer the newest project-keyed file,
        # fall back to the role-only file.
        candidates: list[tuple[float, Path]] = []
        if AGENTS_DIR.exists():
            for p in AGENTS_DIR.glob(f"{agent_type}__{agent_role}*.json"):
                try:
                    candidates.append((p.stat().st_mtime, p))
                except OSError:
                    continue
        candidates.sort(reverse=True)
        for _, path in candidates:
            try:
                if aid := _json.loads(path.read_text()).get("agent_id"):
                    return aid
            except (_json.JSONDecodeError, KeyError):
                continue
        return None

    # No role specified — scan all per-role files for this type, prefer newest.
    # When project_id is given, filter to matching entries.
    candidates = []
    if AGENTS_DIR.exists():
        for p in AGENTS_DIR.glob(f"{agent_type}__*.json"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue

    # Legacy fallback: the pre-DV-832 ``<type>.json`` file (treated as role=misc).
    legacy = AGENTS_DIR / f"{agent_type}.json"
    if legacy.exists():
        try:
            candidates.append((legacy.stat().st_mtime, legacy))
        except OSError:
            pass

    if not candidates:
        return None

    candidates.sort(reverse=True)
    for _, path in candidates:
        try:
            data = _json.loads(path.read_text())
            if project_id:
                stored = data.get("project_id")
                if stored and stored != project_id:
                    continue
            if aid := data.get("agent_id"):
                return aid
        except (_json.JSONDecodeError, KeyError):
            continue
    return None


def load_agent_id_for_active_agent() -> str | None:
    """Best-effort lookup of the active agent's UUID from the local cache.

    Detects the active agent type via the same env/process-tree heuristics used
    elsewhere (``detect_agent_tool``) and returns the agent UUID previously
    persisted by ``agents register`` / ``agents sync`` (DV-751 self-healing).

    Returns ``None`` when no UUID is available — callers should treat the
    ``agent_id`` tag/frontmatter/header field as optional.
    """
    try:
        agent_type, _ = detect_agent_tool()
    except Exception:
        return None
    if not agent_type:
        return None
    return _load_agent_id(agent_type)


def _remove_agent_id(
    agent_type: str,
    agent_role: str | None = None,
    project_id: str | None = None,
) -> None:
    """Remove local agent registration file(s) for this type.

    When ``agent_role`` and ``project_id`` are both given, only that exact
    project-keyed file is removed. When only ``agent_role`` is given, all
    files for that role (across all projects) are removed. Without either,
    every cache for this type (including the legacy ``<type>.json``) is
    cleared — used when a stale local record needs to be wiped before
    re-registration (DV-751).
    """
    if agent_role and project_id:
        _agent_id_path(agent_type, agent_role, project_id).unlink(missing_ok=True)
        return

    if agent_role:
        # Remove all project-keyed and role-only files for this role.
        if AGENTS_DIR.exists():
            for path in AGENTS_DIR.glob(f"{agent_type}__{agent_role}*.json"):
                path.unlink(missing_ok=True)
        return

    if AGENTS_DIR.exists():
        for path in AGENTS_DIR.glob(f"{agent_type}__*.json"):
            path.unlink(missing_ok=True)
    legacy = AGENTS_DIR / f"{agent_type}.json"
    if legacy.exists():
        legacy.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Hook migration — heartbeat is now delivered by the DeepVista plugin
# ---------------------------------------------------------------------------

_HOOK_MARKER = "agents sync"


def _migrate_legacy_hooks(agent_type: str) -> bool:
    """Strip the legacy standalone heartbeat hook from agent settings.

    The agent heartbeat is now owned by the DeepVista Claude Code plugin
    (``plugins/claude-code`` → ``scripts/deepvista-agent-sync.sh``), which wraps
    the ``agents sync`` call in the safe hook pattern (PATH export,
    ``command -v`` guard, backgrounded, output redirected to a log, always
    ``exit 0``). Earlier versions injected a *raw* ``deepvista agents sync`` Stop
    hook straight into ``~/.claude/settings.json``; with no safety wrapper it
    errored and exited non-zero on every Stop whenever DNS/auth failed, which
    Claude Code surfaced as a looping "Stop hook feedback" (DV-1357).

    Registering now removes that legacy hook so the plugin is the single source
    of truth. Returns True if a legacy hook was removed.
    """
    if agent_type == "claude-code":
        return _uninstall_claude_code_hooks()
    # Other agent types can be added here
    return False


def _uninstall_hooks(agent_type: str) -> bool:
    """Remove DeepVista hooks from agent settings."""
    if agent_type == "claude-code":
        return _uninstall_claude_code_hooks()
    return False


def _find_hook_command(entry: dict) -> str:
    """Extract command string from a hook entry (handles nested format)."""
    # Nested format: {"matcher": "", "hooks": [{"type": "command", "command": "..."}]}
    for h in entry.get("hooks", []):
        if isinstance(h, dict):
            cmd = h.get("command", "")
            if cmd:
                return cmd
    # Flat format fallback: {"command": "..."}
    return entry.get("command", "")


def _uninstall_claude_code_hooks() -> bool:
    """Remove DeepVista hooks from ~/.claude/settings.json."""
    settings_path = _HOME / ".claude" / "settings.json"
    if not settings_path.is_file():
        return False

    try:
        settings = _json.loads(settings_path.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        return False

    hooks = settings.get("hooks", {})
    changed = False

    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        filtered = [e for e in entries if not (isinstance(e, dict) and _HOOK_MARKER in _find_hook_command(e))]
        if len(filtered) != len(entries):
            hooks[event] = filtered
            changed = True

    if changed:
        settings_path.write_text(_json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return changed


# ---------------------------------------------------------------------------
# Environment scanning — fingerprint, skills, memory, MCP, permissions, hooks, git
# ---------------------------------------------------------------------------

_HOME = Path.home()


def _build_machine_fingerprint() -> str:
    """Deterministic machine fingerprint: sha256(hostname + first-MAC + os)."""
    import hashlib
    import platform
    import uuid

    hostname = platform.node()
    mac = uuid.getnode()  # first MAC address as int
    os_name = platform.system()
    raw = f"{hostname}:{mac}:{os_name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_fingerprint() -> dict[str, str]:
    """Structured machine fingerprint per RFC."""
    import platform

    return {
        "machine_id": _build_machine_fingerprint(),
        "hostname": platform.node(),
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "os_version": platform.version(),
    }


def _discover_skills(agent_type: str) -> list[str]:
    """Discover installed skill names for a given agent type."""
    dirs: list[Path] = []

    if agent_type in ("claude-code", "opencode", "cursor", "windsurf", "cline"):
        dirs.append(_HOME / ".agents" / "skills")
        dirs.append(Path.cwd() / ".claude" / "skills")
        dirs.append(Path.cwd() / ".claude" / "local-skills")
    elif agent_type == "openclaw":
        dirs.append(_HOME / ".agents" / "skills")
        dirs.append(_HOME / ".openclaw" / "skills")

    skills: list[str] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for child in sorted(d.iterdir()):
            if child.is_dir() and (child / "SKILL.md").exists():
                skills.append(child.name)
    return list(dict.fromkeys(skills))


def _read_memory_index(agent_type: str) -> str | None:
    """Read memory index (MEMORY.md) for the current agent context."""
    candidates: list[Path] = []

    if agent_type in ("claude-code", "opencode"):
        cwd = str(Path.cwd()).replace("/", "-")
        candidates.append(_HOME / ".claude" / "projects" / cwd / "memory" / "MEMORY.md")
        candidates.append(_HOME / ".claude" / "memory" / "MEMORY.md")

    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except OSError:
                continue
    return None


def _read_mcp_servers(agent_type: str) -> list[dict[str, str]] | None:
    """Read MCP server configs from agent settings."""
    if agent_type not in ("claude-code", "opencode"):
        return None

    candidates = [
        Path.cwd() / ".mcp.json",
        _HOME / ".claude" / "mcp.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            return [{"name": k, "command": v.get("command", "")} for k, v in servers.items()]
        except (OSError, _json.JSONDecodeError, AttributeError):
            continue
    return None


def _read_permissions(agent_type: str) -> dict[str, list[str]] | None:
    """Read tool permissions from agent settings."""
    if agent_type != "claude-code":
        return None

    candidates = [
        Path.cwd() / ".claude" / "settings.json",
        _HOME / ".claude" / "settings.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            perms = data.get("permissions", {})
            if perms:
                return perms
        except (OSError, _json.JSONDecodeError):
            continue
    return None


def _read_hooks(agent_type: str) -> dict[str, list[str]] | None:
    """Read hook configurations from agent settings."""
    if agent_type != "claude-code":
        return None

    candidates = [
        Path.cwd() / ".claude" / "settings.json",
        _HOME / ".claude" / "settings.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            if hooks:
                # Simplify: just extract hook names + commands
                result: dict[str, list[str]] = {}
                for event, entries in hooks.items():
                    if isinstance(entries, list):
                        result[event] = [e.get("command", "") for e in entries if isinstance(e, dict)]
                return result if result else None
        except (OSError, _json.JSONDecodeError):
            continue
    return None


def _read_git_context() -> dict[str, str] | None:
    """Read current git context (branch, remote, project name)."""
    import subprocess

    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        remote = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ctx: dict[str, str] = {}
        if branch.returncode == 0:
            ctx["branch"] = branch.stdout.strip()
        if remote.returncode == 0:
            ctx["remote_url"] = remote.stdout.strip()
        if toplevel.returncode == 0:
            ctx["project_name"] = Path(toplevel.stdout.strip()).name
        return ctx if ctx else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_soul(agent_type: str) -> str | None:
    """Auto-read system prompt / soul from agent config files."""
    candidates: list[Path] = []

    if agent_type in ("claude-code", "opencode"):
        # Project CLAUDE.md first, then global
        candidates.append(Path.cwd() / "CLAUDE.md")
        candidates.append(_HOME / ".claude" / "CLAUDE.md")
    elif agent_type == "cursor":
        # Cursor rules
        rules_dir = Path.cwd() / ".cursor" / "rules"
        if rules_dir.is_dir():
            parts = []
            for f in sorted(rules_dir.glob("*.mdc")):
                try:
                    parts.append(f.read_text(encoding="utf-8").strip())
                except OSError:
                    continue
            if parts:
                return "\n\n".join(parts)
    elif agent_type == "cline":
        candidates.append(Path.cwd() / ".clinerules")
    elif agent_type == "windsurf":
        candidates.append(Path.cwd() / ".windsurfrules")
    elif agent_type == "aider":
        candidates.append(Path.cwd() / ".aider.conf.yml")

    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except OSError:
                continue
    return None


def _read_system_prompt_file(path: str | None) -> str | None:
    """Read a custom system prompt (``config.soul``) from a file for register/update.

    Lets a caller set a deliberate persona prompt instead of the soul that is
    auto-read from local agent files — this is what ``agents export`` bakes into
    the generated subagent body.
    """
    if not path:
        return None
    try:
        content = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        output_error(3, "Cannot read --system-prompt-file", str(exc))
        raise SystemExit(3) from exc
    if not content:
        output_error(3, "Empty --system-prompt-file", f"{path} contains no content.")
        raise SystemExit(3)
    return content


def _build_config_snapshot(agent_type: str) -> dict:
    """Build a full config snapshot for sync/register per RFC spec."""
    origin = build_origin()

    config: dict = {
        "machine_fingerprint": _build_machine_fingerprint(),
        "fingerprint": _build_fingerprint(),
        "machine": origin.get("machine"),
        "model": origin.get("model"),
        "tool_version": origin.get("tool_version"),
        "working_directory": str(Path.cwd()),
    }
    # Strip None values
    config = {k: v for k, v in config.items() if v is not None}

    # Skills
    skills = _discover_skills(agent_type)
    if skills:
        config["installed_skills"] = skills

    # Memory
    memory_index = _read_memory_index(agent_type)
    if memory_index:
        config["memory_index"] = memory_index

    # MCP servers
    mcp = _read_mcp_servers(agent_type)
    if mcp:
        config["mcp_servers"] = mcp

    # Permissions
    perms = _read_permissions(agent_type)
    if perms:
        config["permissions"] = perms

    # Hooks
    hooks = _read_hooks(agent_type)
    if hooks:
        config["hooks"] = hooks

    # Git context
    git = _read_git_context()
    if git:
        config["git_context"] = git

    # Soul (system prompt) — auto-read from agent config files
    soul = _read_soul(agent_type)
    if soul:
        config["soul"] = soul

    return config


def _resolve_agent_id(ctx: click.Context, agent_id: str | None, agent_type: str | None) -> str:
    """Resolve agent ID from explicit arg, local storage, or auto-detection."""
    if agent_id:
        return agent_id

    # Try to load from local storage by type
    resolved_type = agent_type or detect_agent_tool()[0]
    if resolved_type:
        stored_id = _load_agent_id(resolved_type)
        if stored_id:
            return stored_id

    output_error(3, "Cannot resolve agent ID", "Provide --agent-id or --type, or run inside a registered agent.")
    raise SystemExit(3)


def _default_agent_name(agent_type: str) -> str:
    """Sensible default display name for an auto-registered agent."""
    import platform

    label = _AGENT_TYPE_LABELS.get(agent_type, agent_type)
    hostname = platform.node() or "unknown-host"
    return f"{label} — {hostname}"


def _register_agent_via_api(
    ctx: click.Context,
    name: str,
    agent_type: str,
    config: dict,
    agent_role: str = DEFAULT_AGENT_ROLE,
) -> tuple[str | None, str | None]:
    """POST /agents and persist the resulting ID. Adopts a pre-existing agent.

    Returns ``(agent_id, error_message)``. When the backend reports
    ``AGENT_ALREADY_REGISTERED`` it includes the existing agent row, so we
    save its ID locally — the row is the source of truth, our local file
    just needs to catch up.
    """
    data = _client(ctx).post(
        "/agents",
        {"name": name, "agent_type": agent_type, "agent_role": agent_role, "config": config},
    )
    agent = data.get("agent")
    if agent and agent.get("id"):
        _save_agent_id(agent_type, agent["id"], agent.get("agent_role", agent_role), agent.get("project_id"))
        return agent["id"], None
    return None, data.get("error", "Registration failed")


def _ensure_agent_registered(ctx: click.Context, agent_type: str) -> str:
    """Return an agent_id for ``agent_type``, registering on-the-fly if needed.

    Used by hook-driven flows (``agents sync``) so a fresh ``deepvista auth
    login`` does not need a follow-up ``agents register`` for SOUL / MEMORY
    pushes to start working (DV-751). Auto-registration defaults to the
    ``misc`` role; users opt into a specific role via ``agents register
    --role`` or ``agents update --role``.
    """
    existing = _load_agent_id(agent_type)
    if existing:
        return existing
    config = _build_config_snapshot(agent_type)
    name = _default_agent_name(agent_type)
    agent_id, error = _register_agent_via_api(ctx, name, agent_type, config, DEFAULT_AGENT_ROLE)
    if not agent_id:
        output_error(1, "Auto-registration failed", error or "Unknown error")
        raise SystemExit(1)
    _migrate_legacy_hooks(agent_type)
    return agent_id


# ---------------------------------------------------------------------------
# Client helper
# ---------------------------------------------------------------------------


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _output(ctx: click.Context, data: object, **kwargs: object) -> None:
    """Shorthand for format_output with common defaults."""
    format_output(
        data,
        ctx.obj.output_format,
        entity_type="agent",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("agents")
def agents_group() -> None:
    """Manage AI agents connected to DeepVista."""


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@agents_group.command("register")
@click.option("--name", required=True, help="Display name for this agent.")
@click.option(
    "--type",
    "agent_type",
    required=False,
    default=None,
    type=click.Choice(
        [
            "claude-code",
            "opencode",
            "openclaw",
            "cursor",
            "windsurf",
            "cline",
            "aider",
            "github-copilot",
            "deepvista-cli",
        ]
    ),
    help="Agent tool type. Auto-detected from the current environment when omitted (DV-1429).",
)
@click.option(
    "--role",
    "agent_role",
    default=DEFAULT_AGENT_ROLE,
    show_default=True,
    help="Functional role this agent owns (free-text, e.g. engineering, marketing).",
)
@click.option(
    "--system-prompt-file",
    "system_prompt_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="File whose contents become this agent's system prompt (config.soul), "
    "overriding the auto-read soul. `agents export` bakes it into the generated subagent body.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def agents_register(
    ctx: click.Context,
    name: str,
    agent_type: str | None,
    agent_role: str,
    system_prompt_file: str | None,
    dry_run: bool,
) -> None:
    """Register a new agent and save its ID locally.

    Auto-reads soul from system files (CLAUDE.md, .cursorrules, etc.) unless
    `--system-prompt-file` is given. Identity is `(type, role, project)` —
    register the same type under a different role to spin up another agent on
    the same machine.

    `--type` is auto-detected from the current environment (Claude Code, Cursor,
    …) when omitted; pass it explicitly to override (DV-1429).

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    if not agent_type:
        detected, _ = detect_agent_tool()
        if not detected:
            output_error(
                1,
                "Could not detect agent type",
                "Run `agents register` from inside a supported agent (Claude Code, Cursor, …), "
                "or pass --type explicitly.",
            )
            return
        agent_type = detected

    existing_id = _load_agent_id(agent_type, agent_role)
    if existing_id:
        msg = f"Agent type '{agent_type}' role '{agent_role}' already registered locally "
        msg += f"(id: {existing_id}). Use 'agents update' to modify."
        click.echo(_json.dumps({"warning": msg}), err=True)
        return

    config = _build_config_snapshot(agent_type)
    custom_soul = _read_system_prompt_file(system_prompt_file)
    if custom_soul:
        config["soul"] = custom_soul

    if dry_run:
        profile = ctx.obj.profile if hasattr(ctx.obj, "profile") else "default"
        _output(
            ctx,
            {
                "dry_run": True,
                "would": "register agent",
                "name": name,
                "agent_type": agent_type,
                "agent_role": agent_role,
                "would_migrate_legacy_hooks": agent_type == "claude-code",
                "config_snapshot": config,
                "profile": profile,
            },
            title="Dry Run: Register Agent",
        )
        return

    data = _client(ctx).post(
        "/agents",
        {"name": name, "agent_type": agent_type, "agent_role": agent_role, "config": config},
    )

    agent = data.get("agent")
    # Adopt a pre-existing server-side row when the local file is missing —
    # the backend returns it with AGENT_ALREADY_REGISTERED.
    if not data.get("success") and not (
        data.get("error_code") == ERROR_CODE_AGENT_ALREADY_REGISTERED and agent and agent.get("id")
    ):
        output_error(1, "Registration failed", data.get("error", "Unknown error"))
        return

    if not agent or not agent.get("id"):
        output_error(1, "Registration failed", "Backend did not return an agent")
        return

    _save_agent_id(agent_type, agent["id"], agent.get("agent_role", agent_role), agent.get("project_id"))

    # Heartbeat is now delivered by the DeepVista plugin; strip any legacy
    # standalone hook a prior CLI version injected into settings.json (DV-1357).
    if _migrate_legacy_hooks(agent_type):
        click.echo(
            _json.dumps({"hooks": "removed legacy standalone heartbeat hook (now provided by the DeepVista plugin)"}),
            err=True,
        )

    # Initial sync — set online immediately so dashboard shows green
    _client(ctx).post(
        f"/agents/{agent['id']}/sync",
        {
            "status": "online",
            "sync_type": "manual",
            "config_patch": config,
        },
    )

    # Re-fetch to get updated heartbeat
    refreshed = _client(ctx).get(f"/agents/{agent['id']}")
    _output(ctx, refreshed.get("agent", agent), title="Registered Agent")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@agents_group.command("list")
@click.option("--type", "agent_type", default=None, help="Filter by agent type.")
@click.pass_context
def agents_list(ctx: click.Context, agent_type: str | None) -> None:
    """List all registered agents.

    Read-only.
    """
    params = {}
    if agent_type:
        params["agent_type"] = agent_type

    data = _client(ctx).get("/agents", params=params)
    agents = data.get("agents", [])
    result = {"agents": agents, "count": len(agents)}
    _output(ctx, result, columns=AGENT_COLUMNS, title="Agents")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@agents_group.command("get")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.pass_context
def agents_get(ctx: click.Context, agent_id: str | None, agent_type: str | None) -> None:
    """Get agent details. Resolves ID from local storage if --type given.

    Read-only.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)
    data = _client(ctx).get(f"/agents/{resolved_id}")
    agent = data.get("agent")
    if not agent:
        output_error(1, "Agent not found", data.get("error", ""))
        return
    _output(ctx, agent, title=f"Agent: {resolved_id}")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@agents_group.command("update")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--name", default=None, help="New display name.")
@click.option("--status", default=None, type=click.Choice(["online", "offline", "error"]), help="Set status.")
@click.option(
    "--role",
    "agent_role",
    default=None,
    help="Reassign agent_role (free-text).",
)
@click.option(
    "--system-prompt-file",
    "system_prompt_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="File whose contents replace this agent's system prompt (config.soul). Overrides the auto-read soul.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def agents_update(
    ctx: click.Context,
    agent_id: str | None,
    agent_type: str | None,
    name: str | None,
    status: str | None,
    agent_role: str | None,
    system_prompt_file: str | None,
    dry_run: bool,
) -> None:
    """Update an agent's name, status, or role.

    The system prompt (config.soul) comes from `--system-prompt-file` when
    given, else it is auto-read from system files (CLAUDE.md, .cursorrules, …).

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)
    resolved_type = agent_type or detect_agent_tool()[0]

    body: dict = {}
    if name:
        body["name"] = name
    if status:
        body["status"] = status
    if agent_role:
        body["agent_role"] = agent_role

    # Explicit prompt file wins; otherwise auto-read soul from system files.
    soul_content = _read_system_prompt_file(system_prompt_file) or _read_soul(resolved_type)
    if soul_content:
        body["config"] = {"soul": soul_content}

    if not body:
        output_error(3, "Nothing to update", "Provide --name, --status, or --role.")
        return

    if dry_run:
        _output(
            ctx,
            {"dry_run": True, "would": "update agent", "agent_id": resolved_id, "payload": body},
            title="Dry Run: Update Agent",
        )
        return

    data = _client(ctx).patch(f"/agents/{resolved_id}", body)
    if not data.get("success"):
        output_error(1, "Update failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Updated Agent")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@agents_group.command("delete")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def agents_delete(ctx: click.Context, agent_id: str | None, agent_type: str | None, dry_run: bool) -> None:
    """Delete an agent and remove its local registration.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)

    if dry_run:
        _output(
            ctx,
            {
                "dry_run": True,
                "would": "delete agent and remove local registration",
                "agent_id": resolved_id,
                "would_uninstall_hooks": agent_type == "claude-code",
            },
            title="Dry Run: Delete Agent",
        )
        return

    data = _client(ctx).delete(f"/agents/{resolved_id}")
    if not data.get("success"):
        output_error(1, "Delete failed", data.get("error", ""))
        return

    # Remove local agent ID file + uninstall hooks
    resolved_type = agent_type
    if agent_type:
        _remove_agent_id(agent_type)
    else:
        # Try to find and remove by scanning local files
        for path in AGENTS_DIR.glob("*.json"):
            try:
                stored = _json.loads(path.read_text())
                if stored.get("agent_id") == resolved_id:
                    resolved_type = stored.get("agent_type")
                    path.unlink()
                    break
            except (_json.JSONDecodeError, KeyError):
                continue

    if resolved_type:
        _uninstall_hooks(resolved_type)

    click.echo(_json.dumps({"success": True, "deleted": resolved_id}))


# ---------------------------------------------------------------------------
# sync (push state to DeepVista)
# ---------------------------------------------------------------------------


@agents_group.command("sync")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--status", default=None, type=click.Choice(["online", "offline", "error"]))
@click.option("--memory", default=None, help="Memory JSON to merge into config.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def agents_sync(
    ctx: click.Context,
    agent_id: str | None,
    agent_type: str | None,
    status: str | None,
    memory: str | None,
    dry_run: bool,
) -> None:
    """Heartbeat + push state to DeepVista. Updates last_heartbeat_at.

    Auto-reads soul, skills, MCP, permissions, hooks, git from system.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_type = agent_type or detect_agent_tool()[0]

    # Resolve agent_id: explicit arg wins; otherwise self-heal from local
    # storage or auto-register so the very first Stop hook on a fresh login
    # starts pushing SOUL / MEMORY without a manual `agents register` step
    # (DV-751).
    if agent_id:
        resolved_id: str = agent_id
    elif resolved_type:
        resolved_id = _ensure_agent_registered(ctx, resolved_type)
    else:
        output_error(3, "Cannot resolve agent ID", "Provide --agent-id or --type, or run inside a registered agent.")
        raise SystemExit(3)

    body: dict = {"sync_type": "manual"}
    if status:
        body["status"] = status

    # Build full config snapshot (fingerprint, skills, memory, MCP, permissions, hooks, git, soul)
    config_patch = _build_config_snapshot(resolved_type)

    if memory:
        try:
            config_patch["memory"] = _json.loads(memory)
        except _json.JSONDecodeError:
            output_error(3, "Invalid --memory JSON", f"Got: {memory}")
            return

    if config_patch:
        body["config_patch"] = config_patch

    if dry_run:
        _output(
            ctx,
            {"dry_run": True, "would": "sync agent state", "agent_id": resolved_id, "payload": body},
            title="Dry Run: Sync Agent",
        )
        return

    data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)

    # Recover from a stale local agent_id: the row was deleted server-side or
    # belongs to a different user. Clear the local record, re-register, and
    # retry the sync once. Only attempts recovery when we know the agent type
    # — otherwise we can't pick a registration target.
    if not data.get("success") and data.get("error_code") == ERROR_CODE_AGENT_NOT_FOUND and resolved_type:
        _remove_agent_id(resolved_type)
        resolved_id = _ensure_agent_registered(ctx, resolved_type)
        data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)

    if not data.get("success"):
        output_error(1, "Sync failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Synced Agent")


# ---------------------------------------------------------------------------
# export (managed agents → Claude Code plugin agent definitions)
# ---------------------------------------------------------------------------


@agents_group.command("export")
@click.option(
    "--target",
    type=click.Path(file_okay=False, resolve_path=True),
    default=None,
    help="Directory to write agent definitions into. Default: ~/.claude/agents.",
)
@click.option(
    "--prefix",
    default=agent_catalog.DEFAULT_PREFIX,
    show_default=True,
    help="Filename prefix for generated definitions (keeps curated agents untouched).",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 500),
    default=agent_catalog.DEFAULT_LIMIT,
    show_default=True,
    help="Cap number of managed agents fetched.",
)
@click.option(
    "--throttle-min",
    type=int,
    default=agent_catalog.DEFAULT_THROTTLE_MIN,
    show_default=True,
    help="Skip export if the last successful run was newer than N minutes.",
)
@click.option("--force", is_flag=True, default=False, help="Ignore the throttle and export now.")
@click.option("--dry-run", is_flag=True, default=False, help="Compute diff, print summary, exit without writing.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress stdout; communicate via exit code only.")
@click.pass_context
def agents_export(
    ctx: click.Context,
    target: str | None,
    prefix: str,
    limit: int,
    throttle_min: int,
    force: bool,
    dry_run: bool,
    quiet: bool,
) -> None:
    """Export managed agents as Claude Code plugin agent definitions.

    Each distinct managed-agent role (DV-832 ``agent_role``) becomes one
    ``<role>.md`` subagent under ``--target``, so it is callable inline in
    Claude Code — e.g. ``@marketing summarize this week``. Re-runs are
    idempotent and throttled; hand-curated agents are never overwritten.

    Read/write on disk only — never calls remote write endpoints. Safe to wire
    into a SessionStart hook: it exits 0 on any failure, leaving the previous
    export's definitions in place.
    """
    target_path = Path(target) if target else agent_catalog.DEFAULT_TARGET_DIR

    try:
        result = agent_catalog.sync_agent_defs(
            _client(ctx),
            target=target_path,
            prefix=prefix,
            limit=limit,
            throttle_min=throttle_min,
            force=force,
            dry_run=dry_run,
        )
    # A SessionStart hook must never fail the session, so we swallow auth/API/
    # network errors (including those raised as SystemExit) and exit 0.
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        if not quiet:
            click.echo(_json.dumps({"error": {"code": 1, "message": f"export failed: {exc}"}}), err=True)
        sys.exit(0)

    if quiet:
        return

    _output(ctx, result, title="Agent definitions export")


# ---------------------------------------------------------------------------
# +status (quick check)
# ---------------------------------------------------------------------------


@agents_group.command("+status")
@click.pass_context
def agents_status(ctx: click.Context) -> None:
    """Show all agents with local registration status.

    Read-only.
    """
    data = _client(ctx).get("/agents")
    agents = data.get("agents", [])

    # Annotate with local registration info. Match by (type, role) first;
    # fall back to type-only for legacy single-role caches.
    for agent in agents:
        atype = agent.get("agent_type", "") or ""
        arole = agent.get("agent_role")
        local_id = _load_agent_id(atype, arole) or _load_agent_id(atype)
        agent["locally_registered"] = local_id == agent.get("id")

    result = {"agents": agents, "count": len(agents)}
    _output(ctx, result, columns=[*AGENT_COLUMNS, "locally_registered"], title="Agent Status")
