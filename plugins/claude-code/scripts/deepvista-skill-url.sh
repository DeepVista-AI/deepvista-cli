#!/usr/bin/env bash
# DeepVista skill-URL announcer — Claude Code PreToolUse hook on the Skill tool.
#
# When a synced DeepVista catalog stub (dv-*) is invoked, looks up the skill's
# server id from its SKILL.md frontmatter and emits a system reminder telling
# Claude to show the user the skill's app.deepvista.ai URL before it runs.
#
# PreToolUse stdout is not surfaced to the user (see Claude Code hooks docs),
# so the URL is injected via hookSpecificOutput.additionalContext and the
# reminder instructs the agent to print it.

set -u

PAYLOAD=$(cat)

read -r SKILL ID <<EOF
$(PAYLOAD="$PAYLOAD" PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}" python3 - <<'PYEOF'
import json, os, re, sys

try:
    data = json.loads(os.environ.get("PAYLOAD", ""))
except Exception:
    sys.exit(0)

skill = (data.get("tool_input") or {}).get("skill") or ""
# Strip any plugin namespace (e.g. "deepvista:dv-foo" -> "dv-foo").
skill = skill.rsplit(":", 1)[-1].strip()

if not skill.startswith("dv-"):
    sys.exit(0)

plugin_root = os.environ.get("PLUGIN_ROOT", "")
if not plugin_root:
    sys.exit(0)

skill_md = os.path.join(plugin_root, "skills", skill, "SKILL.md")
try:
    with open(skill_md, encoding="utf-8") as f:
        head = f.read(4096)
except OSError:
    sys.exit(0)

m = re.search(r"^x-deepvista-id:\s*(.+?)\s*$", head, re.MULTILINE)
if not m:
    sys.exit(0)

skill_id = m.group(1).strip().strip('"').strip("'")
if not skill_id:
    sys.exit(0)

print(f"{skill} {skill_id}")
PYEOF
)
EOF

[ -n "${ID:-}" ] || exit 0

URL="https://app.deepvista.ai/skills/${ID}"

# Emit JSON on stdout — Claude Code parses this and injects additionalContext
# as a system reminder for the next model turn.
python3 - "$URL" <<'PYEOF'
import json, sys

url = sys.argv[1]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            "Before running this DeepVista skill, tell the user they can view "
            f"it on DeepVista: {url}"
        ),
    }
}))
PYEOF
