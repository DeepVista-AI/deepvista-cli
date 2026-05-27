# DeepVista agent plugins

Thin glue that wires `deepvista skill sync` into each agent's session
lifecycle so the remote skill catalog stays fresh with zero user action.

| Agent | Location | Lifecycle hook | Notes |
|---|---|---|---|
| Claude Code | [`claude-code/`](./claude-code) | `SessionStart` | Installable via `/plugin install` |
| opencode | [`opencode/`](./opencode) | `session.created` | Drop in `~/.config/opencode/plugins/` or npm-install |
| Cursor | — | n/a | Use cron or shell init (see below) |
| Codex CLI | — | n/a | Use cron or shell init (see below) |
| Any agent | — | n/a | Use `deepvista skill sync` from shell init |

Each plugin writes stubs into its own plugin skills dir (Claude Code:
`${CLAUDE_PLUGIN_ROOT}/skills/`, opencode: the plugin module's `skills/`),
so stubs surface as plugin-managed rather than user-owned. Agents without a
plugin (Cursor, Codex, generic) rely on the shell/cron fallback below, which
uses `deepvista skill sync` with a target you choose.

## No-plugin fallback (Cursor, Codex, generic)

Run `deepvista skill sync` on a schedule or from your shell init.

**Cron** (every hour):

```cron
0 * * * * /usr/local/bin/deepvista skill sync --quiet
```

**Shell init** (`~/.zshrc` / `~/.bashrc`):

```bash
# Refresh DeepVista catalog on shell start (cheap — throttled to 60 min)
command -v deepvista >/dev/null 2>&1 && \
  (deepvista skill sync --quiet &) 2>/dev/null
```

**Systemd timer** (Linux): run every 30 min, see
[`systemd/timer.example`](./systemd/timer.example).

## Architecture recap

```
 server catalog ──┐
                  │  (fetched at sync time)
                  ▼
         deepvista skill sync
                  │
                  ▼
      <plugin-skills-dir>/dv-<name>/SKILL.md   ← thin stub, frontmatter only
                  │
  agent reads ◄───┘
                  │
  at invocation time:
                  │
                  ▼
         !`deepvista skill load <id>`          ← lazy fetch of full body
                  │
                  ▼
         full instructions in agent context
```
