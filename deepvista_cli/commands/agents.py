"""deepvista agents — register and manage AI agents connected to DeepVista.

Each registered agent (Claude Code, OpenClaw, Cursor, etc.) gets a persistent
identity with config, soul, and memory stored in DeepVista.

Agent IDs are stored locally at ~/.config/deepvista/agents/<agent_type>.json
so the CLI knows which agent it's running inside.
"""

from __future__ import annotations

import json as _json
import os
from pathlib import Path

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import build_origin, detect_agent_tool
from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.output.formatter import format_output, output_error

AGENT_COLUMNS = ["id", "name", "agent_type", "status", "last_heartbeat_at", "updated_at"]
AGENTS_DIR = CONFIG_DIR / "agents"


# ---------------------------------------------------------------------------
# Local agent ID storage
# ---------------------------------------------------------------------------


def _agent_id_path(agent_type: str) -> Path:
    """Path to the local agent registration file for a given type."""
    return AGENTS_DIR / f"{agent_type}.json"


def _save_agent_id(agent_type: str, agent_id: str) -> None:
    """Persist agent ID locally after registration."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _agent_id_path(agent_type)
    path.write_text(_json.dumps({"agent_id": agent_id, "agent_type": agent_type}))
    os.chmod(path, 0o600)


def _load_agent_id(agent_type: str) -> str | None:
    """Load locally stored agent ID for a given type."""
    path = _agent_id_path(agent_type)
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text())
        return data.get("agent_id")
    except (_json.JSONDecodeError, KeyError):
        return None


def _remove_agent_id(agent_type: str) -> None:
    """Remove local agent registration file."""
    path = _agent_id_path(agent_type)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Hook installation — auto-install sync hooks into agent settings
# ---------------------------------------------------------------------------

_HOOK_MARKER = "agents sync"


def _install_hooks(agent_type: str, profile: str) -> bool:
    """Install heartbeat hooks into agent settings. Returns True if hooks were added."""
    if agent_type == "claude-code":
        return _install_claude_code_hooks(profile)
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


def _install_claude_code_hooks(profile: str) -> bool:
    """Add Stop hook to ~/.claude/settings.json for heartbeat sync."""
    settings_path = _HOME / ".claude" / "settings.json"

    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = _json.loads(settings_path.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            settings = {}

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    # Check if already installed
    for entry in stop_hooks:
        if isinstance(entry, dict) and _HOOK_MARKER in _find_hook_command(entry):
            return False  # Already installed

    profile_flag = f" --profile {profile}" if profile != "default" else ""
    sync_cmd = f"deepvista{profile_flag} agents sync --type claude-code --status online"

    stop_hooks.append(
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": sync_cmd}],
        }
    )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True


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
    required=True,
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
    help="Agent tool type.",
)
@click.pass_context
def agents_register(ctx: click.Context, name: str, agent_type: str) -> None:
    """Register a new agent and save its ID locally.

    Auto-reads soul from system files (CLAUDE.md, .cursorrules, etc.).

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    # Check if already registered locally
    existing_id = _load_agent_id(agent_type)
    if existing_id:
        msg = f"Agent type '{agent_type}' already registered locally "
        msg += f"(id: {existing_id}). Use 'agents update' to modify."
        click.echo(_json.dumps({"warning": msg}), err=True)
        return

    config = _build_config_snapshot(agent_type)

    data = _client(ctx).post("/agents", {"name": name, "agent_type": agent_type, "config": config})

    if not data.get("success"):
        output_error(1, "Registration failed", data.get("error", "Unknown error"))
        return

    agent = data["agent"]
    _save_agent_id(agent_type, agent["id"])

    # Auto-install heartbeat hooks
    profile = ctx.obj.profile if hasattr(ctx.obj, "profile") else "default"
    if _install_hooks(agent_type, profile):
        click.echo(_json.dumps({"hooks": "installed Stop hook for heartbeat sync"}), err=True)

    _output(ctx, agent, title="Registered Agent")


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
@click.pass_context
def agents_update(
    ctx: click.Context,
    agent_id: str | None,
    agent_type: str | None,
    name: str | None,
    status: str | None,
) -> None:
    """Update an agent's name or status. Soul is auto-read from system files.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)
    resolved_type = agent_type or detect_agent_tool()[0]

    body: dict = {}
    if name:
        body["name"] = name
    if status:
        body["status"] = status

    # Auto-read soul from system
    soul_content = _read_soul(resolved_type)
    if soul_content:
        body["config"] = {"soul": soul_content}

    if not body:
        output_error(3, "Nothing to update", "Provide --name or --status.")
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
@click.pass_context
def agents_delete(ctx: click.Context, agent_id: str | None, agent_type: str | None) -> None:
    """Delete an agent and remove its local registration.

    > [!CAUTION] This is a destructive write command — confirm with the user before executing.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)

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
@click.pass_context
def agents_sync(
    ctx: click.Context,
    agent_id: str | None,
    agent_type: str | None,
    status: str | None,
    memory: str | None,
) -> None:
    """Heartbeat + push state to DeepVista. Updates last_heartbeat_at.

    Auto-reads soul, skills, MCP, permissions, hooks, git from system.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_id = _resolve_agent_id(ctx, agent_id, agent_type)
    resolved_type = agent_type or detect_agent_tool()[0]

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

    data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)
    if not data.get("success"):
        output_error(1, "Sync failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Synced Agent")


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

    # Annotate with local registration info
    for agent in agents:
        local_id = _load_agent_id(agent.get("agent_type", ""))
        agent["locally_registered"] = local_id == agent.get("id")

    result = {"agents": agents, "count": len(agents)}
    _output(ctx, result, columns=[*AGENT_COLUMNS, "locally_registered"], title="Agent Status")
