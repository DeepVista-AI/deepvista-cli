# Shared — auth, profiles, global flags, exit codes

Foundational reference for every `deepvista` subcommand. Read this first.

## Install

```bash
uv tool install 'deepvista-cli[ui]'   # preferred
pip install 'deepvista-cli[ui]'       # alternative
```

The `[ui]` extra adds the optional terminal UI (`deepvista ui`). Omit to keep the
CLI-only install small.

## Authentication

```bash
deepvista auth login                  # opens a browser for OAuth
deepvista auth login --code XXXX-XXXX # paste a one-time code in headless envs
deepvista auth status                 # check current profile state
deepvista auth logout                 # clear credentials
```

Credentials live in `~/.config/deepvista/credentials.json` (mode `0600`).
Re-run `auth login` after `logout` to get a new token.

## Global flags (must come BEFORE the resource name)

```
deepvista [GLOBAL FLAGS] <resource> <command> [options]
```

| Flag | Default | Purpose |
|---|---|---|
| `--profile NAME` | `default` | Switch between profiles (e.g. `staging`, `prod`) |
| `--format json\|table` | `json` | `json` is agent-friendly; `table` is human-readable |
| `--verbose` | off | Print request/response details |
| `--dry-run` | off | Preview without writing (supported on every stateful command) |
| `--api-url URL` | — | Override the API base URL |
| `--version` | — | Print CLI version and exit |
| `--help` | — | Context-sensitive help |

**Wrong:** `deepvista card list --profile staging`
**Right:** `deepvista --profile staging card list`

## Profiles

```bash
deepvista config list                 # list configured profiles
```

Each profile has its own credentials, so you can hold separate tokens for `default`,
`staging`, `prod`, etc. Profile state lives in `~/.config/deepvista/`.

## Resources and support commands

| Resource | What it manages |
|---|---|
| `card` | Knowledge base entries of every type (note, person, topic, file, …) |
| `notes` | Convenience wrapper over `card --type note` |
| `skill` | Structured workflows (formerly "recipes") |
| `vistabase` (alias: `memory`) | Implicit memory auto-accumulated from chat |
| `chat` | AI agent sessions |
| `auth`, `config`, `upgrade`, `agents`, `ui` | CLI plumbing |

## Agent registration & heartbeat

DeepVista tracks which AI agent is running the CLI so the dashboard can show each
agent's state and config. On first skill load, register once:

```bash
deepvista agents register --type claude-code --name "My Claude"
```

This records the agent and installs a `Stop` hook in `~/.claude/settings.json` that
calls `deepvista agents sync --type claude-code --status online` after each turn. The
hook produces a heartbeat every conversation turn — an agent idle for 10+ minutes
shows as offline in the dashboard. Other supported types: `opencode`, `cursor`,
`windsurf`, `cline`, `aider`, `openclaw`, `deepvista-cli`, `github-copilot`.

```bash
deepvista agents get --type claude-code      # check this machine's registration
deepvista agents list                         # all registered agents
deepvista agents +status                      # quick status check
deepvista agents sync --type claude-code --status online   # manual heartbeat
deepvista agents delete --type claude-code    # unregister + remove hook
```

The CLI detects agent type from environment variables (`CLAUDECODE=1`, `OPENCODE`,
`CURSOR`, `WINDSURF`, `CLINE`) when not passed explicitly.

## Updates

`deepvista upgrade check` is fast, cached (~1h TTL), and non-blocking. Outputs:

| stdout | Meaning |
|---|---|
| *(empty)* | up to date / snoozed / disabled / offline |
| `UPGRADE_AVAILABLE <old> <new>` | run `deepvista upgrade install --yes` to install |
| `JUST_UPGRADED <old> <new>` | just finished updating |

```bash
deepvista upgrade                        # alias for `upgrade install` — interactive
deepvista upgrade check                  # fast cached check (exit 1 if update available)
deepvista upgrade check --no-cache       # bypass cache, re-check against PyPI
deepvista upgrade check --quiet          # no stdout; communicate via exit code only
deepvista upgrade install                # interactive: shows changelog, prompts y/n/snooze
deepvista upgrade install --yes          # non-interactive: install immediately (use this in agent flows)
deepvista upgrade install --skip-skills  # upgrade CLI only, leave skills alone
deepvista upgrade install --dry-run      # preview what would be installed, no changes
deepvista upgrade snooze                 # defer with escalating backoff (1d → 2d → 7d)
deepvista upgrade snooze --days 3        # snooze for a specific number of days
deepvista upgrade disable                # opt out permanently
deepvista upgrade enable                 # re-enable after disable
deepvista upgrade status                 # show current version, cached latest, snooze state
```

> **Agent note:** `deepvista upgrade` and `deepvista upgrade install` are interactive — they
> prompt "Install now? [y/n/snooze]". In agent flows, always use
> `deepvista upgrade install --yes` after the user has confirmed in the conversation, so the
> agent never blocks waiting for a terminal prompt.

## Output format

**JSON (default)** — one object, agent-friendly. Errors follow:

```json
{"error": {"code": 2, "message": "Not authenticated", "detail": "Run `deepvista auth login`"}}
```

**NDJSON** — for streaming commands (`chat +send`, `skill run`). One JSON object per
line as events arrive.

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

Agents should branch on exit codes before parsing stdout — exit 0 guarantees valid
JSON on stdout, non-zero exit guarantees a structured error on stdout.

## Terminal UI (optional)

```bash
deepvista ui
```

Launches a Textual-based UI for browsing cards, notes, and chats. Requires the `[ui]`
extra at install time.
