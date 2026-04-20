# Cards — the knowledge base

`deepvista card` is the full-featured interface to your knowledge base. Every entry
is a card; types include `person`, `organization`, `message`, `todo`, `topic`,
`keypoint`, `file`, `note`, `vistabook`, `vistabook_run`.

`deepvista notes` is a thin convenience wrapper over `card --type note`. Use
[notes.md](notes.md) for note-only ergonomics; use this for everything else.

## Commands

### `list` — read-only

```bash
deepvista card list [--type TYPE] [--status STATUS] [--limit N] [--page N] \
                    [--order-by FIELD] [--order asc|desc]
```

Filter by `--type` (e.g. `person`, `topic`, `file`) and `--status`
(`pinned`, `archived`, `normal`).

### `get` — read-only

```bash
deepvista card get <card_id>
```

Returns the full card including body, metadata, and tags.

### `create` — write

> [!CAUTION] Confirm before running.

```bash
deepvista card create --type TYPE --title "Title" \
  [--content "..." | --content-file PATH] [--tags '["t1","t2"]'] [--no-enrich]
```

`--no-enrich` disables the automatic metadata enrichment (e.g. linking known people
and organizations). Use `--content-file` for large content — same rule as notes.

### `update` — write

> [!CAUTION] Confirm before running.

```bash
deepvista card update <card_id> [--title "..."] [--content "..." | --content-file PATH] \
  [--type TYPE] [--tags '["t1"]'] [--status pinned|archived]
```

Use `--status pinned` / `--status archived` to change visibility. Only provided fields
are modified.

### `edit` — write (targeted string replace)

> [!CAUTION] Confirm before running.

```bash
deepvista card edit <card_id> --old-string "..." --new-string "..." [--replace-all]
```

Works like Claude Code's Edit tool: `--old-string` must appear exactly once in the
current body, and it is replaced with `--new-string`. Pass `--replace-all` to replace
every occurrence. Fails if `--old-string` is not found.

### `delete` — destructive

> [!CAUTION] Destructive. Confirm before running.

```bash
deepvista card delete <card_id> [--type TYPE]
```

### `+search` — read-only

```bash
deepvista card +search "query text" [--type TYPE] [--limit N]
```

Hybrid vector + keyword search. Combines semantic matching with precise keyword
recall. Prefer this over `+grep` when the user's phrasing is fuzzy.

### `+similar` — read-only

```bash
deepvista card +similar <card_id> [--limit N]
```

Pure semantic-neighbor lookup anchored on an existing card.

### `+grep` — read-only

```bash
deepvista card +grep "pattern" [--type TYPE] [-i] [--limit N] [-C N]
```

Literal / regex content matching. `-i` for case-insensitive, `-C N` for N lines of
context. Prefer this when the user wants exact text matches (`TODO`, `FIXME`, URLs).

### `+pin` / `+archive` — write

> [!CAUTION] Confirm before running.

```bash
deepvista card +pin <card_id>
deepvista card +archive <card_id>
```

Shorthand for `update --status pinned` / `update --status archived`.

## Examples

```bash
# Hybrid search
deepvista card +search "quarterly metrics"
deepvista card +search "machine learning team" --type person

# Grep with context
deepvista card +grep "TODO|FIXME" --type note -i
deepvista card +grep "API endpoint" -C 2

# Create a topic card
deepvista card create --type topic \
  --title "Machine Learning Strategy" \
  --content-file /tmp/ml-strategy.md

# Targeted fix
deepvista card edit abc123 --old-string "old API URL" --new-string "new API URL"

# Pin something
deepvista card +pin abc123
```

## After a write

Show the app URL: `https://app.deepvista.ai/vistabase?contextId=<id>`.

## See also

- [notes.md](notes.md) — convenience wrapper for `--type note`
- [vistabase.md](vistabase.md) — read-only view of implicit memory
- [skill-import-files.md](skill-import-files.md) — bulk-import files as cards
