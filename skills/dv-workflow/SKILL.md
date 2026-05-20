---
license: Apache-2.0
name: dv-workflow
description: |
  Create and track a DeepVista workflow skill for the current Claude Code session.
  On first invocation, captures the session goal as a note and synthesizes a
  workflow skill via deepvista skill create-from-note. Subsequent invocations in
  the same session reuse the existing skill. A Stop hook auto-syncs node status,
  timestamps, error details, and session metrics to the skill card after every turn.
metadata:
  type: workflow
  execution: stateful
---

# /dv-workflow — Session Workflow Tracker

Turns the current Claude Code session into a tracked workflow skill stored in
the user's DeepVista vistabase. The goal is captured as a note, a proper workflow
skill is synthesized from it, and node status (including timestamps, error details,
and session metrics) is kept in sync automatically via a Stop hook after every turn.

---

## Phase 1 — Initialize

### Step 1: Check for an existing session

```bash
cat ~/.config/deepvista/current-workflow-session.json 2>/dev/null
```

If the file exists and contains a `skill_id`, **reuse the existing workflow skill** —
skip to Phase 2. Ask the user:
- **Continue** from the last active node
- **Finalize** the current workflow (Phase 3), then start fresh

If no session file exists, continue to Step 2.

### Step 2: Capture the goal

If the user typed `/dv-workflow <goal>`, use that text.
Otherwise ask: _"What should this session accomplish? (One sentence.)"_

### Step 3: Plan nodes

Break the goal into 3–7 sequential, discrete nodes. Good names are verb phrases:
"Understand the codebase", "Implement the feature", "Write tests", "Open PR".
Show the plan and confirm with the user before proceeding.

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

Wait for the final NDJSON event and extract the skill card `id` as `SKILL_ID`.

### Step 6: Write the initial execution state

Write the tracking body to `/tmp/dv-workflow-<SKILL_ID>.md`:

```
**Goal:** <goal>
**Status:** running
**Started:** <UTC ISO timestamp>

## Nodes

| # | Node | Status | Started | Duration | Output |
|---|------|--------|---------|----------|--------|
| 1 | <node 1> | pending |  |  |  |
| 2 | <node 2> | pending |  |  |  |
...

## Metrics

- Nodes: 0/<total> done, 0 failed
- Elapsed: 0m

## Summary

_In progress._
```

Push it:

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
  "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "current_node": 1,
  "error": None,
}, indent=2))
PY
```

### Step 8: Ensure Stop hook is installed

Check `~/.claude/settings.json` for a Stop hook containing `current-workflow-session`.
If absent, install via:

```bash
deepvista agents register --type claude-code
```

Or add manually — see the **Stop hook** section below.

Show: `https://app.deepvista.ai/vistabase/<SKILL_ID>`

---

## Phase 2 — Track each node

Maintain the full tracking body in `/tmp/dv-workflow-<SKILL_ID>.md`.
The Stop hook syncs it after every turn — **no explicit `deepvista card update` needed**.

### Node lifecycle

```
pending  →  running  →  done
                    ↘  failed   (task could not complete — expected outcome)
                    ↘  error    (unexpected tool crash / exception)
```

### Node table schema

| Column | Content |
|--------|---------|
| `#` | Node index |
| `Node` | Verb-phrase description |
| `Status` | `pending` / `running` / `done` / `failed` / `error` |
| `Started` | UTC time when node went `running` (e.g. `14:32`) |
| `Duration` | Elapsed time when node left `running` (e.g. `3m 12s`) |
| `Output` | One-line result, error message, or artifact name |

### When to update

| Event | Action |
|-------|--------|
| Starting a node | Status → `running`, record `Started` |
| Node completes | Status → `done`, fill `Duration` and `Output` |
| Task cannot be done | Status → `failed`, fill `Output` with reason |
| Tool threw an exception | Status → `error`, fill `Output` with error summary |
| Scope expands | Append new rows with `pending` — do not back-date |

### After each transition — write the updated temp file

