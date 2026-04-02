---
name: deepvista-notes
description: |
  DeepVista Notes: Create, read, update, and delete notes in your knowledge base.
  TRIGGER when: user wants to create, capture, save, read, list, update, or delete a note; user says "take a note", "jot this down", "save this as a note", "show my notes", or asks about a specific note by title or ID. Also trigger for "enable auto-capture", "disable auto-capture", "turn on/off auto-capture", or "auto-capture status".
  DO NOT TRIGGER when: user wants to analyze, summarize, or find patterns across notes (use deepvista-recipe-analyze-notes instead); or when working with non-note knowledge base cards.
metadata:
  deepvista:
    category: "service"
    requires:
      bins:
        - uv
      skills:
        - deepvista-shared
    cliHelp: "deepvista notes --help"
---

# Notes

> **PREREQUISITE:** Read [deepvista-shared](../deepvista-shared/SKILL.md) for auth, profiles, and global flags.

Notes are context cards with `type=note`. They support rich markdown content and are a natural fit for agents to capture meeting notes, summaries, and research.

## Commands

### list

```bash
deepvista notes list [--limit N] [--page N]
```

### get

```bash
deepvista notes get <note_id>
```

### create

```bash
deepvista notes create --title "Title" [--content "Markdown content"] [--tags '["t1"]']
```

> [!CAUTION] Write command — confirm with user before executing.

### update

```bash
deepvista notes update <note_id> [--title "..."] [--content "..."] [--tags '["t1"]']
```

> [!CAUTION] Write command — confirm with user before executing.

### delete

```bash
deepvista notes delete <note_id>
```

> [!CAUTION] Destructive command — confirm with user before executing.

### +quick

```bash
deepvista notes +quick "your text here"
```

Quick-create a note from a single line of text. The first ~50 characters become the title; the full text is the content. Entity enrichment runs automatically.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `<text>` | Yes | — | Note content (title auto-derived from first sentence) |

> [!CAUTION] Write command — creates a new note. Confirm with the user before executing.

- Ideal for agents capturing quick observations during a workflow.
- For notes with custom titles, use `notes create --title "..." --content "..."` instead.
- Created notes appear in the VistaBase and can be searched with `vistabase +search`.

## Examples

```bash
# List recent notes
deepvista notes list --limit 5

# Create a meeting note
deepvista notes create --title "Standup 2026-03-26" --content "## Discussed\n- Roadmap priorities\n- CLI release"

# Quick note from a single line
deepvista notes +quick "Alice mentioned the API migration deadline is April 15"

# Update a note
deepvista notes update note_abc --content "Updated content with new findings..."
```

### +autocapture

Manage the auto-capture hook that automatically saves notable facts from conversations to DeepVista notes after each turn.

```bash
# Check current status
deepvista notes +autocapture status

# Enable auto-capture (hook only)
deepvista notes +autocapture enable

# Disable auto-capture (hook only)
deepvista notes +autocapture disable

# Enable everything: hook + Claude instruction in CLAUDE.md
deepvista notes +autocapture enable-all

# Disable everything: hook + Claude instruction in CLAUDE.md
deepvista notes +autocapture disable-all
```

Since `deepvista notes +autocapture` may not exist as a CLI command yet, implement each subcommand as shell steps:

#### status
```bash
grep -q "deepvista-autocapture" "$HOME/.claude/settings.json" 2>/dev/null \
  && echo "Auto-capture is ENABLED" \
  || echo "Auto-capture is DISABLED"
```

#### enable
```bash
# 1. Ensure hook script is present
mkdir -p "$HOME/.claude/hooks"
if [ ! -f "$HOME/.claude/hooks/deepvista-autocapture.sh" ]; then
  curl -sSL "https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/hooks/deepvista-autocapture.sh" \
    -o "$HOME/.claude/hooks/deepvista-autocapture.sh"
  chmod +x "$HOME/.claude/hooks/deepvista-autocapture.sh"
fi

# 2. Register Stop hook in settings.json (idempotent)
python3 - <<'PYEOF'
import json, os

path = os.path.expanduser("~/.claude/settings.json")
hook_cmd = os.path.expanduser("~/.claude/hooks/deepvista-autocapture.sh")

try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

hooks = cfg.setdefault("hooks", {})
stop_list = hooks.setdefault("Stop", [])
already = any(
    any(h.get("command") == hook_cmd for h in e.get("hooks", []))
    for e in stop_list
)
if not already:
    stop_list.append({"matcher": "", "hooks": [{"type": "command", "command": hook_cmd}]})
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print("Auto-capture ENABLED")
else:
    print("Auto-capture already enabled")
PYEOF
```

