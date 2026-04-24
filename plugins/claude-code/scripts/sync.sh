#!/usr/bin/env bash
# DeepVista catalog sync — Claude Code SessionStart hook.
#
# Writes thin SKILL.md stubs into ${CLAUDE_PLUGIN_ROOT}/skills/ so the
# catalog surfaces under the plugin namespace in /skills (shown as
# "locked by plugin"). Live change detection picks them up in the current
# session — no restart needed.
#
# For manual / shell invocation use `deepvista skill sync` directly; this
# script is strictly the plugin hook.
#
# Safety: always exits 0. Missing CLI, network error, or auth failure just
# leaves the previous sync's stubs in place.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

LOG_DIR="$HOME/.deepvista/logs"
LOG_FILE="$LOG_DIR/catalog-sync.log"
mkdir -p "$LOG_DIR"

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[%s] CLAUDE_PLUGIN_ROOT not set; refusing to sync\n' \
    "$(date -u +%FT%TZ)" >>"$LOG_FILE" 2>&1 || true
  exit 0
fi

if ! command -v deepvista >/dev/null 2>&1; then
  printf '[%s] deepvista CLI not on PATH; skipping catalog sync\n' \
    "$(date -u +%FT%TZ)" >>"$LOG_FILE" 2>&1 || true
  exit 0
fi

TARGET="${CLAUDE_PLUGIN_ROOT}/skills"
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
