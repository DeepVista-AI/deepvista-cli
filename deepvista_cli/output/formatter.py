"""Unified output formatting for all CLI commands.

Agents get JSON by default. Humans can use --format table for rich output.
Errors always follow: {"error": {"code": N, "message": "...", "detail": "..."}}
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from deepvista_cli.config import DEFAULT_AUTH_URL

# ---------------------------------------------------------------------------
# URL generation for entities
# ---------------------------------------------------------------------------

# URL patterns for different entity types
# All context cards (vistabase, notes, recipes) use: /vistabase?contextId={id}
# Chat sessions use: /chat?chatId={id}
URL_PATTERNS = {
    "vistabase": "/vistabase?contextId={id}",
    "card": "/vistabase?contextId={id}",
    "note": "/notes/{id}",
    "recipe": "/recipes/{id}",
    "vistabook": "/recipes/{id}",
    "chat": "/chat?chatId={id}",
}


def generate_url(entity_id: str, entity_type: str = "card", base_url: str = DEFAULT_AUTH_URL) -> str:
    """Generate a web app URL for an entity.

    Args:
        entity_id: The UUID of the entity
        entity_type: Type of entity (card, note, recipe, vistabook, chat)
        base_url: Base URL of the web app (defaults to https://app.deepvista.ai)

    Returns:
        Full URL to the entity in the web app
    """
    pattern = URL_PATTERNS.get(entity_type, URL_PATTERNS["card"])
    return f"{base_url.rstrip('/')}{pattern.format(id=entity_id)}"


def add_url_to_entity(entity: dict, entity_type: str = "card", base_url: str = DEFAULT_AUTH_URL) -> dict:
    """Add a 'url' field to an entity dict if it has an 'id' field.

    Args:
        entity: Dict containing entity data with an 'id' field
        entity_type: Type of entity for URL pattern selection
        base_url: Base URL of the web app

    Returns:
        Entity dict with 'url' field added (original dict is not modified)
    """
    if not isinstance(entity, dict) or "id" not in entity:
        return entity

    result = dict(entity)
    result["url"] = generate_url(entity["id"], entity_type, base_url)
    return result


def add_urls_to_data(
    data: Any, entity_type: str = "card", base_url: str = DEFAULT_AUTH_URL, list_key: str | None = None
) -> Any:
    """Add URLs to entities in various data structures.

    Handles:
    - Single entity dict with 'id' field
    - List of entity dicts
    - Dict with a list of entities under a known key (cards, notes, recipes, sessions, etc.)

    Args:
        data: The data structure to process
        entity_type: Type of entity for URL pattern selection
        base_url: Base URL of the web app
        list_key: Optional key for the list of entities in a dict

    Returns:
        Data with URLs added to entities
    """
    if isinstance(data, list):
        return [add_url_to_entity(item, entity_type, base_url) for item in data]

    if isinstance(data, dict):
        # If it's a single entity with an 'id', add URL directly
        if "id" in data and list_key is None:
            return add_url_to_entity(data, entity_type, base_url)

        # Handle wrapped single-entity responses like {"card": {..., "id": "..."}, "created": true}
        single_entity_keys = ["card", "note", "recipe", "vistabook", "session"]
        for key in single_entity_keys:
            if key in data and isinstance(data[key], dict) and "id" in data[key]:
                result = dict(data)
                key_to_type = {
                    "card": entity_type,
                    "note": "note",
                    "recipe": "recipe",
                    "vistabook": "vistabook",
                    "session": "chat",
                }
                item_type = key_to_type.get(key, entity_type)
                result[key] = add_url_to_entity(data[key], item_type, base_url)
                return result

        # Look for known list keys and add URLs to items
        known_keys = ["cards", "notes", "recipes", "vistabooks", "sessions", "results", "similar"]
        keys_to_check = [list_key] if list_key else known_keys

        result = dict(data)
        for key in keys_to_check:
            if key in result and isinstance(result[key], list):
                # Determine entity type from key
                key_to_type = {
                    "cards": "card",
                    "notes": "note",
                    "recipes": "recipe",
                    "vistabooks": "vistabook",
                    "sessions": "chat",
                    "results": entity_type,
                    "similar": entity_type,
                }
                item_type = key_to_type.get(key, entity_type)
                result[key] = [add_url_to_entity(item, item_type, base_url) for item in result[key]]

        return result

    return data


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


def format_output(
    data: Any,
    fmt: str,
    columns: list[str] | None = None,
    title: str | None = None,
    entity_type: str = "card",
    base_url: str = DEFAULT_AUTH_URL,
) -> None:
    """Route output to the correct formatter based on --format flag.

    Automatically adds URLs to entities based on entity_type.

    Args:
        data: The data to format
        fmt: Output format ('json' or 'table')
        columns: Column names for table output
        title: Title for table output
        entity_type: Type of entity for URL generation (card, note, recipe, chat)
        base_url: Base URL for the web app
    """
    # Add URLs to entities
    data_with_urls = add_urls_to_data(data, entity_type=entity_type, base_url=base_url)

    # Update columns to include 'url' if 'id' was in the original columns
    if columns and "id" in columns:
        # Insert 'url' right after 'id'
        idx = columns.index("id")
        columns = columns[:idx] + ["url"] + columns[idx:]

    if fmt == "table":
        output_table(data_with_urls, columns=columns, title=title)
        # Also emit JSON on stdout for piping
        output_json(data_with_urls)
    else:
        output_json(data_with_urls)
