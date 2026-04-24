#!/usr/bin/env bash
# DeepVista catalog sync — fires on Claude Code SessionStart.
#
# Writes thin SKILL.md stubs into ~/.claude/skills/ so the catalog surfaces in
# the /skills UI immediately (live change detection picks them up in the
# current session). Skill bodies are fetched lazily at invocation time by the
# stub's `!`deepvista skill load <id>`` directive.
#
# Safety: never fails the session. Exit code is always 0 — any sync error
# just leaves the previous sync's stubs in place.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

LOG_DIR="$HOME/.deepvista/logs"
LOG_FILE="$LOG_DIR/catalog-sync.log"
mkdir -p "$LOG_DIR"

if ! command -v deepvista >/dev/null 2>&1; then
  printf '[%s] deepvista CLI not on PATH; skipping catalog sync\n' \
    "$(date -u +%FT%TZ)" >>"$LOG_FILE" 2>&1 || true
  exit 0
fi

# Allow the user to override throttle / target without editing the plugin.
THROTTLE_MIN="${DEEPVISTA_SYNC_THROTTLE_MIN:-60}"
LIMIT="${DEEPVISTA_SYNC_LIMIT:-30}"
FORCE_FLAG=""
if [ "${DEEPVISTA_FORCE_SYNC:-}" = "1" ]; then
  FORCE_FLAG="--force"
fi

{
  printf '[%s] starting sync (limit=%s throttle=%s%s)\n' \
    "$(date -u +%FT%TZ)" "$LIMIT" "$THROTTLE_MIN" \
    "${FORCE_FLAG:+ force}"
  deepvista skill sync \
    --limit "$LIMIT" \
    --throttle-min "$THROTTLE_MIN" \
    $FORCE_FLAG \
    --quiet
  printf '[%s] sync exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$LOG_FILE" 2>&1 || true

exit 0
