---
name: deepvista-skill-workflow-host
type: workflow
execution: stateful
description: "Host-agent runtime contract for executing a DeepVista workflow Skill via the `deepvista` CLI. Sibling to `deepvista-skill-workflow` (DeepVista server-agent contract). Trigger when `deepvista skill run <id>` returns a run packet."
---

# Workflow Host Runtime

You (the host agent: Claude Code / OpenClaw / Cursor / …) are driving a
DeepVista workflow Skill yourself. Use your **own tools** (Bash, Edit,
Write, Read, MCPs, …) to execute each phase, and use the `deepvista` CLI
to persist phase progress and artifacts back to DeepVista.

This contract mirrors the DeepVista server agent's run-time contract
(`deepvista-skill-workflow/SKILL.md`) but every primitive is something you
already have. **Do not** call `/imagine` to delegate the run — you drive
every phase yourself.

## Run packet you just received

`deepvista skill run <skill_id>` opened a **run** — a `run_log` card that
records this execution — and printed a JSON header followed by the skill's
full SKILL.md body. The header contains:

- `skill_id`: the workflow card id. It is the **definition** every run of
  this workflow shares — read it, never edit it.
- `run_id`: this run. **Pass `--run-id <run_id>` to every `deepvista skill
  phase …` and `deepvista skill complete` call below.** That is what records
  your progress on the run card (and moves the run's dot on the workflow
  diagram). Without it the CLI falls back to writing the workflow card itself,
  which corrupts the definition for every other run.
- `active_phase`: the phase you should start (or resume) from.
- `resume_with`: the exact command that resumes this run after a pause.
- `user_input`: optional context the user passed via `--input`.

The body that follows the header is the same SKILL.md the DeepVista server
agent would read. The accordion / mermaid invariants from
`deepvista-skill-workflow` apply identically; only the *runner* changes.

## Run workflow (follow strictly)

### 1. Take ownership of the active phase

```
deepvista skill phase open <skill_id> "Phase N: <title>" --run-id <run_id>
```

This moves the run onto that phase. Idempotent — safe to re-run on resume.

### 2. Execute the phase using your own tools

Work through the accordion's numbered steps with your native tools:
- Files / code / commands: Bash, Read, Edit, Write, Grep.
- External services: your installed MCPs (Gmail, Slack, calendar,
  LinkedIn schedulers, …).
- Knowledge base reads: `deepvista card +search` / `deepvista vistabase`
  / `deepvista notes list` are CLI equivalents of the server agent's
  search tools.

Whenever the user supplies meaningful information (decisions, drafts,
links, outputs), persist it as a context card so DeepVista keeps the
artifact:

```
deepvista card create --type artifact --title "..." --content "..." [--tags '["..."]']
```

> [!IMPORTANT] Use `--type artifact`, not `--type note` (DV-1911). A workflow
> run is machine-dispatched, so anything it writes is agent-generated output.
> `type=note` is reserved for content the user *explicitly asked* to record.
> Other `--type` values (`todo`, `keypoint`, `person`, …) are fine when they
> fit the content better.

Capture the returned card id — you'll attach it to the phase in step 3.

To leave a progress note on the run mid-phase:

```
deepvista skill phase note <skill_id> "Phase N: <title>" "<short note>" --run-id <run_id>
```

### 3. Advance the phase

When the phase's `done_when` criteria are met:

```
deepvista skill phase done <skill_id> "Phase N: <title>" --run-id <run_id> \
    [--artifact-card-id <id>]... \
    [--next-phase "Phase N+1: <title>"]
```

This records the phase as finished on the run, copies each artifact card
into the run's log and links it to the workflow. With `--next-phase` the run
moves straight onto that phase (the equivalent of step 1). Without it, the
run lands on Output — so only omit `--next-phase` after the last phase.

### 4. Graceful exit when you can't continue

Two distinct cases:

**User input required** — the phase needs information, a decision, or
approval from the user before it can proceed:

1. Save whatever partial output you produced as an artifact card via
   `deepvista card create --type artifact` so DeepVista keeps the artifact.
