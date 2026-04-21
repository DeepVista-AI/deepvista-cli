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
| `--note-id ID` | Target specific note(s). Repeatable. Bypasses unenriched filter. |
| `--all` | Re-enrich every note up to `--limit`, not just those with a null embedding |
| `--dry-run` | Preview the request without calling the backend |

Posts to the server-side `/index_notes` route, which enqueues one chat task
per card using the same pipeline `create_context_card` uses. Use after
bulk-importing notes, after a long offline period, or when entities appear
missing from the graph. Pair with `deepvista lint --check missing-refs` to
find concepts that still need their own card.

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
