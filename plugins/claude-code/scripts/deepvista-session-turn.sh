#!/usr/bin/env bash
# DeepVista session card — Claude Code Stop hook.
# Appends the newest transcript turn(s) as a versioned block on the session card.
# Install: referenced in ~/.claude/settings.json under hooks.Stop.

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

command -v deepvista >/dev/null 2>&1 || exit 0

PAYLOAD=$(cat)

read -r SESSION_ID TRANSCRIPT <<<"$(
  printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(d.get('session_id', ''), d.get('transcript_path', ''))
" 2>/dev/null || true)"

[ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0

deepvista session tick \
  --session-id "$SESSION_ID" \
  --transcript "$TRANSCRIPT" \
  >/dev/null 2>&1 &

exit 0
