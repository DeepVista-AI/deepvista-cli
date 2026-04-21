# Skill — structured workflows

A Skill (formerly "recipe" / "vistabook") is a multi-step checklist the agent works
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

### `export` — read-only

```bash
deepvista skill export <skill_id> --format skill
```

Generates a portable `SKILL.md` file. Pipe the output to
`~/.agents/skills/<name>/SKILL.md` to install in another agent. Full workflow:
[skill-export-knowledge.md](skill-export-knowledge.md).

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

## Examples

```bash
deepvista skill list
deepvista skill run vb_abc123 --input "Focus on Q4 objectives"
deepvista skill status chat_xyz789
deepvista skill export vb_abc123 --format skill
deepvista skill discover --category persona
deepvista skill install persona-researcher
```

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
- [skill-export-knowledge.md](skill-export-knowledge.md) — turn a Skill into a
  portable `SKILL.md`
- [skill-import-files.md](skill-import-files.md) — bulk-import files as cards so a
  Skill can search them
