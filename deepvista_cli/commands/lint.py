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

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output

LINT_CHECKS = [
    "duplicates",
    "contradictions",
    "stale",
    "orphans",
    "missing-refs",
    "gaps",
    "all",
]

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


def _build_prompt(checks: tuple[str, ...], fix: bool) -> str:
    if "all" in checks or not checks:
        selected = [k for k in _CHECK_INSTRUCTIONS if k != "all"]
    else:
        selected = list(checks)

    lines = [
        "Run an LLM health check over the vistabase. For each check below, "
        "use your search and graph tools to investigate, then produce a "
        "numbered list of findings with card IDs."
    ]
    for i, key in enumerate(selected, 1):
        lines.append(f"{i}. [{key}] {_CHECK_INSTRUCTIONS[key]}")

    lines.append(_FIX_INSTRUCTION if fix else _REPORT_INSTRUCTION)
    return "\n".join(lines)


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


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
@click.option("--chat-id", default=None, help="Continue an existing lint session.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview the prompt without calling the agent.")
@click.pass_context
def lint_command(
    ctx: click.Context,
    checks: tuple[str, ...],
    fix: bool,
    chat_id: str | None,
    dry_run: bool,
) -> None:
    """Health-check the vistabase with the DeepVista agent.

    Checks for duplicates, contradictions, stale claims, orphan cards, missing
    cross-references, and web-fillable data gaps. Reports by default; pass
    `--fix` to let the agent merge/update/link cards.

    > [!CAUTION] With `--fix`, this is a write command — the agent may merge,
    > update, or delete cards. Confirm with the user before executing.
    """
    prompt = _build_prompt(checks, fix)
    body: dict = {"user_instruction": prompt}
    if chat_id:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "send lint prompt to DeepVista agent",
                "checks": list(checks),
                "fix": fix,
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="chat",
            base_url=ctx.obj.auth_url,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))
