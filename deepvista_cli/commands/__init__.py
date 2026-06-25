"""CLI command groups — auth, vistabase, skill, notes, chat."""

from __future__ import annotations

import sys
from collections.abc import Callable

import click

from deepvista_cli.output.formatter import output_error


def project_option[F: Callable](func: F) -> F:
    """Add a per-command ``--project <id>`` override.

    Use together with :func:`apply_project_override` at the top of the command
    body. The override takes precedence over the persisted working project /
    global ``--project`` flag for this single invocation only.
    """
    return click.option(
        "--project",
        "project_override",
        default=None,
        help="Scope this command to a project id (overrides the working project for this call only).",
    )(func)


def apply_project_override(ctx: click.Context, project_override: str | None) -> None:
    """Apply a per-command ``--project`` value to the resolved config.

    Mutating ``ctx.obj.project_id`` is sufficient because the HTTP client holds
    the *same* ``CLIConfig`` object and reads ``project_id`` lazily when it
    builds request headers, so the override flows through to ``X-Project-Id``
    and to emitted web links without touching every callsite.
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
        except OSError as exc:
            output_error(4, "Cannot read content file", str(exc))
    return content
