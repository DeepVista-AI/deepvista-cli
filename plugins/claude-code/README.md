# deepvista (Claude Code plugin)

A thin Claude Code plugin that keeps your local skills directory in sync with
the DeepVista remote skill catalog, and turns your DeepVista managed agents
into callable Claude Code subagents.

## What it does

On every Claude Code `SessionStart`, the plugin runs two syncs:

1. **Skill catalog** — `deepvista skill sync` writes thin `SKILL.md` stubs into
   `${CLAUDE_PLUGIN_ROOT}/skills/` (the plugin's own skill dir). Each stub is
   just frontmatter plus a lazy-load directive — the full skill body is fetched
   from the DeepVista server at invocation time via
   `` !`deepvista skill load <id>` ``. Claude Code's live change detection
   surfaces new/updated stubs in the current session, so there is no restart
   lag.
2. **Agent definitions** — `deepvista agents export` writes one `dv-<role>.md`
   subagent into `${CLAUDE_PLUGIN_ROOT}/agents/` for each distinct role across
   your DeepVista managed agents (`agent_role`, DV-832). You can then call a
   role inline, e.g. `@marketing summarize this week`. Each generated subagent
   preloads the `deepvista` skill and grounds its work in your notes and
   knowledge base. The `misc` default role is skipped, and a hand-curated agent
   of the same name always wins.

The plugin itself ships no skills. All skill content comes from the catalog,
and all agent roles come from your managed agents.

## Requirements

- [`deepvista` CLI](https://cli.deepvista.ai) on `PATH`
  (`uv tool install deepvista-cli` or `pip install deepvista-cli`)
- A logged-in account: `deepvista auth login`

If either is missing at session start, the hook exits silently and leaves
whatever stubs were synced previously in place.

## Install

This is the recommended way to use DeepVista from Claude Code. Run these two
commands inside Claude Code:

```
/plugin marketplace add DeepVista-AI/deepvista-cli
/plugin install deepvista@deepvista-ai
```

If you're on a different agent (Cursor, OpenCode, OpenClaw, …), use the
[install script](../../README.md#for-non-claude-code-agents-cursor-opencode-openclaw-) instead.

For local plugin development:

```
/plugin install /path/to/deepvista-cli/plugins/claude-code
```

## Commands

- `/refresh-skills` — force a catalog resync bypassing the throttle.

## Configuration

Tunable via environment variables (read by the `SessionStart` hook):

| Variable | Default | Purpose |
|---|---|---|
| `DEEPVISTA_SYNC_THROTTLE_MIN` | `60` | Minutes to skip skill re-sync after a successful one |
| `DEEPVISTA_SYNC_LIMIT` | `30` | Cap number of skills fetched |
| `DEEPVISTA_AGENT_SYNC_THROTTLE_MIN` | `60` | Minutes to skip agent re-export after a successful one |
| `DEEPVISTA_AGENT_SYNC_LIMIT` | `50` | Cap number of managed agents fetched |
| `DEEPVISTA_FORCE_SYNC` | unset | Set to `1` to ignore both throttles once |

## What lives where

| Path | Purpose |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/skills/dv-<slug>/SKILL.md` | Synced stub (one per catalog skill) |
| `${CLAUDE_PLUGIN_ROOT}/agents/dv-<role>.md` | Generated subagent (one per managed-agent role) |
| `~/.config/deepvista/catalog-state.json` | Last skill-sync timestamp + stub inventory |
| `~/.config/deepvista/agent-defs-state.json` | Last agent-export timestamp + definition inventory |
| `~/.config/deepvista/config.json` | CLI profiles + top-level `session_skip_cwd_patterns` list |
| `~/.config/deepvista/cache/skill-bodies/` | 5-minute TTL cache of fetched bodies |
| `~/.config/deepvista/logs/catalog-sync.log` | Skill-sync hook stdout/stderr |
| `~/.config/deepvista/logs/agent-export.log` | Agent-export hook stdout/stderr |

Generated files (`dv-*`) are gitignored and re-created on each session start, so
a marketplace `git pull` that wipes them is self-healing; the plugin never
clobbers files it did not author.

## Troubleshooting

Sync not running? Check the logs:

```
tail ~/.config/deepvista/logs/catalog-sync.log
tail ~/.config/deepvista/logs/agent-export.log
```

Force a fresh run from the shell:

```
DEEPVISTA_FORCE_SYNC=1 deepvista skill sync --force
deepvista agents export --force
```

Nested observer/sub-agent sessions showing up in the vistabase (e.g.
`observer-sessions · <hash>` notes from claude-mem's observer sub-claude)?
The plugin's SessionStart hook now skips CWDs matching the top-level
`session_skip_cwd_patterns` list in `~/.config/deepvista/config.json`.
Defaults cover `~/.claude-mem/observer-sessions`; to extend, edit the file
and add patterns (fnmatch-style globs):

```jsonc
{
  "default": { "api_url": "https://api.deepvista.ai" },
  "session_skip_cwd_patterns": [
    "*/.claude-mem/observer-sessions",
    "*/.claude-mem/observer-sessions/*",
    "*/scratchpad/*"
  ]
}
```

No agents showing up as `@<role>`? Confirm you have managed agents with roles:

```
deepvista agents list
deepvista agents export --dry-run     # preview what would be written
```
