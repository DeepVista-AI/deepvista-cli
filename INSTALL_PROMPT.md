# DeepVista Install Prompt

Copy and paste the prompt below into any AI agent (Claude Code, OpenCode, Cursor, etc.) to configure DeepVista.

---

## First: Install

Run this once in your terminal:

```bash
curl -sSL https://raw.githubusercontent.com/DeepVista-AI/deepvista-cli/main/install.sh | bash
```

This installs the `deepvista` CLI and all 9 skills for your agent — no Node or extra tools required.

---

## Then: Paste This Prompt Into Your Agent

```
Load skills: deepvista-shared deepvista-notes deepvista-vistabase deepvista-vistabook deepvista-chat deepvista-persona-knowledge-worker deepvista-recipe-research-to-vistabook deepvista-recipe-export-knowledge-as-skills deepvista-recipe-analyze-notes

Help me get started with DeepVista:

1. Check if the `deepvista` CLI is installed. If not, install it:
   - Preferred: `uv tool install deepvista-cli`
   - Fallback: `pip install deepvista-cli`

2. Run `deepvista auth status` to check if I'm already logged in.

3. If not logged in, run `deepvista auth login` to open the browser login page.
   Guide me through pasting the auth code when I'm ready.

4. Once logged in, confirm with `deepvista auth status` and show me the result.

5. Give me a quick summary of what I can do now — note capture, knowledge base search, VistaBook workflows, and note analysis.
```

---

## What Gets Installed

| Skill | What it teaches your agent |
|-------|---------------------------|
| `deepvista-shared` | Auth, profiles, global flags, security rules |
| `deepvista-vistabase` | Knowledge base — search, read, create, update cards |
| `deepvista-notes` | Note capture and management |
| `deepvista-vistabook` | Run structured AI workflows |
| `deepvista-chat` | Conversational AI agent |
| `deepvista-persona-knowledge-worker` | Daily knowledge workflow patterns |
| `deepvista-recipe-research-to-vistabook` | Search → synthesize → run workflow |
| `deepvista-recipe-export-knowledge-as-skills` | Turn your knowledge into installable skills |
| `deepvista-recipe-analyze-notes` | Analyze, summarize, and find patterns across notes |

---

## Quick Start Prompts

Once installed and authenticated, try these:

### Capture a note
```
Load skills: deepvista-shared deepvista-notes

Take a note: "Key insight from today's meeting — prioritize async workflows over sync for scale."
```

### Analyze your notes
```
Load skills: deepvista-shared deepvista-notes deepvista-vistabase deepvista-recipe-analyze-notes

Analyze my recent notes and tell me what themes keep coming up.
```

### Search your knowledge base
```
Load skills: deepvista-shared deepvista-vistabase

Search my knowledge base for everything I've captured about product strategy.
Show me the top 5 results.
```

### Run a VistaBook workflow
```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook deepvista-recipe-research-to-vistabook

I want to synthesize patterns from my knowledge base. Find my Research Synthesis VistaBook
and run it — but show me what you find before running so I can confirm.
```

---

## Troubleshooting

**Skill reads require confirmation?**
Run once to allow it globally:
```bash
claude config set allowedPaths "~/.claude/skills" --global
```

**Skills not found?**
Re-run the install command:
```bash
cd ~ && npx skills add DeepVista-AI/deepvista-cli --yes
```

**Auth issues?**
```bash
deepvista auth logout
deepvista auth login
```