```bash
cat > /tmp/dv-workflow-<SKILL_ID>.md << 'STATE'
**Goal:** <goal>
**Status:** running
**Started:** <ISO>

## Nodes

| # | Node | Status | Started | Duration | Output |
|---|------|--------|---------|----------|--------|
| 1 | <node 1> | done | 14:30 | 2m | <output> |
| 2 | <node 2> | running | 14:32 |  |  |
...

## Metrics

- Nodes: 1/<total> done, 0 failed
- Elapsed: <Xm>

## Summary

_In progress._
STATE
```

The Stop hook picks it up at end-of-turn.

### Error capture

If a Bash command or tool fails unexpectedly, capture the details immediately:

```bash
# Update the current node to error status
# Replace | 2 | <node name> | running | ... |
# with    | 2 | <node name> | error   | 14:32 | 0m 5s | <error summary> |
```

Record a brief error summary in `Output` (tool name, exit code, first line of stderr).
Then decide: retry the node, mark it `failed` and continue, or stop the session.

---

## Phase 3 — Finalize

When the session goal is achieved or the user ends the session:

### Step 1: Write the final state

- Set `**Status:**` to `done` (or `failed` / `error`)
- Fill all remaining `Duration` values
- Update `## Metrics` with final counts and total elapsed time
- Write a 2–4 sentence `## Summary`:
  - What was accomplished
  - Key outputs or artifacts
  - Any remaining items or known issues

Write to `/tmp/dv-workflow-<SKILL_ID>.md` (the Stop hook will sync it),
or push immediately:

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

Reads the session file, updates `last_active`, and pushes the temp file to the
skill card. Install once via `deepvista agents register --type claude-code`.

To add manually under `hooks.Stop` in `~/.claude/settings.json`:

```json
{
  "type": "command",
  "command": "python3 -c \"import json,pathlib,subprocess,datetime,sys; p=pathlib.Path.home()/'.config/deepvista/current-workflow-session.json'; d=json.loads(p.read_text()) if p.exists() else None; d and [p.write_text(json.dumps({**d,'last_active':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2)),pathlib.Path(f\\\"/tmp/dv-workflow-{d.get('skill_id','')}.md\\\").exists() and subprocess.run(['deepvista','card','update',d.get('skill_id',''),'--content-file',f\\\"/tmp/dv-workflow-{d.get('skill_id','')}.md\\\"],capture_output=True)]\" 2>/dev/null || true"
}
```

The hook exits silently when no session is active.

---

## Optional: PostToolUse error-capture hook

To automatically flag Bash failures into the session file, add under `hooks.PostToolUse`:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 -c \"\nimport json,pathlib,sys,datetime\ndata=json.load(sys.stdin)\nif data.get('tool_response',{}).get('exit_code',0)==0: sys.exit(0)\np=pathlib.Path.home()/'.config/deepvista/current-workflow-session.json'\nif not p.exists(): sys.exit(0)\nd=json.loads(p.read_text())\nd['last_error']={'cmd':data.get('tool_input',{}).get('command','')[:120],'exit_code':data['tool_response'].get('exit_code'),'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}\np.write_text(json.dumps(d,indent=2))\n\" 2>/dev/null || true"
    }
  ]
}
```

This writes `last_error` to the session file whenever a Bash command exits non-zero.
The agent can read it on the next turn to fill the node's `Output` field accurately.

---

## Conventions

| Rule | Detail |
|------|--------|
| Reuse within session | If session file has `skill_id`, skip creation and continue. |
| Workflow skill, not a raw card | Use `deepvista skill create-from-note` — produces `type=skill`. |
| Temp file is source of truth | Write all state to `/tmp/dv-workflow-<SKILL_ID>.md`; Stop hook syncs it. |
| Timestamps on every node | Record `Started` when going `running`; `Duration` when leaving it. |
| Errors are first-class | `error` ≠ `failed`: error means the tool broke, failed means the task couldn't be done. |
| Metrics stay current | Update the `## Metrics` block on every state change. |
| Confirm before creating | Show node plan and get approval before `deepvista skill create-from-note`. |
