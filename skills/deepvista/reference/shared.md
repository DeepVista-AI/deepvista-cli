# Shared — auth, profiles, global flags, exit codes

Foundational reference for every `deepvista` subcommand. Read this first.
Run `deepvista --help` or `deepvista <subcommand> --help` for full flag reference.

## Authentication

```bash
deepvista auth login                  # opens a browser for OAuth
deepvista auth login --code XXXX-XXXX # paste a one-time code in headless envs
deepvista auth status                 # check current profile state
deepvista auth logout                 # clear credentials
```

Credentials live in `~/.config/deepvista/credentials.json` (mode `0600`).

## Global flags — must come BEFORE the resource name

```
deepvista [GLOBAL FLAGS] <resource> <command> [options]
```

**Wrong:** `deepvista card list --profile staging`
**Right:** `deepvista --profile staging card list`

Key global flags: `--profile NAME`, `--project ID`, `--format json|table`, `--verbose`, `--dry-run`, `--api-url URL`.

`--dry-run` is supported on every stateful command — use it to preview before writing.

## Project scoping

Every entity (card, note, chat, skill, …) lives inside a **project**. The CLI
scopes requests to a *working project* and sends it as the `X-Project-Id`
header; web links it emits are prefixed `/project/{id}/…` to match the app.

```bash
deepvista project list            # projects you own or that are shared with you
deepvista project current         # the project the backend resolves right now
deepvista project use <id>        # set the working project for this profile
deepvista project clear           # unset → fall back to the backend default
```

Resolution order (highest wins): `--project <id>` flag → `DEEPVISTA_PROJECT_ID`
env → profile working project (`project use`) → none (backend default). The
working project is client-side scoping only — it does **not** change your
server-side default project. See [reference/project.md](project.md).

## Profiles

```bash
deepvista config list                 # list configured profiles
```

Each profile holds separate credentials. Profile state lives in `~/.config/deepvista/`.

## Agent registration & heartbeat

Register once per machine so the DeepVista dashboard shows this agent's state:

```bash
deepvista agents register --type claude-code --name "My Claude"
```

This installs a `Stop` hook in `~/.claude/settings.json` that sends a heartbeat after each turn.

```bash
deepvista agents list                         # all registered agents
deepvista agents sync --type claude-code --status online   # manual heartbeat
deepvista agents delete --type claude-code    # unregister + remove hook
```

## Updates

`deepvista upgrade check` is fast, cached (~1h TTL), non-blocking.

| stdout | Meaning |
|---|---|
| *(empty)* | up to date / snoozed / disabled / offline |
| `UPGRADE_AVAILABLE <old> <new>` | run `deepvista upgrade install --yes` to install |
| `JUST_UPGRADED <old> <new>` | just finished updating |

```bash
deepvista upgrade check                  # fast cached check (exit 1 if update available)
deepvista upgrade install --yes          # non-interactive install (use in agent flows)
deepvista upgrade snooze                 # defer upgrade
deepvista upgrade disable                # opt out permanently
deepvista upgrade status                 # show version + snooze state
```

> **Agent note:** `deepvista upgrade` and `deepvista upgrade install` are interactive — they
> prompt "Install now? [y/n/snooze]". In agent flows always use
> `deepvista upgrade install --yes` after user confirmation so the agent never blocks.

## Output format

**JSON (default)** — agent-friendly. Errors:

```json
{"error": {"code": 2, "message": "Not authenticated", "detail": "Run `deepvista auth login`"}}
```

**NDJSON** — streaming commands (`chat +send`, `skill run`): one JSON object per line.

**Table** — pass `--format table` for human-readable output.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | API error |
| 2 | auth error |
| 3 | validation error |
| 4 | network error |
| 5 | internal error |

Branch on exit codes before parsing stdout — exit 0 guarantees valid JSON; non-zero guarantees a structured error object.
