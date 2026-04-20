# Persona — Knowledge Worker

A daily workflow pattern, not a runnable command. Apply this when the user says
"check my priorities", "what's my daily workflow", "review my cards", "find context
for today", "summarize my week", or starts their day with "what should I work on".

## Daily loop

1. **Check pinned cards** — the user's manual high-priority shortlist (read-only):
   ```bash
   deepvista --format table card list --status pinned --limit 10
   ```
   Also useful: recent activity.
   ```bash
   deepvista card list --order-by updated_at --order desc --limit 5
   ```

2. **Pull context for today's focus** (read-only):
   ```bash
   deepvista card +search "today's focus area"
   ```
   Or for specific themes: `deepvista card +search "Q4 migration" --type topic`.

3. **Capture as you go** (write — confirm before each):
   > [!CAUTION] Write.
   ```bash
   deepvista notes +quick "Key insight from standup: prioritize async migration"
   ```

4. **Run a Skill** when the task fits a template (write — confirm):
   > [!CAUTION] Write.
   ```bash
   deepvista skill list
   deepvista skill run <skill_id> --input "context for today"
   ```

5. **Ask the agent to synthesize** (write — confirm):
   > [!CAUTION] Write.
   ```bash
   deepvista chat +send "Summarize what I've captured this week and identify themes"
   ```

6. **Review implicit memory** — what has the agent learned about the user
   (read-only):
   ```bash
   deepvista vistabase show --limit 20
   ```

## Loading this persona

A user pasting "load the knowledge-worker persona" expects the agent to pull in:

- [shared.md](shared.md) — auth / flags
- [vistabase-card.md](vistabase-card.md) — pin / search / list
- [notes.md](notes.md) — quick capture
- [skill.md](skill.md) — run / list / discover
- [chat.md](chat.md) — synthesis
- [vistabase.md](vistabase.md) — "what has the agent learned"

Each reference file stands on its own, so you can read whichever the user's request
actually needs.

## See also

- [openclaw.md](openclaw.md) — automatic capture hook for OpenClaw agents
