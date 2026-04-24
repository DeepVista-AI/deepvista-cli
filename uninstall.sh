#!/usr/bin/env bash
set -e

SKILL="deepvista"

# Uninstall CLI
echo "==> Uninstalling deepvista CLI..."

if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q deepvista-cli; then
  uv tool uninstall deepvista-cli
elif command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q deepvista-cli; then
  pipx uninstall deepvista-cli
elif command -v pip3 >/dev/null 2>&1 && pip3 show deepvista-cli >/dev/null 2>&1; then
  pip3 uninstall -y deepvista-cli
elif command -v pip >/dev/null 2>&1 && pip show deepvista-cli >/dev/null 2>&1; then
  pip uninstall -y deepvista-cli
else
  echo "    deepvista CLI not found via uv/pipx/pip — skipping"
fi

# Remove skills from all known agent skill directories
echo "==> Removing DeepVista skills..."

SKILL_DIRS=()
[ -d "$HOME/.claude/skills" ]   && SKILL_DIRS+=("$HOME/.claude/skills")
[ -d "$HOME/.agents/skills" ]   && SKILL_DIRS+=("$HOME/.agents/skills")
[ -d "$HOME/.cursor/skills" ]   && SKILL_DIRS+=("$HOME/.cursor/skills")
[ -d "$HOME/.opencode/skills" ] && SKILL_DIRS+=("$HOME/.opencode/skills")

if [ ${#SKILL_DIRS[@]} -eq 0 ]; then
  echo "    No agent skill directories found — nothing to remove"
else
  for dir in "${SKILL_DIRS[@]}"; do
    target="$dir/$SKILL"
    if [ -d "$target" ]; then
      rm -rf "$target"
      echo "    Removed $target"
    fi
  done
fi

# Remove auto-capture blocks from agent config files
echo "==> Removing DeepVista auto-capture settings..."

remove_autocapture() {
  local config_file="$1"
  if [ ! -f "$config_file" ]; then return; fi
  if ! grep -q "deepvista-auto-capture" "$config_file" 2>/dev/null; then return; fi
  # Remove everything between <!-- deepvista-auto-capture --> markers (inclusive)
  # Use a temp file to avoid in-place issues on macOS and Linux
  local tmp
  tmp=$(mktemp)
  awk '/<!-- deepvista-auto-capture -->/{skip=1} !skip{print} /<!-- \/deepvista-auto-capture -->/{skip=0}' \
    "$config_file" > "$tmp"
  mv "$tmp" "$config_file"
  echo "    Removed auto-capture block from $config_file"
}

remove_autocapture "$HOME/.claude/CLAUDE.md"
remove_autocapture "$HOME/.cursor/rules"
remove_autocapture "$HOME/.opencode/AGENTS.md"

echo "==> Removing DeepVista skill interpretation rules..."

remove_skill_rules() {
  local config_file="$1"
  if [ ! -f "$config_file" ]; then return; fi
  if ! grep -q "deepvista-skill-rules" "$config_file" 2>/dev/null; then return; fi
  local tmp
  tmp=$(mktemp)
  awk '/<!-- deepvista-skill-rules -->/{skip=1} !skip{print} /<!-- \/deepvista-skill-rules -->/{skip=0}' \
    "$config_file" > "$tmp"
  mv "$tmp" "$config_file"
  echo "    Removed skill rules block from $config_file"
}

remove_skill_rules "$HOME/.claude/CLAUDE.md"
remove_skill_rules "$HOME/.cursor/rules"
remove_skill_rules "$HOME/.opencode/AGENTS.md"

OPENCLAW_WORKSPACE="$HOME/.openclaw/workspace"
[ -d "$OPENCLAW_WORKSPACE" ] && remove_autocapture "$OPENCLAW_WORKSPACE/AGENTS.md"
[ -d "$OPENCLAW_WORKSPACE" ] && remove_skill_rules "$OPENCLAW_WORKSPACE/AGENTS.md"

# Remove Stop hook from Claude Code settings.json
echo "==> Removing DeepVista auto-capture hook..."

remove_stop_hook() {
  local settings_file="$1"
  local hook_script="$2"
  [ ! -f "$settings_file" ] && return
  grep -q "deepvista-autocapture" "$settings_file" 2>/dev/null || return

  python3 - "$settings_file" "$hook_script" <<'PYEOF'
import sys, json

settings_path, hook_cmd = sys.argv[1], sys.argv[2]
try:
    with open(settings_path) as f:
        cfg = json.load(f)
except Exception:
    sys.exit(0)

hooks = cfg.get("hooks", {})
stop_list = hooks.get("Stop", [])
hooks["Stop"] = [
    entry for entry in stop_list
    if not any(h.get("command") == hook_cmd for h in entry.get("hooks", []))
]
if not hooks["Stop"]:
    del hooks["Stop"]
if not hooks:
    cfg.pop("hooks", None)

with open(settings_path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

  echo "    Removed Stop hook from $settings_file"
}

HOOK_SCRIPT="$HOME/.claude/hooks/deepvista-autocapture.sh"
remove_stop_hook "$HOME/.claude/settings.json" "$HOOK_SCRIPT"

# Remove the hook script itself
if [ -f "$HOOK_SCRIPT" ]; then
  rm -f "$HOOK_SCRIPT"
  echo "    Removed $HOOK_SCRIPT"
fi

echo ""
echo "DeepVista has been uninstalled."
