#!/usr/bin/env bash
set -e

REPO="DeepVista-AI/deepvista-cli"

# Single consolidated skill (DV-385). Collapses the 12 legacy `deepvista-*`
# skills into one `deepvista/` skill + reference files.
SKILL="deepvista"

# Legacy skill directories to remove on upgrade so users don't end up with
# a mix of old and new.
LEGACY_SKILLS=(
  deepvista-shared
  deepvista-vistabase
  deepvista-vistabase-card
  deepvista-notes
  deepvista-skill
  deepvista-chat
  deepvista-persona-knowledge-worker
  deepvista-skill-research-to-skill
  deepvista-skill-export-knowledge
  deepvista-skill-analyze-notes
  deepvista-skill-import-files
  deepvista-openclaw
)

echo "==> Installing deepvista CLI..."

# Install uv if not present
if ! command -v uv >/dev/null 2>&1; then
  echo "    uv not found — installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Add uv to PATH for the rest of this script
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if command -v uv >/dev/null 2>&1; then
  # Remove broken tool environment before reinstalling (e.g. missing Python executable)
  uv tool uninstall deepvista-cli 2>/dev/null || true
  uv tool install --force "deepvista-cli[ui]"
elif command -v pipx >/dev/null 2>&1; then
  pipx install "deepvista-cli[ui]"
elif command -v pip3 >/dev/null 2>&1; then
  pip3 install --user "deepvista-cli[ui]"
elif command -v pip >/dev/null 2>&1; then
  pip install --user "deepvista-cli[ui]"
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
# OpenClaw: skills live in the workspace directory
[ -d "$HOME/.openclaw/workspace" ] && SKILL_DIRS+=("$HOME/.openclaw/workspace/skills")

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
else
  echo "Error: git required to install skills (the consolidated skill has multiple reference files; piecewise curl is no longer supported)" >&2
  exit 1
fi

for dir in "${SKILL_DIRS[@]}"; do
  mkdir -p "$dir"

  # Remove the legacy per-subcommand skills so users upgrading don't end up
  # with both the new consolidated skill and the old 12 entries.
  for legacy in "${LEGACY_SKILLS[@]}"; do
    if [ -e "$dir/$legacy" ]; then
      rm -rf "${dir:?}/$legacy"
      echo "    Removed legacy $dir/$legacy"
    fi
  done

  # Install (or replace) the consolidated skill.
  rm -rf "${dir:?}/$SKILL"
  cp -r "$SRC/$SKILL" "$dir/$SKILL"
  echo "    Skill installed to $dir/$SKILL"
done

# Auto-capture instruction block (written to each agent's global instructions file)
read -r -d '' AUTOCAPTURE_BLOCK << 'EOF' || true

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

# OpenClaw: install autocapture to workspace AGENTS.md
OPENCLAW_WORKSPACE="$HOME/.openclaw/workspace"
if [ -d "$OPENCLAW_WORKSPACE" ]; then
  install_autocapture "$OPENCLAW_WORKSPACE/AGENTS.md"
fi

# Skill interpretation rules block (written to each agent's global instructions file)
read -r -d '' SKILL_RULES_BLOCK << 'EOF' || true

<!-- deepvista-skill-rules -->
## Skill Interpretation Rules

When you load or invoke any skill, check its frontmatter for two fields: `type` and `execution`.

### Handling `type`

**`type: persona`**
Do not invoke this as a command. Load it as background context that shapes how you
behave for the rest of the session. Apply its tone, expertise, and decision patterns silently.

**`type: tool`**
Treat this as a discrete capability. Invoke it when the task calls for it and return
its result. No special handling needed.

**`type: workflow`**
Treat this as a self-contained sequence of steps. Work through them in order. Do not
mix steps from other skills into this sequence unless explicitly instructed.

### Handling `execution`

**`execution: stateless`**
Run freely. Retry on failure. No confirmation needed.

**`execution: stateful`**
Before executing, stop and do two things:
1. If the skill or its underlying command supports `--dry-run`, run that first and show the output.
2. Summarize what you are about to do and what will change, then ask for confirmation before proceeding.

Never skip this checkpoint for stateful skills, even if the task seems straightforward.

### Fallback rules
- If `type` is missing, use the information in the skill to guess its type.
- If `execution` is missing, treat as `stateful` and apply the checkpoint.
- If a workflow is stateful, treat all its steps as stateful unless they declare otherwise.
<!-- /deepvista-skill-rules -->
EOF

