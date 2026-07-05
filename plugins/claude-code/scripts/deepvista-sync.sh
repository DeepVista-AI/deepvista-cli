#!/usr/bin/env bash
# DeepVista skill catalog sync — Claude Code SessionStart hook.
#
# Runs `deepvista skill sync` into the plugin's skills dir so stubs surface in
# the current session via live change detection (no restart):
#   `deepvista skill sync` → ${CLAUDE_PLUGIN_ROOT}/skills/  (dv-<slug>/SKILL.md stubs)
#
# For manual invocation use `deepvista skill sync` directly; this script is
# strictly the plugin hook.
#
# Safety: always exits 0. Missing CLI, network error, or auth failure just
# leaves the previous run's generated files in place.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

LOG_DIR="$HOME/.config/deepvista/logs"
mkdir -p "$LOG_DIR"
SKILL_LOG="$LOG_DIR/catalog-sync.log"

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[%s] CLAUDE_PLUGIN_ROOT not set; refusing to sync\n' \
    "$(date -u +%FT%TZ)" >>"$SKILL_LOG" 2>&1 || true
  exit 0
fi

if ! command -v deepvista >/dev/null 2>&1; then
  printf '[%s] deepvista CLI not on PATH; skipping sync\n' \
    "$(date -u +%FT%TZ)" >>"$SKILL_LOG" 2>&1 || true
  exit 0
fi

FORCE_FLAG=""
if [ "${DEEPVISTA_FORCE_SYNC:-}" = "1" ]; then
  FORCE_FLAG="--force"
fi

SKILL_TARGET="${CLAUDE_PLUGIN_ROOT}/skills"
SKILL_THROTTLE_MIN="${DEEPVISTA_SYNC_THROTTLE_MIN:-60}"
SKILL_LIMIT="${DEEPVISTA_SYNC_LIMIT:-30}"
{
  printf '[%s] starting sync target=%s limit=%s throttle=%s%s\n' \
    "$(date -u +%FT%TZ)" "$SKILL_TARGET" "$SKILL_LIMIT" "$SKILL_THROTTLE_MIN" \
    "${FORCE_FLAG:+ force}"
  deepvista skill sync \
    --target "$SKILL_TARGET" \
    --limit "$SKILL_LIMIT" \
    --throttle-min "$SKILL_THROTTLE_MIN" \
    $FORCE_FLAG \
    --quiet
  printf '[%s] sync exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$SKILL_LOG" 2>&1 || true

exit 0
