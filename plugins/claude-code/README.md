# deepvista (Claude Code plugin)

A thin Claude Code plugin that keeps your local skills directory in sync
with the DeepVista remote skill catalog.

## What it does

On every Claude Code `SessionStart`, the plugin runs `deepvista skill sync`,
which writes thin `SKILL.md` stubs into `~/.claude/skills/`. Each stub is
just frontmatter plus a lazy-load directive — the full skill body is
fetched from the DeepVista server at invocation time via
`` !`deepvista skill load <id>` ``. Claude Code's live change detection
surfaces new/updated stubs in the current session, so there is no restart
lag.

The plugin itself ships no skills. All skill content comes from the
catalog.

## Requirements

- [`deepvista` CLI](https://cli.deepvista.ai) on `PATH`
  (`uv tool install deepvista-cli` or `pip install deepvista-cli`)
- A logged-in account: `deepvista auth login`

If either is missing at session start, the hook exits silently and leaves
whatever stubs were synced previously in place.

## Install

Local development:

```
/plugin install /path/to/deepvista-cli/plugins/claude-code
```

From the marketplace:

```
/plugin marketplace add /path/to/deepvista-cli/plugins
/plugin install deepvista@deepvista-ai
```

## Commands

- `/refresh-skills` — force a catalog resync bypassing the throttle.

## Configuration

Tunable via environment variables (read by the `SessionStart` hook):

| Variable | Default | Purpose |
|---|---|---|
| `DEEPVISTA_SYNC_THROTTLE_MIN` | `60` | Minutes to skip re-sync after a successful one |
| `DEEPVISTA_SYNC_LIMIT` | `30` | Cap number of skills fetched |
| `DEEPVISTA_FORCE_SYNC` | unset | Set to `1` to ignore the throttle once |

## What lives where

| Path | Purpose |
|---|---|
| `~/.claude/skills/dv-<slug>/SKILL.md` | Synced stub (one per catalog skill) |
| `~/.config/deepvista/catalog-state.json` | Last-sync timestamp + stub inventory |
| `~/.config/deepvista/cache/skill-bodies/` | 5-minute TTL cache of fetched bodies |
| `~/.deepvista/logs/catalog-sync.log` | Hook stdout/stderr |

The plugin never writes inside `${CLAUDE_PLUGIN_ROOT}` itself, so marketplace
auto-updates will not revert synced stubs.

## Troubleshooting

Sync not running? Check the log:

```
tail ~/.deepvista/logs/catalog-sync.log
```

Force a fresh run from the shell:

```
DEEPVISTA_FORCE_SYNC=1 deepvista skill sync --force
```
