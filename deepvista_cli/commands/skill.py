"""deepvista skill — list, get, run, status.

Skills are structured checklist workflows stored as context cards (type=skill).
Skill Runs are execution instances (type=skill_run) linked via a master chat session.

Five resources: card · skill · vistabase · chat
"""

from __future__ import annotations

import json
import re
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import click

from deepvista_cli import skill_catalog
from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error
from deepvista_cli.workflow_doc import (
    WorkflowDocument,
    is_phase_server_routable,
)

# Run modes for `deepvista skill run`. ``host`` is the default — the
# packet is printed to stdout for the host agent to drive; ``deepvista``
# forwards to /imagine (legacy behaviour); ``auto`` decides per-phase by
# inspecting each phase's ``tool_plan``.
_RUN_MODES = ("host", "deepvista", "auto")
_DEFAULT_RUN_MODE = "host"

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]

SKILL_KINDS = ("workflow",)

# Cap applied when a selector returns a large set so a single synthesis run stays
# within the agent's usable context. Overridable via --limit.
_DEFAULT_MULTI_NOTE_LIMIT = 5

# Upper cap when scanning `/get_context_cards` for tag filtering — tags are filtered
# client-side since the list endpoint has no native tag filter.
_TAG_SCAN_LIMIT = 200

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


@click.group("skill")
def skill_group() -> None:
    """Manage Skills — structured executable workflows."""


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------


