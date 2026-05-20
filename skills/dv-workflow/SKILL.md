---
license: Apache-2.0
name: dv-workflow
description: |
  Create and track a DeepVista workflow execution card for the current Claude Code session.
  When invoked, plans the session as named nodes, creates a skill_run card in the user's
  vistabase, updates each node's status and output as work progresses, and writes a final
  summary when the session ends.
metadata:
  type: workflow
  execution: stateful
---

# /dv-workflow — Session Workflow Tracker

Turns the current Claude Code session into a tracked workflow. Captures the goal,
breaks it into nodes, records each node's status and output as you work, and writes
a final summary — all stored as a `skill_run` card in the user's DeepVista vistabase.

---

## Phase 1 — Initialize

### Step 1: Capture the goal

If the user typed `/dv-workflow <goal>`, use that text as the goal.
Otherwise ask: _"What should this session accomplish? (One sentence.)"_

### Step 2: Check for an existing session

```bash
cat ~/.config/deepvista/current-workflow-session.json 2>/dev/null
```

If the file exists, ask the user:
- **Continue** the existing workflow (skip to Phase 2, resume from the last node)
- **Finalize** the old one first (run Phase 3 for it, then start fresh)
- **Discard** and start fresh (delete the session file)

### Step 3: Plan nodes

Break the goal into 3–7 sequential, discrete nodes — the major steps you will take.
Good node names are verb phrases: "Understand the codebase", "Implement the feature",
"Write tests", "Open PR". Confirm the plan with the user before proceeding.

### Step 4: Create the workflow card

Write the initial card body to a temp file:

```bash
cat > /tmp/dv-workflow-init.md << 'CARD'
**Goal:** <goal>
**Status:** running
**Started:** <UTC ISO timestamp>

## Nodes

| # | Node | Status | Output |
|---|------|--------|--------|
| 1 | <node 1> | pending |  |
| 2 | <node 2> | pending |  |
...

## Summary

_In progress._
CARD
```

Create the card (confirm before running — write operation):

```bash
deepvista card create --type skill_run \
  --title "<goal>" \
  --content-file /tmp/dv-workflow-init.md
```

Extract the `id` field from the JSON response. Call it `CARD_ID`.

### Step 5: Write the session state file

```bash
python3 - << 'PY'
import json, pathlib, datetime
p = pathlib.Path.home() / ".config/deepvista/current-workflow-session.json"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
  "card_id": "CARD_ID",
  "goal": "GOAL",
  "started_at": datetime.datetime.utcnow().isoformat() + "Z",
}, indent=2))
PY
```

Show the card URL: `https://app.deepvista.ai/vistabase/<CARD_ID>`

---

## Phase 2 — Track each node

Keep the full card body in memory throughout the session. After each meaningful
step, update it and push the change.

### Node lifecycle

```
pending  →  running  →  done
                    ↘  failed
```

- Mark a node **running** when you start working on it.
- Mark it **done** with a one-line output summary when it completes.
- Mark it **failed** with the reason if it cannot be completed.

### Pushing an update

After any status change, write the current card body to a temp file and call:

```bash
deepvista card update <CARD_ID> \
  --content-file /tmp/dv-workflow-<CARD_ID>.md
```

> **Update cadence:** after each node transitions state, not after every individual
> tool call. A node that takes ten tool calls gets one update when it finishes.

### Adding unplanned nodes

If the scope expands, append new rows with `pending` status in the next card update.
Do not back-date completed work as a new node.

---

## Phase 3 — Finalize

When the session goal is achieved, or the user explicitly ends the session:

### Step 1: Write the final card body

Set the top-level `**Status:**` to `done` (or `failed`).
Write a 2–4 sentence `## Summary` covering:
- What was accomplished
- Key outputs or artifacts produced
- Any remaining items or known issues

### Step 2: Push the final update

```bash
deepvista card update <CARD_ID> \
  --content-file /tmp/dv-workflow-<CARD_ID>.md
```

### Step 3: Clean up

```bash
rm -f ~/.config/deepvista/current-workflow-session.json
rm -f /tmp/dv-workflow-*.md
```

Show the final card: `https://app.deepvista.ai/vistabase/<CARD_ID>`

---

## Stop hook — live heartbeat after each turn (optional)

Add this entry under `hooks.Stop` in `~/.claude/settings.json` so the session
file stays fresh even between explicit node updates:

```json
{
  "type": "command",
  "command": "python3 -c \"import json,pathlib,datetime; p=pathlib.Path.home()/'.config/deepvista/current-workflow-session.json'; d=json.loads(p.read_text()) if p.exists() else None; d and p.write_text(json.dumps({**d,'last_active':datetime.datetime.utcnow().isoformat()+'Z'},indent=2))\" 2>/dev/null || true"
}
```

The hook updates `last_active` in the session file after every turn. It exits
silently when no session is active — safe to leave permanently.

To install via DeepVista's hook manager instead:

```bash
deepvista agents register --type claude-code
```

---

## Conventions

| Rule | Detail |
|------|--------|
| One active workflow per session | If a session file already exists on `/dv-workflow`, ask the user what to do (continue / finalize / discard). |
| Confirm before card create | Show the node plan and get approval before calling `deepvista card create`. |
| Full-body updates only | Use `deepvista card update --content-file` (not `card edit`) to push state — avoids exact-string fragility. |
| Temp file naming | Use `/tmp/dv-workflow-<CARD_ID>.md` so multiple sessions on the same machine don't collide. |
| Don't update every tool call | Update after node transitions only — avoids API noise. |
