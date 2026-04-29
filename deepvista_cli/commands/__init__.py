"""CLI command groups — auth, vistabase, skill, notes, chat."""

from __future__ import annotations

import sys

from deepvista_cli.output.formatter import output_error


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