install_skill_rules() {
  local config_file="$1"
  mkdir -p "$(dirname "$config_file")"
  # Idempotent: skip if already installed
  if [ -f "$config_file" ] && grep -q "deepvista-skill-rules" "$config_file" 2>/dev/null; then
    return
  fi
  printf '%s\n' "$SKILL_RULES_BLOCK" >> "$config_file"
  echo "    Skill interpretation rules injected in $config_file"
}

echo "==> Injecting skill interpretation rules..."

[ -d "$HOME/.claude" ]   && install_skill_rules "$HOME/.claude/CLAUDE.md"
[ -d "$HOME/.cursor" ]   && install_skill_rules "$HOME/.cursor/rules"
[ -d "$HOME/.opencode" ] && install_skill_rules "$HOME/.opencode/AGENTS.md"

if [ -d "$OPENCLAW_WORKSPACE" ]; then
  install_skill_rules "$OPENCLAW_WORKSPACE/AGENTS.md"
fi

echo "==> Installing DeepVista auto-capture hook..."

# Write hook script directly (embedded) so installation works without network access
HOOK_SRC="$TMP/deepvista-autocapture.sh"
cat > "$HOOK_SRC" << 'HOOKEOF'
#!/usr/bin/env bash
# DeepVista Auto-Capture — Claude Code Stop Hook
# Saves notable user statements to DeepVista notes after each conversation turn.
# Install: referenced in ~/.claude/settings.json under hooks.Stop

# Set up PATH for common tool install locations
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

# Silently exit if deepvista is not installed
command -v deepvista >/dev/null 2>&1 || exit 0

# Read the hook payload from stdin
PAYLOAD=$(cat)

# Extract transcript path from payload JSON
TRANSCRIPT_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('transcript_path', ''))
except Exception:
    print('')
" 2>/dev/null || true)

[ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ] && exit 0

# Extract the last user message from the JSONL transcript
LAST_USER=$(TRANSCRIPT_PATH="$TRANSCRIPT_PATH" python3 - <<'PYEOF'
import sys, json, os

path = os.environ.get("TRANSCRIPT_PATH", "")
last_text = ""
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            # Support both flat {role, content} and nested {message: {role, content}} formats
            role = entry.get("role")
            content_raw = entry.get("content")
            if not role:
                msg = entry.get("message") or {}
                role = msg.get("role")
                content_raw = msg.get("content")
            if role != "user" or not content_raw:
                continue
            if isinstance(content_raw, str):
                last_text = content_raw
            elif isinstance(content_raw, list):
                parts = [
                    b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else ""
                    for b in content_raw
                ]
                last_text = " ".join(p for p in parts if p).strip()
except Exception:
    pass

# Truncate to avoid oversized notes
print(last_text[:1500] if last_text else "")
PYEOF
)

# Skip empty or trivially short messages
[ -z "$LAST_USER" ] || [ "${#LAST_USER}" -lt 20 ] && exit 0

# Only save messages that contain factual statements about the user, their work,
# decisions, or plans — skip pure questions and commands
LOWER=$(printf '%s' "$LAST_USER" | tr '[:upper:]' '[:lower:]')
printf '%s' "$LOWER" | grep -qE \
  "(i am|i'm |we are|we're |my |our |i have|we have|i don't|i do not|i like|i love|i hate|i prefer|decided|planning|going to|working on|we built|i built|the tool|the product|the company|we('re| are) building|i want to|we want to|it is |it's )" \
  || exit 0

# Save to DeepVista in background — non-blocking so Claude isn't delayed
deepvista notes +quick "$LAST_USER" >/dev/null 2>&1 &

exit 0
HOOKEOF

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
    echo "    Stop hook already registered in $settings_file"
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

# Claude Code: copy hook and register in settings.json
copy_hook "$HOME/.claude/hooks"
install_stop_hook "$HOME/.claude/settings.json" "$HOME/.claude/hooks/deepvista-autocapture.sh"

# Other detected agent dirs: copy hook so it's available if the agent supports it
[ -d "$HOME/.agents" ]   && copy_hook "$HOME/.agents/hooks"
[ -d "$HOME/.cursor" ]   && copy_hook "$HOME/.cursor/hooks"
[ -d "$HOME/.opencode" ] && copy_hook "$HOME/.opencode/hooks"

echo "    Auto-capture hook active — notable facts will be saved to DeepVista after each conversation turn"

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
echo '  Load skill: deepvista'
echo '  Help me get started with DeepVista.'
echo ""
