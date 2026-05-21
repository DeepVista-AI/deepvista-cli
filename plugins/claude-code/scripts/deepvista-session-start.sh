#!/usr/bin/env bash
# DeepVista session card — SessionStart hook.
# Creates-or-gets a rolling DeepVista session card (type='session') keyed by session_id.
# Agent type + version are auto-detected by the CLI from env / process tree
# (Claude Code, Cursor, Windsurf, etc. — see deepvista_cli.client.origin).
# Install: referenced in ~/.claude/settings.json under hooks.SessionStart.

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

command -v deepvista >/dev/null 2>&1 || exit 0

PAYLOAD=$(cat)

read -r SESSION_ID TRANSCRIPT CWD AGENT_VERSION <<<"$(
  printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(
    d.get('session_id', ''),
    d.get('transcript_path', ''),
    d.get('cwd', ''),
    (d.get('client') or {}).get('version', ''),
)
" 2>/dev/null || true)"

[ -z "$SESSION_ID" ] || [ -z "$CWD" ] && exit 0

AGENT_VERSION_FLAG=()
[ -n "$AGENT_VERSION" ] && AGENT_VERSION_FLAG=(--agent-version "$AGENT_VERSION")

deepvista session init \
  --session-id "$SESSION_ID" \
  --transcript "$TRANSCRIPT" \
  --cwd "$CWD" \
  "${AGENT_VERSION_FLAG[@]}" \
  >/dev/null 2>&1 &

exit 0
