---
name: daily-planning
description: |
  Generate today's *Daily Planning YYYYMMDD* note by reading yesterday's plan
  (and progress), recent context cards from the last 7 days, and the set of
  registered `@<role>` managed-agent subagents — then reason about what
  carries over, what's new, and what each role should own today. Save the
  result as a real DeepVista note via `deepvista planning daily-note
  --content-file -`. Use when the user runs `/deepvista run` and today's
  planning note doesn't yet exist (or is still the templated stub), or when
  the user asks to "draft today's plan", "make today's standup", or
  "regenerate my daily planning note".
---

# Daily planning — generate today's plan from yesterday's context

This skill produces today's *Daily Planning* note as an LLM-reasoned plan,
not a static template. The flow:

1. Read **yesterday's** planning note + summary (if it exists).
2. Read the **last 7 days** of context cards (notes, todos, sessions).
3. List the **`@<role>` subagents** registered for this user.
4. Reason about carry-over, new tasks, and stretch goals.
5. Save the result via `deepvista planning daily-note --content-file -`.

The CLI does the data lookups; this skill is the reasoning runbook. Each
step has a single shell command and a single short output.

## Step 1 — Read yesterday's plan

```bash
YESTERDAY=$(date -v-1d +%Y%m%d 2>/dev/null || date -d 'yesterday' +%Y%m%d)
TODAY=$(date +%Y%m%d)

deepvista --format json planning today --date "$YESTERDAY" 2>/dev/null || echo '{"missing":true}'
```

Parse the result:

- `description` — yesterday's full markdown (plan + appended `## Summary`s).
- `sections` — `{ role: section_markdown }` for the assigned tasks.
- `source` — `agent` (LLM-generated) or `template` (stub only).

If `missing` is true, treat yesterday as a clean slate.

## Step 2 — Read the last 7 days of context cards

Each of these is bounded (`--limit 20`); pick whichever is informative.
Skip silently if a call fails.

```bash
deepvista --format json notes list --limit 20 --order-by updated_at --order desc
deepvista --format json card list --type todo  --limit 20 --order-by updated_at --order desc
deepvista --format json card list --type session --limit 10 --order-by updated_at --order desc
deepvista --format json card +search "progress OR blocker OR shipped OR next" --limit 10
```

For each result, keep only items updated in the last 7 days. Extract:
- title
- last-updated date
- a one-sentence read of what it implies for today

## Step 3 — List the registered `@<role>` subagents

The Claude Code plugin's generated subagents live at
`${CLAUDE_PLUGIN_ROOT}/agents/dv-*.md`. Use the filename (minus the `dv-`
prefix and `.md` suffix) as the role:

```bash
ls "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/deepvista}/agents/" 2>/dev/null \
  | grep -E '^dv-.*\.md$' \
  | sed 's/^dv-//; s/\.md$//'
```

If the list is empty, default to `marketing,engineering,gtm` — the v1
planning roles. (The user can register more via `deepvista agents register`.)

## Step 4 — Reason about today's plan

You now have:

- Yesterday's plan + appended summaries (what was assigned vs. what shipped).
- A 7-day rolling window of notes/todos/sessions (the *why* behind today).
- The list of available `@<role>` subagents (the *who* of today).

Produce markdown that:

1. **Opens with a 2-3 sentence preamble** restating the week's arc — what's
   in progress, what shipped yesterday, what's next.
2. **`## Workflow today`** — a short bulleted list of cross-cutting work the
   *main agent* will run directly (not delegated). Include `/refresh-skills`
   if subagents are stale; pull from explicit user todos; surface blockers.
3. **One `## <role>` section per registered subagent**, each with:
   - **1 must-do** — finishable today, traceable to a card or yesterday's
     summary. Reference the source card id inline (e.g. `(see card-xyz)`).
   - **0–2 stretch goals** — only if there's spare bandwidth.
   - **Blockers** — call out anything the role can't proceed without.
4. **`## Summary`** — leave empty (`_Subagent results land here after
   `/deepvista run` finishes._`). The `/deepvista run` flow fills it later.

Hard constraints:

- Total length ≤ 600 words. Brevity beats completeness for a daily plan.
- Every task must trace to a real card, note, or yesterday's summary —
  never invent work to fill a section. If a role has nothing genuinely
  ready, write `- _No queued work today — the {role} specialist is free for
  ad-hoc requests._` and move on.
- Use the section headers (`## Workflow today`, `## <role>`, `## Summary`)
  exactly — `deepvista planning today` parses them by string match.

## Step 5 — Save the plan

Pipe the markdown straight into the CLI:

```bash
cat <<'PLAN' | deepvista planning daily-note --content-file - --force
# Daily Planning $TODAY

<preamble>

## Workflow today
- …

## marketing
- …

## engineering
- …

## Summary

_Subagent results land here after `/deepvista run` finishes._
PLAN
```

`--force` is intentional: if a templated stub was created by the SessionStart
hook earlier, this overwrites it with the agent-generated plan. The note is
tagged `source:agent` automatically so the slash command knows it's the real
thing.

Confirm with the user before running the save (this is a write command).
Surface the note URL — `https://app.deepvista.ai/notes/<id>` — in the
response so they can edit any section before `/deepvista run` dispatches it.

## Quick reference

| Command | Reads | Writes |
|---|---|---|
| `planning today --date <YYYYMMDD>` | one planning note | — |
| `notes list --limit 20` | recent notes | — |
| `card list --type todo` | recent todos | — |
| `card +search "<query>"` | semantic match across cards | — |
| `planning daily-note --content-file -` | stdin markdown | new planning note (idempotent unless `--force`) |
| `planning append-summary --note-id <id>` | stdin markdown | appends to a planning note |
