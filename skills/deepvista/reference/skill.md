# Skill — structured workflows

A Skill is a multi-step workflow the agent works through phase by phase.
Run `deepvista skill --help` or `deepvista skill <cmd> --help` for full flag reference.

## Commands

`list` · `get` · `run` · `phase` · `complete` · `status`
`create-from-note` · `discover` · `install` · `sync` · `load`

## Agent conventions

> [!CAUTION] `run`, `phase`, `complete`, `install` are writes. Confirm first.

Read-only: `list`, `get`, `status`, `discover`, `sync --dry-run`, `load`.

Show the app URL after writes: `https://app.deepvista.ai/skills/<id>`

## Non-obvious: `skill run` modes

`skill run` has three modes (set with `--mode`, default `host`):

| Mode | Behaviour |
|---|---|
| `host` | CLI prints a JSON run packet + SKILL.md body. The **host agent** (Claude Code, Cursor, etc.) drives the run using `skill phase` / `skill complete` shims. Use when the workflow needs host tools (Bash, Edit, MCPs, repo state). |
| `deepvista` | Posts to `/imagine`, streams NDJSON from the DeepVista server agent end-to-end. Use for KB-internal workflows where server tools are sufficient. |
| `auto` | Routes per-phase: server-side tool phases go to DeepVista, the rest stay host. |

## Non-obvious: host-mode shims

After `skill run --mode host`, drive the run with:

```bash
deepvista skill phase open <skill_id> "Phase N: <title>"
deepvista skill phase done <skill_id> "Phase N: <title>" [--artifact-card-id ID] [--next-phase "…"]
deepvista skill phase pause <skill_id> --reason "<sentence>"
deepvista skill complete <skill_id> --review "<3–6 retrospective bullets>"
```

`complete` appends `## Review`, releases the run lock, and emits `{"done": true}`.

## Non-obvious: `sync` and `load`

`sync` writes thin `SKILL.md` stubs (frontmatter + lazy-fetch shell) into the agent
skills directory. Safe in a `SessionStart` hook — always exits 0. Idempotent; only
touches dirs with the `x-deepvista-catalog` marker; never overwrites user-authored
skills.

`load` fetches the full SKILL.md body for a catalog skill at invocation time (5-min
cache). Called by stubs — rarely needed directly.

## Examples

```bash
deepvista skill list
deepvista skill run <skill_id> --input "Focus on Q4"          # host mode
deepvista skill run <skill_id> --mode deepvista                # server agent
deepvista skill run <skill_id> --mode auto                     # per-phase routing
deepvista skill phase open <skill_id> "Phase 1: …"
deepvista skill phase done <skill_id> "Phase 1: …" --artifact-card-id <id>
deepvista skill complete <skill_id> --review "clean run, shipped Friday"
deepvista skill discover --category workflow
deepvista skill sync --dry-run
```

## Continuing a run

`skill run` returns a `run_chat_id`. Continue with:

```bash
deepvista chat +send "Add one more step" --chat-id <run_chat_id>
```

## See also

- [skill-create-from-note.md](skill-create-from-note.md) — synthesize a skill from notes
- [skill-research-to-skill.md](skill-research-to-skill.md) — research then run pattern
- [skill-analyze-notes.md](skill-analyze-notes.md) — notes synthesis pattern
