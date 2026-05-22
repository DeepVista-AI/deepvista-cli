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

## Executing a workflow skill — required sequence

> [!IMPORTANT] To run a workflow skill you **must** call `deepvista skill run --mode host <skill_id>` first. Do NOT call `skill get` and drive the phases manually — that skips the run lock, phase tracking, and the host runtime contract entirely.

`skill run --mode host` does three things `skill get` does not:
1. Acquires the run lock (`status = "in_progress"`) on the skill card.
2. Emits the host runtime contract that tells you to call the `skill phase` shims.
3. Indicates the `active_phase` so resumed runs continue from the right place.

**Required sequence for every workflow run:**

```bash
# 1. Initiate the run (acquires lock, emits run packet + host runtime contract)
deepvista skill run --mode host <skill_id>

# 2. For each phase — open → execute → done
deepvista skill phase open <skill_id> "Phase N: <title>"
# … execute the phase using your own tools …
deepvista skill phase done <skill_id> "Phase N: <title>" [--next-phase "Phase N+1: <title>"]

# 3. Finalize
deepvista skill complete <skill_id> --review "<3–6 retrospective bullets>"
```

If you called `skill get` and are already mid-workflow without a lock, call `skill run --mode host` now — it is idempotent on an already-in-progress card and will re-emit the correct active phase.

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
deepvista skill phase open  <skill_id> "Phase N: <title>"
deepvista skill phase done  <skill_id> "Phase N: <title>" [--artifact-card-id ID] [--next-phase "…"]
deepvista skill phase reset <skill_id> "Phase N: <title>"   # revert a done/active phase to pending
deepvista skill phase pause <skill_id> --reason "<sentence>"
deepvista skill complete    <skill_id> --review "<3–6 retrospective bullets>"
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
