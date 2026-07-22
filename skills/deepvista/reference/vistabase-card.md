# Cards — the knowledge base

`deepvista card` manages every knowledge base entry. Types: `person`, `organization`,
`message`, `email`, `todo`, `topic`, `keypoint`, `file`, `note`, `session`, `skill`,
`run_log`, `schedule_job`, `task`, `conversation_starter`, `artifact`.

`note` is reserved for human-authored notes; `artifact` is the agent's fallback
for its own output when no structured type fits (DV-1573).

`deepvista vistabase` is a backward-compatible alias — every `card` subcommand
works under `vistabase` too (hidden from `--help`).

Run `deepvista card --help` or `deepvista card <cmd> --help` for full flag reference.

`deepvista notes` is a thin convenience wrapper over `card --type note`.
Use [notes.md](notes.md) for note-only ergonomics.

## Commands

`list` · `get` · `create` · `update` · `edit` · `delete` · `upload`
`index` · `history` · `diff` · `restore`
`comment list|add|edit|delete`
`+search` · `+similar` · `+search-content` · `+pin` · `+archive`

## Agent conventions

> [!CAUTION] `create`, `update`, `edit`, `delete`, `index`, `restore`, `+pin`, `+archive` are writes.
> Confirm first (except `create` under OpenClaw auto-capture — see [openclaw.md](openclaw.md), DV-1484).
> Use `--dry-run` to preview.

- **Always use `--content-file <absolute-path>`** for large content — never inline.
- Show the app URL after any write: `https://app.deepvista.ai/vistabase/<id>`
- Read-only commands (`list`, `get`, `history`, `diff`, `+search`, `+similar`, `+search-content`) are safe
  to run without confirmation.

## Non-obvious gotchas

**`edit` requires an exact string match.** `--old-string` must appear exactly once in
the current body — it is replaced with `--new-string`. Fails if not found. Use
`card get` to read the current body before calling `edit`. Prefer `update
--content-file` when replacing large sections.

**`+search` vs `+search-content`:** both are hybrid vector+keyword (fuzzy, semantic) —
`+search` ranks by title/snippet/keywords, `+search-content` ranks against a card's
full body via the search_vector + embedding hybrid. Omit the query on
`+search-content` to browse cards of `--type`, most-recently-updated first (no
regex/exact-match mode exists anymore — for a boolean OR use `websearch_to_tsquery`
syntax, e.g. `"TODO OR FIXME"`).

**`upload <path>`** — the ONLY way to put an image/video/binary into DeepVista: it
uploads the file and mints a `type=file` card (`card create --content-file` reads UTF-8
text only and errors on binaries). To show the image in a note, embed the returned
`gs://…` URL with plain markdown: `![alt](gs://…)` (DV-1650).

**`index`** — queues entity extraction + embedding refresh on unprocessed cards
(`--type note` by default). Run after bulk imports or a long offline period.

**`history` / `diff` / `restore`** — version history for any card. `restore`
captures the current state as a new version first, so it's reversible.

**`comment`** — a flat, markdown comment thread on a card (DV-1308). Use comments for
enrichment / running commentary instead of editing the card body. The CLI posts as the
authenticated user (`commenter_type=human`); you can only `edit`/`delete` your own comments.
`add`/`edit` take `--content` or `--content-file`; `list <card_id>` and `edit`/`delete <comment_id>`.

## Examples

```bash
# Search
deepvista card +search "quarterly metrics"
deepvista card +search "ML team" --type person
deepvista card +search-content "TODO OR FIXME" --type note

# Create
deepvista card create --type topic \
  --title "ML Strategy" --content-file /tmp/ml-strategy.md

# Targeted patch
deepvista card edit <id> --old-string "old API URL" --new-string "new API URL"

# Pin
deepvista card +pin <id>

# Comment on a card (enrichment / running commentary — not a body edit)
deepvista card comment add <card_id> --content "Confirmed the Q3 numbers with finance."
deepvista card comment list <card_id>
deepvista card comment edit <comment_id> --content-file /tmp/updated.md
deepvista card comment delete <comment_id>
```

## See also

- [notes.md](notes.md) — `--type note` convenience wrapper
- [skill-import-files.md](skill-import-files.md) — bulk-import files as `type=file` cards
