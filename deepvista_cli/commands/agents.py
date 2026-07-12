"""deepvista agents — Machine identity heartbeat.

A Machine is this device (fingerprint = hostname + MAC + OS) **registered to
a project**. Server uniqueness is ``(project_id, machine_fingerprint)``.
Project members can see the Machine; only the registering user syncs/claims.
``agent_type`` is soft metadata (last-seen tool). ``agent_role`` is unused.

Local cache: ``~/.config/deepvista/machines/<fingerprint>__<project_id>.json``.
Legacy ``agents/<type>__<project>.json`` files are migrated on read.

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
# Legacy path; new writes go to MACHINES_DIR. Reads fall back here.
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


def _machine_path(project_id: str, fingerprint: str | None = None) -> Path:
    fp = fingerprint or _machine_fingerprint()
    return MACHINES_DIR / f"{fp}__{project_id}.json"


def _read_json_file(path: Path) -> dict | None:
    try:
        return _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError, KeyError):
        return None


def _save_machine_id(
    agent_id: str,
    project_id: str,
    *,
    fingerprint: str | None = None,
    last_seen_tool: str | None = None,
    project_name: str | None = None,
) -> None:
    """Persist this Machine's server agent_id for ``(fingerprint, project_id)``."""
    fp = fingerprint or _machine_fingerprint()
    MACHINES_DIR.mkdir(parents=True, exist_ok=True)
    path = _machine_path(project_id, fp)
    data: dict = {
        "agent_id": agent_id,
        "machine_fingerprint": fp,
        "project_id": project_id,
    }
    if last_seen_tool:
        data["last_seen_tool"] = last_seen_tool
        data["agent_type"] = last_seen_tool
    if project_name:
        data["project_name"] = project_name
    path.write_text(_json.dumps(data))
    os.chmod(path, 0o600)


def _load_machine_id(project_id: str, fingerprint: str | None = None) -> str | None:
    """Return cached agent_id for this Machine in ``project_id``."""
    fp = fingerprint or _machine_fingerprint()
    path = _machine_path(project_id, fp)
    if path.exists():
        if data := _read_json_file(path):
            if aid := data.get("agent_id"):
                return str(aid)
        return None

    # Migrate legacy agents/<type>__<project>.json and fingerprint-only machines/.
    return _migrate_legacy_agent_cache(fp, project_id)


def _migrate_legacy_agent_cache(fingerprint: str, project_id: str) -> str | None:
    """Adopt legacy cache files into ``machines/{fp}__{project}.json``."""
    candidates: list[tuple[float, Path]] = []

    # Prefer project-scoped legacy agent files.
    if AGENTS_DIR.exists():
        for path in AGENTS_DIR.glob(f"*__{project_id}.json"):
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for path in AGENTS_DIR.glob("*.json"):
            try:
                data = _read_json_file(path)
            except Exception:
                continue
            if data and data.get("project_id") == project_id:
                try:
                    candidates.append((path.stat().st_mtime, path))
                except OSError:
                    continue

    # Also adopt older fingerprint-only machine files (user-level experiment).
    legacy_fp_only = MACHINES_DIR / f"{fingerprint}.json"
    if legacy_fp_only.exists():
        try:
            candidates.append((legacy_fp_only.stat().st_mtime, legacy_fp_only))
        except OSError:
            pass

    for _, path in sorted(candidates, reverse=True):
        data = _read_json_file(path)
        if not data:
            continue
        aid = data.get("agent_id")
        if not aid:
            continue
        # fingerprint-only file without matching project: only adopt if it
        # claims this project_id or has none (best-effort).
        if path.parent == MACHINES_DIR and "__" not in path.stem:
            stored_pid = data.get("project_id")
            if stored_pid and stored_pid != project_id:
                continue
        _save_machine_id(
            str(aid),
            project_id,
            fingerprint=fingerprint,
            last_seen_tool=data.get("agent_type") or data.get("last_seen_tool"),
            project_name=data.get("project_name"),
        )
        return str(aid)
    return None


def _remove_machine_id(project_id: str, fingerprint: str | None = None) -> None:
    _machine_path(project_id, fingerprint).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------


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
    if not project_id:
        # Global registrations are no longer first-class; require a project.
        return
    _save_machine_id(
        agent_id,
        project_id,
        last_seen_tool=agent_type,
        project_name=project_name,
    )


def _load_agent_id(agent_type: str, project_id: str | None = None) -> str | None:
    if not project_id:
        return None
    _ = agent_type
    return _load_machine_id(project_id)


def load_agent_id_for_active_agent() -> str | None:
    """Return a cached agent UUID for this Machine (any project), or None.

    Prefers the newest ``machines/<fp>__*.json`` file for this fingerprint.
    """
    fp = _machine_fingerprint()
    if not MACHINES_DIR.exists():
        # Fall back to legacy global / any agent file.
        if not AGENTS_DIR.exists():
            return None
        newest: tuple[float, str] | None = None
        for path in AGENTS_DIR.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                data = _read_json_file(path)
            except OSError:
                continue
            if data and data.get("agent_id"):
                if newest is None or mtime > newest[0]:
                    newest = (mtime, str(data["agent_id"]))
        return newest[1] if newest else None

    newest: tuple[float, str] | None = None
    for path in MACHINES_DIR.glob(f"{fp}__*.json"):
        try:
            mtime = path.stat().st_mtime
            data = _read_json_file(path)
        except OSError:
            continue
        if data and data.get("agent_id"):
            if newest is None or mtime > newest[0]:
                newest = (mtime, str(data["agent_id"]))
    if newest:
        return newest[1]
    # fingerprint-only legacy
    data = _read_json_file(MACHINES_DIR / f"{fp}.json")
    if data and data.get("agent_id"):
        return str(data["agent_id"])
    return None


