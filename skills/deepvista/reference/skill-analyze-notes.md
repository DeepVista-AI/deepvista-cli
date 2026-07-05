# Analyze notes — surface themes, patterns, open questions

Not a separate Skill — a pattern for using `card +search`, `card list`, and
`card create` together to synthesize findings from many notes.

Use when the user says: "analyze my notes", "summarize my notes", "what have I been
thinking about", "find patterns", "what are common topics", "review my notes".

## Workflow

1. **Search** for relevant notes (read-only):
   ```bash
   deepvista card +search "<topic>" --type note --limit 20
   ```
   Fall back to a broad list if the topic is unclear:
   ```bash
   deepvista card list --type note --limit 20
   ```

2. **Read** the full content of the top candidates (read-only):
   ```bash
   deepvista card get <note_id>
   ```

3. **Analyze** in your own reasoning — identify themes, decisions, open questions, a
   rough timeline, and contradictions. Keep this step in-context; no CLI call needed.

4. **Present** the synthesis to the user first. Don't save by default.

5. **Optionally save** as a new note — confirm with the user first.

   > [!CAUTION] Write operation.
   ```bash
   deepvista card create --type note \
     --title "Analysis — <topic> — 2026-04-20" \
     --content-file /tmp/analysis.md
   ```

## Tips

- For deep analyses across many notes, paste each note body into a `chat +send`
  conversation and ask the agent to synthesize — the agent has access to tools you
  don't (e.g. semantic clustering).
- Prefer `card +search` (hybrid vector + keyword) over `+grep` unless the user wants
  exact text matches.
- Filter by `--type note` to avoid dredging up person / topic / file cards.

## Examples

```bash
# Narrow search
deepvista card +search "project alpha" --type note --limit 15

# Read a candidate
deepvista card get note_abc123

# Save the synthesis
deepvista card create --type note \
  --title "Weekly Themes — 2026-04-20" \
  --content-file /tmp/themes.md \
  --tags '["analysis","weekly"]'
```

## See also

- [notes.md](notes.md) — CRUD on notes
- [vistabase-card.md](vistabase-card.md) — the underlying `card +search` command
