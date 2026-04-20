# DeepVista Install Prompt

Copy and paste the prompt below into any AI agent (Claude Code, OpenCode, Cursor,
etc.) to configure DeepVista.

---

## First: Install

Run this once in your terminal:

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash
```

This installs the `deepvista` CLI and a single consolidated `deepvista` skill for
your agent — no Node or extra tools required. The skill ships with an index
(`SKILL.md`) plus one reference file per subcommand under `reference/`.

Alternative install paths:

```bash
gh skill install DeepVista-AI/deepvista-cli       # GitHub CLI (preview)
npx skills add DeepVista-AI/deepvista-cli         # skills.sh
```

---

## Then: Paste This Prompt Into Your Agent

```
Load skill: deepvista

Help me get started with DeepVista:

1. Check if the `deepvista` CLI is installed. If not, install it:
   - Preferred: `uv tool install deepvista-cli`
   - Fallback: `pip install deepvista-cli`

2. Run `deepvista auth status` to check if I'm already logged in.

3. If not logged in, run `deepvista auth login` to open the browser login page.
   Guide me through pasting the auth code when I'm ready.

4. Once logged in, confirm with `deepvista auth status` and show me the result.

5. Give me a quick summary of what I can do now — note capture, knowledge base
   search, Skill workflows, and note analysis. Point me at the right reference
   file inside the skill for each.
```

---

## What Gets Installed

| Skill | What it teaches your agent |
|-------|---------------------------|
| `deepvista` | Everything: auth, profiles, global flags, notes, cards, memory, chat, Skills, analyze/export/import, persona workflows, OpenClaw auto-capture |

All subcommand detail lives under `skills/deepvista/reference/` — the agent loads
the matching file on demand. Read the skill index for the full subcommand table.

---

## Quick Start Prompts

Once installed and authenticated, try these:

### Capture a note
```
Load skill: deepvista

Take a note: "Key insight from today's meeting — prioritize async workflows over sync for scale."
```

### Analyze your notes
```
Load skill: deepvista

Analyze my recent notes and tell me what themes keep coming up.
```

### Search your knowledge base
```
Load skill: deepvista

Search my knowledge base for everything I've captured about product strategy.
Show me the top 5 results.
```

### Run a Skill workflow
```
Load skill: deepvista

I want to synthesize patterns from my knowledge base. Find my Research Synthesis
Skill and run it — but show me what you find before running so I can confirm.
```

---

## Troubleshooting

**Skill reads require confirmation?**
Run once to allow it globally:
```bash
claude config set allowedPaths "~/.claude/skills" --global
```

**Skill not found?**
Re-run the install command:
```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash
```

**Still seeing legacy `deepvista-*` skills?**
The installer removes the 12 legacy skills on upgrade (see DV-385), but if they're
still around, remove them manually:
```bash
rm -rf ~/.claude/skills/deepvista-*
rm -rf ~/.agents/skills/deepvista-*
```

**Auth issues?**
```bash
deepvista auth logout
deepvista auth login
```
