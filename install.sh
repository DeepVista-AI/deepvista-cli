#!/usr/bin/env bash
set -e

REPO="DeepVista-AI/deepvista-cli"
SKILLS=(
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

echo "==> Installing deepvista CLI..."

if command -v uv >/dev/null 2>&1; then
  uv tool install deepvista-cli
elif command -v pipx >/dev/null 2>&1; then
  pipx install deepvista-cli
elif command -v pip3 >/dev/null 2>&1; then
  pip3 install --user deepvista-cli
elif command -v pip >/dev/null 2>&1; then
  pip install --user deepvista-cli
else
  echo "Error: no Python package manager found (pip, pipx, or uv required)" >&2
  exit 1
fi

echo "==> Installing DeepVista skills..."

# Detect which agent skill directories to install into
SKILL_DIRS=()
[ -d "$HOME/.claude" ]  && SKILL_DIRS+=("$HOME/.claude/skills")
[ -d "$HOME/.agents" ]  && SKILL_DIRS+=("$HOME/.agents/skills")
[ -d "$HOME/.cursor" ]  && SKILL_DIRS+=("$HOME/.cursor/skills")
[ -d "$HOME/.opencode" ] && SKILL_DIRS+=("$HOME/.opencode/skills")

# Default to Claude if no agent directory found
if [ ${#SKILL_DIRS[@]} -eq 0 ]; then
  SKILL_DIRS+=("$HOME/.claude/skills")
fi

# Download skills via git clone (fastest) or curl as fallback
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if command -v git >/dev/null 2>&1; then
  git clone --depth 1 --quiet "https://github.com/$REPO.git" "$TMP/repo"
  SRC="$TMP/repo/skills"
elif command -v curl >/dev/null 2>&1; then
  # Download each skill's SKILL.md individually
  SRC="$TMP/skills"
  for skill in "${SKILLS[@]}"; do
    mkdir -p "$SRC/$skill"
    curl -sSL "https://raw.githubusercontent.com/$REPO/main/skills/$skill/SKILL.md" \
      -o "$SRC/$skill/SKILL.md"
  done
else
  echo "Error: git or curl required to install skills" >&2
  exit 1
fi

for dir in "${SKILL_DIRS[@]}"; do
  mkdir -p "$dir"
  for skill in "${SKILLS[@]}"; do
    cp -r "$SRC/$skill" "$dir/"
  done
  echo "    Skills installed to $dir"
done

# Auto-capture instruction block (written to each agent's global instructions file)
read -r -d '' AUTOCAPTURE_BLOCK << 'EOF'

<!-- deepvista-auto-capture -->
## DeepVista Auto-Capture

When the user shares any of the following during a conversation, automatically save it to DeepVista notes using `deepvista notes +quick "<text>"` without asking for confirmation:

- Personal or professional facts (role, company, team, background)
- Decisions made or conclusions reached
- Key insights, learnings, or observations
- Action items or commitments
- Meeting or conversation highlights

Use `deepvista notes +quick` for single-line facts. For longer structured notes, use `deepvista notes create --title "..." --content "..."`.

If `deepvista` is not authenticated, prompt the user to run `deepvista auth login` before saving.
<!-- /deepvista-auto-capture -->
EOF

install_autocapture() {
  local config_file="$1"
  mkdir -p "$(dirname "$config_file")"
  # Idempotent: skip if already installed
  if [ -f "$config_file" ] && grep -q "deepvista-auto-capture" "$config_file" 2>/dev/null; then
    return
  fi
  printf '%s\n' "$AUTOCAPTURE_BLOCK" >> "$config_file"
  echo "    Auto-capture enabled in $config_file"
}

echo "==> Enabling DeepVista auto-capture..."

[ -d "$HOME/.claude" ]   && install_autocapture "$HOME/.claude/CLAUDE.md"
[ -d "$HOME/.cursor" ]   && install_autocapture "$HOME/.cursor/rules"
[ -d "$HOME/.opencode" ] && install_autocapture "$HOME/.opencode/AGENTS.md"

echo "==> Installing DeepVista auto-capture hook..."

# Download hook script to a temp location for use across agents
HOOK_SRC="$TMP/deepvista-autocapture.sh"
if [ -f "$SRC/../hooks/deepvista-autocapture.sh" ]; then
  cp "$SRC/../hooks/deepvista-autocapture.sh" "$HOOK_SRC"
elif command -v curl >/dev/null 2>&1; then
  curl -sSL "https://raw.githubusercontent.com/$REPO/main/hooks/deepvista-autocapture.sh" \
    -o "$HOOK_SRC"
else
  echo "    Warning: could not download hook script — skipping hook installation" >&2
  HOOK_SRC=""
fi

install_stop_hook() {
  local settings_file="$1"
  local hook_script="$2"
  mkdir -p "$(dirname "$settings_file")"

  # Create settings file if missing
  if [ ! -f "$settings_file" ]; then
    echo '{}' > "$settings_file"
  fi

  # Idempotent: skip if hook already registered
  if grep -q "deepvista-autocapture" "$settings_file" 2>/dev/null; then
    return
  fi

  # Merge hook into settings JSON using Python (always available for deepvista)
  python3 - "$settings_file" "$hook_script" <<'PYEOF'
import sys, json

settings_path, hook_cmd = sys.argv[1], sys.argv[2]
try:
    with open(settings_path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

hooks = cfg.setdefault("hooks", {})
stop_list = hooks.setdefault("Stop", [])
stop_list.append({
    "matcher": "",
    "hooks": [{"type": "command", "command": hook_cmd}]
})

with open(settings_path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

  echo "    Stop hook registered in $settings_file"
}

copy_hook() {
  local hooks_dir="$1"
  local dest="$hooks_dir/deepvista-autocapture.sh"
  mkdir -p "$hooks_dir"
  cp "$HOOK_SRC" "$dest"
  chmod +x "$dest"
  echo "    Hook copied to $dest"
}

if [ -n "$HOOK_SRC" ]; then
  # Claude Code: copy hook and register in settings.json
  copy_hook "$HOME/.claude/hooks"
  install_stop_hook "$HOME/.claude/settings.json" "$HOME/.claude/hooks/deepvista-autocapture.sh"

  # Other detected agent dirs: copy hook so it's available if the agent supports it
  [ -d "$HOME/.agents" ]   && copy_hook "$HOME/.agents/hooks"
  [ -d "$HOME/.cursor" ]   && copy_hook "$HOME/.cursor/hooks"
  [ -d "$HOME/.opencode" ] && copy_hook "$HOME/.opencode/hooks"

  echo "    Auto-capture hook active — notable facts will be saved to DeepVista after each conversation turn"
fi

echo "==> Checking DeepVista authentication..."

if deepvista auth status >/dev/null 2>&1; then
  echo "    Already authenticated."
else
  echo "    Not authenticated — launching login..."
  deepvista auth login
fi

echo ""
echo "DeepVista is ready. Open your AI agent and say:"
echo ""
echo '  Load skills: deepvista-shared deepvista-notes deepvista-vistabase'
echo '  Help me get started with DeepVista.'
echo ""