def _remove_agent_id(agent_type: str, project_id: str | None = None) -> None:
    _ = agent_type
    if project_id:
        _remove_machine_id(project_id)


def _build_config_snapshot(agent_type: str | None = None) -> dict:
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
    import platform

    hostname = platform.node() or "unknown-host"
    tool = agent_type or _resolve_agent_type()
    label = _AGENT_TYPE_LABELS.get(tool, tool)
    return f"{hostname} ({label})"


def _find_local_registration_for_project(
    project_id: str,
    agent_type: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(agent_id, last_seen_tool)`` for this Machine in ``project_id``."""
    resolved_type = agent_type or _resolve_agent_type()
    if cached := _load_machine_id(project_id):
        return cached, resolved_type
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


def _agent_exists_on_server(ctx: click.Context, agent_id: str, project_id: str) -> bool:
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
    project_id: str,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    """POST /agents. Adopts only when returned Machine matches our fingerprint."""
    local_fp = config.get("machine_fingerprint") or _machine_fingerprint()
    body: dict = {
        "name": name,
        "agent_type": agent_type,
        "config": config,
    }
    data = _client(ctx).post("/agents", body, extra_headers=_project_headers(project_id))
    agent = data.get("agent")

    def _persist(aid: str) -> str:
        _save_machine_id(
            aid,
            project_id,
            fingerprint=local_fp,
            last_seen_tool=agent_type,
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
        # Same fingerprint already in this project — adopt (possibly another
        # user's prior registration of this device is unusual; fingerprint match
        # means this device).
        return _persist(agent["id"]), None

    return None, data.get("error", "Registration failed")


def resolve_or_register_machine(
    ctx: click.Context,
    project_id: str,
    *,
    agent_type: str | None = None,
    agent_role: str = "misc",  # noqa: ARG001 — deprecated
    project_name: str | None = None,
    quiet: bool = False,
) -> str | None:
    """Resolve this Machine for ``project_id``, registering when needed.

    Identity is ``(project_id, machine_fingerprint)``. Trust-but-verify:

      1. Use the local cache when the server still knows that agent id.
      2. Otherwise register (or adopt same-fingerprint row in this project).
      3. Never adopt a row whose fingerprint differs from this device.
    """
    _ = agent_role
    resolved_type = _resolve_agent_type(agent_type)
    config = _build_config_snapshot(resolved_type)
    local_fp = config["machine_fingerprint"]

    cached_id = _load_machine_id(project_id, local_fp)
    if cached_id and _agent_exists_on_server(ctx, cached_id, project_id):
        _sync_machine_online(ctx, cached_id, project_id, config)
        return cached_id
    if cached_id:
        _remove_machine_id(project_id, local_fp)

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
                f"  [warn] could not register machine for project {project_id}: {error or 'unknown'}",
                err=True,
            )
        return None

    _sync_machine_online(ctx, agent_id, project_id, config)
    if not quiet:
        click.echo(
            f"  registered machine {agent_id} for project {project_id} (fingerprint {local_fp})",
            err=True,
        )
    return agent_id


def _ensure_agent_registered(ctx: click.Context, agent_type: str) -> str:
    project_id = getattr(getattr(ctx, "obj", None), "project_id", None)
    if project_id:
        if existing := _load_machine_id(project_id):
            return existing
        agent_id = resolve_or_register_machine(ctx, project_id, agent_type=agent_type, quiet=True)
        if agent_id:
            return agent_id
        output_error(1, "Auto-registration failed", f"Could not register for project {project_id}")
        raise SystemExit(1)

    # No working project — try any cached registration for origin tagging.
    if existing := load_agent_id_for_active_agent():
        return existing
    output_error(
        3,
        "No working project to register a Machine",
        "Run `deepvista project use <id>` or pass `--project <id>`.",
    )
    raise SystemExit(3)


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
    """Heartbeat + push state. Auto-registers this Machine for the working project.

    > [!CAUTION] This is a write command — confirm with the user before executing.
    """
    resolved_type = agent_type
    if not resolved_type:
        try:
            resolved_type, _ = detect_agent_tool()
        except Exception:
            resolved_type = None

    project_id = getattr(ctx.obj, "project_id", None)

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

    headers = _project_headers(project_id) if project_id else None
    data = _client(ctx).post(f"/agents/{resolved_id}/sync", body, extra_headers=headers)
    if not data.get("success") and data.get("error_code") == ERROR_CODE_AGENT_NOT_FOUND:
        if project_id:
            _remove_machine_id(project_id)
        resolved_id = _ensure_agent_registered(ctx, resolved_type or "deepvista-cli")
        data = _client(ctx).post(f"/agents/{resolved_id}/sync", body, extra_headers=headers)

    if not data.get("success"):
        output_error(1, "Sync failed", data.get("error", ""))
        return
    _output(ctx, data["agent"], title="Synced Agent")
