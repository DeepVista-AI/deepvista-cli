"""deepvista session — record agent conversations as `type='session'` cards.

A session card is one rolling card per agent run, with the body holding YAML-ish
frontmatter + an append-only list of turn blocks. Lifecycle:

  * `session init`      — create-or-get the card (idempotent on SessionStart).
  * `session tick`      — append the newest turn(s) from the transcript.
  * `session finalize`  — mark the card complete and queue enrichment.

Backwards compatibility: existing rolling notes created via
`deepvista notes session-*` (which wrote `type='note'`) are still operated on by
their id, so an in-flight session created before this CLI upgrade can be ticked
and finalized through either entry point.
"""

from __future__ import annotations

import json as _json
from typing import Any

import click

from deepvista_cli import session_note as sn
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.client.origin import detect_agent_tool
from deepvista_cli.output.formatter import format_output, output_error

SESSION_CARD_TYPE = "session"
SESSION_ENTITY_TYPE = "session"


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _cached_card_id(state: dict[str, Any]) -> str | None:
    """Return the cached card id, tolerating the legacy `note_id` key."""
    return state.get("card_id") or state.get("note_id")


def _save_card_id(state: dict[str, Any], card_id: str) -> None:
    """Persist the canonical `card_id` and drop the legacy `note_id` key."""
    state["card_id"] = card_id
    state.pop("note_id", None)


def _find_session_card(client: DeepVistaClient, session_id: str) -> dict[str, Any] | None:
    """Find a session card by its `cc-session:<id>` tag.

    Searches `type='session'` first, then falls back to `type='note'` so an
    in-flight rolling note created by the pre-DV-742 CLI is still recoverable
    on session resume.
    """
    tag = f"{sn.SESSION_TAG_PREFIX}{session_id}"
    base_query = {
        "tag_contains": [tag],
        "limit": 1,
        "page_number": 1,
        "order_by": "updated_at",
        "order_direction": "desc",
    }
    for card_type in (SESSION_CARD_TYPE, "note"):
        data = client.post("/get_context_cards", {**base_query, "card_type": card_type})
        cards = data.get("cards") or []
        if cards:
            return cards[0]
    return None


def _parse_counter(raw: Any) -> dict[str, int]:
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items() if isinstance(v, int | float)}
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            loaded = _json.loads(raw)
            if isinstance(loaded, dict):
                return {str(k): int(v) for k, v in loaded.items() if isinstance(v, int | float)}
        except _json.JSONDecodeError:
            return {}
    return {}


@click.group("session")
def session_group() -> None:
    """Manage agent conversation sessions.

    A session is a rolling context card (`type='session'`) that captures the
    transcript of one agent run — created on SessionStart, ticked per turn,
    finalized on Stop. Distinct from `notes` (user-authored) and the generic
    `card` group (incidental snippets).
    """


@session_group.command("init")
@click.option("--session-id", required=True, help="Agent session ID (Claude Code session_id).")
@click.option("--transcript", required=True, help="Path to the transcript JSONL.")
@click.option("--cwd", required=True, help="Project working directory the session is running in.")
@click.option("--agent", default=None, help="Agent type. Auto-detected from env/process-tree when omitted.")
@click.option("--agent-version", default=None, help="Agent version string. Auto-detected when omitted.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def session_init(
    ctx: click.Context,
    session_id: str,
    transcript: str,
    cwd: str,
    agent: str | None,
    agent_version: str | None,
    dry_run: bool,
) -> None:
    """Create-or-get a rolling session card for the given session_id.

    Idempotent — safe to call on every SessionStart hook fire.

    > [!CAUTION] This is a write command (creates a card on first call).
    """
    from deepvista_cli.commands.agents import load_agent_id_for_active_agent

    if agent is None:
        detected_agent, detected_version = detect_agent_tool()
        agent = detected_agent
        if agent_version is None:
            agent_version = detected_version
    state = sn.load_state(session_id)
    card_id = _cached_card_id(state)
    if not card_id:
        existing = _find_session_card(_client(ctx), session_id)
        if existing:
            card_id = existing.get("id")

    if card_id:
        _save_card_id(state, card_id)
        state["session_id"] = session_id
        sn.save_state(session_id, state)
        format_output(
            {"card_id": card_id, "session_id": session_id, "created": False},
            ctx.obj.output_format,
            title="Session card (existing)",
            entity_type=SESSION_ENTITY_TYPE,
            base_url=ctx.obj.auth_url,
        )
        return

    agent_id = load_agent_id_for_active_agent()
    fm = sn.seed_frontmatter(
        session_id,
        cwd,
        transcript,
        agent=agent,
        agent_version=agent_version,
        agent_id=agent_id,
    )
    body = sn.build_initial_body(fm)
    payload = {
        "card_type": SESSION_CARD_TYPE,
        "title": sn.default_title(session_id, cwd),
        "description": body,
        "tags": sn.session_tags(session_id, agent, cwd, agent_id=agent_id),
        "enrich": False,
    }

    if dry_run:
        format_output(
            {"dry_run": True, "would": "create session card", "payload": payload},
            ctx.obj.output_format,
            entity_type=SESSION_ENTITY_TYPE,
            base_url=ctx.obj.auth_url,
        )
        return

    data = _client(ctx).post("/create_context_card", payload)
    new_id = (data.get("card") or data).get("id") if isinstance(data, dict) else None
    if new_id:
        _save_card_id(state, new_id)
        state.update({"session_id": session_id, "last_turn_index": 0})
        sn.save_state(session_id, state)
    format_output(
        {"card_id": new_id, "session_id": session_id, "created": True, "response": data},
        ctx.obj.output_format,
        title="Session card (created)",
        entity_type=SESSION_ENTITY_TYPE,
        base_url=ctx.obj.auth_url,
    )


