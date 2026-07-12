"""deepvista agents — Machine identity heartbeat.

A Machine is this device (fingerprint = hostname + MAC + OS). Identity is
``(user_id, machine_fingerprint)`` on the server; ``agent_type`` is soft
metadata (last-seen tool), not part of uniqueness. ``agent_role`` is not used.

``agents sync`` auto-registers on first run, then heartbeats config/state.
Local cache: ``~/.config/deepvista/machines/<fingerprint>.json``. Legacy
``agents/<type>[__project].json`` files are migrated on read.

Storage helpers here are shared with ``tasks``, ``session``, ``notes`` and
origin detection.
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

MACHINES_DIR = CONFIG_DIR / "machines"
# Legacy path kept so older tests / installs that monkeypatch AGENTS_DIR still
# work; new writes go to MACHINES_DIR. Reads fall back to AGENTS_DIR.
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


def _machine_fingerprint() -> str:
    import hashlib
    import platform
    import uuid

    raw = f"{platform.node()}:{uuid.getnode()}:{platform.system()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _machine_path(fingerprint: str | None = None) -> Path:
    return MACHINES_DIR / f"{fingerprint or _machine_fingerprint()}.json"


def _read_json_file(path: Path) -> dict | None:
    try:
        return _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError, KeyError):
        return None


def _save_machine_id(
    agent_id: str,
    *,
    fingerprint: str | None = None,
    last_seen_tool: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> None:
    """Persist this Machine's server agent_id keyed by fingerprint."""
    fp = fingerprint or _machine_fingerprint()
    MACHINES_DIR.mkdir(parents=True, exist_ok=True)
    path = _machine_path(fp)
    data: dict = {
        "agent_id": agent_id,
        "machine_fingerprint": fp,
    }
    if last_seen_tool:
        data["last_seen_tool"] = last_seen_tool
        data["agent_type"] = last_seen_tool  # compat for callers reading agent_type
    if project_id:
        data["project_id"] = project_id
    if project_name:
        data["project_name"] = project_name
    path.write_text(_json.dumps(data))
    os.chmod(path, 0o600)


def _load_machine_id(fingerprint: str | None = None) -> str | None:
    """Return the cached agent_id for this Machine, migrating legacy files if needed."""
    fp = fingerprint or _machine_fingerprint()
    path = _machine_path(fp)
    if path.exists():
        if data := _read_json_file(path):
            if aid := data.get("agent_id"):
                return str(aid)
        return None

    # Migrate: pick the newest legacy agents/*.json and rewrite under machines/.
    legacy = _migrate_legacy_agent_cache(fp)
    return legacy


