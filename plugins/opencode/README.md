# @deepvista/opencode-plugin

Keeps your local opencode skills directory in sync with the DeepVista remote
skill catalog by calling `deepvista skill sync` on `session.created`.

## Requirements

- [`deepvista` CLI](https://cli.deepvista.ai) on `PATH`
- A logged-in account: `deepvista auth login`
- [opencode](https://opencode.ai) v1.0.190 or newer (native skills support)

## Install

### Option A: as a published package

```bash
npm install -g @deepvista/opencode-plugin
```

Add to `~/.config/opencode/opencode.json`:

```json
{
  "plugin": ["@deepvista/opencode-plugin"]
}
```

### Option B: as a local plugin

```bash
mkdir -p ~/.config/opencode/plugins/deepvista
cp index.js package.json ~/.config/opencode/plugins/deepvista/
```

opencode will auto-discover plugins under `~/.config/opencode/plugins/`.

## How it works

opencode reads skills from `~/.claude/skills/` natively for cross-agent
compatibility. This plugin writes stubs to that shared directory. Each stub
is a minimal `SKILL.md` whose body runs:

```
!`deepvista skill load <id>`
```

At skill-invocation time opencode executes the command and injects its
stdout into the skill context. The full body never sits on disk — you
always get the server's current version.

## Configuration

Environment variables honoured by the sync hook:

| Variable | Default | Purpose |
|---|---|---|
| `DEEPVISTA_SYNC_THROTTLE_MIN` | `60` | Minutes to skip re-sync after success |
| `DEEPVISTA_SYNC_LIMIT` | `30` | Cap number of skills fetched |
| `DEEPVISTA_FORCE_SYNC` | unset | Set to `1` to bypass the throttle |

## Manual sync

```bash
deepvista skill sync --force
```
