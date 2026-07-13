"""deepvista schedule — opt-in recurring runs of the daily-planning skill.

Daily planning generation lives on the DeepVista server (the
``deepvista-daily-planning`` skill). This command lets the user *explicitly*
activate a recurring server job that generates today's planning note on a cron
schedule — nothing runs automatically until the user opts in here, which keeps
token spend under their control.

Under the hood each "activation" is a ``schedule_job`` context card on the
server (DV-1166) whose ``prompt`` asks the agent to run the daily-planning
skill. The heartbeat dispatcher drains due jobs and runs the agent.

Identity + creation are delegated to the server's ``POST /scheduled-jobs/
activate`` endpoint (DV-1045), keyed on the stable ``kind="daily_planning"``
attribute rather than a title string — the same endpoint the web Settings /
Home "Scheduled Job" toggle drives. Matching on ``kind`` (instead of a
hardcoded title, as this command used to) is what keeps this command and the
web UI pointed at the same row instead of each silently creating its own
duplicate (DV-1537).
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

# Stable identifier the server keys the (user_id, kind) upsert on — mirrors
# ``DAILY_PLANNING_JOB_KIND`` in ai/vista_common/services/scheduled_job_service.py.
JOB_KIND = "daily_planning"
# Only used to build a --cron/--weekly override; the server supplies its own
# canonical cron (currently daily 09:00 in the user's timezone) when neither
# flag is passed, so there's no local default to duplicate/drift from.
DEFAULT_WEEKLY_CRON = "0 9 * * 1"

# Columns shown in `--format table`.
_JOB_COLUMNS = ["id", "title", "cron_schedule", "enabled", "next_run_at", "last_run_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _find_daily_planning_job(ctx: click.Context) -> dict | None:
    """Return the existing daily-planning job for this user, or None.

    Matches on the stable ``kind`` attribute (DV-1045) — the same field the
    server's ``(user_id, kind)`` upsert is keyed on — so this reliably finds
    the same row the server's activate endpoint would touch, regardless of
    what title the row happens to carry.
    """
    data = _client(ctx).get("/scheduled-jobs")
    for job in data.get("jobs", []):
        if job.get("kind") == JOB_KIND:
            return job
    return None


@click.group("schedule")
def schedule_group() -> None:
    """Manage the recurring daily-planning job (opt-in)."""


@schedule_group.command("activate")
@click.option(
    "--cron",
    "cron_schedule",
    default=None,
    help="5-field cron override (default: the server's canonical daily cadence).",
)
@click.option(
    "--weekly",
    is_flag=True,
    default=False,
    help="Run weekly (Mon 09:00) instead of the server default (daily).",
)
@click.pass_context
def schedule_activate(ctx: click.Context, cron_schedule: str | None, weekly: bool) -> None:
    """Activate the recurring daily-planning job.

    Idempotent: if a daily-planning job already exists it is re-enabled rather
    than duplicated (the server upserts on ``kind``, keyed the same way the web
    Settings / Home "Scheduled Job" toggle activates it — see DV-1537). Without
    --cron/--weekly the server's own canonical prompt + cadence are used; pass
    either flag to override the cadence on top of that.
    """
    cron_override = cron_schedule or (DEFAULT_WEEKLY_CRON if weekly else None)
    existing = _find_daily_planning_job(ctx)

    if existing is not None and existing.get("enabled") and cron_override is None:
        format_output(
            {"status": "already_active", "job": existing},
            ctx.obj.output_format,
            title="Daily planning already active",
        )
        return

    resp = _client(ctx).post("/scheduled-jobs/activate", {"kind": JOB_KIND})
    if not resp.get("success"):
        output_error(1, "Failed to activate daily planning", resp.get("error", ""))
        return
    job = resp.get("job") or {}

    if cron_override is not None and job.get("cron_schedule") != cron_override:
        patch_resp = _client(ctx).patch(f"/scheduled-jobs/{job['id']}", {"cron_schedule": cron_override})
        if not patch_resp.get("success"):
            output_error(1, "Activated but failed to set the requested cron", patch_resp.get("error", ""))
            return
        job = patch_resp.get("job", job)

    if existing is None:
        status, title = "activated", "Daily planning activated"
    elif not existing.get("enabled"):
        status, title = "reactivated", "Daily planning reactivated"
    else:
        status, title = "updated", "Daily planning schedule updated"

    format_output({"status": status, "job": job}, ctx.obj.output_format, title=title)


@schedule_group.command("deactivate")
@click.pass_context
def schedule_deactivate(ctx: click.Context) -> None:
    """Disable the daily-planning job (keeps the row so it can be re-activated)."""
    existing = _find_daily_planning_job(ctx)
    if existing is None:
        output_error(1, "No daily-planning job found", "Run: deepvista schedule activate")
    if not existing.get("enabled"):
        format_output(
            {"status": "already_inactive", "job": existing},
            ctx.obj.output_format,
            title="Daily planning already inactive",
        )
        return
    resp = _client(ctx).patch(f"/scheduled-jobs/{existing['id']}", {"enabled": False})
    format_output(
        {"status": "deactivated", "job": resp.get("job", resp)},
        ctx.obj.output_format,
        title="Daily planning deactivated",
    )


@schedule_group.command("list")
@click.pass_context
def schedule_list(ctx: click.Context) -> None:
    """List the caller's scheduled jobs (read-only)."""
    data = _client(ctx).get("/scheduled-jobs")
    jobs = data.get("jobs", [])
    format_output(
        {"jobs": jobs, "count": len(jobs)},
        ctx.obj.output_format,
        columns=_JOB_COLUMNS,
        title="Scheduled Jobs",
    )


@schedule_group.command("delete")
@click.argument("job_id", required=False)
@click.pass_context
def schedule_delete(ctx: click.Context, job_id: str | None) -> None:
    """Delete a scheduled job permanently.

    With no JOB_ID, deletes the daily-planning job. To change its cadence
    instead, use ``activate --cron``/``--weekly``, which patches it in place.
    Pass ``--dry-run`` on the root command to preview without deleting.
    """
    if job_id is None:
        existing = _find_daily_planning_job(ctx)
        if existing is None:
            output_error(1, "No daily-planning job found", "Pass a JOB_ID, or run: deepvista schedule list")
        job_id = existing["id"]

    resp = _client(ctx).delete(f"/scheduled-jobs/{job_id}")
    if not resp.get("success"):
        output_error(1, "Failed to delete scheduled job", resp.get("error", ""))
    format_output(
        {"status": "deleted", "job_id": job_id},
        ctx.obj.output_format,
        title="Scheduled job deleted",
    )
