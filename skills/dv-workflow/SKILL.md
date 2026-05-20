---
license: Apache-2.0
name: dv-workflow
description: |
  Create and track a DeepVista workflow skill for the current Claude Code session.
  On first invocation, captures the session goal as a note and synthesizes a
  workflow skill via deepvista skill create-from-note. Subsequent invocations in
  the same session reuse the existing skill. A Stop hook auto-syncs node status
  and output to the skill card after every turn — no manual update calls needed.
metadata:
  type: workflow
  execution: stateful
---

# /dv-workflow — Session Workflow Tracker

Turns the current Claude Code session into a tracked workflow skill stored in
the user's DeepVista vistabase. The goal is captured as a note, a proper workflow
skill is synthesized from it, and node status is kept in sync automatically via a
Stop hook after every agent turn.

---

## Phase 1 — Initialize

### Step 1: Check for an existing session

```bash
cat ~/.config/deepvista/current-workflow-session.json 2>/dev/null
```

If the file exists and contains a `skill_id`, **reuse the existing workflow skill** —
skip to Phase 2 (the workflow was already created this session). Ask the user:
- **Continue** from the last active node
- **Finalize** the current workflow (Phase 3), then start fresh

If no session file exists, continue to Step 2.

### Step 2: Capture the goal

If the user typed `/dv-workflow <goal>`, use that text.
Otherwise ask: _"What should this session accomplish? (One sentence.)"_

### Step 3: Plan nodes

Break the goal into 3–7 sequential, discrete nodes — the major steps you will take.
Good names are verb phrases: "Understand the codebase", "Implement the feature",
"Write tests", "Open PR". Show the plan and confirm with the user before proceeding.

### Step 4: Capture the goal as a note

```bash
deepvista notes create \
  --title "<goal>" \
  --content "Session goal: <goal>

## Planned nodes
1. <node 1>
2. <node 2>
...
"
```

Extract the note `id` as `NOTE_ID`.

### Step 5: Synthesize the workflow skill

```bash
deepvista skill create-from-note <NOTE_ID> --kind workflow --yes
```

This streams NDJSON. Wait for the final event and extract the skill card `id` as `SKILL_ID`.

### Step 6: Write the initial execution state

Write the tracking body to `/tmp/dv-workflow-<SKILL_ID>.md`:

```
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
```

Push it to the skill card:

```bash
deepvista card update <SKILL_ID> \
  --content-file /tmp/dv-workflow-<SKILL_ID>.md
```

### Step 7: Write the session state file

```bash
python3 - << 'PY'
import json, pathlib, datetime
p = pathlib.Path.home() / ".config/deepvista/current-workflow-session.json"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
  "skill_id": "SKILL_ID",
  "note_id": "NOTE_ID",
  "goal": "GOAL",
  "started_at": datetime.datetime.utcnow().isoformat() + "Z",
}, indent=2))
PY
```

### Step 8: Install the Stop hook (once per machine)

Check if the Stop hook is already present in `~/.claude/settings.json`. If not, add it:

```bash
deepvista agents register --type claude-code
```

This installs a Stop hook that syncs the workflow card after every turn (see below).
If `deepvista agents register` is unavailable, add the hook manually — see the
**Stop hook** section at the bottom of this skill.

Show: `https://app.deepvista.ai/vistabase/<SKILL_ID>`

---

## Phase 2 — Track each node

Maintain the full tracking body in `/tmp/dv-workflow-<SKILL_ID>.md` in memory.
The Stop hook syncs this file to DeepVista automatically after each turn —
**you do not need to call `deepvista card update` explicitly**.

Just keep the temp file current:

### Node lifecycle

```
pending  →  running  →  done
                    ↘  failed
```

- Mark a node **running** when you begin it.
- Mark it **done** with a one-line output summary when it completes.
- Mark it **failed** with the reason if it cannot complete.

### After each node transition — write the updated temp file

```bash
cat > /tmp/dv-workflow-<SKILL_ID>.md << 'STATE'
**Goal:** <goal>
**Status:** running
...updated table...
STATE
```

The Stop hook will pick it up and push it to DeepVista at the end of the turn.

### Adding unplanned nodes

Append new rows with `pending` status. Do not back-date completed work.

---

## Phase 3 — Finalize

When the session goal is achieved or the user ends the session:

### Step 1: Write the final state

Set `**Status:**` to `done` (or `failed`). Write a 2–4 sentence `## Summary`:
- What was accomplished
- Key outputs or artifacts produced
- Any remaining items or known issues

Write to `/tmp/dv-workflow-<SKILL_ID>.md` — the Stop hook will push it.
Or push immediately:

```bash
deepvista card update <SKILL_ID> \
  --content-file /tmp/dv-workflow-<SKILL_ID>.md
```

### Step 2: Clean up

```bash
rm -f ~/.config/deepvista/current-workflow-session.json
rm -f /tmp/dv-workflow-*.md
```

Show: `https://app.deepvista.ai/vistabase/<SKILL_ID>`

---

## Stop hook — auto-sync after every turn

The Stop hook reads the session file, updates `last_active`, and pushes the current
temp file to the skill card. Install once via `deepvista agents register --type claude-code`.

To add manually, put this under `hooks.Stop` in `~/.claude/settings.json`:

```json
{
  "type": "command",
  "command": "python3 -c \"\nimport json, pathlib, subprocess, datetime, sys\np = pathlib.Path.home() / '.config/deepvista/current-workflow-session.json'\nif not p.exists(): sys.exit(0)\nd = json.loads(p.read_text())\nd['last_active'] = datetime.datetime.utcnow().isoformat() + 'Z'\np.write_text(json.dumps(d, indent=2))\nskill_id = d.get('skill_id', '')\ntmp = pathlib.Path(f'/tmp/dv-workflow-{skill_id}.md')\nif skill_id and tmp.exists():\n    subprocess.run(['deepvista', 'card', 'update', skill_id, '--content-file', str(tmp)], capture_output=True)\n\" 2>/dev/null || true"
}
```

The hook exits silently when no session is active — safe to leave permanently.

---

## Conventions

| Rule | Detail |
|------|--------|
| Reuse the existing skill | If a session file with `skill_id` exists, skip creation and continue tracking. |
| Workflow skill, not a raw card | Use `deepvista skill create-from-note` — produces a proper `skill` type card, not `skill_run`. |
| Temp file is the source of truth | Write node updates to `/tmp/dv-workflow-<SKILL_ID>.md`; the Stop hook syncs it automatically. |
| Confirm before writing | Show planned nodes and get approval before running `deepvista skill create-from-note`. |
| One session at a time | If a session file exists on invocation, ask: continue or finalize first. |
