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

echo ""
echo "DeepVista is ready. Open your AI agent and say:"
echo ""
echo '  Load skills: deepvista-shared deepvista-notes deepvista-vistabase'
echo '  Help me get started with DeepVista.'
echo ""
