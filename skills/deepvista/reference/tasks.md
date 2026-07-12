# `deepvista tasks` — run work dispatched to this Machine (DV-1247)

> Read [shared.md](shared.md) first (auth, profiles, global-flags-before-resource).

## Concepts

- **Machine** — this device (fingerprint = hostname + MAC + OS) **registered
  to a project**. Uniqueness is `(project_id, machine_fingerprint)`. Local
  cache: `~/.config/deepvista/machines/<fingerprint>__<project_id>.json`.
- **Project access** — anyone with access to the project can **see** Machines
  registered to it (Settings → Machines under that project). Only the user who
  registered the device can sync / claim / run `tasks run` on it.
- **agent_type** — soft metadata (`last_seen_tool`). Not part of identity.
- **Task** — a one-off prompt enqueued for a Machine. Stored as a project-scoped
  `task` card. The Machine claims it and runs it headless with
  `claude -p "/deepvista <prompt>"`.

Same physical laptop in two projects → two Machine rows (one per project).
A teammate's schedule in a shared project can target your Machine; your
`tasks run` on that project claims the work.

## Commands

| Command | Use when |
|---|---|
| `deepvista tasks run` | Poll + execute task cards for the working project (auto-registers this Machine for that project). |
| `deepvista tasks list` | Show task cards for this Machine (optionally `--status …`). |
| `deepvista tasks note <id> "<note>"` | Append a progress note to a running task card. |
| `deepvista tasks clean` | Delete terminated task cards. Preview with `--dry-run`. |
| `deepvista tasks setup` | Install/remove a crontab entry (`--interval N`, macOS/Linux). |

### `tasks run` — the poll loop

```bash
deepvista tasks run --project <id>     # register + claim for that project
deepvista project use <id> && deepvista tasks run
deepvista tasks run --run-once
deepvista tasks run --poll-interval 30
deepvista tasks run --max-parallel 3
```

You still need a project (flag / `project use` / backend default) because
Machines are project-scoped. Switching `--project` registers (or reuses) this
device **in that project** — it does not create a global user-level Machine.

## How a task gets here

On DeepVista web chat / schedules, work is enqueued for a Machine in the
project. The next `deepvista tasks run --project …` on that device claims it.

## Cron

`deepvista tasks setup --interval 5` installs a crontab entry that runs
`deepvista tasks run --run-once` every 5 minutes (macOS/Linux).
