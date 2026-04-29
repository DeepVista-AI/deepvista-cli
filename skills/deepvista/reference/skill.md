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
deepvista skill create-from-note <note_id> [--kind persona|workflow]... [--yes] [--dry-run]
```

Synthesizes one `persona` skill and/or one `workflow` skill from a source
note (podcast, interview, book chapter, research summary). Full guide:
[skill-create-from-note.md](skill-create-from-note.md).

### `run` — write

> [!CAUTION] Starts a new Skill run and creates a chat session. Confirm first.

```bash
deepvista skill run <skill_id> [--input "context text"]
```

Output is **NDJSON** — same format as [chat.md](chat.md). The very first event
contains the `run_chat_id` you'll need for `status` and continuation.

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
deepvista skill run <skill_id> --input "Focus on Q4 objectives"
deepvista skill status <run_chat_id>
deepvista skill discover --category persona
deepvista skill install persona-researcher
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
