---
description: DeepVista controls — `run` generates + dispatches today's planning note via the daily-planning skill; no args shows help
argument-hint: "[run]"
---

DeepVista control surface. Behaviour depends on `$ARGUMENTS`:

- **No argument** (or any value other than `run`) → print the help block below.
- **`run`** → generate today's *Daily Planning* note via the `daily-planning`
  skill (if one doesn't already exist or is still a templated stub), dispatch
  each `## <role>` section to its matching `@<role>` subagent, and append a
  consolidated summary back onto the note.

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
> - Personalise a subagent's voice by setting `config.system_prompt = "skill:<persona-card-id>"`
>   on its managed agent and re-running `/refresh-skills`.
> - Need help with the CLI itself? `deepvista --help` or `deepvista <group> --help`.

## If `$ARGUMENTS` is `run`

Execute the daily-planning dispatch workflow.

### Step 1 — Make sure today's plan exists and is agent-generated

```bash
deepvista --format json planning today
```

Three cases to handle:

- **Exit non-zero / "No planning note for …"** → today's note doesn't exist.
  **Load the `daily-planning` skill and follow it end-to-end** to produce
  today's plan. The skill ends with a `deepvista planning daily-note
  --content-file - --force` call that saves the result. Then re-run
  `planning today` to pick up the saved note.

- **Exit zero, `"source": "template"`** → a stub exists (e.g. from a manual
  `deepvista planning daily-note` call). Tell the user the current plan is
  still a stub and ask whether to regenerate via the `daily-planning` skill.
  If they confirm, load the skill, follow it (it will `--force`-overwrite
  the stub), then re-run `planning today`.

- **Exit zero, `"source": "agent"`** → an agent-generated plan already
  exists. Proceed to Step 2 without changes.

Parse the final JSON for `note_id`, `title`, and `sections`. `sections`
is `{ role: section_markdown }` with reserved sections filtered out.

### Step 2 — Dispatch each role section to its subagent

For each `(role, section_markdown)` in `sections`, invoke the matching
subagent inline. Skip any role that has no on-disk `dv-<role>.md`
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

- Whether the plan was generated this run (and via which skill), or pulled
  from an existing agent-generated note.
- Roles dispatched (and any skipped because no matching subagent existed),
  plus the planning note URL.

If any step fails, stop and surface the error — do not silently fall through.
