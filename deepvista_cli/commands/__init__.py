"""CLI command groups — auth, vistabase, skill, notes, chat."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable

import click

from deepvista_cli.output.formatter import output_error

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.fullmatch(value))


def resolve_project_ref(ctx: click.Context, ref: str) -> str:
    """Resolve a project reference — UUID or slug (DV-1564) — to the canonical UUID.

    UUIDs pass through without a lookup. Anything else is treated as a slug
    and matched against ``GET /projects`` first; if that list doesn't happen
    to echo a matching ``slug`` field, fall back to asking the backend to
    resolve it directly via the ``X-Project-Id`` header — the same path
    other endpoints (e.g. ``/get_context_cards``) already use to accept a
    slug that isn't present in the ``/projects`` listing. Exits with a
    validation error only if both resolution paths fail. Canonicalizing to
    the UUID keeps every project-keyed artifact (persisted profile config,
    machine cache files, run locks) stable regardless of how the user
    spelled the project.
    """
    if looks_like_uuid(ref):
        return ref
    raw = ctx.obj._client.get("/projects")
    projects = raw if isinstance(raw, list) else raw.get("projects", []) if isinstance(raw, dict) else []
    for project in projects:
        if project.get("slug") == ref or project.get("id") == ref:
            return str(project["id"])
    try:
        data = ctx.obj._client.get("/projects/me", extra_headers={"X-Project-Id": ref})
    except SystemExit:
        data = None
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    output_error(
        3,
        f"Project '{ref}' not found or not accessible",
        "Run `deepvista project list` to see available projects (id and slug).",
    )
    raise SystemExit(3)


def project_option[F: Callable](func: F) -> F:
    """Add a per-command ``--project <id|slug>`` override.

    Use together with :func:`apply_project_override` at the top of the command
    body. The override takes precedence over the persisted working project /
    global ``--project`` flag for this single invocation only.
    """
    return click.option(
        "--project",
        "project_override",
        default=None,
        help="Scope this command to a project id or slug (overrides the working project for this call only).",
    )(func)


def apply_project_override(ctx: click.Context, project_override: str | None) -> None:
    """Apply a per-command ``--project`` value to the resolved config.

    Mutating ``ctx.obj.project_id`` is sufficient because the HTTP client holds
    the *same* ``CLIConfig`` object and reads ``project_id`` lazily when it
    builds request headers, so the override flows through to ``X-Project-Id``
    and to emitted web links without touching every callsite. Slugs pass
    through as-is — the backend resolves slug-or-UUID in the header (DV-1564).
    """
    if project_override:
        ctx.obj.project_id = project_override


def resolve_content(content: str | None, content_file: str | None) -> str | None:
    """Resolve content from ``--content`` or ``--content-file``.

    ``--content-file`` takes precedence when provided.  Use ``-`` to read from
    stdin.  Returns the resolved content string, or *None* if neither option was
    supplied.
    """
    if content_file is not None:
        if content_file == "-":
            return sys.stdin.read()
        try:
            with open(content_file, encoding="utf-8") as fh:
                return fh.read()
        except UnicodeDecodeError:
            output_error(
                3,
                "Content file is not UTF-8 text",
                f"{content_file} looks binary — use `deepvista card upload {content_file}` "
                "to attach it as a file card instead (DV-1650).",
            )
        except OSError as exc:
            output_error(4, "Cannot read content file", str(exc))
    return content
