# `deepvista tasks` — run work dispatched to this Machine (DV-1247)

> Read [shared.md](shared.md) first (auth, profiles, global-flags-before-resource).

## Concepts

- **Machine** — a device running the DeepVista CLI (this one). Registered with
  `deepvista agents register`; a user can have several (a laptop, a cloud VM).
  Machines are a *user-level* concept and live in the `managed_agents` table.
- **Task** — a one-off prompt the web chat (or another agent) enqueues for a
  Machine. Stored as a project-scoped `task` context card. The Machine claims it
  and runs it **headless** with `claude -p "/deepvista <prompt>"`; stdout becomes
  the task's output (saved as a linked output card) and the exit code decides
  completed vs. failed. The run log accretes on the task card under `## Run`.

This is different from a *workflow run* (a structured multi-phase Skill) — a task
is just a prompt. `tasks run` handles both: task cards **and** the legacy
pull-based queue (queued `deepvista …` CLI commands + host-driven workflow runs).

## Commands

| Command | Use when |
|---|---|
| `deepvista tasks run` | Start the poll loop on this Machine. Claims pending tasks across **every project** you can access (Owner/Editor), runs each, reports results. |
| `deepvista tasks list` | Show the tasks dispatched to this Machine (optionally `--status pending\|running\|completed\|failed`). Read-only. |

> `task_queue` remains as a deprecated alias of `tasks` so existing cron jobs
> keep working — prefer `tasks`.

### `tasks run` — the poll loop

```bash
deepvista tasks run                 # poll forever (Ctrl-C to stop)
deepvista tasks run --run-once      # one pass then exit (what `setup`'s cron uses)
deepvista tasks run --poll-interval 30
deepvista tasks run --total-time 600   # poll for up to 10 minutes
deepvista tasks run --project <id>     # restrict to one project's Machine
```

- **All projects by default**: with no `--type/--role/--project`, the loop
  ensures this Machine is registered in every project you can access and polls
  all of them, so nothing is missed. Each claim stamps the Machine's
  `last_polled`, so it shows **online** in Settings → Machines while polling.
- **Single instance**: a PID lock (`~/.config/deepvista/task_queue.run.lock`)
  means only one `tasks run` is active per Machine — a foreground poller and a
  cron tick never double-claim.
- **Headless execution**: each task runs `claude -p "/deepvista <prompt>"`.
  - Override the binary with `DEEPVISTA_CLAUDE_BIN` (also the test seam).
  - Permission posture defaults to `bypassPermissions` (unattended); override
    with `DEEPVISTA_TASK_PERMISSION_MODE`.
  - Working directory defaults to the poller's CWD; override with
    `DEEPVISTA_TASK_CWD`.

## How a task gets here

On DeepVista web chat, ask the agent to delegate — e.g.
*"add a task to the local agent queue to reply hello world"*. The chat agent
calls the `enqueue_task` tool, which creates a pending `task` card targeting one
of your Machines (auto-selected when you have exactly one). The next
`deepvista tasks run` poll on that Machine claims and runs it.

## Cron

`deepvista tasks setup --interval 5` installs a crontab entry that runs
`deepvista tasks run --run-once` every 5 minutes (macOS/Linux).
