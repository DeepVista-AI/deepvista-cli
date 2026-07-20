"""deepvista project — inspect and switch the CLI's working project.

Every DeepVista entity is scoped to a **project** (DV-1164 and follow-ups).
The backend resolves each request to a project via the ``X-Project-Id`` header,
falling back to the caller's default project when the header is absent.

This group lets a user pick a **working project** once and have every other
subcommand (card, notes, chat, skill, …) operate inside it. The working
project is persisted in the active profile and is *distinct* from the
backend's per-user default project: ``project use`` only changes which project
the CLI scopes to — it never calls ``set_default`` / ``activate``.

Resolution order for the working project (highest wins):
  --project flag  →  DEEPVISTA_PROJECT_ID env  →  profile project_id  →  none

Endpoints:
  GET /projects        -> list owned + shared projects
  GET /projects/me     -> the resolved/default project
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.config import (
    EXIT_VALIDATION_ERROR,
    clear_working_project,
    set_working_project,
)
from deepvista_cli.output.formatter import format_output, output_error

PROJECT_COLUMNS = ["id", "slug", "name", "role"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _projects(ctx: click.Context) -> list[dict]:
    """Return the list of accessible projects from ``GET /projects``.

    The backend returns a bare JSON array; tolerate a ``{"projects": [...]}``
    envelope too for forward-compatibility.
    """
    raw = _client(ctx).get("/projects")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        projects = raw.get("projects", [])
        return projects if isinstance(projects, list) else []
    return []


def _match_project(projects: list[dict], ref: str) -> dict | None:
    """Find a project by id or slug (DV-1564)."""
    return next((p for p in projects if p.get("id") == ref or (p.get("slug") and p.get("slug") == ref)), None)


def _project_not_found(ref: str) -> None:
    output_error(
        EXIT_VALIDATION_ERROR,
        f"Project '{ref}' not found or not accessible",
        detail="Run `deepvista project list` to see available projects (id and slug).",
    )


def _project_role(project: dict) -> str | None:
    """Best-effort role for a project: explicit permission, else owner/shared."""
    permission = project.get("permission")
    if permission:
        return permission
    if project.get("is_shared"):
        return None
    return "owner"


# Metadata fields worth surfacing in the slim view; the raw Project model also
# carries large `tags` / `conversation_starters` arrays that drown the output.
_SLIM_OPTIONAL_FIELDS = (
    "is_shared",
    "is_active",
    "icon_url",
    "timezone",
    "backend_api_endpoint",
    "owner_name",
    "owner_email",
    "created_at",
    "updated_at",
)


def _slim_project(project: dict) -> dict:
    """Project down to the useful metadata (id, name, role, …).

    Keeps the ``id`` so the formatter still attaches a ``/project/{id}`` link.
    """
    slim: dict = {
        "id": project.get("id"),
        "slug": project.get("slug"),
        "name": project.get("name"),
        "role": _project_role(project),
    }
    for key in _SLIM_OPTIONAL_FIELDS:
        if project.get(key) is not None:
            slim[key] = project[key]
    return slim


@click.group("project")
def project_group() -> None:
    """Inspect and switch the CLI's working project.

    Pick a working project once with `project use <id|slug>`; every subcommand
    then scopes to it (sends `X-Project-Id` and emits `/project/{id}/...`
    links). Override per-invocation with the global `--project <id|slug>` flag
    or the `DEEPVISTA_PROJECT_ID` env var. `project clear` falls back to the
    backend default.
    """


@project_group.command("list")
@click.option("--full", is_flag=True, default=False, help="Show the raw project objects (tags, starters, …).")
@click.pass_context
def project_list(ctx: click.Context, full: bool) -> None:
    """List projects you own or that are shared with you."""
    projects = _projects(ctx)
    if not full:
        projects = [_slim_project(p) for p in projects]
    result = {"projects": projects, "count": len(projects), "current": ctx.obj.project_id}
    format_output(
        result,
        ctx.obj.output_format,
        columns=PROJECT_COLUMNS,
        title="Projects",
        entity_type="project",
    )


@project_group.command("current")
@click.option("--full", is_flag=True, default=False, help="Show the raw project object (tags, starters, …).")
@click.pass_context
def project_current(ctx: click.Context, full: bool) -> None:
    """Show the project the backend resolves for this CLI right now.

    Reflects the working project (`X-Project-Id`) when one is set, else the
    user's backend default project.
    """
    data = _client(ctx).get("/projects/me")
    if not full and isinstance(data, dict):
        data = _slim_project(data)
    format_output(data, ctx.obj.output_format, title="Current project", entity_type="project")


@project_group.command("show")
@click.argument("project_ref", required=False)
@click.option("--full", is_flag=True, default=False, help="Show the raw project object (tags, starters, …).")
@click.pass_context
def project_show(ctx: click.Context, project_ref: str | None, full: bool) -> None:
    """Show metadata for a project — by id or slug (defaults to the resolved current project)."""
    if project_ref:
        # There is no GET /projects/{id}; resolve the ref (id or slug, DV-1564)
        # against the projects list, which returns the full project object.
        match = _match_project(_projects(ctx), project_ref)
        if match is None:
            _project_not_found(project_ref)
            return
        data = match
    else:
        data = _client(ctx).get("/projects/me")
    if not full and isinstance(data, dict):
        data = _slim_project(data)
    format_output(data, ctx.obj.output_format, title="Project", entity_type="project")


@project_group.command("use")
@click.argument("project_ref")
@click.pass_context
def project_use(ctx: click.Context, project_ref: str) -> None:
    """Set the working project for this profile after validating membership.

    PROJECT_REF is the project's id or slug (DV-1564); the canonical UUID is
    what gets persisted in the active profile. This is client-side scoping
    only — it does not change the backend's per-user default project.
    """
    match = _match_project(_projects(ctx), project_ref)
    if match is None:
        _project_not_found(project_ref)
        return

    project_id = str(match.get("id"))
    set_working_project(ctx.obj.profile, project_id)
    ctx.obj.project_id = project_id
    result = {
        "working_project": project_id,
        "slug": match.get("slug"),
        "name": match.get("name"),
        "profile": ctx.obj.profile,
    }
    format_output(result, ctx.obj.output_format, title="Working project set")


@project_group.command("clear")
@click.pass_context
def project_clear(ctx: click.Context) -> None:
    """Unset the working project; fall back to the backend default."""
    cleared = clear_working_project(ctx.obj.profile)
    ctx.obj.project_id = None
    format_output(
        {"cleared": cleared, "profile": ctx.obj.profile},
        ctx.obj.output_format,
        title="Working project cleared",
    )
