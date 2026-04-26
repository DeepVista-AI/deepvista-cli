#!/usr/bin/env bash
# DeepVista session note — Claude Code SessionEnd hook.
# Marks the session note complete and queues enrichment.
# Install: referenced in ~/.claude/settings.json under hooks.SessionEnd.

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

[ -z "$SESSION_ID" ] && exit 0

TRANSCRIPT_FLAG=()
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] && TRANSCRIPT_FLAG=(--transcript "$TRANSCRIPT")

deepvista notes session-finalize \
  --session-id "$SESSION_ID" \
  "${TRANSCRIPT_FLAG[@]}" \
  >/dev/null 2>&1 &

exit 0
