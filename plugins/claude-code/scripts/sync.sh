#!/usr/bin/env bash
# DeepVista catalog sync — Claude Code SessionStart hook.
#
# Writes thin SKILL.md stubs into ${CLAUDE_PLUGIN_ROOT}/skills/ so the
# catalog surfaces under the plugin namespace in the /skills UI (shown as
# "locked by plugin" rather than "user"). Claude Code's live change detection
# picks up new stubs in the current session — no restart needed.
#
# Falls back to ~/.claude/skills/ when CLAUDE_PLUGIN_ROOT is not set, so the
# same script works when invoked manually from a shell.
#
# Safety: always exits 0. A missing CLI, network error, or auth failure just
# leaves the previous sync's stubs in place.

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

# Claude Code sets CLAUDE_PLUGIN_ROOT when invoking plugin hooks. The synced
# stubs then live under the plugin namespace and are shown as "locked by
# plugin" in /skills. When run outside the plugin (e.g. manual invocation)
# we fall back to ~/.claude/skills/.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  TARGET="${CLAUDE_PLUGIN_ROOT}/skills"
else
  TARGET="$HOME/.claude/skills"
fi

THROTTLE_MIN="${DEEPVISTA_SYNC_THROTTLE_MIN:-60}"
LIMIT="${DEEPVISTA_SYNC_LIMIT:-30}"
FORCE_FLAG=""
if [ "${DEEPVISTA_FORCE_SYNC:-}" = "1" ]; then
  FORCE_FLAG="--force"
fi

{
  printf '[%s] starting sync target=%s limit=%s throttle=%s%s\n' \
    "$(date -u +%FT%TZ)" "$TARGET" "$LIMIT" "$THROTTLE_MIN" \
    "${FORCE_FLAG:+ force}"
  deepvista skill sync \
    --target "$TARGET" \
    --limit "$LIMIT" \
    --throttle-min "$THROTTLE_MIN" \
    $FORCE_FLAG \
    --quiet
  printf '[%s] sync exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$LOG_FILE" 2>&1 || true

exit 0
