# Notes — explicit user-authored knowledge

Notes are for content **the user explicitly asked to record** (long-form
text, "what I want to remember"). They are cards with `type=note`. For
agent-recorded incidental snippets use `deepvista card create --type …`
(see [vistabase-card.md](vistabase-card.md)); for session transcripts use
[`deepvista session`](session.md) (DV-742).

Run `deepvista notes --help` or `deepvista notes <cmd> --help` for full
flag reference.

## Commands

`list` · `get` · `create` · `update` · `delete` · `+quick`

> [!NOTE] Version history (`history` / `diff` / `restore`) and entity
> re-indexing (`index`) are generic card features — use
> `deepvista card history|diff|restore|index` (see
> [vistabase-card.md](vistabase-card.md)). They work on notes by ID.

## Agent conventions

> [!CAUTION] `create`, `update`, `delete` are writes.
> Confirm with the user first — always, with no auto-capture exception. Notes are
> human-driven: only create one when the user explicitly asks to save/write/record
> a note. Everything an agent notices on its own belongs on `deepvista card`
> instead (see [openclaw.md](openclaw.md), DV-1484).

- **Always use `--content-file <absolute-path>`** for anything more than ~200 chars or
  containing newlines. Never paste large content inline. Pass `-` to read from stdin.
- Show the app URL after any write: `https://app.deepvista.ai/notes/<id>`
- Use `--dry-run` to preview without writing.

## Non-obvious commands

**`+quick`** — single-line fast capture. First ~50 chars become the title:
```bash
deepvista notes +quick "Alice confirmed the API deadline is April 15"
```

### Hook installation (Claude Code plugin)

```
/plugin marketplace add DeepVista-AI/deepvista-cli
/plugin install deepvista@deepvista-ai
```

Manual install: copy `plugins/claude-code/hooks/` into `~/.claude/hooks/` and wire
`SessionStart`, `Stop`, and `SessionEnd` in `~/.claude/settings.json`.

## Examples

```bash
# Quick capture
deepvista notes +quick "Decided to drop legacy auth middleware — compliance req"

# Structured note from file
deepvista notes create --title "Standup 2026-04-20" \
  --content-file /tmp/standup.md --tags '["standup"]'

# Read then edit
deepvista notes get <note_id>
deepvista notes update <note_id> --title "Standup — April 20"

# From stdin
curl -sL https://example.com/page.md | \
  deepvista notes create --title "Reference page" --content-file -

# Re-index after bulk import (generic card command; notes are the default type)
deepvista card index --limit 100
```

## See also

- [vistabase-card.md](vistabase-card.md) — underlying `card --type note` commands, version history, indexing
- [openclaw.md](openclaw.md) — agent auto-capture (writes context cards, never notes)