@session_group.command("tick")
@click.option("--session-id", required=True, help="Agent session ID.")
@click.option("--transcript", required=True, help="Path to the transcript JSONL.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def session_tick(ctx: click.Context, session_id: str, transcript: str, dry_run: bool) -> None:
    """Append the newest turn(s) from the transcript into the session card.

    Idempotent per turn — uses ``last_turn_index`` in the state cache to skip
    turns already persisted. Safe to call on every Stop hook fire.

    > [!CAUTION] This is a write command.
    """
    state = sn.load_state(session_id)
    card_id = _cached_card_id(state)
    if not card_id:
        output_error(3, "Unknown session", f"No session card cached for {session_id}. Run session init first.")
        return

    turns = sn.parse_transcript(transcript)
    last_idx = int(state.get("last_turn_index") or 0)
    new_turns = turns[last_idx:]
    if not new_turns:
        format_output(
            {"card_id": card_id, "session_id": session_id, "appended": 0, "turn_count": last_idx},
            ctx.obj.output_format,
            title="Session tick (no-op)",
            entity_type=SESSION_ENTITY_TYPE,
            base_url=ctx.obj.auth_url,
        )
        return

    # Don't constrain the lookup to a card_type — the cached card may be a
    # legacy `note` (pre-DV-742) or a new `session` card.
    card = _client(ctx).post("/get_context_card", {"card_id": card_id})
    body = (card.get("card") or card).get("description") or sn.build_initial_body({})
    fm, _ = sn.parse_frontmatter(body)

    for offset, turn in enumerate(new_turns):
        turn_num = last_idx + offset + 1
        block = sn.summarize_turn(turn, turn_num)
        updates = {
            "updated_at": sn.now_iso(),
            "turn_count": turn_num,
            "version": turn_num,
        }
        existing_tools = _parse_counter(fm.get("tools_used"))
        for name, count in turn.tool_counts.items():
            existing_tools[name] = existing_tools.get(name, 0) + count
        if existing_tools:
            updates["tools_used"] = dict(sorted(existing_tools.items()))
        body = sn.append_turn(body, block, updates)
        fm, _ = sn.parse_frontmatter(body)

    payload = {"card_id": card_id, "description": body, "reason": "session-tick"}

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "update session card",
                "card_id": card_id,
                "appended": len(new_turns),
                "new_turn_count": last_idx + len(new_turns),
            },
            ctx.obj.output_format,
            entity_type=SESSION_ENTITY_TYPE,
            base_url=ctx.obj.auth_url,
        )
        return

    data = _client(ctx).post("/update_context_card", payload)
    state["last_turn_index"] = last_idx + len(new_turns)
    sn.save_state(session_id, state)
    format_output(
        {
            "card_id": card_id,
            "session_id": session_id,
            "appended": len(new_turns),
            "turn_count": state["last_turn_index"],
            "response": data,
        },
        ctx.obj.output_format,
        title="Session tick",
        entity_type=SESSION_ENTITY_TYPE,
        base_url=ctx.obj.auth_url,
    )


@session_group.command("finalize")
@click.option("--session-id", required=True, help="Agent session ID.")
@click.option("--transcript", default=None, help="Transcript path (final flush). Optional.")
@click.option(
    "--no-enrich", is_flag=True, default=False, help="Skip the index-notes enrich call (useful in tests/offline)."
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def session_finalize(
    ctx: click.Context, session_id: str, transcript: str | None, no_enrich: bool, dry_run: bool
) -> None:
    """Mark a session card complete and queue enrichment.

    If ``--transcript`` is given, runs a final ``session tick`` first to flush
    any remaining turns.

    > [!CAUTION] This is a write command.
    """
    state = sn.load_state(session_id)
    card_id = _cached_card_id(state)
    if not card_id:
        output_error(3, "Unknown session", f"No session card cached for {session_id}.")
        return

    if transcript:
        ctx.invoke(session_tick, session_id=session_id, transcript=transcript, dry_run=dry_run)

    card = _client(ctx).post("/get_context_card", {"card_id": card_id})
    body = (card.get("card") or card).get("description") or ""
    body = sn.append_turn(body, "", {"status": "complete", "updated_at": sn.now_iso()})
    payload = {"card_id": card_id, "description": body, "reason": "session-finalize"}

    if dry_run:
        format_output(
            {"dry_run": True, "would": "finalize session card", "card_id": card_id},
            ctx.obj.output_format,
            entity_type=SESSION_ENTITY_TYPE,
            base_url=ctx.obj.auth_url,
        )
        return

    _client(ctx).post("/update_context_card", payload)
    enrich_result: Any = None
    if not no_enrich:
        card_type = (card.get("card") or card).get("type") or SESSION_CARD_TYPE
        enrich_result = _client(ctx).post(
            "/index_notes",
            {"card_ids": [card_id], "card_type": card_type, "only_unenriched": False},
        )
    format_output(
        {"card_id": card_id, "session_id": session_id, "status": "complete", "enrich": enrich_result},
        ctx.obj.output_format,
        title="Session finalized",
        entity_type=SESSION_ENTITY_TYPE,
        base_url=ctx.obj.auth_url,
    )
