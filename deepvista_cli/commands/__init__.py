"""CLI command groups — auth, vistabase, skill, notes, chat."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import click

from deepvista_cli.output.formatter import format_output, output_error


def get_client(ctx: click.Context) -> Any:
    """Return the shared HTTP client stashed on the CLI context by main.py."""
    return ctx.obj._client


def emit(ctx: click.Context, data: object, *, entity_type: str = "card", **kwargs: object) -> None:
    """Render command output, filling in the format/base_url/project_id that every callsite repeats."""
    format_output(
        data,
        ctx.obj.output_format,
        entity_type=entity_type,
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
        **kwargs,  # type: ignore[arg-type]
    )


def maybe_dry_run(
    ctx: click.Context,
    dry_run: bool,
    would: str,
    payload: object = None,
    *,
    entity_type: str = "card",
    title: str | None = None,
    **extra: object,
) -> bool:
    """Preview a write command's payload instead of sending it, when ``--dry-run`` was passed.

    ``payload`` becomes the ``"payload"`` key when given; any other fields the
    caller wants alongside ``dry_run``/``would`` (e.g. ``card_id=...``) can be
    passed as extra keyword arguments. Returns True if the preview was
    emitted, in which case the caller should return immediately.
    """
    if not dry_run:
        return False
    body: dict[str, object] = {"dry_run": True, "would": would}
    if payload is not None:
        body["payload"] = payload
    body.update(extra)
    emit_kwargs: dict[str, object] = {"entity_type": entity_type}
    if title is not None:
        emit_kwargs["title"] = title
    emit(ctx, body, **emit_kwargs)  # type: ignore[arg-type]
    return True


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
