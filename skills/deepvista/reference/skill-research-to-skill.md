# Research → Run a Skill

A pattern: search the knowledge base for relevant context, synthesize the findings,
then pass them as `--input` to a Skill run so the workflow starts with curated
context instead of a blank slate.

Use when the user says: "research and run a workflow", "find context then execute a
skill", "synthesize findings and continue".

## Workflow

1. **Search** for relevant cards (read-only):
   ```bash
   deepvista card +search "<topic>" --limit 10
   ```

2. **Fetch** the full bodies of the top candidates (read-only):
   ```bash
   deepvista card get <card_id>
   ```

3. **Summarize** in your own reasoning. Keep this step in-context.

4. **Pick the right Skill** (read-only):
   ```bash
   deepvista skill list
   ```

5. **Confirm and run** — the only step that writes.

   > [!CAUTION] Write — starts a new Skill run.
   ```bash
   deepvista skill run <skill_id> --input "Based on my research: <summary>"
   ```

6. **Continue** if needed:
   ```bash
   deepvista skill status <run_chat_id>
   deepvista chat +send "Next question…" --chat-id <run_chat_id>
   ```

## Notes

- The Skill run has full knowledge-base access during execution. `--input` focuses
  the run; it doesn't restrict what the Skill can read.
- If the summary is long, write it to a file first and pass via
  `chat +send` instead — `skill run --input` expects a short framing prompt, not a
  document.

## Examples

```bash
deepvista card +search "Q4 priorities" --limit 10
deepvista card get card_abc123
deepvista skill list
deepvista skill run vb_def456 \
  --input "Based on my research: Q4 priorities are platform migration (owner: Alice), ..."
```

## See also

- [vistabase-card.md](vistabase-card.md) — `card +search` and `card get`
- [skill.md](skill.md) — `skill list`, `skill run`, `skill status`
- [chat.md](chat.md) — continuing the run
