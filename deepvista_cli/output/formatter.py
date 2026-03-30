"""Unified output formatting for all CLI commands.

Agents get JSON by default. Humans can use --format table for rich output.
Errors always follow: {"error": {"code": N, "message": "...", "detail": "..."}}
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click


def output_json(data: Any, **kwargs: Any) -> None:
    """Write JSON to stdout. This is the default agent-friendly format."""
    click.echo(json.dumps(data, indent=2, default=str))


def output_table(data: Any, columns: list[str] | None = None, title: str | None = None) -> None:
    """Write a rich table to stderr (so stdout stays clean for piping)."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console(stderr=True)

        if isinstance(data, list) and data:
            table = Table(title=title, show_lines=False)
            cols = columns or (list(data[0].keys()) if isinstance(data[0], dict) else ["value"])
            for col in cols:
                table.add_column(col, style="cyan" if col == "id" else None)
            for row in data:
                if isinstance(row, dict):
                    table.add_row(*[str(row.get(c, "")) for c in cols])
                else:
                    table.add_row(str(row))
            console.print(table)
        elif isinstance(data, dict):
            table = Table(title=title, show_lines=False)
            table.add_column("Field", style="bold")
            table.add_column("Value")
            for k, v in data.items():
                if k != "embedding":  # skip large vectors
                    table.add_row(k, str(v) if v is not None else "")
            console.print(table)
        else:
            console.print(data)
    except ImportError:
        # rich not available — fall back to JSON
        output_json(data)


def output_error(code: int, message: str, detail: str = "") -> None:
    """Write structured error to stderr and exit."""
    err = {"error": {"code": code, "message": message}}
    if detail:
        err["error"]["detail"] = detail
    click.echo(json.dumps(err, indent=2), err=True)
    sys.exit(code)


def format_output(data: Any, fmt: str, columns: list[str] | None = None, title: str | None = None) -> None:
    """Route output to the correct formatter based on --format flag."""
    if fmt == "table":
        output_table(data, columns=columns, title=title)
        # Also emit JSON on stdout for piping
        output_json(data)
    else:
        output_json(data)
