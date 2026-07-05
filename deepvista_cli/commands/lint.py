"""deepvista lint — LLM health checks over the vistabase.

Invokes the DeepVista agent with a curated prompt asking it to audit the
knowledge base for: duplicates, contradictions, stale claims, orphan pages,
missing cross-references, and data gaps that could be filled with a web search.

Inspired by karpathy's "LLM health checks" over the wiki:
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

Streams the agent's response as NDJSON (same format as `chat +send`).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import click

from deepvista_cli.commands import get_client as _client
from deepvista_cli.commands import maybe_dry_run

LINT_CHECKS = [
    "duplicates",
    "contradictions",
    "stale",
    "orphans",
    "missing-refs",
    "gaps",
    "skills-refresh",
    "all",
]

# Write-intensive checks — excluded from `--check all` and gated behind a
# confirmation prompt unless `-y` is passed.
_WRITE_CHECKS: frozenset[str] = frozenset({"skills-refresh"})

_TIME_RANGE_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_time_range(value: str) -> tuple[int, str]:
    """Parse a duration like ``1d`` / ``4h`` / ``30m`` into ``(seconds, canonical)``.

    Raises ``click.BadParameter`` if the format is invalid — the message lists
    the accepted suffixes so the user can fix it without re-reading the docs.
    """
    if not value:
        raise click.BadParameter("--time-range is required for the skills-refresh check (e.g. 1h, 1d, 7d)")
    match = _TIME_RANGE_RE.match(value)
    if not match:
        raise click.BadParameter(
            f"invalid --time-range {value!r}: expected <int><s|m|h|d|w> (e.g. 30m, 4h, 1d, 7d, 2w)"
        )
    n = int(match.group(1))
    if n <= 0:
        raise click.BadParameter(f"invalid --time-range {value!r}: duration must be positive")
    unit = match.group(2).lower()
    return n * _UNIT_SECONDS[unit], f"{n}{unit}"


def _resolve_cutoff(seconds: int, *, now: datetime | None = None) -> str:
    """Return the ISO-8601 UTC timestamp ``seconds`` ago. ``now`` overridable for tests."""
    moment = now or datetime.now(UTC)
    return (moment - timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


_CHECK_INSTRUCTIONS = {
    "duplicates": (
        "Find duplicate or near-duplicate cards in the vistabase. "
        "Use `find_similar_cards` to detect semantic duplicates. "
        "For each pair, report which one is canonical and why."
    ),
    "contradictions": (
        "Find cards that contradict each other — claims on one card that "
        "newer cards or sources have superseded. Cite both card IDs."
    ),
    "stale": (
        "Find stale claims: cards whose content is likely out of date relative "
        "to newer cards or general knowledge. Suggest updates."
    ),
    "orphans": (
        "Find orphan cards — cards with no inbound references from other cards "
        "and no relationships in the knowledge graph. Suggest where they could "
        "be linked."
    ),
    "missing-refs": (
        "Find concepts mentioned in card content that lack their own card, "
        "or that are not cross-referenced where they should be. List candidate "
        "new cards to create."
    ),
    "gaps": (
        "Find data gaps that could be filled with a web search — important "
        "entities or topics that are mentioned but under-described. Suggest "
        "search queries."
    ),
    "skills-refresh": (
        "Refresh the workflow skill library against recently updated "
        "notes (since {cutoff_iso}, i.e. the last {window}).\n"
        "  1. Call `get_context_cards` with card_type=note and "
        "updated_after={cutoff_iso!r} to list recent notes.\n"
        "  2. Call `get_context_cards` with card_type=skill to enumerate every "
        "existing skill (title + summary).\n"
        "  3. For each recent note, decide which existing skills should be "
        "updated to incorporate the note's new information. For each update, "
        "call `upsert_context_card` on the skill, preserving its accordion / "
        "mermaid structure — append or amend prose, don't rewrite the shell.\n"
        "  4. Detect new skill candidates: clusters of recent notes that "
        "describe a procedure or framework not yet in the library. For each "
        "candidate, emit one JSON record "
        '`{{"skill_name": "...", "kind": "workflow", "source_note_ids": [...]}}` '
        "and then drive the existing `deepvista-skill-workflow` flow to "
        "create the skill, linking every source note via "
        "`related_context_card_ids`.\n"
        "  5. End with a compact summary: "
        '`{{"updated": [...], "created": [...], "skipped": [...]}}`.'
    ),
}

_FIX_INSTRUCTION = (
    "\n\nAfter identifying issues, FIX them: merge duplicates by calling "
    "`upsert_context_card` on the canonical card and deleting the loser, "
    "update stale cards with current info, and link orphans. Confirm each "
    "change as you go."
)

_REPORT_INSTRUCTION = (
    "\n\nReport findings only — do NOT modify, merge, or delete any cards. "
    "List each issue with card IDs and a recommended action."
)


def _resolve_checks(checks: tuple[str, ...]) -> list[str]:
    """Expand "all" to the read-only check set. "all" + others => all (with a warning).

    Write-intensive checks (``_WRITE_CHECKS``) are *not* part of ``all`` —
    they must be requested explicitly. If the user combines ``all`` with one
    of those, we honor the explicit write check alongside the full
    read-only set rather than silently dropping it.
    """
    if not checks or "all" in checks:
        explicit_writes = [c for c in checks if c in _WRITE_CHECKS]
        explicit_other = [c for c in checks if c not in ("all", "") and c not in _WRITE_CHECKS]
        if explicit_other:
            click.echo(
                f"warning: --check all supersedes {', '.join(explicit_other)}; running the full check set.",
                err=True,
            )
        full = [k for k in _CHECK_INSTRUCTIONS if k != "all" and k not in _WRITE_CHECKS]
        return full + explicit_writes
    # Preserve caller order; de-dup while keeping first occurrence.
    seen: set[str] = set()
    return [c for c in checks if not (c in seen or seen.add(c))]


def _build_prompt(selected: list[str], fix: bool, *, cutoff_iso: str | None = None, window: str | None = None) -> str:
    lines = [
        "Run an LLM health check over the vistabase. For each check below, "
        "use your search and graph tools to investigate, then produce a "
        "numbered list of findings with card IDs."
    ]
    for i, key in enumerate(selected, 1):
        text = _CHECK_INSTRUCTIONS[key]
        if key == "skills-refresh":
            assert cutoff_iso is not None and window is not None, "skills-refresh requires a resolved cutoff + window"
            text = text.format(cutoff_iso=cutoff_iso, window=window)
        lines.append(f"{i}. [{key}] {text}")

    lines.append(_FIX_INSTRUCTION if fix else _REPORT_INSTRUCTION)
    return "\n".join(lines)


@click.command("lint")
@click.option(
    "--check",
    "checks",
    type=click.Choice(LINT_CHECKS, case_sensitive=False),
    multiple=True,
    default=("all",),
    help="Which checks to run. Repeatable. Default: all.",
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Let the agent apply fixes (merge duplicates, etc.) instead of only reporting.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the --fix confirmation prompt. Use only in scripts/cron.",
)
@click.option(
    "--time-range",
    "time_range",
    default=None,
    metavar="DURATION",
    help=(
        "Time window for the `skills-refresh` check (e.g. 30m, 4h, 1d, 7d, 2w). "
        "Required when `--check skills-refresh` is selected."
    ),
)
@click.option("--chat-id", default=None, help="Continue an existing lint session.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview the prompt without calling the agent.")
@click.pass_context
def lint_command(
    ctx: click.Context,
    checks: tuple[str, ...],
    fix: bool,
    assume_yes: bool,
    time_range: str | None,
    chat_id: str | None,
    dry_run: bool,
) -> None:
    """Health-check the vistabase with the DeepVista agent.

    Checks for duplicates, contradictions, stale claims, orphan cards, missing
    cross-references, and web-fillable data gaps. Reports by default; pass
    `--fix` to let the agent merge/update/link cards.

    `--check skills-refresh --time-range <duration>` folds recent notes into
    the workflow skill library, updating existing skills and creating new
    ones where warranted (DV-724).

    > [!CAUTION] With `--fix` or `--check skills-refresh`, this is a write
    > command — the agent may merge, update, create, or delete cards.
    > Confirm with the user before executing.
    """
    selected = _resolve_checks(checks)

    cutoff_iso: str | None = None
    window: str | None = None
    needs_time_range = "skills-refresh" in selected
    if needs_time_range:
        if not time_range:
            raise click.UsageError("--time-range is required when --check skills-refresh is selected")
        seconds, window = _parse_time_range(time_range)
        cutoff_iso = _resolve_cutoff(seconds)
    elif time_range:
        click.echo(
            "warning: --time-range is only used by --check skills-refresh; ignoring.",
            err=True,
        )

    prompt = _build_prompt(selected, fix, cutoff_iso=cutoff_iso, window=window)
    body: dict[str, Any] = {"user_instruction": prompt}
    if chat_id:
        body["chat_id"] = chat_id

    is_write_run = fix or any(c in _WRITE_CHECKS for c in selected)

    if dry_run:
        extra: dict[str, Any] = {}
        if cutoff_iso:
            extra["time_range"] = {"window": window, "cutoff_iso": cutoff_iso}
        maybe_dry_run(
            ctx,
            dry_run,
            "send lint prompt to DeepVista agent",
            body,
            checks=selected,
            fix=fix,
            entity_type="chat",
            **extra,
        )
        return

    if is_write_run and not assume_yes:
        reasons: list[str] = []
        if fix:
            reasons.append("--fix lets the agent merge, update, and delete cards")
        write_checks = [c for c in selected if c in _WRITE_CHECKS]
        if write_checks:
            reasons.append(f"the agent will create/update skill cards for: {', '.join(write_checks)}")
        click.confirm(
            "; ".join(reasons) + ". Continue?",
            abort=True,
        )

    try:
        for event in _client(ctx).stream_sse("/imagine", body):
            click.echo(json.dumps(event, default=str))
    except (KeyboardInterrupt, click.Abort):
        click.echo(json.dumps({"type": "interrupted", "message": "lint stream aborted by user"}), err=True)
        raise
    except Exception as exc:
        click.echo(
            json.dumps({"type": "error", "message": f"lint stream failed: {exc}"}),
            err=True,
        )
        raise
