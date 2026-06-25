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
  GET /projects/{id}   -> a single project's metadata
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

PROJECT_COLUMNS = ["id", "name", "role"]


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


@click.group("project")
def project_group() -> None:
    """Inspect and switch the CLI's working project.

    Pick a working project once with `project use <id>`; every subcommand then
    scopes to it (sends `X-Project-Id` and emits `/project/{id}/...` links).
    Override per-invocation with the global `--project <id>` flag or the
    `DEEPVISTA_PROJECT_ID` env var. `project clear` falls back to the backend
    default.
    """


@project_group.command("list")
@click.pass_context
def project_list(ctx: click.Context) -> None:
    """List projects you own or that are shared with you."""
    projects = _projects(ctx)
    result = {"projects": projects, "count": len(projects), "current": ctx.obj.project_id}
    format_output(
        result,
        ctx.obj.output_format,
        columns=PROJECT_COLUMNS,
        title="Projects",
        entity_type="project",
    )


@project_group.command("current")
@click.pass_context
def project_current(ctx: click.Context) -> None:
    """Show the project the backend resolves for this CLI right now.

    Reflects the working project (`X-Project-Id`) when one is set, else the
    user's backend default project.
    """
    data = _client(ctx).get("/projects/me")
    format_output(data, ctx.obj.output_format, title="Current project", entity_type="project")


@project_group.command("show")
@click.argument("project_id", required=False)
@click.pass_context
def project_show(ctx: click.Context, project_id: str | None) -> None:
    """Show metadata for a project (defaults to the resolved current project)."""
    if project_id:
        data = _client(ctx).get(f"/projects/{project_id}")
    else:
        data = _client(ctx).get("/projects/me")
    format_output(data, ctx.obj.output_format, title="Project", entity_type="project")


@project_group.command("use")
@click.argument("project_id")
@click.pass_context
def project_use(ctx: click.Context, project_id: str) -> None:
    """Set the working project for this profile after validating membership.

    Persists ``project_id`` in the active profile. This is client-side scoping
    only — it does not change the backend's per-user default project.
    """
    projects = _projects(ctx)
    match = next((p for p in projects if p.get("id") == project_id), None)
    if match is None:
        output_error(
            EXIT_VALIDATION_ERROR,
            f"Project {project_id} not found or not accessible",
            detail="Run `deepvista project list` to see available projects.",
        )

    set_working_project(ctx.obj.profile, project_id)
    ctx.obj.project_id = project_id
    result = {
        "working_project": project_id,
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
