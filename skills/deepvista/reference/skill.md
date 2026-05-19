# Skill — structured workflows

A Skill is a multi-step checklist the agent works
through phase by phase. `deepvista skill run` creates a chat session linked to the
Skill run so you can continue it like a regular conversation.

## Commands

### `list` — read-only

```bash
deepvista skill list [--limit N] [--page N]
```

### `get` — read-only

```bash
deepvista skill get <skill_id>
```

Returns the full Skill definition including every phase and step.

### `create-from-note` — write

> [!CAUTION] The agent creates skill cards grounded in a source note.
> Confirm first (or pass `--yes` in batch scripts).

```bash
deepvista skill create-from-note <note_id> [--kind workflow]... [--yes] [--dry-run]
```

Synthesizes a `workflow` skill from a source note (podcast, interview,
book chapter, research summary). Full guide:
[skill-create-from-note.md](skill-create-from-note.md).

### `run` — write

> [!CAUTION] Acquires the parent Skill card's run lock and either prints a host run packet or starts a DeepVista chat session. Confirm first.

```bash
deepvista skill run <skill_id> [--mode host|deepvista|auto] [--input "context text"]
```

Three modes, picked with `--mode` (default `host`):

- **`host`** *(default)* — the CLI does **not** call `/imagine`. It prints a JSON header (`type: "skill_run_packet"`, skill_id, active phase, per-phase routing, user_input) followed by the workflow's SKILL.md body and the host-mode runtime contract. The host agent (Claude Code / OpenClaw / Cursor) drives the run itself via the [`phase`](#phase--mutate-an-in-progress-run-write) and [`complete`](#complete--release-the-run-lock-write) shims below. Use this when the workflow needs tools the host has (Bash, Edit, MCPs, your repo state).
- **`deepvista`** — legacy behaviour: POSTs to `/imagine` and streams NDJSON from the DeepVista server agent, which drives the workflow end-to-end. Use this for KB-internal workflows (research, synthesis, card updates) where the server's tools are sufficient.
- **`auto`** — inspects each phase's `tool_plan` and routes per phase. Phases whose plan is entirely server-side tools (`chat_cypher_search`, `upsert_context_card`, …) get a `"deepvista"` route in the packet; the rest stay `"host"`. The host agent follows the table.

### `phase` — mutate an in-progress run (write)

Used by host agents driving the workflow themselves after `skill run --mode host`. Each command parses the skill card, mutates accordion + mermaid markers, and writes via `/update_context_card`.

```bash
deepvista skill phase open <skill_id> "Phase N: <title>"
deepvista skill phase done <skill_id> "Phase N: <title>" [--artifact-card-id ID]... [--next-phase "Phase N+1: …"]
deepvista skill phase pause <skill_id> --reason "<short sentence>"
deepvista skill phase run-on-deepvista <skill_id> "Phase N: <title>" [--input "..."]
```

- `open` marks the accordion `open="true"` and the mermaid node `:::dvActive`.
- `done` marks `checked="true"` / `:::dvDone` and optionally embeds artifact `<contextCardBlock>`s. Pass `--next-phase` to open the next phase in the same write.
- `pause` does **not** change `status` (the run lock stays held). Exits non-zero; the user resumes by re-running `deepvista skill run --mode host`.
- `run-on-deepvista` delegates a single phase to the DeepVista server agent. Used by `--mode auto` for server-routable phases.

### `complete` — release the run lock (write)

```bash
deepvista skill complete <skill_id> --review "<3–6 retrospective bullets>"
```

Appends the `## Review` section, sets `status="completed"` (releases the lock so the skill can be run again), and emits `<json>{"done": true}</json>`.

### `status` — read-only

```bash
deepvista skill status <run_chat_id>
```

Returns run state: `running`, `awaiting_input`, `completed`, `failed`, `paused`.

### `discover` — read-only

```bash
deepvista skill discover [--search "query"] [--category persona|productivity|workflow] [--limit N]
```

Browse the marketplace of public skills.

### `install` — write

> [!CAUTION] Copies a marketplace skill into the user's library. Confirm first.

```bash
deepvista skill install <skill_id>
```

### `sync` — catalog sync (safe, throttled)

```bash
deepvista skill sync [--target DIR] [--prefix dv-] [--limit N]
                     [--throttle-min N] [--force] [--dry-run] [--quiet]
```

Writes thin `SKILL.md` stubs into an agent skills directory (default
`~/.claude/skills/`, which opencode / Cursor / Codex also read). Each stub
is frontmatter plus `` !`deepvista skill load <id>` `` — the real body is
fetched at skill-invocation time, not at sync time.

Idempotent. Adds / updates / removes stubs to match the server catalog.
Only touches dirs carrying the `x-deepvista-catalog` marker — user-authored
skills are never overwritten. Safe inside a SessionStart hook: always exits
0 even on auth or network errors.

### `load` — print full SKILL.md body (lazy fetch)

```bash
deepvista skill load <skill_id> [--no-cache] [--ttl N]
```

Prints the full SKILL.md body for one catalog skill to stdout. Called by
stubs at invocation time. On error, prints a readable error body (not a
traceback) so agents don't blow up. 5-minute on-disk body cache by default.

## Examples

```bash
deepvista skill list
deepvista skill run <skill_id> --input "Focus on Q4 objectives"           # host mode (default)
deepvista skill run <skill_id> --mode deepvista                            # legacy server-agent run
deepvista skill run <skill_id> --mode auto                                 # per-phase routing
deepvista skill phase open <skill_id> "Phase 1: …"                         # host: open the first phase
deepvista skill phase done <skill_id> "Phase 1: …" --artifact-card-id <id> # host: complete + attach artifact
deepvista skill complete <skill_id> --review "shipped on Friday — clean run"
deepvista skill status <run_chat_id>
deepvista skill discover --category persona
deepvista skill install deepvista-persona-founder-coach
deepvista skill sync --dry-run --throttle-min 0
deepvista skill load 11111111-1111-1111-1111-111111111111
```

## Plugin install

For auto-sync on every session:

- **Claude Code**: `/plugin install /path/to/deepvista-cli/plugins/claude-code`
- **opencode**: drop `plugins/opencode/` into `~/.config/opencode/plugins/deepvista/`
- **Cursor / Codex / other**: add `deepvista skill sync --quiet` to a cron or shell init

See [plugins/README.md](../../plugins/README.md) for full install recipes.

## Continuing a run

`skill run` returns a `run_chat_id`. To keep the conversation going:

```bash
deepvista chat +send "Add one more step to phase 2" --chat-id <run_chat_id>
```

## After a write

Show the app URL: `https://app.deepvista.ai/skills/<id>`.

## See also

- [skill-analyze-notes.md](skill-analyze-notes.md) — common Skill that searches +
  synthesizes notes
- [skill-research-to-skill.md](skill-research-to-skill.md) — pattern for running a
  Skill with curated knowledge-base context as `--input`
- [skill-import-files.md](skill-import-files.md) — bulk-import files as cards so a
  Skill can search them
