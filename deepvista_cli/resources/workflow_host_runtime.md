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

`deepvista skill run <skill_id>` printed a JSON header followed
by the skill's full SKILL.md body. The header contains:

- `skill_id`: the parent workflow card id you'll be mutating.
- `active_phase`: the phase you should resume from (the first
  `<accordion>` with `open="true"`, or the first phase if none).
- `user_input`: optional context the user passed via `--input`.

The body that follows the header is the same SKILL.md the DeepVista server
agent would read. The accordion / mermaid invariants from
`deepvista-skill-workflow` apply identically; only the *runner* changes.

## Run workflow (follow strictly)

### 1. Take ownership of the active phase

```
deepvista skill phase open <skill_id> "Phase N: <title>"
```

This flips the target accordion to `open="true" checked="false"`, marks
its mermaid node `:::dvActive`, and drops `open="true"` from every other
accordion. Idempotent — safe to re-run on resume.

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
deepvista notes create --title "..." --content "..." [--tags '["..."]']
# OR for non-note types:
deepvista card create --type note --title "..." --content "..." [--tags '["..."]']
```

Capture the returned card id — you'll attach it to the phase in step 3.

### 3. Advance the phase

When the phase's `done_when` criteria are met:

```
deepvista skill phase done <skill_id> "Phase N: <title>" \
    [--artifact-card-id <id>]... \
    [--next-phase "Phase N+1: <title>"]
```

This flips the accordion to `checked="true"` (drops `open="true"`), marks
its mermaid node `:::dvDone`, and embeds a `<contextCardBlock>` for each
artifact card you produced under the accordion body. If `--next-phase` is
given, it also runs the equivalent of step 1 on that phase. Otherwise the
next phase is left pending and you should call `phase open` explicitly
before starting it.

### 4. Graceful exit when you can't continue

Two distinct cases:

**User input required** — the phase needs information, a decision, or
approval from the user before it can proceed:

1. Save whatever partial output you produced as a note card via
   `deepvista notes create` so DeepVista keeps the artifact.
2. Run:
   ```
   deepvista skill phase need-input <skill_id> "<Phase N: title>" \
       --reason "<one short sentence describing what's needed>"
   ```
   This sets the mermaid node to `:::dvNeedIntervention`, **keeps the
   run lock held** (`status` stays `in_progress`), and exits non-zero.
3. Tell the user in plain language what you need and how to resume
   once they've provided it (e.g. "Please confirm the target audience
   and re-run `deepvista skill run` to continue Phase 2").

**Technical blocker** — a tool, MCP, or credential is unavailable:

1. Save whatever partial output you produced as a note card via
   `deepvista notes create` so DeepVista keeps the artifact.
2. Run:
   ```
   deepvista skill phase pause <skill_id> --reason "<one short sentence>"
   ```
   This also sets the active phase's mermaid node to `:::dvNeedIntervention`,
   **keeps the run lock held** (`status` stays `in_progress`), and exits non-zero.
3. Tell the user in plain language what's missing and how to resume
   (e.g. "Reconnect Gmail MCP and re-run `deepvista skill run` to
   continue Phase 3"). Do not pretend the phase succeeded.

When the blocker clears, the user re-runs `deepvista skill run
<skill_id>`. The CLI re-emits the packet pointing at the same active
phase and you resume from step 2.

### 5. Finalize

When the last phase is done:

```
deepvista skill complete <skill_id> --review "<3–6 retrospective bullets>"
```

This appends a `## Review` section to the description with the bullets you
pass, sets `status="completed"` (releasing the run lock so the skill can
be run again), and emits `<json>{"done": true}</json>`.

## Tools cheat sheet

| What you want | Host command |
| --- | --- |
| Open a phase | `deepvista skill phase open <skill_id> "Phase N: …"` |
| Mark a phase done | `deepvista skill phase done <skill_id> "Phase N: …" [--artifact-card-id ID]…` |
| Reset phase to pending | `deepvista skill phase reset <skill_id> "Phase N: …"` |
| Needs user input (:::dvNeedIntervention) | `deepvista skill phase need-input <skill_id> "Phase N: …" --reason "…"` |
| Pause — technical blocker (:::dvNeedIntervention, lock held) | `deepvista skill phase pause <skill_id> --reason "…"` |
| Resume from pause / need-input | re-run `deepvista skill run <skill_id>` |
| Finalize the run | `deepvista skill complete <skill_id> --review "…"` |
| Save an artifact (note) | `deepvista notes create --title "…" --content "…"` |
| Search the knowledge base | `deepvista card +search "…"` |
| Inspect current state | `deepvista skill get <skill_id>` |

## Rules

- **One** `phase open` ⇒ **one** `phase done` per phase. Don't open
  Phase N+1 before closing Phase N (the CLI tolerates it but the
  workflow card will show inconsistent state).
- Don't write the SKILL.md body to disk. Don't paste it back in chat.
  All mutation happens through the CLI shims so the server-side schema
  stays canonical.
- Don't call `/imagine` directly — all mutation happens through the CLI
  shims.
- Respect the run lock. If `skill phase pause` was the last write, treat
  the skill as still in progress on the next session.

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
<json>{"done": false, "paused": true, "reason": "<your reason>"}</json>
```
