#!/usr/bin/env bash
# DeepVista agent heartbeat — Claude Code SessionStart / Stop / SessionEnd hook.
#
# Pushes presence (online/offline) + a config snapshot so the agent shows live
# on the DeepVista dashboard. This is the single source of truth for the
# heartbeat: it replaces the legacy raw `agents sync` Stop hook that older CLI
# versions injected straight into ~/.claude/settings.json (DV-1357).
#
# Usage (from hooks.json):
#   deepvista-agent-sync.sh online    # SessionStart, Stop
#   deepvista-agent-sync.sh offline   # SessionEnd
#
# Safety: always exits 0. A missing CLI, network error (e.g. a resolver that
# blocks deepvista.ai), or stale auth is logged and swallowed so it can never
# error noisily and loop the Stop hook.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

STATUS="${1:-online}"

LOG_DIR="$HOME/.config/deepvista/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG="$LOG_DIR/agent-heartbeat.log"

# Claude Code delivers the hook payload on stdin; the heartbeat doesn't need it.
cat >/dev/null 2>&1 || true

if ! command -v deepvista >/dev/null 2>&1; then
  printf '[%s] deepvista CLI not on PATH; skipping heartbeat\n' \
    "$(date -u +%FT%TZ)" >>"$LOG" 2>&1 || true
  exit 0
fi

{
  printf '[%s] heartbeat status=%s\n' "$(date -u +%FT%TZ)" "$STATUS"
  deepvista agents sync --type claude-code --status "$STATUS"
  printf '[%s] heartbeat exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$LOG" 2>&1 &

exit 0