def _migrate_legacy_agent_cache(fingerprint: str) -> str | None:
    """Adopt the newest ``AGENTS_DIR`` entry into ``MACHINES_DIR/{fingerprint}.json``."""
    if not AGENTS_DIR.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for path in AGENTS_DIR.glob("*.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True):
        data = _read_json_file(path)
        if not data:
            continue
        aid = data.get("agent_id")
        if not aid:
            continue
        _save_machine_id(
            str(aid),
            fingerprint=fingerprint,
            last_seen_tool=data.get("agent_type") or data.get("last_seen_tool"),
            project_id=data.get("project_id"),
            project_name=data.get("project_name"),
        )
        return str(aid)
    return None


def _remove_machine_id(fingerprint: str | None = None) -> None:
    _machine_path(fingerprint).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Backward-compatible wrappers (type/project-keyed API → fingerprint cache)
# ---------------------------------------------------------------------------


def _agent_id_path(agent_type: str, project_id: str | None = None) -> Path:
    """Legacy path helper — prefer ``_machine_path``. Kept for tests."""
    if project_id:
        return AGENTS_DIR / f"{agent_type}__{project_id}.json"
    return AGENTS_DIR / f"{agent_type}.json"


def _save_agent_id(
    agent_type: str,
    agent_id: str,
    project_id: str | None = None,
    project_name: str | None = None,
) -> None:
    _save_machine_id(
        agent_id,
        last_seen_tool=agent_type,
        project_id=project_id,
        project_name=project_name,
    )


def _load_agent_id(agent_type: str, project_id: str | None = None) -> str | None:
    """Load this Machine's agent_id.

    ``agent_type`` / ``project_id`` are ignored for identity (Machine is
    fingerprint-keyed). Legacy type/project files are still consulted via
    migration when the machines/ cache is empty.
    """
    _ = agent_type
    cached = _load_machine_id()
    if cached:
        return cached
    if project_id:
        path = _agent_id_path(agent_type, project_id)
        if path.exists():
            if data := _read_json_file(path):
                if aid := data.get("agent_id"):
                    _save_machine_id(
                        str(aid),
                        last_seen_tool=agent_type,
                        project_id=project_id,
                        project_name=data.get("project_name"),
                    )
                    return str(aid)
    path = _agent_id_path(agent_type)
    if path.exists():
        if data := _read_json_file(path):
            if aid := data.get("agent_id"):
                _save_machine_id(str(aid), last_seen_tool=agent_type, project_id=data.get("project_id"))
                return str(aid)
    return None


def load_agent_id_for_active_agent() -> str | None:
    """Return this Machine's cached agent UUID, or None."""
    return _load_machine_id()


def _remove_agent_id(agent_type: str, project_id: str | None = None) -> None:
    _ = agent_type, project_id
    _remove_machine_id()


def _build_config_snapshot(agent_type: str | None = None) -> dict:
    """Minimal config: fingerprint + origin metadata + last_seen_tool."""
    resolved = agent_type or _resolve_agent_type()
    origin = build_origin()
    config: dict = {
        "machine_fingerprint": _machine_fingerprint(),
        "working_directory": str(Path.cwd()),
        "last_seen_tool": resolved,
    }
    for key in ("machine", "model", "tool_version"):
        if val := origin.get(key):
            config[key] = val
    return config


def _default_agent_name(agent_type: str | None = None) -> str:
    """Human-readable Machine name — hostname first; tool is soft metadata."""
    import platform

    hostname = platform.node() or "unknown-host"
    tool = agent_type or _resolve_agent_type()
    label = _AGENT_TYPE_LABELS.get(tool, tool)
    return f"{hostname} ({label})"


def _find_local_registration_for_project(
    project_id: str,
    agent_type: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(agent_id, last_seen_tool)`` for this Machine.

    ``project_id`` is not part of Machine identity; kept in the signature for
    call-site compatibility. Prefer the fingerprint cache; fall back to legacy
    project-scoped files only to migrate.
    """
    _ = project_id
    resolved_type = agent_type or _resolve_agent_type()
    if cached := _load_machine_id():
        return cached, resolved_type
    if agent_type and (legacy := _load_agent_id(agent_type, project_id)):
        return legacy, agent_type
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


def _agent_fingerprint(agent: dict | None) -> str | None:
    if not agent:
        return None
    fp = agent.get("machine_fingerprint")
    if isinstance(fp, str) and fp.strip():
        return fp.strip()
    config = agent.get("config") or {}
    nested = config.get("machine_fingerprint")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return None


def _agent_exists_on_server(ctx: click.Context, agent_id: str, project_id: str | None = None) -> bool:
    """Return True when ``agent_id`` is a Machine for this user."""
    headers = _project_headers(project_id) if project_id else None
    data = _client(ctx).get(f"/agents/{agent_id}", extra_headers=headers)
    return bool(data.get("agent"))


def _sync_machine_online(
    ctx: click.Context,
    agent_id: str,
    project_id: str | None,
    config: dict,
) -> None:
    headers = _project_headers(project_id) if project_id else None
    _client(ctx).post(
        f"/agents/{agent_id}/sync",
        {"status": "online", "sync_type": "manual", "config_patch": config},
        extra_headers=headers,
    )


def _register_agent_via_api(
    ctx: click.Context,
    name: str,
    agent_type: str,
    config: dict,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    """POST /agents. Adopts only when the returned Machine matches our fingerprint."""
    local_fp = config.get("machine_fingerprint") or _machine_fingerprint()
    body: dict = {
        "name": name,
        "agent_type": agent_type,
        "config": config,
    }
    extra_headers = _project_headers(project_id) if project_id else None
    data = _client(ctx).post("/agents", body, extra_headers=extra_headers)
    agent = data.get("agent")

    def _persist(aid: str) -> str:
        _save_machine_id(
            aid,
            fingerprint=local_fp,
            last_seen_tool=agent_type,
            project_id=project_id or (agent.get("project_id") if agent else None),
            project_name=project_name,
        )
        return aid

    if data.get("success") and agent and agent.get("id"):
        return _persist(agent["id"]), None

    if data.get("error_code") == ERROR_CODE_AGENT_ALREADY_REGISTERED and agent and agent.get("id"):
        remote_fp = _agent_fingerprint(agent)
        if remote_fp and remote_fp != local_fp:
            return None, (
                f"server returned a different machine (fingerprint {remote_fp}, "
                f"local {local_fp}); backend uniqueness may be stale"
            )
        return _persist(agent["id"]), None

    return None, data.get("error", "Registration failed")


def resolve_or_register_machine(
    ctx: click.Context,
    project_id: str,
    *,
    agent_type: str | None = None,
    agent_role: str = "misc",  # noqa: ARG001 — deprecated; accepted for call-site compat
    project_name: str | None = None,
    quiet: bool = False,
) -> str | None:
    """Resolve this Machine's managed agent, registering when needed.

    ``project_id`` scopes claim/sync headers and satisfies the backend FK on
    first create — it is **not** part of Machine identity. Trust-but-verify:

      1. Use the local fingerprint cache when the server still knows that id.
      2. Otherwise register (or adopt the same-fingerprint server row), save
         locally, and mark online.
      3. Never adopt a row whose fingerprint differs from this device.
    """
    _ = agent_role
    resolved_type = _resolve_agent_type(agent_type)
    config = _build_config_snapshot(resolved_type)
    local_fp = config["machine_fingerprint"]

    cached_id = _load_machine_id(local_fp)
    if cached_id and _agent_exists_on_server(ctx, cached_id, project_id):
        _sync_machine_online(ctx, cached_id, project_id, config)
        return cached_id
    if cached_id:
        _remove_machine_id(local_fp)

    agent_id, error = _register_agent_via_api(
        ctx,
        _default_agent_name(resolved_type),
        resolved_type,
        config,
        project_id=project_id,
        project_name=project_name,
    )
    if not agent_id:
        if not quiet:
            click.echo(
                f"  [warn] could not register machine: {error or 'unknown'}",
                err=True,
            )
        return None

    _sync_machine_online(ctx, agent_id, project_id, config)
    if not quiet:
        click.echo(f"  registered machine {agent_id} (fingerprint {local_fp})", err=True)
    return agent_id


def _ensure_agent_registered(ctx: click.Context, agent_type: str) -> str:
    if existing := _load_machine_id():
        return existing
    # Prefer a working project from the CLI context when available.
    project_id = getattr(getattr(ctx, "obj", None), "project_id", None)
    if project_id:
        agent_id = resolve_or_register_machine(ctx, project_id, agent_type=agent_type, quiet=True)
        if agent_id:
            return agent_id
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
    """Machine identity heartbeat for DeepVista."""


@agents_group.command("sync")
@click.argument("agent_id", required=False, default=None)
@click.option("--type", "agent_type", default=None, help="Last-seen tool label (soft metadata).")
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
    """Heartbeat + push state to DeepVista. Auto-registers this Machine on first run.

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
    else:
        resolved_id = _ensure_agent_registered(ctx, resolved_type or "deepvista-cli")

    body: dict = {"sync_type": "manual"}
    if status:
        body["status"] = status

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
            {"dry_run": True, "would": "sync machine state", "agent_id": resolved_id, "payload": body},
            title="Dry Run: Sync Agent",
        )
        return

    data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)
    if not data.get("success") and data.get("error_code") == ERROR_CODE_AGENT_NOT_FOUND:
        _remove_machine_id()
        resolved_id = _ensure_agent_registered(ctx, resolved_type or "deepvista-cli")
        data = _client(ctx).post(f"/agents/{resolved_id}/sync", body)

    if not data.get("success"):
        output_error(1, "Sync failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Synced Agent")
