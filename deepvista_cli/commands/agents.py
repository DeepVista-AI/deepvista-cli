"""deepvista agents — the agent identity heartbeat.

Each agent tool (Claude Code, OpenClaw, Cursor, etc.) gets a persistent
identity with config stored in DeepVista. ``agents sync`` is the single
command: it auto-registers on first run, then heartbeats config/state.

Agent IDs are stored locally at ~/.config/deepvista/agents/<agent_type>.json
(or ``<agent_type>__<project_id>.json`` per project) so the CLI knows which
agent it's running inside. The storage helpers here are shared with
``tasks``, ``session``, ``notes`` and origin detection.
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

AGENTS_DIR = CONFIG_DIR / "agents"

ERROR_CODE_AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
ERROR_CODE_AGENT_ALREADY_REGISTERED = "AGENT_ALREADY_REGISTERED"

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


def _agent_id_path(agent_type: str, project_id: str | None = None) -> Path:
    if project_id:
        return AGENTS_DIR / f"{agent_type}__{project_id}.json"
    return AGENTS_DIR / f"{agent_type}.json"


def _save_agent_id(
    agent_type: str,
    agent_id: str,
    project_id: str | None = None,
    project_name: str | None = None,
) -> None:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _agent_id_path(agent_type, project_id)
    data: dict = {"agent_id": agent_id, "agent_type": agent_type}
    if project_id:
        data["project_id"] = project_id
    if project_name:
        data["project_name"] = project_name
    path.write_text(_json.dumps(data))
    os.chmod(path, 0o600)


def _read_agent_id_file(path: Path) -> dict | None:
    try:
        return _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError, KeyError):
        return None


def _load_agent_id(agent_type: str, project_id: str | None = None) -> str | None:
    path = _agent_id_path(agent_type, project_id)
    if not path.exists():
        return None
    if data := _read_agent_id_file(path):
        if aid := data.get("agent_id"):
            return aid
    return None


def load_agent_id_for_active_agent() -> str | None:
    """Return the active agent UUID from the local cache, or None."""
    try:
        agent_type, _ = detect_agent_tool()
    except Exception:
        return None
    if not agent_type:
        return None
    return _load_agent_id(agent_type)


def _remove_agent_id(agent_type: str, project_id: str | None = None) -> None:
    _agent_id_path(agent_type, project_id).unlink(missing_ok=True)


def _machine_fingerprint() -> str:
    import hashlib
    import platform
    import uuid

    raw = f"{platform.node()}:{uuid.getnode()}:{platform.system()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_config_snapshot(_agent_type: str) -> dict:
    """Minimal config: origin metadata + working directory."""
    origin = build_origin()
    config: dict = {
        "machine_fingerprint": _machine_fingerprint(),
        "working_directory": str(Path.cwd()),
    }
    for key in ("machine", "model", "tool_version"):
        if val := origin.get(key):
            config[key] = val
    return config


def _default_agent_name(agent_type: str) -> str:
    import platform

    label = _AGENT_TYPE_LABELS.get(agent_type, agent_type)
    hostname = platform.node() or "unknown-host"
    return f"{label} — {hostname}"


def _find_local_registration_for_project(
    project_id: str,
    agent_type: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(agent_id, agent_type)`` from the local cache for ``project_id``."""
    if agent_type:
        if cached := _load_agent_id(agent_type, project_id):
            return cached, agent_type
    if not AGENTS_DIR.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for path in AGENTS_DIR.glob("*.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True):
        data = _read_agent_id_file(path)
        if not data or data.get("project_id") != project_id:
            continue
        aid = data.get("agent_id")
        if not aid:
            continue
        atype = str(data.get("agent_type") or agent_type or "deepvista-cli")
        return str(aid), atype
    return None


def _project_headers(project_id: str) -> dict[str, str]:
    return {"X-Project-Id": project_id}


def _resolve_agent_type(agent_type: str | None = None) -> str:
    if agent_type:
        return agent_type
    try:
        detected, _ = detect_agent_tool()
    except Exception:
        detected = None
    return detected or "deepvista-cli"


def _agent_exists_on_server(ctx: click.Context, agent_id: str, project_id: str) -> bool:
    """Return True when ``agent_id`` is a managed agent for this user in ``project_id``."""
    data = _client(ctx).get(f"/agents/{agent_id}", extra_headers=_project_headers(project_id))
    return bool(data.get("agent"))


def _sync_machine_online(
    ctx: click.Context,
    agent_id: str,
    project_id: str,
    config: dict,
) -> None:
    _client(ctx).post(
        f"/agents/{agent_id}/sync",
        {"status": "online", "sync_type": "manual", "config_patch": config},
        extra_headers=_project_headers(project_id),
    )


def _register_agent_via_api(
    ctx: click.Context,
    name: str,
    agent_type: str,
    config: dict,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
    agent_role: str = "misc",
) -> tuple[str | None, str | None]:
    body: dict = {
        "name": name,
        "agent_type": agent_type,
        "agent_role": agent_role,
        "config": config,
    }
    extra_headers = _project_headers(project_id) if project_id else None
    data = _client(ctx).post("/agents", body, extra_headers=extra_headers)
    agent = data.get("agent")
    save_project_id = project_id or (agent.get("project_id") if agent else None)
    if agent and agent.get("id"):
        _save_agent_id(agent_type, agent["id"], save_project_id, project_name)
        return agent["id"], None
    if data.get("error_code") == ERROR_CODE_AGENT_ALREADY_REGISTERED and agent and agent.get("id"):
        _save_agent_id(agent_type, agent["id"], save_project_id, project_name)
        return agent["id"], None
    return None, data.get("error", "Registration failed")


def resolve_or_register_machine(
    ctx: click.Context,
    project_id: str,
    *,
    agent_type: str | None = None,
    agent_role: str = "misc",
    project_name: str | None = None,
    quiet: bool = False,
) -> str | None:
    """Resolve this machine's managed agent for ``project_id``, registering when needed.

    Trust-but-verify flow:
      1. Use the local cache when the server still knows that agent id.
      2. Otherwise register (or adopt an existing server row via
         ``AGENT_ALREADY_REGISTERED``), save locally, and mark online.
    """
    resolved_type = _resolve_agent_type(agent_type)
    config = _build_config_snapshot(resolved_type)

    local = _find_local_registration_for_project(project_id, resolved_type)
    cached_id = local[0] if local else None
    cached_type = local[1] if local else resolved_type
    if cached_id and _agent_exists_on_server(ctx, cached_id, project_id):
        _sync_machine_online(ctx, cached_id, project_id, config)
        return cached_id
    if cached_id:
        _remove_agent_id(cached_type, project_id)

    agent_id, error = _register_agent_via_api(
        ctx,
        _default_agent_name(resolved_type),
        resolved_type,
        config,
        project_id=project_id,
        project_name=project_name,
        agent_role=agent_role,
    )
    if not agent_id:
        if not quiet:
            click.echo(
                f"  [warn] could not register agent for project {project_id}: {error or 'unknown'}",
                err=True,
            )
        return None

    _sync_machine_online(ctx, agent_id, project_id, config)
    if not quiet:
        click.echo(f"  registered agent {agent_id} for project {project_id}", err=True)
    return agent_id


def _ensure_agent_registered(ctx: click.Context, agent_type: str) -> str:
    if existing := _load_agent_id(agent_type):
        return existing
    config = _build_config_snapshot(agent_type)
    agent_id, error = _register_agent_via_api(ctx, _default_agent_name(agent_type), agent_type, config)
    if not agent_id:
        output_error(1, "Auto-registration failed", error or "Unknown error")
        raise SystemExit(1)
    return agent_id


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _output(ctx: click.Context, data: object, **kwargs: object) -> None:
    format_output(
        data,
        ctx.obj.output_format,
        entity_type="agent",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
        **kwargs,  # type: ignore[arg-type]
    )


@click.group("agents")
def agents_group() -> None:
    """Agent identity heartbeat for DeepVista."""


@agents_group.command("sync")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Resolve agent by type from local storage.")
@click.option("--status", default=None, type=click.Choice(["online", "offline", "error"]))
@click.option("--memory", default=None, help="Memory JSON to merge into config.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without making changes.")
@click.pass_context
def agents_sync(
    ctx: click.Context,
    agent_id: str | None,
    agent_type: str | None,
    status: str | None,
    memory: str | None,
    dry_run: bool,
) -> None:
    """Heartbeat + push state to DeepVista. Auto-registers on first run.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_type = agent_type
    if not resolved_type:
        try:
            resolved_type, _ = detect_agent_tool()
        except Exception:
            resolved_type = None

    if agent_id:
        resolved_id = agent_id
    elif resolved_type:
        resolved_id = _ensure_agent_registered(ctx, resolved_type)
    else:
        output_error(3, "Cannot resolve agent ID", "Provide --agent-id or --type, or run inside a registered agent.")
        raise SystemExit(3)

    body: dict = {"sync_type": "manual"}
    if status:
        body["status"] = status

    config_patch = _build_config_snapshot(resolved_type or "")
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
    if not data.get("success") and data.get("error_code") == ERROR_CODE_AGENT_NOT_FOUND and resolved_type:
        _remove_agent_id(resolved_type)
        resolved_id = _ensure_agent_registered(ctx, resolved_type)
        data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)

    if not data.get("success"):
        output_error(1, "Sync failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Synced Agent")
