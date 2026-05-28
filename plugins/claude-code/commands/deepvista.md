---
description: DeepVista controls — `run` dispatches today's planning note to subagents; no args shows help
argument-hint: "[run]"
---

DeepVista control surface. Behaviour depends on `$ARGUMENTS`:

- **No argument** (or any value other than `run`) → print the help block below.
- **`run`** → dispatch today's Daily Planning note to the role specialist
  subagents and append a summary.

---

## If `$ARGUMENTS` is empty or not `run`

Print this verbatim, then stop:

> **DeepVista — Claude Code commands**
>
> - `/deepvista run` — read today's *Daily Planning YYYYMMDD* note and dispatch
>   each `## <role>` section to the matching `@<role>` subagent
>   (`@marketing`, `@engineering`, `@gtm`, …). Subagent results are appended
>   back to the planning note under a `## Summary — <timestamp>` block.
> - `/refresh-skills` — resync the DeepVista skill catalog and agent
>   definitions immediately (bypasses the 60-minute throttle).
>
> **Tips**
>
> - No planning note yet? Run `deepvista planning daily-note` (or wait for the
>   next SessionStart hook to seed it).
> - Personalise a subagent's voice by setting `config.system_prompt = "skill:<persona-card-id>"`
>   on its managed agent and re-running `/refresh-skills`.
> - Need help with the CLI itself? `deepvista --help` or `deepvista <group> --help`.

## If `$ARGUMENTS` is `run`

Execute the daily-planning dispatch workflow.

### Step 1 — Resolve today's planning note

```bash
deepvista --format json planning today
```

If the command exits non-zero with "No planning note for …", run:

```bash
deepvista --format json planning daily-note
```

…then re-run `planning today`. Parse the JSON `note_id`, `title`, and
`sections` fields. `sections` is `{ role: section_markdown }`.

### Step 2 — Dispatch each role section to its subagent

For each `(role, section_markdown)` in `sections`, invoke the matching
subagent inline. Skip any role that has no on-disk `dv-<role>.md` definition —
the user hasn't registered a managed agent for it yet. Example body:

```
@<role>

You are dispatched from today's Daily Planning note (id: <note_id>).

Your section reads:

<section_markdown>

Complete it end-to-end. Return your deliverable in the standard subagent
output format (Frame → Deliverable → Sources → Captured).
```

Collect each subagent's full reply.

### Step 3 — Append a consolidated summary

Build a single markdown block:

```
### @marketing
<that subagent's reply>

### @engineering
<that subagent's reply>

…
```

Then write it back onto the planning note:

```bash
deepvista planning append-summary --note-id <note_id> --summary-file -
```

…passing the consolidated block on stdin.

### Step 4 — Report

Tell the user, in two lines:

- Roles dispatched (and any skipped because no matching subagent existed).
- Link / id of the updated planning note.

If any step fails, stop and surface the error — do not silently fall through.
