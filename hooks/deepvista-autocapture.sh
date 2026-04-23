#!/usr/bin/env bash
# DeepVista Auto-Capture — Claude Code Stop Hook
# Saves notable user statements to DeepVista notes after each conversation turn.
# Install: referenced in ~/.claude/settings.json under hooks.Stop

# Set up PATH for common tool install locations
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

# Silently exit if deepvista is not installed
command -v deepvista >/dev/null 2>&1 || exit 0

# Read the hook payload from stdin
PAYLOAD=$(cat)

# Extract transcript path from payload JSON
TRANSCRIPT_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('transcript_path', ''))
except Exception:
    print('')
" 2>/dev/null || true)

[ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ] && exit 0

# Extract the last user message from the JSONL transcript
LAST_USER=$(TRANSCRIPT_PATH="$TRANSCRIPT_PATH" python3 - <<'PYEOF'
import sys, json, os

path = os.environ.get("TRANSCRIPT_PATH", "")
last_text = ""
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            # Support both flat {role, content} and nested {message: {role, content}} formats
            role = entry.get("role")
            content_raw = entry.get("content")
            if not role:
                msg = entry.get("message") or {}
                role = msg.get("role")
                content_raw = msg.get("content")
            if role != "user" or not content_raw:
                continue
            if isinstance(content_raw, str):
                if content_raw.strip():
                    last_text = content_raw
            elif isinstance(content_raw, list):
                parts = [
                    b.get("text", "")
                    for b in content_raw
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = " ".join(p for p in parts if p).strip()
                # Skip tool_result / empty entries so they don't wipe a real
                # user message that came earlier in the transcript.
                if text:
                    last_text = text
except Exception:
    pass

# Truncate to avoid oversized notes
print(last_text[:1500] if last_text else "")
PYEOF
)

# Skip empty or trivially short messages
[ -z "$LAST_USER" ] || [ "${#LAST_USER}" -lt 20 ] && exit 0

# Only save messages that contain factual statements about the user, their work,
# decisions, or plans — skip pure questions and commands. Word-boundaries
# (\b) prevent substring false positives like "your" matching "our ".
LOWER=$(printf '%s' "$LAST_USER" | tr '[:upper:]' '[:lower:]')
printf '%s' "$LOWER" | grep -qE \
  "\b(i am|i'm|we are|we're|my|our|i have|we have|i don't|i do not|i like|i love|i hate|i prefer|decided|planning|going to|working on|we built|i built|the tool|the product|the company|we('re| are) building|i want to|we want to|it is|it's|this is|here is|here's|note:)\b" \
  || exit 0

# Save to DeepVista in background — non-blocking so Claude isn't delayed
deepvista notes +quick "$LAST_USER" >/dev/null 2>&1 &

exit 0
