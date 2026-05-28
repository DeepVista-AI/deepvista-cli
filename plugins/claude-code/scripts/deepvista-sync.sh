#!/usr/bin/env bash
# DeepVista catalog + agent sync — Claude Code SessionStart hook.
#
# Runs two converging syncs into the plugin's own dirs so both surface in the
# current session via live change detection (no restart):
#   1. `deepvista skill sync`    → ${CLAUDE_PLUGIN_ROOT}/skills/  (dv-<slug>/SKILL.md stubs)
#   2. `deepvista agents export` → ${CLAUDE_PLUGIN_ROOT}/agents/  (dv-<role>.md subagents)
#
# For manual / shell invocation use `deepvista skill sync` and
# `deepvista agents export` directly; this script is strictly the plugin hook.
#
# Safety: always exits 0. Missing CLI, network error, or auth failure just
# leaves the previous run's generated files in place.

set -u

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

LOG_DIR="$HOME/.config/deepvista/logs"
mkdir -p "$LOG_DIR"
SKILL_LOG="$LOG_DIR/catalog-sync.log"
AGENT_LOG="$LOG_DIR/agent-export.log"
PLANNING_LOG="$LOG_DIR/daily-planning.log"

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

# 1. Skill catalog → ${CLAUDE_PLUGIN_ROOT}/skills/
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

# 2. Managed agents → ${CLAUDE_PLUGIN_ROOT}/agents/
AGENT_TARGET="${CLAUDE_PLUGIN_ROOT}/agents"
AGENT_THROTTLE_MIN="${DEEPVISTA_AGENT_SYNC_THROTTLE_MIN:-60}"
AGENT_LIMIT="${DEEPVISTA_AGENT_SYNC_LIMIT:-50}"
{
  printf '[%s] starting export target=%s limit=%s throttle=%s%s\n' \
    "$(date -u +%FT%TZ)" "$AGENT_TARGET" "$AGENT_LIMIT" "$AGENT_THROTTLE_MIN" \
    "${FORCE_FLAG:+ force}"
  deepvista agents export \
    --target "$AGENT_TARGET" \
    --limit "$AGENT_LIMIT" \
    --throttle-min "$AGENT_THROTTLE_MIN" \
    $FORCE_FLAG \
    --quiet
  printf '[%s] export exit=%s\n' "$(date -u +%FT%TZ)" "$?"
} >>"$AGENT_LOG" 2>&1 || true

# 3. Daily planning note (DV-853) — *don't* auto-create a templated stub from
# the hook. Generation belongs to the `daily-planning` skill (yesterday's plan
# + last 7 days of cards → reasoned plan), which the user invokes via
# `/deepvista run`. We only log presence here so the log shows whether a
# regeneration is due.
{
  TODAY="$(date +%Y%m%d)"
  if deepvista --format json planning today --date "$TODAY" >/dev/null 2>&1; then
    printf '[%s] planning note exists for %s\n' "$(date -u +%FT%TZ)" "$TODAY"
  else
    printf '[%s] no planning note for %s — run /deepvista run to generate\n' \
      "$(date -u +%FT%TZ)" "$TODAY"
  fi
} >>"$PLANNING_LOG" 2>&1 || true

exit 0
