---
name: deepvista-notes
description: |
  DeepVista Notes: Create, read, update, and delete notes (explicit knowledge managed by the user).
  Notes are a shorthand for knowledge cards with type=note — the same as `deepvista card --type note`.
  TRIGGER when: user wants to create, capture, save, read, list, update, or delete a note; user says "take a note", "jot this down", "save this as a note", "show my notes", or asks about a specific note by title or ID.
  DO NOT TRIGGER when: user wants to analyze, summarize, or find patterns across notes (use deepvista-recipe-analyze-notes instead); or when working with non-note knowledge base cards.
metadata:
  openclaw:
    category: service
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-shared
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
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
deepvista notes create --title "Title" [--content "Markdown content"] [--content-file path/to/file.md] [--tags '["t1","t2"]']
```

- Use `--content-file <path>` to read content from a local file. This is **required** when importing files, URLs, or any content longer than a few sentences. Never paste large content inline via `--content` — always write it to a temporary file first, then use `--content-file`.
- Use `--content-file -` to read from stdin (e.g. `curl ... | deepvista notes create --title "..." --content-file -`).
- `--content-file` takes precedence over `--content` when both are provided.

> [!CAUTION] Write command — confirm with user before executing.

### update

```bash
deepvista notes update <note_id> [--title "..."] [--content "..."] [--content-file path/to/file.md] [--tags '["t1"]']
```

- Use `--content-file <path>` for large content updates, same as `create`.

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

## Importing files or URLs as notes

When the user asks to import a file, URL, or any large body of text as a note, **always use `--content-file`** to preserve the full content. Never summarize, truncate, or paraphrase the content — the user expects the exact text to be stored.

### Importing a local file

```bash
deepvista notes create --title "Meeting transcript" --content-file /path/to/transcript.md
```

### Importing from a URL

1. Download the file first, then import it:

```bash
curl -sL "https://example.com/document.md" -o /tmp/document.md
deepvista notes create --title "Document title" --content-file /tmp/document.md
```

Or pipe directly via stdin:

```bash
curl -sL "https://example.com/document.md" | deepvista notes create --title "Document title" --content-file -
```

### Why `--content-file` instead of `--content`?

When an agent reads a file and tries to pass it inline via `--content "..."`, the content often gets summarized or truncated because:
- The agent's context window makes it impractical to echo large files verbatim
- Shell argument length limits may apply
- The agent may inadvertently paraphrase rather than copy

`--content-file` reads the file directly from disk, bypassing the agent's context entirely. This guarantees the **exact, complete** file content is stored.

## Examples

```bash
# List recent notes
deepvista notes list --limit 5

# Create a meeting note
deepvista notes create --title "Standup 2026-03-26" --content "## Discussed\n- Roadmap priorities\n- CLI release"

# Import a file as a note (preferred for any file or large content)
deepvista notes create --title "Architecture doc" --content-file docs/architecture.md

# Import from URL via stdin
curl -sL "https://example.com/article.md" | deepvista notes create --title "Article" --content-file -

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
