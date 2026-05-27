#!/usr/bin/env bash
# DeepVista agent-definition export — Claude Code SessionStart hook.
#
# Writes one `<role>.md` subagent definition into ${CLAUDE_PLUGIN_ROOT}/agents/
# for each distinct role across the user's DeepVista managed agents, so they
# become callable in Claude Code (e.g. `@marketing`). Generated files are
# prefixed `dv-` and ignored by git; curated agents in the same dir are never
# touched.
#
# For manual / shell invocation use `deepvista agents export` directly; this
# script is strictly the plugin hook.
#
# Safety: always exits 0. Missing CLI, network error, or auth failure just
# leaves the previous export's definitions in place.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

LOG_DIR="$HOME/.config/deepvista/logs"
LOG_FILE="$LOG_DIR/agent-export.log"
mkdir -p "$LOG_DIR"

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[%s] CLAUDE_PLUGIN_ROOT not set; refusing to export\n' \
    "$(date -u +%FT%TZ)" >>"$LOG_FILE" 2>&1 || true
  exit 0
fi

if ! command -v deepvista >/dev/null 2>&1; then
  printf '[%s] deepvista CLI not on PATH; skipping agent export\n' \
    "$(date -u +%FT%TZ)" >>"$LOG_FILE" 2>&1 || true
  exit 0
fi

TARGET="${CLAUDE_PLUGIN_ROOT}/agents"
THROTTLE_MIN="${DEEPVISTA_AGENT_SYNC_THROTTLE_MIN:-60}"
LIMIT="${DEEPVISTA_AGENT_SYNC_LIMIT:-50}"
FORCE_FLAG=""
if [ "${DEEPVISTA_FORCE_SYNC:-}" = "1" ]; then
  FORCE_FLAG="--force"
fi

{
  printf '[%s] starting export target=%s limit=%s throttle=%s%s\n' \
    "$(date -u +%FT%TZ)" "$TARGET" "$LIMIT" "$THROTTLE_MIN" \
    "${FORCE_FLAG:+ force}"
  deepvista agents export \
    --target "$TARGET" \
    --limit "$LIMIT" \
    --throttle-min "$THROTTLE_MIN" \
    $FORCE_FLAG \
    --quiet
  printf '[%s] export exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$LOG_FILE" 2>&1 || true

exit 0
