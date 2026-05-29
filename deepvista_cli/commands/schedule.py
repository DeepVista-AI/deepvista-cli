"""deepvista schedule — opt-in recurring runs of the daily-planning skill.

Daily planning generation lives on the DeepVista server (the
``deepvista-daily-planning`` skill). This command lets the user *explicitly*
activate a recurring server job that generates today's planning note on a cron
schedule — nothing runs automatically until the user opts in here, which keeps
token spend under their control.

Under the hood each "activation" is a row in the server's ``scheduled_jobs``
table whose ``prompt`` asks the agent to run the daily-planning skill. The
heartbeat dispatcher drains due rows and runs the agent.
"""

from __future__ import annotations

import click

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.output.formatter import format_output, output_error

# The server-side workflow skill that generates the planning note.
DAILY_PLANNING_SKILL = "deepvista-daily-planning"
# Stable title used to find this job again (activate is idempotent on it).
JOB_TITLE = "Daily Planning"
# 08:00 every day / 08:00 every Monday (5-field cron, validated server-side).
DEFAULT_DAILY_CRON = "0 8 * * *"
DEFAULT_WEEKLY_CRON = "0 8 * * 1"

# Columns shown in `--format table`.
_JOB_COLUMNS = ["id", "title", "cron_schedule", "enabled", "next_run_at", "last_run_at"]


def _client(ctx: click.Context) -> DeepVistaClient:
    return ctx.obj._client


def _find_daily_planning_job(ctx: click.Context) -> dict | None:
    """Return the existing daily-planning job for this user, or None.

    Matches on the stable ``JOB_TITLE`` so repeated activations re-use the same
    row instead of stacking duplicates.
    """
    data = _client(ctx).get("/scheduled-jobs")
    for job in data.get("jobs", []):
        if job.get("title") == JOB_TITLE:
            return job
    return None


@click.group("schedule")
def schedule_group() -> None:
    """Manage the recurring daily-planning job (opt-in)."""


@schedule_group.command("activate")
@click.option("--cron", "cron_schedule", default=None, help="5-field cron (default: daily 08:00).")
@click.option("--weekly", is_flag=True, default=False, help="Run weekly (Mon 08:00) instead of daily.")
@click.pass_context
def schedule_activate(ctx: click.Context, cron_schedule: str | None, weekly: bool) -> None:
    """Activate the recurring daily-planning job.

    Idempotent: if a daily-planning job already exists it is re-enabled rather
    than duplicated. To change the cron of an existing job, deactivate + delete
    it first, then activate again with a new --cron.
    """
    cadence = "weekly" if weekly else "daily"
    if cron_schedule is None:
        cron_schedule = DEFAULT_WEEKLY_CRON if weekly else DEFAULT_DAILY_CRON

    existing = _find_daily_planning_job(ctx)
    if existing is not None:
        if existing.get("enabled"):
            format_output(
                {"status": "already_active", "job": existing},
                ctx.obj.output_format,
                title="Daily planning already active",
            )
            return
        resp = _client(ctx).patch(f"/scheduled-jobs/{existing['id']}", {"enabled": True})
        format_output(
            {"status": "reactivated", "job": resp.get("job", resp)},
            ctx.obj.output_format,
            title="Daily planning reactivated",
        )
        return

    prompt = (
        f"Run the {DAILY_PLANNING_SKILL} skill to generate today's daily "
        f"planning note (cadence: {cadence}). List the workflow Skills that "
        f"should run today as context-card chips in the note's Planning section."
    )
    resp = _client(ctx).post(
        "/scheduled-jobs",
        {
            "prompt": prompt,
            "cron_schedule": cron_schedule,
            "title": JOB_TITLE,
            "enabled": True,
        },
    )
    if not resp.get("success"):
        output_error(1, "Failed to activate daily planning", resp.get("error", ""))
    format_output(
        {"status": "activated", "cadence": cadence, "job": resp.get("job", resp)},
        ctx.obj.output_format,
        title="Daily planning activated",
    )


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

    With no JOB_ID, deletes the daily-planning job. Use this (then ``activate``)
    to change a job's cron, which PATCH can't edit. Pass ``--dry-run`` on the
    root command to preview without deleting.
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
