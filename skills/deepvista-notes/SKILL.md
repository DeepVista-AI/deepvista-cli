---
name: deepvista-notes
description: |
  DeepVista Notes: Create, read, update, and delete notes (explicit knowledge managed by the user).
  Notes are a shorthand for knowledge cards with type=note — the same as `deepvista card --type note`.
  TRIGGER when: user wants to create, capture, save, read, list, update, or delete a note; user says "take a note", "jot this down", "save this as a note", "show my notes", or asks about a specific note by title or ID.
  DO NOT TRIGGER when: user wants to analyze, summarize, or find patterns across notes (use deepvista-recipe-analyze-notes instead); or when working with non-note knowledge base cards.
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista notes --help"
---

# Notes

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Notes are context cards with `type=note`. They support rich markdown content and are the primary way to explicitly capture knowledge — meeting notes, summaries, research, decisions.

`deepvista notes` is a convenience shorthand. Every notes command has an exact equivalent using `deepvista card`:

| Notes command | Equivalent card command |
|---------------|------------------------|
| `deepvista notes list` | `deepvista card list --type note` |
| `deepvista notes get <id>` | `deepvista card get <id>` |
| `deepvista notes create ...` | `deepvista card create --type note ...` |
| `deepvista notes +quick "..."` | *(shorthand only, no direct card equivalent)* |

## App URLs

After any write operation (create, update, +quick), always show the note URL to the user:

```
https://app.deepvista.ai/notes/<id>
```

Extract the `id` from the JSON response (`card.id`) and present it as a clickable link.

## Commands

### list

```bash
deepvista notes list [--limit N] [--page N]
```

Read-only — lists all notes, newest first.

### get

```bash
deepvista notes get <note_id>
```

Read-only — returns full note content including markdown body.

### create

```bash
deepvista notes create --title "Title" [--content "Markdown content"] [--tags '["t1","t2"]']
```

> [!CAUTION] Write command — confirm with user before executing.

### update

```bash
deepvista notes update <note_id> [--title "..."] [--content "..."] [--tags '["t1"]']
```

> [!CAUTION] Write command — confirm with user before executing.

### delete

```bash
deepvista notes delete <note_id>
```

> [!CAUTION] Destructive command — confirm with user before executing.

### +quick

```bash
deepvista notes +quick "your text here"
```

Quick-create a note from a single line of text. The first ~50 characters become the title; the full text becomes the content. Entity enrichment runs automatically.

> [!CAUTION] Write command — creates a new note. Confirm with the user before executing.

- Ideal for capturing quick observations mid-workflow.
- For notes with custom titles or structured content, use `notes create` instead.
- Created notes are searchable with `deepvista card +search`.

## Examples

```bash
# List recent notes
deepvista notes list --limit 5

# Create a meeting note
deepvista notes create --title "Standup 2026-03-26" --content "## Discussed\n- Roadmap priorities\n- CLI release"

# Quick capture from a single line
deepvista notes +quick "Alice mentioned the API migration deadline is April 15"

# Update a note
deepvista notes update note_abc --content "Updated content with new findings..."

# Search notes (uses card search)
deepvista card +search "API migration" --type note
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Full knowledge base API (all card types)
- [deepvista-recipe-analyze-notes](../deepvista-recipe-analyze-notes/SKILL.md) — Analyze patterns across notes
