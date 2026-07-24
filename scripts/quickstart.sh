#!/usr/bin/env bash
# quickstart.sh — one-shot setup + launch for a DeepVista project.
#
# 1. Installs Claude Code (the `claude` CLI) if it's missing.
# 2. Runs `claude auth login` if Claude Code isn't authenticated yet.
# 3. Installs + authenticates the `deepvista` CLI if needed, then starts the
#    task daemon (`deepvista tasks run`) scoped to the given project.
#
# Usage:
#   scripts/quickstart.sh <project-slug> [extra `deepvista tasks run` args...]
#
# Example:
#   scripts/quickstart.sh acme-corp
#   scripts/quickstart.sh acme-corp --run-once

set -euo pipefail

SLUG="${1:-}"
if [ -z "$SLUG" ]; then
  echo "Usage: $0 <project-slug> [extra 'deepvista tasks run' args...]" >&2
  exit 1
fi
shift

log() { echo ">> $*" >&2; }

# --- 1. Claude Code CLI -----------------------------------------------------

if ! command -v claude >/dev/null 2>&1; then
  log "Claude Code not found — installing..."
  if command -v npm >/dev/null 2>&1; then
    npm install -g @anthropic-ai/claude-code
  else
    echo "npm is required to install Claude Code. Install Node.js/npm and re-run." >&2
    exit 1
  fi
else
  log "Claude Code already installed ($(claude --version))."
fi

# --- 2. Claude Code auth -----------------------------------------------------

if claude auth status --json >/dev/null 2>&1; then
  log "Claude Code already authenticated."
else
  log "Claude Code not authenticated — running 'claude auth login'..."
  claude auth login
fi

# --- 3. DeepVista CLI + server ----------------------------------------------

if ! command -v deepvista >/dev/null 2>&1; then
  log "DeepVista CLI not found — installing..."
  if command -v uv >/dev/null 2>&1; then
    uv tool install deepvista-cli
  elif command -v pip >/dev/null 2>&1; then
    pip install deepvista-cli
  else
    echo "Need 'uv' or 'pip' to install deepvista-cli. Install one and re-run." >&2
    exit 1
  fi
else
  log "DeepVista CLI already installed ($(deepvista --version 2>/dev/null || echo unknown))."
fi

if ! deepvista auth status >/dev/null 2>&1; then
  log "DeepVista not authenticated — running 'deepvista auth login'..."
  deepvista auth login
else
  log "DeepVista already authenticated."
fi

PROJECT_ID="$(deepvista --format json project use "$SLUG" | python3 -c 'import json,sys; print(json.load(sys.stdin)["working_project"])')"
log "Resolved project slug '$SLUG' -> id $PROJECT_ID"

log "Starting DeepVista task daemon for project $PROJECT_ID..."
exec deepvista tasks run --project "$PROJECT_ID" "$@"
