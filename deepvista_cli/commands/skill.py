"""deepvista skill — list, get, run, phase, complete, sync, load, create-from-note.

Skills are structured checklist workflows stored as context cards (type=skill).
A run executes in **host mode**: `skill run` prints a run packet (JSON header +
SKILL.md body + host runtime contract) and the host agent (Claude Code /
OpenClaw / Cursor) drives the workflow itself via the `skill phase ...` shims,
finishing with `skill complete`.

Resources: card · skill · chat
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
from deepvista_cli.commands import apply_project_override, project_option
from deepvista_cli.output.formatter import format_output, output_error
from deepvista_cli.workflow_doc import WorkflowDocument

SKILL_COLUMNS = ["id", "title", "display_status", "updated_at"]

# Cap applied to create-from-note sources so a single synthesis run stays
# within the agent's usable context. Overridable via --limit.
_DEFAULT_MULTI_NOTE_LIMIT = 5

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
@project_option
@click.pass_context
def skill_list(ctx: click.Context, limit: int, page_number: int, project_override: str | None) -> None:
    """List all Skills.

    Read-only — never modifies your Skills.
    """
    apply_project_override(ctx, project_override)
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
        project_id=ctx.obj.project_id,
    )


@skill_group.command("get")
@click.argument("skill_id")
@project_option
@click.pass_context
def skill_get(ctx: click.Context, skill_id: str, project_override: str | None) -> None:
    """Get a Skill by ID.

    Read-only — never modifies the Skill. To *execute* a workflow skill with
    phase tracking, use `deepvista skill run` instead of driving it manually.
    """
    apply_project_override(ctx, project_override)
    data = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    format_output(
        data,
        ctx.obj.output_format,
        title=f"Skill: {skill_id}",
        entity_type="skill",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


# ---------------------------------------------------------------------------
# Action commands
# ---------------------------------------------------------------------------


@skill_group.command("run")
@click.argument("skill_id")
@click.option("--input", "user_input", default=None, help="Context or instructions for the run.")
@click.option(
    "--mode",
    type=click.Choice(("host",), case_sensitive=False),
    default="host",
    hidden=True,
    help="Deprecated compatibility flag — host mode is the only mode.",
)
@click.option(
    "--webhook",
    is_flag=True,
    default=False,
    help=(
        "Mark this as a webhook-queued run (DV-955). Appends the task-card "
        "progress contract so the host agent reports updates via "
        "`deepvista tasks note` while the run is in flight."
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
    """Run a Skill — prints the run packet for the host agent to drive.

    > [!CAUTION] This is a write command — it acquires the parent Skill
    > card's run lock (``status="in_progress"``) and prints the run packet
    > for the agent driving execution. Confirm with the user before executing.

    Output is a JSON header + the workflow's SKILL.md body + the host
    runtime contract — all on stdout, no SSE. The host agent reads it and
    drives the workflow using ``deepvista skill phase ...`` shims.
    """
    if not _UUID_RE.match(skill_id):
        output_error(3, "Invalid skill ID", f"Expected UUID format, got: {skill_id!r}")

    emit_host_run_packet(
        ctx,
        skill_id,
        user_input,
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

    Shared by ``skill run`` when driving a workflow from a host agent session.
    ``task_id`` threads a related task card into the progress contract when the
    run was dispatched as a task card (DV-1247). ``mode`` is retained for
    compatibility; host is the only mode.
    """
    card = _client(ctx).post("/get_context_card", {"card_id": skill_id, "card_type": "skill"})
    if not card or not card.get("description"):
        output_error(3, "Skill not found or has empty description", f"skill_id={skill_id}")

    doc = WorkflowDocument(card["description"])
    phases = doc.phases()
    if not phases:
        output_error(3, "Skill has no <accordion> phases", f"skill_id={skill_id}")

    active = doc.active_phase() or doc.first_pending_phase() or phases[0]

    run_header = {
        "type": "skill_run_packet",
        "mode": mode,
        "skill_id": skill_id,
        "skill_title": card.get("title", ""),
        "active_phase": active.title,
        "phases": [{"index": p.index, "title": p.title, "state": p.state} for p in phases],
        "user_input": user_input or "",
        "skill_status": card.get("status", ""),
        "webhook": webhook,
        "best_effort": best_effort,
    }
    if task_id:
        run_header["task_id"] = task_id

    if dry_run:
        format_output(
            {"dry_run": True, "would": "emit host-mode run packet", **run_header},
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
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
    """Progress contract for webhook-queued runs tied to a task card (DV-955)."""
    task_ref = task_id or "<task_id from `deepvista tasks list`>"
    return f"""\
## Webhook task progress

This run is tied to task card `{task_ref}`. While you work, report progress so
the delegating agent can see updates in real time:

```
deepvista tasks note {task_ref} "<brief update after each significant step>"
```

When this run is headless via `deepvista tasks run`, the task card's final
status is reported automatically when the enclosing `claude -p` run exits."""


# ---------------------------------------------------------------------------
# Phase mutators — used by host agents driving the workflow themselves
# ---------------------------------------------------------------------------


@skill_group.group("phase")
def skill_phase_group() -> None:
    """Phase-level operations on an in-progress workflow Skill run.

    Used by host agents (Claude Code / OpenClaw / Cursor) that drove
    ``deepvista skill run`` and are now advancing the workflow
    themselves. Each command delegates the phase mutation to the server
    via ``POST /workflow_phase`` — accordion and mermaid markers are
    updated server-side in a single atomic write.
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
            project_id=ctx.obj.project_id,
        )
        return

    result = _phase(ctx, skill_id, phase_label=phase_label, action="open")
    format_output(
        {"ok": True, "skill_id": skill_id, "active_phase": phase_label, "title": result.get("title", "")},
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
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
            project_id=ctx.obj.project_id,
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
        project_id=ctx.obj.project_id,
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
            project_id=ctx.obj.project_id,
        )
        return

    result = _phase(ctx, skill_id, phase_label=phase_label, action="reset")
    format_output(
        {"ok": True, "skill_id": skill_id, "reset_phase": phase_label, "title": result.get("title", "")},
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@skill_phase_group.command("note")
@click.argument("skill_id")
@click.argument("phase_label")
@click.argument("note_text")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing.")
@click.pass_context
def skill_phase_note(ctx: click.Context, skill_id: str, phase_label: str, note_text: str, dry_run: bool) -> None:
    """Set or update the dvNote annotation bubble next to a phase node.

    The annotation appears as a side bubble in the workflow mermaid diagram —
    useful for recording task dispatch status, short summaries, or interim results.
    Calling this command again with different text replaces the previous note.
    """
    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "set phase note",
                "skill_id": skill_id,
                "phase": phase_label,
                "note_text": note_text,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    result = _phase(ctx, skill_id, phase_label=phase_label, action="note", note_text=note_text)
    format_output(
        {"ok": True, "skill_id": skill_id, "phase": phase_label, "note": note_text, "title": result.get("title", "")},
        ctx.obj.output_format,
        entity_type="skill",
        base_url=ctx.obj.auth_url,
        project_id=ctx.obj.project_id,
    )


@skill_phase_group.command("pause")
@click.argument("skill_id")
@click.option("--reason", required=True, help="Short sentence explaining what's blocking the run.")
@click.pass_context
def skill_phase_pause(ctx: click.Context, skill_id: str, reason: str) -> None:
    """Pause the run (lock held), marking the active phase ``:::dvNeedIntervention``.

    Sets the active phase's mermaid node to ``:::dvNeedIntervention`` so the
    DeepVista UI shows the workflow is waiting for human action. Does NOT change
    the card's ``status`` — the run lock stays held so a re-run resumes the same
    phase. Exits non-zero so wrapping scripts notice.
    """
    card, doc = _load_skill_doc(ctx, skill_id)
    active = doc.active_phase()
    if active:
        _phase(ctx, skill_id, phase_label=active.title, action="need_input", reason=reason)
    out = {
        "ok": False,
        "paused": True,
        "skill_id": skill_id,
        "title": card.get("title", ""),
        "active_phase": active.title if active else None,
        "reason": reason,
        "resume_with": f"deepvista skill run {skill_id}",
    }
    format_output(
        out, ctx.obj.output_format, entity_type="skill", base_url=ctx.obj.auth_url, project_id=ctx.obj.project_id
    )
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

        deepvista skill run <skill_id>
    """
    result = _phase(ctx, skill_id, phase_label=phase_label, action="need_input", reason=reason)
    out = {
        "ok": False,
        "need_input": True,
        "skill_id": skill_id,
        "phase": phase_label,
        "title": result.get("title", ""),
        "reason": reason,
        "resume_with": f"deepvista skill run {skill_id}",
    }
    format_output(out, ctx.obj.output_format, entity_type="skill", base_url=ctx.obj.auth_url)
    sys.exit(2)


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
            project_id=ctx.obj.project_id,
        )
        return

    _client(ctx).post(
        "/update_context_card",
        {"card_id": skill_id, "description": doc.body, "reason": "host-skill-complete", "status": "completed"},
    )
    click.echo(json.dumps({"done": True, "skill_id": skill_id, "title": card.get("title", "")}, default=str))


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
    # `default_target_dir()` follows CLAUDE_PLUGIN_ROOT when set, so a bare
    # `deepvista skill sync` lands where the plugin's hook puts stubs instead of
    # bouncing them between two locations on every manual run (DV-1869).
    target_path = Path(target) if target else skill_catalog.default_target_dir()

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
        client = _client(ctx)
        card = skill_catalog.load_skill_card(client, skill_id, use_cache=not no_cache, ttl_sec=ttl)
        body = skill_catalog.render_skill_body(card)
        # DV-1816: install bundled scripts/references before printing the body,
        # so a skill that says "run scripts/render.py" finds it there. Doing it
        # here rather than at sync time keeps the catalog lazy — sync still
        # writes only stubs, and an unbundled skill costs nothing.
        bundle_root = skill_catalog.ensure_skill_bundle(client, skill_id, card)
        if bundle_root is not None:
            # State the root explicitly and say how to resolve against it. The
            # bundle no longer sits next to this SKILL.md (DV-1869: it lives in a
            # store that survives plugin upgrades), and the agent's cwd is the
            # project anyway — so every relative path in the body above needs
            # this base to mean anything.
            body += (
                f"\n\n---\n\n**Bundled files for this skill are installed at `{bundle_root}`.**\n"
                f"Resolve every file path mentioned above against that directory — "
                f"e.g. `cd {bundle_root} && uv run --script <script>`.\n"
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
# create-from-note — synthesize skills from source notes via the agent
# ---------------------------------------------------------------------------


def _build_create_from_note_instruction(note_ids: list[str]) -> str:
    """Build a thin user instruction that lets the server-side skill do the work.

    Emits `<contextCard>` chips for each source note followed by a short trigger
    phrase. The chat agent's intent router matches the phrase against the
    `description` of `deepvista-skill-workflow` and loads its SKILL.md — that's
    where the full prompt, frontmatter rules, mermaid requirements, and
    `upsert_context_card` instructions live.
    """
    if not note_ids:
        raise ValueError("at least one note is required")

    chips = " ".join(f'<contextCard id="{nid}" cardType="note">Note</contextCard>' for nid in note_ids)
    source_phrase = "these notes" if len(note_ids) > 1 else "this note"
    return f"{chips} Create a workflow skill from {source_phrase}."


@skill_group.command("create-from-note")
@click.argument("note_ids_positional", metavar="[NOTE_ID]...", nargs=-1)
@click.option(
    "--note-id",
    "note_id_flags",
    multiple=True,
    help="Source note by ID. Repeatable — pass multiple to synthesize across notes.",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 25),
    default=_DEFAULT_MULTI_NOTE_LIMIT,
    help=f"Cap source notes (default {_DEFAULT_MULTI_NOTE_LIMIT}, max 25).",
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
    limit: int,
    chat_id: str | None,
    assume_yes: bool,
    dry_run: bool,
) -> None:
    """Synthesize a workflow skill from one or more notes via the DeepVista agent.

    Pass note UUIDs positionally or via repeated `--note-id`. To find source
    notes first, use `deepvista card +search` / `+search-content` / `+similar` and pass
    the resulting IDs here. The agent produces one `workflow` skill (executable
    steps), grounded in the union of all source notes and linked back to
    every source.

    The actual synthesis prompt lives server-side in `deepvista-skill-workflow`.
    This command sends only `<contextCard>` chips plus a short trigger phrase
    so the chat agent picks the right skill and runs it — keeping prompt logic
    on the server as the single source of truth (DV-585).

    Streams NDJSON identical to `chat +send` and `skill run`.

    > [!CAUTION] This is a write command — the agent creates skill cards in
    > the user's project. Confirm before executing.
    """
    for nid in (*note_ids_positional, *note_id_flags):
        if not _UUID_RE.match(nid):
            output_error(3, "Invalid note ID", f"Expected UUID format, got: {nid!r}")

    # De-duplicate while preserving first-seen order, then cap.
    note_ids = list(dict.fromkeys((*note_ids_positional, *note_id_flags)))[:limit]

    if not note_ids:
        output_error(3, "No source notes given", "pass a NOTE_ID positionally or via --note-id")

    instruction = _build_create_from_note_instruction(note_ids)
    body: dict[str, Any] = {"user_instruction": instruction}
    if chat_id:
        body["chat_id"] = chat_id

    if dry_run:
        format_output(
            {
                "dry_run": True,
                "would": "synthesize a workflow skill from note(s) via DeepVista agent",
                "note_ids": note_ids,
                "payload": body,
            },
            ctx.obj.output_format,
            entity_type="skill",
            base_url=ctx.obj.auth_url,
            project_id=ctx.obj.project_id,
        )
        return

    if not assume_yes:
        click.confirm(
            f"The agent will create a workflow skill synthesized from {len(note_ids)} source note(s). Continue?",
            abort=True,
        )

    try:
        for event in _client(ctx).stream_sse("/imagine", body):
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