#### disable
```bash
python3 - <<'PYEOF'
import json, os

path = os.path.expanduser("~/.claude/settings.json")
hook_cmd = os.path.expanduser("~/.claude/hooks/deepvista-autocapture.sh")

try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    print("No settings.json found")
    raise SystemExit(0)

hooks = cfg.get("hooks", {})
stop_list = hooks.get("Stop", [])
filtered = [
    e for e in stop_list
    if not any(h.get("command") == hook_cmd for h in e.get("hooks", []))
]
hooks["Stop"] = filtered
if not filtered:
    del hooks["Stop"]
if not hooks:
    cfg.pop("hooks", None)

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
print("Auto-capture DISABLED")
PYEOF
```

#### disable-all
Disables both the Stop hook and the Claude auto-capture instruction in CLAUDE.md:

```bash
# 1. Disable the Stop hook (same as disable above)
python3 - <<'PYEOF'
import json, os
path = os.path.expanduser("~/.claude/settings.json")
hook_cmd = os.path.expanduser("~/.claude/hooks/deepvista-autocapture.sh")
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
hooks = cfg.get("hooks", {})
stop_list = hooks.get("Stop", [])
filtered = [e for e in stop_list if not any(h.get("command") == hook_cmd for h in e.get("hooks", []))]
hooks["Stop"] = filtered
if not filtered:
    del hooks["Stop"]
if not hooks:
    cfg.pop("hooks", None)
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

# 2. Remove the auto-capture instruction block from CLAUDE.md
python3 - <<'PYEOF'
import os, re
path = os.path.expanduser("~/.claude/CLAUDE.md")
if not os.path.exists(path):
    raise SystemExit(0)
with open(path) as f:
    content = f.read()
# Remove marked block
cleaned = re.sub(r'\n<!-- deepvista-auto-capture -->.*?<!-- /deepvista-auto-capture -->', '', content, flags=re.DOTALL)
# Also remove unmarked ## DeepVista Auto-Capture section if present
cleaned = re.sub(r'\n## DeepVista Auto-Capture\n.*?(?=\n## |\Z)', '', cleaned, flags=re.DOTALL)
with open(path, "w") as f:
    f.write(cleaned.strip() + "\n")
print("Auto-capture fully DISABLED (hook + CLAUDE.md instruction)")
PYEOF
```

#### enable-all
Re-enables both the Stop hook and adds the Claude auto-capture instruction to CLAUDE.md:

```bash
# 1. Enable the Stop hook (same as enable above)
mkdir -p "$HOME/.claude/hooks"
if [ ! -f "$HOME/.claude/hooks/deepvista-autocapture.sh" ]; then
  curl -sSL "https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/hooks/deepvista-autocapture.sh" \
    -o "$HOME/.claude/hooks/deepvista-autocapture.sh"
  chmod +x "$HOME/.claude/hooks/deepvista-autocapture.sh"
fi
python3 - <<'PYEOF'
import json, os
path = os.path.expanduser("~/.claude/settings.json")
hook_cmd = os.path.expanduser("~/.claude/hooks/deepvista-autocapture.sh")
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
hooks = cfg.setdefault("hooks", {})
stop_list = hooks.setdefault("Stop", [])
already = any(any(h.get("command") == hook_cmd for h in e.get("hooks", [])) for e in stop_list)
if not already:
    stop_list.append({"matcher": "", "hooks": [{"type": "command", "command": hook_cmd}]})
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
PYEOF

# 2. Add auto-capture instruction back to CLAUDE.md (idempotent)
python3 - <<'PYEOF'
import os
path = os.path.expanduser("~/.claude/CLAUDE.md")
block = """
<!-- deepvista-auto-capture -->
## DeepVista Auto-Capture

When the user shares any of the following during a conversation, automatically save it to DeepVista notes using `deepvista notes +quick "<text>"` without asking for confirmation:

- Personal or professional facts (role, company, team, background)
- Decisions made or conclusions reached
- Key insights, learnings, or observations
- Action items or commitments
- Meeting or conversation highlights

Use `deepvista notes +quick` for single-line facts. For longer structured notes, use `deepvista notes create --title "..." --content "..."`.

If `deepvista` is not authenticated, prompt the user to run `deepvista auth login` before saving.
<!-- /deepvista-auto-capture -->"""

content = open(path).read() if os.path.exists(path) else "# Claude Code — Global Instructions\n"
if "deepvista-auto-capture" not in content:
    with open(path, "a") as f:
        f.write(block + "\n")
    print("Auto-capture fully ENABLED (hook + CLAUDE.md instruction)")
else:
    print("Auto-capture instruction already present in CLAUDE.md")
PYEOF
```

> [!NOTE] Changes to CLAUDE.md take effect in the next conversation. Hook changes also take effect in the next session.

## See Also

- [deepvista-shared](../deepvista-shared/SKILL.md) — Auth and global flags
- [deepvista-vistabase](../deepvista-vistabase/SKILL.md) — Full knowledge base API
