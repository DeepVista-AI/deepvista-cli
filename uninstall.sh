#!/usr/bin/env bash
set -e

SKILLS=(
  dv
  deepvista-shared
  deepvista-vistabase
  deepvista-notes
  deepvista-vistabook
  deepvista-chat
  deepvista-persona-knowledge-worker
  deepvista-recipe-research-to-vistabook
  deepvista-recipe-export-knowledge-as-skills
  deepvista-recipe-analyze-notes
)

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
    for skill in "${SKILLS[@]}"; do
      target="$dir/$skill"
      if [ -d "$target" ]; then
        rm -rf "$target"
        echo "    Removed $target"
      fi
    done
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

echo ""
echo "DeepVista has been uninstalled."