2. Run:
   ```
   deepvista skill phase need-input <skill_id> "<Phase N: title>" --run-id <run_id> \
       --reason "<one short sentence describing what's needed>"
   ```
   This marks the run as waiting on a person at that phase (it stays open)
   and exits non-zero.
3. Tell the user in plain language what you need and how to resume
   once they've provided it — the packet's `resume_with` command
   (`deepvista skill run <skill_id> --run-id <run_id>`).

**Technical blocker** — a tool, MCP, or credential is unavailable:

1. Save whatever partial output you produced as an artifact card via
   `deepvista card create --type artifact` so DeepVista keeps the artifact.
2. Run:
   ```
   deepvista skill phase pause <skill_id> --run-id <run_id> --reason "<one short sentence>"
   ```
   This also marks the run as waiting where it stands (it stays open) and
   exits non-zero.
3. Tell the user in plain language what's missing and how to resume
   (e.g. "Reconnect Gmail MCP and re-run `deepvista skill run <skill_id>
   --run-id <run_id>` to continue Phase 3"). Do not pretend the phase
   succeeded.

When the blocker clears, the user runs the `resume_with` command. The CLI
re-emits the packet for the **same run**, pointing at the phase it stopped
on, and you resume from step 1. A plain `deepvista skill run <skill_id>`
(without `--run-id`) starts a new, separate run instead.

If the run cannot be finished at all, close it as failed rather than leaving
it open:

```
deepvista skill complete <skill_id> --run-id <run_id> --outcome error --review "<what went wrong>"
```

### 5. Finalize

When the last phase is done:

```
deepvista skill complete <skill_id> --run-id <run_id> --review "<3–6 retrospective bullets>"
```

This closes the run as done, records the bullets in the run's log, and
emits `{"done": true}`. The workflow card is not touched, so the skill can
be run again (even in parallel) at any time.

## Tools cheat sheet

Every command below takes `--run-id <run_id>` (or reads `$DEEPVISTA_RUN_ID`).

| What you want | Host command |
| --- | --- |
| Open a phase | `deepvista skill phase open <skill_id> "Phase N: …" --run-id <run_id>` |
| Mark a phase done | `deepvista skill phase done <skill_id> "Phase N: …" --run-id <run_id> [--artifact-card-id ID]… [--next-phase "…"]` |
| Note progress on the run | `deepvista skill phase note <skill_id> "Phase N: …" "…" --run-id <run_id>` |
| Needs user input | `deepvista skill phase need-input <skill_id> "Phase N: …" --run-id <run_id> --reason "…"` |
| Pause — technical blocker | `deepvista skill phase pause <skill_id> --run-id <run_id> --reason "…"` |
| Resume from pause / need-input | `deepvista skill run <skill_id> --run-id <run_id>` |
| Finalize the run | `deepvista skill complete <skill_id> --run-id <run_id> --review "…"` |
| Close a run that can't finish | `deepvista skill complete <skill_id> --run-id <run_id> --outcome error --review "…"` |
| Save an artifact | `deepvista card create --type artifact --title "…" --content "…"` |
| Search the knowledge base | `deepvista card +search "…"` |
| Inspect the workflow definition | `deepvista skill get <skill_id>` |

## Rules

- **Always pass `--run-id`.** Never edit the workflow card during a run —
  no `deepvista card update` / `card edit` on `<skill_id>`, no `phase reset`.
  Its body is the definition every run shares; a run's state lives on its
  run card only.
- **One** `phase open` ⇒ **one** `phase done` per phase. Don't open
  Phase N+1 before closing Phase N — use `phase done … --next-phase`.
- Don't write the SKILL.md body to disk. Don't paste it back in chat.
  All progress goes through the CLI shims so the server-side record
  stays canonical.
- Don't call `/imagine` directly — all progress goes through the CLI
  shims.
- A paused run stays open. Resume it with its `run_id`; don't start a
  second run for the same work.

## Output format

When you finish the run, emit:

```
<contextCardBlock id="<skill_id>" cardType="skill" view="compact">
<Title Case Display Name>
<one-sentence description>
</contextCardBlock>

<json>{"done": true}</json>
```

When you pause:

```
<json>{"done": false, "paused": true, "run_id": "<run_id>", "reason": "<your reason>"}</json>
```
