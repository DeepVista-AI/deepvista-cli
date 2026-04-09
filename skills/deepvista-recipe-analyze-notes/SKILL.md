---
name: deepvista-recipe-analyze-notes
description: |
  Recipe: Analyze, summarize, and find patterns across notes in your DeepVista knowledge base.
  TRIGGER when: user asks to analyze notes, summarize notes, find patterns or themes in notes, review notes, get insights from notes, "what have I been thinking about", "what are common topics in my notes", "synthesize my notes", or any request to make sense of multiple notes at once.
  DO NOT TRIGGER when: user wants to create, update, or delete a single note (use deepvista-notes instead); or when the request is about a specific known note by ID.
metadata:
  openclaw:
    category: recipe
    requires:
      bins:
        - deepvista
      skills:
        - deepvista-shared
        - deepvista-vistabase
        - deepvista-notes
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista card +search --help"
---

# Analyze Notes

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md), [deepvista-vistabase](../deepvista-vistabase/SKILL.md), and [deepvista-notes](../deepvista-notes/SKILL.md).

Search, retrieve, and analyze notes from the knowledge base to surface insights, patterns, and summaries.

## Steps

1. **Search for relevant notes** using a query derived from the user's request:
   ```bash
   deepvista card +search "<topic or keyword>" --type note --limit 20
   ```

2. **List recent notes** if no specific topic was given, to get a broad view:
   ```bash
   deepvista notes list --limit 20
   ```

3. **Fetch full content** for the most relevant notes (pick IDs from search/list results):
   ```bash
   deepvista notes get <note_id>
   ```
   Repeat for each note you need to read in full.

4. **Analyze and synthesize** — read the content and identify:
   - Recurring themes or topics
   - Key decisions or action items
   - Open questions or unresolved threads
   - Timeline of ideas if dates are present

5. **Present findings** to the user as a structured summary.

6. **Optionally save the analysis** back as a new note (confirm with user first):
   ```bash
   deepvista notes create --title "Analysis: <topic> — <date>" --content "<synthesis>"
   ```
   > [!CAUTION] Write command — confirm with user before saving.

## Tips

- Use `card +search` with specific keywords rather than listing everything — it uses hybrid vector+keyword search and returns the most relevant results.
- Filter by type to stay focused on notes: `deepvista card +search "<query>" --type note`.
- For time-bounded analysis ("notes from this week"), use `notes list` and filter by `created_at` in the JSON output.
- Use `chat +send` to ask the AI agent to synthesize across a large set of notes:
  ```bash
  deepvista chat +send "Here are my recent notes: <paste content>. What are the key themes?"
  ```

## Examples

```bash
# Find all notes about a project
deepvista card +search "project alpha" --type note --limit 15

# Get full content of a note
deepvista notes get note_abc123

# Save analysis as a new note
deepvista notes create \
  --title "Weekly Themes — 2026-04-02" \
  --content "## Key Themes\n- Theme 1\n- Theme 2\n\n## Open Questions\n- ..."
```

## See Also

- [deepvista-notes](../deepvista-notes/SKILL.md) — CRUD operations on individual notes
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Full knowledge base search and management
- [deepvista-recipe-research-to-recipe](../deepvista-recipe-research-to-recipe/SKILL.md) — Run a Recipe workflow with research findings
