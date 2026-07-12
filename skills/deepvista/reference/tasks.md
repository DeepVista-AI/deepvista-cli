# `deepvista tasks` — run work dispatched to this Machine (DV-1247)

> Read [shared.md](shared.md) first (auth, profiles, global-flags-before-resource).

## Concepts

- **Machine** — this device, identified by a stable `machine_fingerprint`
  (hostname + MAC + OS). Registered automatically by `deepvista tasks run` /
  `agents sync`. A user can have several (a laptop, a cloud VM). Machines are
  *user-level*: uniqueness is `(user_id, machine_fingerprint)`. Local cache:
  `~/.config/deepvista/machines/<fingerprint>.json`.
- **Project** — claim/list scope only. `tasks run --project <id>` tells the
  Machine which project's task cards to claim; it does **not** create a second
  Machine row.
- **agent_type** — soft metadata (`last_seen_tool`: claude-code, deepvista-cli, …).
  Not part of identity. Claude Code sync and `tasks run` on the same laptop
  share one Machine.
- **Task** — a one-off prompt the web chat (or scheduled jobs) enqueues for a
  Machine. Stored as a project-scoped `task` context card. The Machine claims it
  and runs it **headless** with `claude -p "/deepvista <prompt>"`; stdout becomes
  the task's output (saved as a linked output card) and the exit code decides
  completed vs. failed. The run log accretes on the task card under `## Run`.

## Commands

| Command | Use when |
|---|---|
| `deepvista tasks run` | Start the poll loop on this Machine. Claims pending task cards for the **current project** (working project or backend default), runs each, reports results. |
| `deepvista tasks list` | Show task cards for this Machine (optionally `--status pending\|running\|completed\|failed`). Read-only. |
| `deepvista tasks note <id> "<note>"` | Append a progress note to a running task card (used by headless runs). |
| `deepvista tasks clean` | Delete terminated task cards (default: completed + failed). Preview with `--dry-run`. |
| `deepvista tasks setup` | Install (or `--remove`) a crontab entry that polls on a recurring interval (`--interval N`, macOS/Linux). |

> The command was named `task_queue` in earlier releases. The `task_queue`
> alias has been removed — use `tasks`. Cron entries installed by an older
> version are detected and replaced the next time you run `deepvista tasks setup`.

### `tasks run` — the poll loop

```bash
deepvista tasks run                 # poll forever (Ctrl-C to stop)
deepvista tasks run --run-once      # one pass then exit (what `setup`'s cron uses)
deepvista tasks run --poll-interval 30
deepvista tasks run --total-time 600   # poll for up to 10 minutes
deepvista tasks run --project <id>     # claim scope for this run (same Machine)
deepvista tasks run --max-parallel 3   # cap concurrent headless runs (default 5)
```

- **Current project by default**: scopes claims to the working project (`project use`,
  global `--project`, or `DEEPVISTA_PROJECT_ID`), falling back to your backend
  default (`GET /projects/me`). Override per-invocation with `--project`.
  Each claim stamps the Machine's `last_heartbeat_at`, so it shows **online**
  in Settings → Machines while polling.
- **Single instance**: a PID lock (`~/.config/deepvista/task_queue.run.lock`)
  means only one `tasks run` is active per Machine — a foreground poller and a
  cron tick never double-claim.
- **Parallel execution**: up to 5 headless `claude -p` runs execute concurrently
  by default. Override with `--max-parallel N`.
- **Headless execution**: each task runs `claude -p "/deepvista <prompt>"`.
  - Override the binary with `DEEPVISTA_CLAUDE_BIN` (also the test seam).
  - Permission posture defaults to `bypassPermissions` (unattended); override
    with `DEEPVISTA_TASK_PERMISSION_MODE`.
  - Working directory defaults to the poller's CWD; override with
    `DEEPVISTA_TASK_CWD`.

## How a task gets here

On DeepVista web chat, ask the agent to delegate — e.g.
*"add a task to the local agent queue to reply hello world"*. The chat agent
creates a pending `task` card targeting one of your Machines (auto-selected
when you have exactly one). The next `deepvista tasks run` poll on that Machine
claims and runs it.

Scheduled jobs that target a Machine also create task cards when the prompt
includes a workflow skill chip.

## Cron

`deepvista tasks setup --interval 5` installs a crontab entry that runs
`deepvista tasks run --run-once` every 5 minutes (macOS/Linux).