@skill_group.command("list")
@click.option("--limit", default=20, help="Max results (default 20).")
@click.option("--page", "page_number", default=1, help="Page number.")
@click.pass_context
def skill_list(ctx: click.Context, limit: int, page_number: int) -> None:
    """List all Skills.

    Read-only — never modifies your Skills.
    """
    data = _client(ctx).post(
        "/get_context_cards",
        {
            "card_type": "skill",
            "limit": limit,
            "page_number": page_number,
        },
    )
    cards = data.get("cards", [])
    result = {"skills": cards, "count": len(cards), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=SKILL_COLUMNS,
        title="Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("get")
@click.argument("skill_id")
@click.pass_context
def skill_get(ctx: click.Context, skill_id: str) -> None:
    """Get a Skill by ID.

    Read-only — never modifies the Skill.
    """
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    # Remind host agents that workflow skills must be executed via `skill run`,
    # not by reading the body with `skill get` and driving phases manually.
    attrs = data.get("attributes") or {}
    if attrs.get("type") == "workflow":
        data["run_hint"] = (
            f"workflow skill — to execute with phase tracking run: deepvista skill run --mode host {skill_id}"
        )
    format_output(
        data, ctx.obj.output_format, title=f"Skill: {skill_id}", entity_type="skill", base_url=ctx.obj.auth_url
    )


# ---------------------------------------------------------------------------
# Action commands
# ---------------------------------------------------------------------------


@skill_group.command("run")
@click.argument("skill_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.option(
    "--mode",
    type=click.Choice(_RUN_MODES, case_sensitive=False),
    default=_DEFAULT_RUN_MODE,
    show_default=True,
    help=(
        "Where the workflow executes. ``host`` (default) prints a run packet "
        "for the host agent (Claude Code / OpenClaw) to drive itself via the "
        "`deepvista skill phase ...` CLI shims. ``deepvista`` forwards to "
        "/imagine so the DeepVista server agent runs the whole workflow "
        "(legacy behaviour). ``auto`` decides per-phase from each phase's "
        "tool_plan."
    ),
)
@click.option(
    "--webhook",
    is_flag=True,
    default=False,
    help=(
        "Mark this as a webhook-queued run (DV-955). Appends the task-queue "
        "completion contract so the host agent reports the queue task after "
        "`skill complete`. Set automatically on commands the webhook enqueues."
    ),
)
@click.option(
    "--best-effort",
    is_flag=True,
    default=False,
    help=(
        "Unattended run: instruct the host agent to answer open questions "
        "from the vistabase instead of stalling, note assumptions, and only "
        "pause on hard blockers (DV-955)."
    ),
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_run(
    ctx: click.Context,
    skill_id: str,
    user_input: str | None,
    mode: str,
    webhook: bool,
    best_effort: bool,
    dry_run: bool,
) -> None:
    """Run a Skill — host mode by default; ``--mode deepvista`` delegates the whole run server-side.

    > [!CAUTION] This is a write command — host mode acquires the parent
    > Skill card's run lock (``status="in_progress"``) and prints the run
    > packet for the agent driving execution. Deepvista mode creates a new
    > chat session and streams the server agent's response. Confirm with
    > the user before executing.

    Host-mode output is a JSON header + the workflow's SKILL.md body + the
    host runtime contract — all on stdout, no SSE. The host agent reads it
    and drives the workflow using ``deepvista skill phase ...`` shims.

    Deepvista-mode output is NDJSON (one JSON object per line) as the
    server agent streams its response.
    """
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    mode = mode.lower()

    if mode == "deepvista":
        _skill_run_deepvista(ctx, skill_id, user_input, dry_run=dry_run)
        return

    emit_host_run_packet(
        ctx,
        skill_id,
        user_input,
        mode,
        dry_run=dry_run,
        webhook=webhook,
        best_effort=best_effort,
    )


def emit_host_run_packet(
    ctx: click.Context,
    skill_id: str,
    user_input: str | None,
    mode: str = "host",
    *,
    dry_run: bool = False,
    webhook: bool = False,
    best_effort: bool = False,
    task_id: str | None = None,
) -> None:
    """Fetch the skill, acquire the run lock, and print the host run packet.

    Shared by ``skill run`` (host / auto modes) and ``task_queue run --host``
    (DV-955), which emits packets for webhook-queued workflow tasks instead
    of subprocess-executing them — a queued workflow needs the surrounding
    host agent to drive it. ``task_id`` (only known on the task-queue path)
    threads the queue entry into the completion contract.
    """
    # host / auto: fetch the card, optionally acquire the lock, and emit a
    # run packet the host agent drives.
    card = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    if not card or not card.get("description"):
        output_error(3, "Skill not found or has empty description", f"skill_id={skill_id}")

    doc = WorkflowDocument(card["description"])
    phases = doc.phases()
    if not phases:
        output_error(3, "Skill has no <accordion> phases", f"skill_id={skill_id}")

    active = doc.active_phase() or doc.first_pending_phase() or phases[0]

    phase_routes: list[dict[str, str]] = []
    if mode == "auto":
        for p in phases:
            phase_routes.append(
                {
                    "phase": p.title,
                    "route": "deepvista" if is_phase_server_routable(p) else "host",
                }
            )
    else:
        for p in phases:
            phase_routes.append({"phase": p.title, "route": "host"})

    run_header = {
        "type": "skill_run_packet",
        "mode": mode,
        "skill_id": skill_id,
        "skill_title": card.get("title", ""),
        "active_phase": active.title,
        "phases": [{"index": p.index, "title": p.title, "state": p.state} for p in phases],
        "phase_routes": phase_routes,
        "user_input": user_input or "",
        "skill_status": card.get("status", ""),
        "webhook": webhook,
        "best_effort": best_effort,
    }
    if task_id:
        run_header["task_id"] = task_id

    if dry_run:
        format_output(
            {"dry_run": True, "would": f"emit host-mode run packet ({mode})", **run_header},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    # Acquire / refresh the run lock. Idempotent: re-runs while already
    # ``in_progress`` are accepted as resume (the host agent is the lock
    # owner in host mode, not a chat session).
    _client(ctx).post(
        "/update_context_card",
        {"card_id": skill_id, "status": "in_progress", "reason": "skill-run-host-mode"},
    )

    click.echo(json.dumps(run_header, default=str))
    click.echo()  # blank line so agents can split header from body cheaply
    click.echo(card["description"])
    click.echo()
    click.echo("---")
    click.echo()
    click.echo(_load_host_runtime_contract())
    if best_effort:
        click.echo()
        click.echo(_BEST_EFFORT_STANZA)
    if webhook:
        click.echo()
        click.echo(_webhook_task_stanza(task_id))


def _skill_run_deepvista(
    ctx: click.Context, skill_id: str, user_input: str | None, *, dry_run: bool, force: bool = False
) -> None:
    """Forward the run to the DeepVista server agent via /imagine."""
    instruction = user_input or "Run this skill"
    body: dict[str, Any] = {
        "user_instruction": f'<contextCard id="{skill_id}" cardType="skill"></contextCard> {instruction}',
    }
    if force:
        body["force"] = True

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "start DeepVista server-agent Skill run",
                "skill_id": skill_id,
                "instruction": instruction,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))


def _load_host_runtime_contract() -> str:
    """Return the embedded host-mode runtime contract markdown."""
    return resources.files("deepvista_cli.resources").joinpath("workflow_host_runtime.md").read_text(encoding="utf-8")


# Appended to the runtime contract for unattended runs (DV-955). The run was
# triggered by a webhook — there is no human in the loop to answer questions.
_BEST_EFFORT_STANZA = """\
## Best-effort mode (unattended run)

This run was triggered without a human in the loop. Do NOT stall waiting
for answers:

- When a step needs information, search the vistabase first:
  `deepvista card +search "…"`, `deepvista vistabase +search "…"`,
  `deepvista notes list`. Prefer an answer found there over asking.
- When nothing answers, make the most reasonable assumption, state it in
  the phase's artifact note, and move to the next step.
- Reserve `deepvista skill phase pause` for hard blockers only (missing
  credentials, unavailable tools) — never for open questions.
- Anything that would normally be sent externally (emails, invites) must
  be left as a DRAFT for human review, never dispatched."""


def _webhook_task_stanza(task_id: str | None) -> str:
    """Completion contract for webhook-queued runs (DV-955).

    The queue entry stays ``running`` until the host agent reports it —
    nothing else will, so skipping this leaves a permanently stuck task.
    """
    task_ref = task_id or "<task_id from `deepvista task_queue list`>"
    return f"""\
## Webhook task completion

This run came off the agent task queue. The queue entry stays `running`
until YOU report it — after `deepvista skill complete` (or on failure):

```
deepvista task_queue complete {task_ref} --status completed
# or, when the run could not finish:
deepvista task_queue complete {task_ref} --status failed --note "<one short sentence>"
```"""


# ---------------------------------------------------------------------------
# Phase mutators — used by host agents driving the workflow themselves
# ---------------------------------------------------------------------------


@skill_group.group("phase")
def skill_phase_group() -> None:
    """Phase-level operations on an in-progress workflow Skill run.

    Used by host agents (Claude Code / OpenClaw / Cursor) that drove
    ``deepvista skill run --mode host`` and are now advancing the
    workflow themselves. Each command delegates the phase mutation to
    the server via ``POST /workflow_phase`` — accordion and mermaid
    markers are updated server-side in a single atomic write.
    """


def _load_skill_doc(ctx: click.Context, skill_id: str) -> tuple[dict, WorkflowDocument]:
    """Fetch the parent Skill card and return ``(card, WorkflowDocument)``."""
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")
    card = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    if not card or not card.get("description"):
        output_error(3, "Skill not found or empty description", f"skill_id={skill_id}")
    return card, WorkflowDocument(card["description"])


def _phase(ctx: click.Context, card_id: str, **kwargs: Any) -> dict:
    """Call /workflow_phase and return the API response."""
    return _client(ctx).post("/workflow_phase", {"card_id": card_id, **kwargs})


@skill_phase_group.command("open")
@click.argument("skill_id")
@click.argument("phase_label")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing.")
@click.pass_context
def skill_phase_open(ctx: click.Context, skill_id: str, phase_label: str, dry_run: bool) -> None:
    """Mark a phase as active (accordion open, mermaid ``:::dvActive``).

    Idempotent — re-opening the already-active phase is a no-op write.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "open phase", "skill_id": skill_id, "phase": phase_label},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    result = _phase(ctx, skill_id, phase_label=phase_label, action="open")
    format_output(
        {"ok": True, "skill_id": skill_id, "active_phase": phase_label, "title": result.get("title", "")},
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_phase_group.command("done")
@click.argument("skill_id")
@click.argument("phase_label")
@click.option(
    "--artifact-card-id",
    "artifact_card_ids",
    multiple=True,
    help="Card ID to attach as an artifact for this phase. Repeatable.",
)
@click.option(
    "--next-phase",
    default=None,
    help="If set, also open this phase immediately after marking the current one done.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing.")
@click.pass_context
def skill_phase_done(
    ctx: click.Context,
    skill_id: str,
    phase_label: str,
    artifact_card_ids: tuple[str, ...],
    next_phase: str | None,
    dry_run: bool,
) -> None:
    """Mark a phase complete and optionally advance to the next phase.

    Each ``--artifact-card-id`` is embedded as a ``<contextCardBlock>``
    under the phase's accordion. Pass ``--next-phase`` to open the
    following phase in the same write (cheaper than two round-trips).
    """
    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "mark phase done",
                "skill_id": skill_id,
                "phase": phase_label,
                "artifacts": list(artifact_card_ids),
                "next_phase": next_phase,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    result = _phase(
        ctx,
        skill_id,
        phase_label=phase_label,
        action="done",
        artifact_card_ids=list(artifact_card_ids),
        next_phase=next_phase,
    )
    format_output(
        {
            "ok": True,
            "skill_id": skill_id,
            "completed_phase": phase_label,
            "next_phase": next_phase,
            "artifacts": list(artifact_card_ids),
            "title": result.get("title", ""),
        },
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_phase_group.command("reset")
@click.argument("skill_id")
@click.argument("phase_label")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing.")
@click.pass_context
def skill_phase_reset(ctx: click.Context, skill_id: str, phase_label: str, dry_run: bool) -> None:
    """Reset a phase back to pending (unchecked, closed, mermaid dvTodo).

    Use this to re-run a phase that was already marked done or active.
    The run lock (status=in_progress) is not affected.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "reset phase to pending", "skill_id": skill_id, "phase": phase_label},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    result = _phase(ctx, skill_id, phase_label=phase_label, action="reset")
    format_output(
        {"ok": True, "skill_id": skill_id, "reset_phase": phase_label, "title": result.get("title", "")},
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_phase_group.command("pause")
@click.argument("skill_id")
@click.option("--reason", required=True, help="Short sentence explaining what's blocking the run.")
@click.pass_context
def skill_phase_pause(ctx: click.Context, skill_id: str, reason: str) -> None:
    """Pause the run (lock held). Exits non-zero so wrapping scripts notice.

    Does NOT change the card's ``status`` — the run lock stays held so a
    re-run resumes the same phase. The user resumes by re-invoking
    ``deepvista skill run --mode host <skill_id>``.
    """
    card, doc = _load_skill_doc(ctx, skill_id)
    active = doc.active_phase()
    out = {
        "ok": False,
        "paused": True,
        "skill_id": skill_id,
        "title": card.get("title", ""),
        "active_phase": active.title if active else None,
        "reason": reason,
        "resume_with": f"deepvista skill run --mode host {skill_id}",
    }
    format_output(out, ctx.obj.output_format, entity_type="skill", base_url=ctx.obj.auth_url)
    sys.exit(2)


@skill_phase_group.command("need-input")
@click.argument("skill_id")
@click.argument("phase_label")
@click.option("--reason", required=True, help="Short sentence describing what input is needed from the user.")
@click.pass_context
def skill_phase_need_input(ctx: click.Context, skill_id: str, phase_label: str, reason: str) -> None:
    """Signal that a phase is blocked waiting for user input (mermaid ``:::dvNeedIntervention``).

    Marks the accordion open and sets the mermaid node to
    ``:::dvNeedIntervention`` so the DeepVista UI shows the phase as
    waiting for the user — distinct from a technical blocker (``phase pause``)
    or an error. Exits non-zero so wrapping scripts notice.

    The user provides the required information and then resumes with:

        deepvista skill run --mode host <skill_id>
    """
    result = _phase(ctx, skill_id, phase_label=phase_label, action="need_input", reason=reason)
    out = {
        "ok": False,
        "need_input": True,
        "skill_id": skill_id,
        "phase": phase_label,
        "title": result.get("title", ""),
        "reason": reason,
        "resume_with": f"deepvista skill run --mode host {skill_id}",
    }
    format_output(out, ctx.obj.output_format, entity_type="skill", base_url=ctx.obj.auth_url)
    sys.exit(2)


@skill_phase_group.command("run-on-deepvista")
@click.argument("skill_id")
@click.argument("phase_label")
@click.option(
    "--input",
    "user_input",
    default=None,
    help="Extra context for the DeepVista agent on top of the phase-scoped instruction.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without calling /imagine.")
@click.pass_context
def skill_phase_run_on_deepvista(
    ctx: click.Context, skill_id: str, phase_label: str, user_input: str | None, dry_run: bool
) -> None:
    """Delegate a single phase to the DeepVista server agent and return.

    Used by ``--mode auto`` runs (and by the host agent on demand) when
    the active phase's ``tool_plan`` is entirely server-side tools. The
    server agent runs only that phase — it should mark the accordion
    ``checked="true"`` and the mermaid node ``:::dvDone`` but NOT
    advance further or set ``status="completed"``. Control returns to
    the host once the server agent emits ``done: true`` for the phase.
    """
    # Validate phase exists locally before paying for an /imagine call.
    _, doc = _load_skill_doc(ctx, skill_id)
    if not any(p.title == phase_label for p in doc.phases()):
        output_error(3, "Phase not found", f"No accordion titled {phase_label!r}")

    extra = f" Extra context from the host: {user_input}" if user_input else ""
    instruction = (
        f'<contextCard id="{skill_id}" cardType="skill"></contextCard> '
        f'Run ONLY the phase "{phase_label}". After completing it '
        '(accordion checked="true", mermaid node :::dvDone), STOP. '
        "Do NOT advance to any subsequent phase. Do NOT set "
        'status="completed" — the host agent is driving the rest of the workflow.' + extra
    )
    body: dict[str, Any] = {"user_instruction": instruction, "force": True}

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "delegate one phase to DeepVista server agent via /imagine",
                "skill_id": skill_id,
                "phase": phase_label,
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    for event in _client(ctx).stream_sse("/imagine", body):
        click.echo(json.dumps(event, default=str))


@skill_group.command("complete")
@click.argument("skill_id")
@click.option(
    "--review",
    required=True,
    help="3–6 retrospective bullets to append as the final ``## Review`` section.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing.")
@click.pass_context
def skill_complete(ctx: click.Context, skill_id: str, review: str, dry_run: bool) -> None:
    """Finalize a host-mode workflow run.

    Appends the ``## Review`` section, sets ``status="completed"``
    (releasing the run lock so the skill can be run again), and emits
    ``<json>{"done": true}</json>`` for the host agent's output channel.
    """
    card, doc = _load_skill_doc(ctx, skill_id)
    doc.append_review(review)

    if dry_run:
        format_output(
            {"dry_run": True, "would": "append Review + release run lock", "skill_id": skill_id, "review": review},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    _client(ctx).post(
        "/update_context_card",
        {"card_id": skill_id, "description": doc.body, "reason": "host-skill-complete", "status": "completed"},
    )
    click.echo(json.dumps({"done": True, "skill_id": skill_id, "title": card.get("title", "")}, default=str))


@skill_group.command("status")
@click.argument("run_id", metavar="RUN_CHAT_ID")
@click.pass_context
def skill_status(ctx: click.Context, run_id: str) -> None:
    """Check the status of a Skill run.

    Read-only — uses the chat session endpoint to check run state.
    """
    data = _client(ctx).get(f"/chat_sessions/{run_id}")
    session = data.get("session", data)
    result = {
        "id": run_id,  # Use 'id' so URL generation works
        "chat_id": run_id,
        "summary": session.get("summary", ""),
        "run_status": session.get("run_status", ""),
        "visibility": session.get("visibility", ""),
        "created_at": session.get("created_at", ""),
    }
    format_output(result, ctx.obj.output_format, title=f"Run: {run_id}", entity_type="chat", base_url=ctx.obj.auth_url)


# ---------------------------------------------------------------------------
# Catalog: remote-managed skills distributed as thin SKILL.md stubs
# ---------------------------------------------------------------------------


@skill_group.command("sync")
@click.option(
    "--target",
    type=click.Path(file_okay=False, resolve_path=True),
    default=None,
    help=("Skills directory to write stubs into. Default: ~/.claude/skills (also read by opencode, Cursor, Codex)."),
)
@click.option(
    "--prefix",
    default=skill_catalog.DEFAULT_STUB_PREFIX,
    show_default=True,
    help="Namespace prefix for stub dir names (keeps user-authored skills untouched).",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 200),
    default=skill_catalog.DEFAULT_LIMIT,
    show_default=True,
    help="Cap number of skills fetched. Honors server-side ordering (pinned → recent).",
)
@click.option(
    "--throttle-min",
    type=int,
    default=skill_catalog.DEFAULT_THROTTLE_MIN,
    show_default=True,
    help="Skip sync if last successful sync was newer than N minutes.",
)
@click.option("--force", is_flag=True, default=False, help="Ignore the throttle and sync now.")
@click.option("--dry-run", is_flag=True, default=False, help="Compute diff, print summary, exit without writing.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress stdout; communicate via exit code only.")
@click.pass_context
def skill_sync(
    ctx: click.Context,
    target: str | None,
    prefix: str,
    limit: int,
    throttle_min: int,
    force: bool,
    dry_run: bool,
    quiet: bool,
) -> None:
    """Sync thin DeepVista catalog stubs into an agent skills directory.

    Each stub is a minimal ``SKILL.md`` — frontmatter plus a lazy-load
    directive. The real skill body is fetched at invocation time via
    ``deepvista skill load <id>``. Re-runs are idempotent and throttled.

    Read/write — writes stub files but never calls remote write endpoints.
    Safe to wire into a SessionStart hook (it exits 0 on any network failure
    and previous sync state remains usable).
    """
    target_path = Path(target) if target else skill_catalog.DEFAULT_TARGET_DIR

    try:
        result = skill_catalog.sync_catalog(
            _client(ctx),
            target=target_path,
            prefix=prefix,
            limit=limit,
            throttle_min=throttle_min,
            force=force,
            dry_run=dry_run,
        )
    # Same SystemExit rationale as `skill load`: a hook must never fail the
    # session, so we swallow auth/API/network errors raised as sys.exit too.
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        if not quiet:
            click.echo(json.dumps({"error": {"code": 1, "message": f"sync failed: {exc}"}}), err=True)
        sys.exit(0)

    if quiet:
        return

    format_output(result, ctx.obj.output_format, title="Skill catalog sync", entity_type="skill")


@skill_group.command("load")
@click.argument("skill_id")
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk body cache.")
@click.option(
    "--ttl",
    type=int,
    default=skill_catalog.DEFAULT_BODY_CACHE_TTL_SEC,
    show_default=True,
    help="Body cache TTL in seconds.",
)
@click.pass_context
def skill_load(ctx: click.Context, skill_id: str, no_cache: bool, ttl: int) -> None:
    """Print the full SKILL.md body for a catalog skill.

    Called by stub SKILL.md bodies at invocation time (`` !`deepvista skill
    load <id>` ``). The output replaces the preprocessor placeholder so the
    invoking agent receives the real instructions.

    Read-only. Output is raw Markdown on stdout — global ``--format`` is
    deliberately ignored so shell preprocessing works regardless of profile.
    """
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    try:
        body = skill_catalog.load_skill_body(
            _client(ctx),
            skill_id,
            use_cache=not no_cache,
            ttl_sec=ttl,
        )
    # Catch SystemExit too — the HTTP client calls sys.exit on API/auth
    # errors, but at skill-invocation time we'd rather return a readable
    # error body than bubble a raw exit code into the agent's context.
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        reason = "API error" if isinstance(exc, SystemExit) else str(exc) or type(exc).__name__
        click.echo(
            "---\n"
            'name: "deepvista-skill-load-error"\n'
            'description: "DeepVista skill body could not be loaded."\n'
            "---\n\n"
            f"# Could not load skill `{skill_id}`\n\n"
            f"Reason: {reason}\n\n"
            "Fix: run `deepvista auth status` and `deepvista skill sync --force`, then retry.\n"
        )
        sys.exit(0)

    click.echo(body)


# ---------------------------------------------------------------------------
# Marketplace: Discover & Install
# ---------------------------------------------------------------------------

DISCOVER_COLUMNS = ["id", "title", "category", "version", "installed"]


@skill_group.command("discover")
@click.option("--search", "-s", default=None, help="Search term to filter skills.")
@click.option(
    "--category",
    "-c",
    type=click.Choice(["persona", "productivity", "workflow"]),
    default=None,
    help="Filter by category.",
)
@click.option("--limit", default=50, help="Max results (default 50).")
@click.pass_context
def skill_discover(ctx: click.Context, search: str | None, category: str | None, limit: int) -> None:
    """Discover public skills from the marketplace.

    Read-only — browse available skills without installing anything.
    Use `deepvista skill install <id>` to install a skill.
    """
    body: dict = {"limit": limit, "offset": 0}
    if search:
        body["search"] = search
    if category:
        body["category"] = category

    data = _client(ctx).post("/discover_skills", body)
    skills = data.get("skills", [])
    result = {"skills": skills, "count": len(skills), "has_more": data.get("has_more", False)}
    format_output(
        result,
        ctx.obj.output_format,
        columns=DISCOVER_COLUMNS,
        title="Marketplace Skills",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
    )


@skill_group.command("install")
@click.argument("skill_id")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would happen without making any changes.")
@click.pass_context
def skill_install(ctx: click.Context, skill_id: str, dry_run: bool) -> None:
    """Install a marketplace skill into your library.

    > [!CAUTION] This is a write command — it creates a new Skill in your
    > library from the marketplace. Confirm with the user before executing.

    The skill_id must match an entry in the marketplace registry.
    Use `deepvista skill discover` to browse available skills.
    """
    if dry_run:
        format_output(
            {"dry_run": True, "would": "install marketplace skill", "skill_id": skill_id},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    data = _client(ctx).post("/install_marketplace_skill", {"skill_id": skill_id})

    if data.get("already_installed"):
        click.echo(json.dumps({"status": "already_installed", "card": data.get("card", {})}, indent=2, default=str))
    else:
        click.echo(json.dumps({"status": "installed", "card": data.get("card", {})}, indent=2, default=str))


# ---------------------------------------------------------------------------
# create-from-note — synthesize skills from a source note via the agent
# ---------------------------------------------------------------------------


def _build_create_from_note_instruction(notes: list[tuple[str, str]], kinds: tuple[str, ...]) -> str:
    """Build a thin user instruction that lets the server-side skill do the work.

    Emits `<contextCard>` chips for each source note followed by a short trigger
    phrase. The chat agent's intent router matches the phrase against the
    `description` of `deepvista-skill-workflow` and loads its SKILL.md — that's
    where the full prompt, frontmatter rules, mermaid requirements, and
    `upsert_context_card` instructions live.

    ``kinds`` is retained for forward-compatibility but currently only
    ``workflow`` is supported (DV-750 — the persona maker was removed
    server-side, so the CLI no longer offers it).
    """
    if not notes:
        raise ValueError("at least one note is required")

    chips = " ".join(f'<contextCard id="{nid}" cardType="note">{title or "Note"}</contextCard>' for nid, title in notes)

    plural = len(notes) > 1
    source_phrase = "these notes" if plural else "this note"
    trigger = f"Create a workflow skill from {source_phrase}."

    return f"{chips} {trigger}"


# ---------------------------------------------------------------------------
# Selector resolution — turn flags into a concrete list of note IDs
# ---------------------------------------------------------------------------


def _read_ids_from_file(path: str) -> list[str]:
    """Read one ID per line from a file. ``-`` means stdin."""
    if path == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            output_error(4, "Cannot read --from-file", str(exc))
            return []  # unreachable; output_error exits

    ids: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Tolerate `jq -r '.notes[].id'` style or whitespace-separated tokens.
        ids.extend(tok for tok in line.split() if tok and not tok.startswith("#"))
    return ids


def _cards_to_pairs(cards: list[dict], *, skip_id: str | None = None) -> list[tuple[str, str]]:
    """Extract ``(id, title)`` pairs from an API card list, dropping ``skip_id``."""
    pairs: list[tuple[str, str]] = []
    for card in cards:
        cid = card.get("id")
        if not cid or cid == skip_id:
            continue
        pairs.append((cid, card.get("title", "") or ""))
    return pairs


def _resolve_from_search(client: DeepVistaClient, query: str, limit: int) -> list[tuple[str, str]]:
    body = {"query_text": query, "card_type": "note", "limit": limit}
    data = client.post("/get_context_cards", body)
    return _cards_to_pairs(data.get("cards", []))


def _resolve_from_similar(client: DeepVistaClient, seed_id: str, limit: int) -> list[tuple[str, str]]:
    """Find notes related to a seed card via hybrid search on its title + snippet.

    Matches the behaviour of `card +similar` (card.py) so results feel consistent.
    """
    seed = client.post("/get_context_card", {"card_id": seed_id})
    title = seed.get("title", "") or ""
    snippet = seed.get("snippet", "") or ""
    query = f"{title} {snippet}".strip()
    if not query:
        output_error(3, "Seed card has no content for similarity search", f"Card: {seed_id}")
    # Ask for one extra so we can drop the seed itself and still satisfy --limit.
    body = {"query_text": query, "card_type": "note", "limit": limit + 1}
    data = client.post("/get_context_cards", body)
    return _cards_to_pairs(data.get("cards", []), skip_id=seed_id)[:limit]


def _resolve_from_tag(client: DeepVistaClient, tag: str, limit: int) -> list[tuple[str, str]]:
    """Filter notes by tag (client-side — the list endpoint has no tag filter)."""
    body = {"card_type": "note", "limit": _TAG_SCAN_LIMIT, "page_number": 1}
    data = client.post("/get_context_cards", body)
    matched = [c for c in data.get("cards", []) if tag in (c.get("tags") or [])]
    return _cards_to_pairs(matched)[:limit]


def _resolve_from_grep(client: DeepVistaClient, pattern: str, limit: int) -> list[tuple[str, str]]:
    """Regex-match note content via `/grep_context_cards`."""
    body = {
        "pattern": pattern,
        "case_insensitive": False,
        "limit": limit,
        "context_lines": 0,
        "card_type": "note",
    }
    data = client.post("/grep_context_cards", body)
    # The grep endpoint returns `matches` grouped by card; we only need ids+titles.
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in data.get("matches", data.get("results", [])):
        cid = match.get("card_id") or match.get("id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        pairs.append((cid, match.get("title", "") or ""))
    return pairs[:limit]


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """De-duplicate while preserving first-seen order. Prefer non-empty titles."""
    seen: dict[str, str] = {}
    order: list[str] = []
    for cid, title in pairs:
        if cid not in seen:
            seen[cid] = title
            order.append(cid)
        elif not seen[cid] and title:
            seen[cid] = title
    return [(cid, seen[cid]) for cid in order]


def _resolve_note_ids(
    client: DeepVistaClient | None,
    *,
    positional: tuple[str, ...],
    extra: tuple[str, ...],
    from_file: str | None,
    from_search: str | None,
    from_similar: str | None,
    from_tag: str | None,
    from_grep: str | None,
    limit: int,
) -> list[tuple[str, str]]:
    """Merge every source of note IDs into a single ordered, capped list.

    ``client`` may be ``None`` when the caller only supplies explicit IDs (tests
    rely on this). Selectors that need the API will fail loudly if it's missing.
    """
    pairs: list[tuple[str, str]] = [(nid, "") for nid in positional]
    pairs.extend((nid, "") for nid in extra)
    if from_file is not None:
        pairs.extend((nid, "") for nid in _read_ids_from_file(from_file))

    def require_client() -> DeepVistaClient:
        if client is None:
            raise RuntimeError("API client is required for search/similar/tag/grep selectors")
        return client

    if from_search:
        pairs.extend(_resolve_from_search(require_client(), from_search, limit))
    if from_similar:
        if not _UUID_RE.match(from_similar):
            output_error(3, "Invalid --from-similar seed", f"Expected UUID, got: {from_similar!r}")
        pairs.extend(_resolve_from_similar(require_client(), from_similar, limit))
    if from_tag:
        pairs.extend(_resolve_from_tag(require_client(), from_tag, limit))
    if from_grep:
        pairs.extend(_resolve_from_grep(require_client(), from_grep, limit))

    pairs = _dedupe_pairs(pairs)
    return pairs[:limit]


@skill_group.command("create-from-note")
@click.argument("note_ids_positional", metavar="[NOTE_ID]...", nargs=-1)
@click.option(
    "--note-id",
    "note_id_flags",
    multiple=True,
    help="Source note by ID. Repeatable — pass multiple to synthesize across notes.",
)
@click.option(
    "--from-file",
    default=None,
    metavar="PATH",
    help="Read note IDs (one per line) from a file. Use '-' for stdin.",
)
@click.option(
    "--from-search",
    default=None,
    metavar="QUERY",
    help="Resolve source notes via hybrid search (same backend as `card +search`).",
)
@click.option(
    "--from-similar",
    default=None,
    metavar="SEED_NOTE_ID",
    help="Resolve source notes related to a seed note (graph-style neighbours).",
)
@click.option(
    "--from-tag",
    default=None,
    metavar="TAG",
    help="Resolve source notes whose tags list contains TAG.",
)
@click.option(
    "--from-grep",
    default=None,
    metavar="REGEX",
    help="Resolve source notes whose content matches a regex.",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 25),
    default=_DEFAULT_MULTI_NOTE_LIMIT,
    help=f"Cap resolved source notes (default {_DEFAULT_MULTI_NOTE_LIMIT}, max 25).",
)
@click.option(
    "--kind",
    "kinds",
    type=click.Choice(SKILL_KINDS, case_sensitive=False),
    multiple=True,
    default=SKILL_KINDS,
    help="Which skill kinds to synthesize. Repeatable. Currently only `workflow` is supported.",
)
@click.option("--chat-id", default=None, help="Continue an existing synthesis session.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the write confirmation prompt. Use only in scripts/batch conversion.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview the prompt without calling the agent.")
@click.pass_context
def skill_create_from_note(
    ctx: click.Context,
    note_ids_positional: tuple[str, ...],
    note_id_flags: tuple[str, ...],
    from_file: str | None,
    from_search: str | None,
    from_similar: str | None,
    from_tag: str | None,
    from_grep: str | None,
    limit: int,
    kinds: tuple[str, ...],
    chat_id: str | None,
    assume_yes: bool,
    dry_run: bool,
) -> None:
    """Synthesize skill card(s) from one or more notes via the DeepVista agent.

    Pass a single note UUID positionally for the original single-note behaviour,
    or combine multiple notes via repeated positionals, `--note-id`, `--from-file`
    (including stdin via `-`), `--from-search`, `--from-similar`, `--from-tag`,
    and `--from-grep`. The agent produces one `workflow` skill (executable
    steps), grounded in the union of all resolved notes and linked back to
    every source.

    The actual synthesis prompt lives server-side in `deepvista-skill-workflow`.
    This command sends only `<contextCard>` chips plus a short trigger phrase
    so the chat agent picks the right skill and runs it — keeping prompt logic
    on the server as the single source of truth (DV-585).

    Streams NDJSON identical to `chat +send` and `skill run`.

    > [!CAUTION] This is a write command — the agent creates skill cards in
    > the user's project. Confirm before executing.
    """
    # Validate any directly-supplied IDs up front — cheap + gives a useful error.
    for nid in (*note_ids_positional, *note_id_flags):
        if not _UUID_RE.match(nid):
            output_error(3, "Invalid note ID", f"Expected UUID format, got: {nid!r}")

    # Selectors that require API access skip in dry-run with no client yet? We still
    # want to dry-run from real data to show the exact prompt the agent will see,
    # so the client is always built lazily on first access.
    selectors_used = any([from_file, from_search, from_similar, from_tag, from_grep])
    api_needed = bool(from_search or from_similar or from_tag or from_grep)

    client = _client(ctx) if api_needed else None
    resolved = _resolve_note_ids(
        client,
        positional=note_ids_positional,
        extra=note_id_flags,
        from_file=from_file,
        from_search=from_search,
        from_similar=from_similar,
        from_tag=from_tag,
        from_grep=from_grep,
        limit=limit,
    )

    if not resolved:
        hint = (
            "pass a NOTE_ID or a selector (--note-id, --from-file, --from-search, "
            "--from-similar, --from-tag, --from-grep)"
        )
        output_error(3, "No source notes resolved", hint if not selectors_used else "selectors returned zero notes")

    # De-dup `--kind` while preserving order. Empty tuple shouldn't happen (has default).
    seen_k: set[str] = set()
    selected = tuple(k for k in (kinds or SKILL_KINDS) if not (k in seen_k or seen_k.add(k)))

    instruction = _build_create_from_note_instruction(resolved, selected)
    body: dict[str, Any] = {"user_instruction": instruction}
    if chat_id:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "synthesize skills from note(s) via DeepVista agent",
                "note_ids": [nid for nid, _ in resolved],
                "resolved_notes": [{"id": nid, "title": title} for nid, title in resolved],
                "kinds": list(selected),
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
        )
        return

    if not assume_yes:
        click.confirm(
            (
                f"The agent will create {len(selected)} skill card(s) synthesized from "
                f"{len(resolved)} source note(s). Continue?"
            ),
            abort=True,
        )

    try:
        active_client = client or _client(ctx)
        for event in active_client.stream_sse("/imagine", body):
            click.echo(json.dumps(event, default=str))
    except (KeyboardInterrupt, click.Abort):
        click.echo(json.dumps({"type": "interrupted", "message": "skill synthesis aborted by user"}), err=True)
        raise
    except Exception as exc:
        click.echo(
            json.dumps({"type": "error", "message": f"skill synthesis stream failed: {exc}"}),
            err=True,
        )
        raise
