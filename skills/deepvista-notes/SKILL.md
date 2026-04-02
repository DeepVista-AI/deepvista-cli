---
name: deepvista-notes
description: |
  DeepVista Notes: Create, read, update, and delete notes in your knowledge base.
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

Notes are context cards with `type=note`. They support rich markdown content and are a natural fit for agents to capture meeting notes, summaries, and research.

## Commands

### list

```bash
deepvista notes list [--limit N] [--page N]
```

### get

```bash
deepvista notes get <note_id>
```

### create

```bash
deepvista notes create --title "Title" [--content "Markdown content"] [--tags '["t1"]']
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

Quick-create a note from a single line of text. The first ~50 characters become the title; the full text is the content. Entity enrichment runs automatically.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<text>` | Yes | — | Note content (title auto-derived from first sentence) |

> [!CAUTION] Write command — creates a new note. Confirm with the user before executing.

- Ideal for agents capturing quick observations during a workflow.
- For notes with custom titles, use `notes create --title "..." --content "..."` instead.
- Created notes appear in the VistaBase and can be searched with `vistabase +search`.

## Examples

```bash
# List recent notes
deepvista notes list --limit 5

# Create a meeting note
deepvista notes create --title "Standup 2026-03-26" --content "## Discussed\n- Roadmap priorities\n- CLI release"

# Quick note from a single line
deepvista notes +quick "Alice mentioned the API migration deadline is April 15"

# Update a note
deepvista notes update note_abc --content "Updated content with new findings..."
```

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Full knowledge base API
