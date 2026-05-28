---
description: DeepVista controls — `run` generates + dispatches today's planning note via the daily-planning skill; no args shows help
argument-hint: "[run]"
---

DeepVista control surface. Behaviour depends on `$ARGUMENTS`:

- **No argument** (or any value other than `run`) → print the help block below.
- **`run`** → generate today's *Daily Planning* note via the `daily-planning`
  skill (if one doesn't already exist), dispatch each `## <role>` section to
  its matching `@<role>` subagent, and append a consolidated summary back
  onto the note.

Planning notes are stored as regular DeepVista notes (`type=note`) tagged
``daily-planning`` + ``date:YYYYMMDD``. No dedicated `deepvista planning`
CLI command exists — read/write everything via `deepvista notes` and
`deepvista card +search`.

---

## If `$ARGUMENTS` is empty or not `run`

Print this verbatim, then stop:

> **DeepVista — Claude Code commands**
>
> - `/deepvista run` — generate today's *Daily Planning* note (LLM-reasoned,
>   driven by the `daily-planning` skill: yesterday's progress + last 7 days
>   of cards → per-role tasks), then dispatch each `## <role>` section to
>   the matching `@<role>` subagent. Subagent results are appended back to
>   the planning note under a `## Summary — <timestamp>` block.
> - `/refresh-skills` — resync the DeepVista skill catalog and agent
>   definitions immediately (bypasses the 60-minute throttle).
>
> **Tips**
>
> - Want to draft a plan without dispatching? Just say *"draft today's
>   planning note"* and the `daily-planning` skill kicks in.
> - Personalise a subagent's voice by setting `config.system_prompt` on its
>   managed agent (free text, e.g. *"You are the marketing specialist;
>   follow persona context card persona-mkt-001."*) and re-running
>   `/refresh-skills`. The agent loads the persona card at runtime.
> - Need help with the CLI itself? `deepvista --help` or `deepvista <group> --help`.

## If `$ARGUMENTS` is `run`

Execute the daily-planning dispatch workflow.

### Step 1 — Find today's planning note (or generate one)

```bash
TODAY=$(date +%Y%m%d)
deepvista --format json card +search "Daily Planning $TODAY" --limit 5
```

Walk the result and pick the card with both ``daily-planning`` and
``date:$TODAY`` in `tags`. Two cases:

- **No match** → today's note doesn't exist. **Load the `daily-planning`
  skill and follow it end-to-end** to produce today's plan. The skill ends
  by saving the note via `deepvista notes create`. Re-run the search above
  to pick up the new note id.

- **Match found** → fetch its full body:
  ```bash
  deepvista --format json notes get <note-id>
  ```

Parse `description` and split on `## ` headings. Treat headings that match
``Workflow today`` or ``Summary`` (case-insensitive) as reserved; everything
else is a role section keyed by its heading text (lowercased).

### Step 2 — Dispatch each role section to its subagent

For each `(role, section_markdown)` in the role sections, invoke the
matching subagent inline. Skip any role with no on-disk `dv-<role>.md`
definition — the user hasn't registered a managed agent for it yet.
Example body:

```
@<role>

You are dispatched from today's Daily Planning note (id: <note_id>).

Your section reads:

<section_markdown>

Complete it end-to-end. Return your deliverable in the standard subagent
output format (Frame → Deliverable → Sources → Captured).
```

Collect each subagent's full reply.

### Step 3 — Append a consolidated summary to the note

Build a single markdown block:

```
## Summary — <YYYY-MM-DD HH:MM>

### @marketing
<that subagent's reply>

### @engineering
<that subagent's reply>

…
```

Read the current body, append the block, write it back:

```bash
deepvista --format json notes get <note-id>
# Capture description from JSON, append the block, then:
deepvista notes update <note-id> --content-file -
# (pass `description + appended_block` on stdin)
```

### Step 4 — Report

Tell the user, in two lines:

- Whether the plan was generated this run (and via which skill), or pulled
  from an existing note.
- Roles dispatched (and any skipped because no matching subagent existed),
  plus the planning note URL (`https://app.deepvista.ai/notes/<id>`).

If any step fails, stop and surface the error — do not silently fall through.
