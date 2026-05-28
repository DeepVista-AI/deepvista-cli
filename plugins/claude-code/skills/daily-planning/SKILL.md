---
name: daily-planning
description: |
  Generate today's *Daily Planning* note by reading yesterday's plan (and its
  appended progress summary) along with recent context cards from the last 7
  days — then reason about what carries over, what's new, and what each
  registered `@<role>` managed-agent subagent should own today. Save the
  result as a regular DeepVista note tagged ``daily-planning`` +
  ``date:YYYYMMDD``. Use when the user runs `/deepvista run` and today's
  planning note doesn't yet exist, or when the user asks to "draft today's
  plan", "make today's standup", or "regenerate my daily planning note".
---

# Daily planning — generate today's plan from yesterday's context

This skill produces today's *Daily Planning* note as an LLM-reasoned plan,
not a static template. Planning notes are plain `deepvista notes` cards
(type=note) tagged ``daily-planning`` + ``date:YYYYMMDD`` — there is no
dedicated `deepvista planning` subcommand. The flow:

1. Read **yesterday's** planning note + appended summary (if it exists).
2. Read the **last 7 days** of context cards (notes, todos, sessions).
3. List the **`@<role>` subagents** registered for this user.
4. Reason about carry-over, new tasks, and blockers.
5. Save the result as a note via `deepvista notes create`.

The CLI does the data lookups; this skill is the reasoning runbook.

## Step 1 — Read yesterday's plan

Search for yesterday's planning note by tag (titles can be edited; tags
shouldn't). Hybrid search filtered to `type=note` is the most robust:

```bash
YESTERDAY=$(date -v-1d +%Y%m%d 2>/dev/null || date -d 'yesterday' +%Y%m%d)
TODAY=$(date +%Y%m%d)

deepvista --format json card +search "Daily Planning $YESTERDAY" --limit 5
# If a match is found, fetch its full body:
# deepvista --format json notes get <id>
```

Parse `description` (yesterday's full markdown — plan + any
`## Summary — <timestamp>` blocks that `/deepvista run` appended after
subagents finished). If nothing matches, treat yesterday as a clean slate.

## Step 2 — Read the last 7 days of context cards

Each call is bounded (`--limit 20`). Skip silently on failure.

```bash
deepvista --format json notes list --limit 20
deepvista --format json card list --type todo  --limit 20
deepvista --format json card list --type session --limit 10
deepvista --format json card +search "progress OR blocker OR shipped OR next" --limit 10
```

For each result, keep only items updated in the last 7 days. Extract:

- title
- last-updated date
- a one-sentence read of what it implies for today

## Step 3 — List the registered `@<role>` subagents

```bash
ls "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/deepvista}/agents/" 2>/dev/null \
  | grep -E '^dv-.*\.md$' \
  | sed 's/^dv-//; s/\.md$//'
```

If the list is empty, default to `marketing,engineering,gtm`. The user can
register more via `deepvista agents register`.

## Step 4 — Reason about today's plan

You now have:

- Yesterday's plan + appended summaries (assigned vs. shipped).
- A 7-day rolling window of notes/todos/sessions (the *why* behind today).
- The list of available `@<role>` subagents (the *who* of today).

Produce markdown that:

1. **Opens with a 2-3 sentence preamble** restating the week's arc — what's
   in progress, what shipped yesterday, what's next.
2. **`## Workflow today`** — a short bulleted list of cross-cutting work the
   *main agent* will run directly (not delegated). Include `/refresh-skills`
   if subagents are stale; surface explicit user todos; surface blockers.
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
  never invent work. If a role has nothing genuinely ready, write
  `- _No queued work today — the {role} specialist is free for ad-hoc
  requests._` and move on.
- Use the section headers (`## Workflow today`, `## <role>`, `## Summary`)
  exactly — the `/deepvista run` slash command parses them by string match.

## Step 5 — Save the plan as a DeepVista note

Pipe the markdown straight into `deepvista notes create` and tag it so
tomorrow's run finds it:

```bash
cat <<'PLAN' | deepvista notes create \
  --title "Daily Planning $TODAY" \
  --content-file - \
  --tags "[\"daily-planning\",\"date:$TODAY\",\"source:agent\"]"
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

Confirm with the user before running the save (this is a write command).
Surface the note URL — `https://app.deepvista.ai/notes/<id>` — in the
response so they can edit any section before `/deepvista run` dispatches it.

## Append a summary after `/deepvista run` finishes

The slash command appends each subagent's reply onto today's note. There is
no dedicated `append-summary` CLI — use `deepvista notes update`:

```bash
deepvista notes get <note-id>          # read current description
# build new_description = current + "\n\n## Summary — <timestamp>\n<consolidated block>\n"
deepvista notes update <note-id> --content-file -   # pipe new_description on stdin
```

## Quick reference

| Command | Reads | Writes |
|---|---|---|
| `card +search "Daily Planning <date>"` | semantic search across cards | — |
| `notes get <id>` | one note's full body | — |
| `notes list --limit 20` | recent notes | — |
| `card list --type todo` | recent todos | — |
| `notes create --title ... --content-file - --tags ...` | stdin markdown | new note |
| `notes update <id> --content-file -` | stdin markdown | replaces the note body |
