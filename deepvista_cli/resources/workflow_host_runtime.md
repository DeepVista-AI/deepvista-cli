---
name: deepvista-skill-workflow-host
type: workflow
execution: stateful
description: "Host-agent runtime contract for executing a DeepVista workflow Skill via the `deepvista` CLI. Sibling to `deepvista-skill-workflow` (DeepVista server-agent contract). Trigger when `deepvista skill run --mode host <id>` returns a run packet."
---

# Workflow Host Runtime

You (the host agent: Claude Code / OpenClaw / Cursor / …) are driving a
DeepVista workflow Skill yourself. Use your **own tools** (Bash, Edit,
Write, Read, MCPs, …) to execute each phase, and use the `deepvista` CLI
to persist phase progress and artifacts back to DeepVista.

This contract mirrors the DeepVista server agent's run-time contract
(`deepvista-skill-workflow/SKILL.md`) but every primitive is something you
already have. **Do not** call `/imagine` to delegate the whole run — that
defeats the purpose of host-mode. You may delegate a single phase via
`deepvista skill phase run-on-deepvista` when the phase's `tool_plan` is
entirely DeepVista-server-only tools.

## Run packet you just received

`deepvista skill run --mode host <skill_id>` printed a JSON header followed
by the skill's full SKILL.md body. The header contains:

- `skill_id`: the parent workflow card id you'll be mutating.
- `active_phase`: the phase you should resume from (the first
  `<accordion>` with `open="true"`, or the first phase if none).
- `phase_routes`: only present when `--mode auto` — a per-phase
  routing decision (`"host"` or `"deepvista"`) derived from each
  phase's `tool_plan`. Follow it for `--mode auto` runs; otherwise
  every phase is `"host"`.
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

### 4. Per-phase fallback to DeepVista (optional)

If a phase is entirely knowledge-base-internal (its `tool_plan` is only
`chat_cypher_search` / `read_context_card` / `exa_search` /
`upsert_context_card` / `edit_context_card` / `find_similar_cards` /
`enrich_card_entities` / `load_skill` / `run_skill`), you can delegate it
to the DeepVista server agent for one turn:

```
deepvista skill phase run-on-deepvista <skill_id> "Phase N: <title>"
```

This POSTs to `/imagine` with `"Run only Phase N"` instructions; the
server agent reads the same card, mutates the same accordion, persists
artifacts, and returns. You stay in control of every other phase.

In `--mode auto`, follow the `phase_routes` table in the run packet:
phases marked `"deepvista"` use this command; phases marked `"host"`
follow steps 1–3.

### 5. Graceful exit when you can't continue

If the current phase requires a tool you don't have (the user is offline,
an MCP is unavailable, credentials are missing, …):

1. Save whatever partial output you produced as a note card via
   `deepvista notes create` so DeepVista keeps the artifact.
2. Run:
   ```
   deepvista skill phase pause <skill_id> --reason "<one short sentence>"
   ```
   This **keeps the run lock held** (`status` stays `in_progress`),
   prints the reason for the user, and exits non-zero.
3. Tell the user in plain language what's missing and how to resume
   (e.g. "Reconnect Gmail MCP and re-run `deepvista skill run` to
   continue Phase 3"). Do not pretend the phase succeeded.

When the blocker clears, the user re-runs `deepvista skill run --mode
host <skill_id>`. The CLI re-emits the packet pointing at the same active
phase and you resume from step 2.

### 6. Finalize

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
| Pause (lock held) | `deepvista skill phase pause <skill_id> --reason "…"` |
| Resume from pause | re-run `deepvista skill run --mode host <skill_id>` |
| One-phase fallback to DeepVista | `deepvista skill phase run-on-deepvista <skill_id> "Phase N: …"` |
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
- Don't call `/imagine` directly. The only allowed route to the server
  agent is `deepvista skill phase run-on-deepvista` (per-phase) or
  `deepvista skill run --mode deepvista` (whole run).
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
