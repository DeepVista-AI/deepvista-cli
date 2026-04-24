# Notes — quick capture and CRUD

Notes are shorthand for knowledge cards with `type=note`. Everything here is
equivalent to the matching `deepvista card --type note ...` call.

Global flags and authentication: see [shared.md](shared.md).

## Commands

### `list` — read-only

```bash
deepvista notes list [--limit N] [--page N]
```

Returns titles, ids, and update timestamps. Default page size is 20.

### `get` — read-only

```bash
deepvista notes get <note_id>
```

Returns the full note including the markdown body. Use this before editing.

### `create` — write

> [!CAUTION] Creates a note. Confirm with the user first.

```bash
deepvista notes create --title "Title" [--content "..."] [--content-file PATH] [--tags '["t1","t2"]']
```

| Flag | When |
|---|---|
| `--title` | required |
| `--content` | short inline content only — ≤200 chars, no newlines |
| `--content-file PATH` | **preferred** for anything bigger. Use an absolute path. `--content-file -` reads from stdin. |
| `--tags` | JSON array of strings |
| `--dry-run` | preview without writing |

**Always use `--content-file` for large content, files, or URLs.** Never paraphrase —
the file contents are stored verbatim.

### `update` — write

> [!CAUTION] Modifies an existing note. Confirm first.

```bash
deepvista notes update <note_id> [--title "..."] [--content "..."] [--content-file PATH] [--tags '["t1"]']
```

Same content rules as `create`. Only provided fields are changed.

### `delete` — destructive

> [!CAUTION] Destructive. Confirm first.

```bash
deepvista notes delete <note_id>
```

### `index` — write

> [!CAUTION] Queues the DeepVista agent to run entity extraction + graph
> linking + embedding refresh on unprocessed notes. Confirm first.

```bash
deepvista notes index [--limit N] [--note-id ID]... [--all] [--dry-run]
```

| Flag | When |
|---|---|
| `--limit N` | Max notes to process (default 50, max 500, newest first) |
| `--note-id ID` | Target specific note(s). Repeatable. Implies re-enrichment — the unenriched filter is dropped for explicit IDs, and `--all` is redundant. |
| `--all` | Re-enrich every note up to `--limit`, not just those with a null embedding. Ignored when `--note-id` is set. |
| `--dry-run` | Preview the request without calling the backend |

Posts to the server-side `/index_notes` route, which enqueues one chat task
per card using the same pipeline `create_context_card` uses. Use after
bulk-importing notes, after a long offline period, or when entities appear
missing from the graph. Pair with `deepvista lint --check missing-refs` to
find concepts that still need their own card.

### `session-init` — write

> [!CAUTION] Creates a rolling note on first call per `session-id`. Meant
> for agent SessionStart hooks; confirm before running by hand.

```bash
deepvista notes session-init \
  --session-id <id> \
  --transcript <path> \
  --cwd <dir> \
  [--agent claude-code] [--agent-version X.Y.Z] [--dry-run]
```

Idempotent. Looks up an existing session note by `cc-session:<id>` tag; if
none, creates one with seeded frontmatter (agent, project_dir, git branch/commit,
started_at, status=active). Caches the resolved `note_id` at
`$XDG_STATE_HOME/deepvista/sessions/<session-id>.json` so every subsequent
`session-tick` is a single HTTP call.

### `session-tick` — write

> [!CAUTION] Appends a new turn block and bumps the note's version.

```bash
deepvista notes session-tick \
  --session-id <id> \
  --transcript <path> \
  [--dry-run]
```

Parses the transcript JSONL, extracts turns newer than `last_turn_index`
from the cache, renders a heuristic summary per turn (first ~400 chars of
user/assistant + tool counts + files touched), prepends it inside
`## Turns`, and updates `turn_count` / `version` / `updated_at` in the
frontmatter. Body capped at ~50 KB — oldest turns are dropped first.

### `session-finalize` — write

> [!CAUTION] Flips status to `complete` and queues enrichment.

```bash
deepvista notes session-finalize \
  --session-id <id> \
  [--transcript <path>] \
  [--no-enrich] [--dry-run]
```

Marks the frontmatter `status: complete` and calls `/index_notes` on the
session note. Pass `--transcript` to flush any remaining turns first.

### `history` — read-only

```bash
deepvista notes history <note_id> [--limit N]
```

List prior versions of a note (newest first). Returns `version`, `reason`,
`changed_by`, `created_at`. Backed by `/get_context_card_history`.

### `diff` — read-only

```bash
deepvista notes diff <note_id> <from_version> <to_version>
```

Unified diff between two versions of a note. In `--format table` mode the
diff is printed directly; in `--format json` it is returned under `.diff`.

### `restore` — write (reversible)

> [!CAUTION] Rolls the note back. Current state is captured as a new
> version first so restore itself is reversible.

```bash
deepvista notes restore <note_id> <version> [--yes] [--dry-run]
```

Backed by `/restore_context_card_version`. The server's UPDATE trigger
captures the pre-restore state, so you can always `restore` again to the
prior `version`.

### Hook installation (Claude Code)

Install the DeepVista Claude Code plugin — it registers all three hooks
(`SessionStart`, `Stop`, `SessionEnd`) automatically:

```
/plugin marketplace add DeepVista-AI/deepvista-cli
/plugin install deepvista@deepvista-ai
```

The plugin ships the canonical scripts at
`${CLAUDE_PLUGIN_ROOT}/hooks/deepvista-session-{start,turn,end}.sh`.

Manual install (non-plugin users): copy the scripts from
`plugins/claude-code/hooks/` in the repo into `~/.claude/hooks/` and
reference them in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "$HOME/.claude/hooks/deepvista-session-start.sh" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "$HOME/.claude/hooks/deepvista-session-turn.sh" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "$HOME/.claude/hooks/deepvista-session-end.sh" }] }
    ]
  }
}
```

Every script is non-blocking (`&` background) so Claude Code latency is
unaffected. Scripts silently no-op if `deepvista` is not on `PATH` or
auth is missing.

### `+quick` — write

> [!CAUTION] Writes a new note. Confirm first (or skip confirmation if the agent is
> running as an auto-capture hook — see [openclaw.md](openclaw.md)).

```bash
deepvista notes +quick "your text here"
```

Single-line quick capture. First ~50 characters of the text become the title; the full
text is saved as the body.

## Examples

```bash
# List recent
deepvista notes list --limit 5

# Structured note
deepvista notes create \
  --title "Standup 2026-04-20" \
  --content-file /tmp/standup-notes.md \
  --tags '["standup","team"]'

# Quick capture
deepvista notes +quick "Alice mentioned the API migration deadline is April 15"

# Read-then-edit
deepvista notes get note_abc123
deepvista notes update note_abc123 --title "Standup — April 20"

# From stdin
curl -s https://example.com/page.md | \
  deepvista notes create --title "Reference page" --content-file -
```

## After a write

Show the user the app URL: `https://app.deepvista.ai/notes/<id>`.
