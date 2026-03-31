# DeepVista CLI — Agent & Human Guide

DeepVista is a knowledge base for people who think for a living. The CLI lets you capture, search, and synthesize knowledge from the terminal — and ships with agent skills so AI assistants (Claude Code, OpenCode, and others) can use your knowledge base on your behalf.

---

## Table of Contents

- [Install the CLI](#install-the-cli)
- [Install Skills for AI Agents](#install-skills-for-ai-agents)
- [Load Skills in Your Agent](#load-skills-in-your-agent)
- [Authenticate](#authenticate)
- [Core Concepts](#core-concepts)
- [Use Case 1 — Capture Insights from Podcasts](#use-case-1--capture-insights-from-podcasts)
- [Use Case 2 — Research to VistaBook Workflow](#use-case-2--research-to-vistabook-workflow)
- [Use Case 3 — Build a Founder Playbook with AI](#use-case-3--build-a-founder-playbook-with-ai)
- [VistaBook Patterns](#vistabook-patterns)
- [Tips for AI Agents](#tips-for-ai-agents)

---

## Install the CLI

```bash
# Recommended: uv tool (isolated, system-wide)
uv tool install --prerelease=allow deepvista-cli

# pip
pip install --pre deepvista-cli

# pipx
pipx install deepvista-cli --pip-args="--pre"
```

Verify:

```bash
deepvista --version
```

---

## Install Skills for AI Agents

Skills are SKILL.md files that teach your AI agent the DeepVista CLI — commands, auth conventions, security rules, and recipes.

```bash
npx skills add DeepVista-AI/deepvista-cli --yes
```

This installs 8 skills into `~/.claude/skills/` (or your agent's skills directory):

| Skill | Purpose |
|-------|---------|
| `deepvista-shared` | Auth, global flags, security rules |
| `deepvista-vistabase` | Knowledge base cards — CRUD + search |
| `deepvista-notes` | Quick note capture |
| `deepvista-vistabook` | Structured workflow templates + AI-run execution |
| `deepvista-chat` | Conversational AI agent |
| `deepvista-persona-knowledge-worker` | Daily knowledge workflow persona |
| `deepvista-recipe-research-to-vistabook` | Search → synthesize → run workflow |
| `deepvista-recipe-export-knowledge-as-skills` | Export knowledge as installable skills |

---

## Load Skills in Your Agent

### Claude Code

```
/skills deepvista-shared deepvista-vistabase deepvista-notes deepvista-vistabook
```

Or load all DeepVista skills at once:

```
/skills deepvista-shared deepvista-notes deepvista-vistabase deepvista-vistabook deepvista-chat deepvista-persona-knowledge-worker
```

### OpenCode

OpenCode picks up skills from `~/.agents/skills/` automatically. Run `npx skills add` from your home directory and they'll be available in all sessions.

### Allow skill reads (Claude Code)

If Claude Code prompts you to confirm skill file reads, add the skills path to allowed paths once:

```bash
claude config set allowedPaths "~/.claude/skills" --global
```

---

## Authenticate

```bash
# Step 1: open browser login page
deepvista auth login

# Step 2: after logging in, paste the command shown in the browser
deepvista auth login --code <base64_code>

# Check auth state
deepvista auth status
```

### Profiles for different environments

```bash
# Register a staging profile
deepvista config set staging --api-url https://api-staging.deepvista.ai

# Use it with any command
deepvista --profile staging auth login
deepvista --profile staging notes list
```

Credentials are stored per profile at `~/.config/deepvista/credentials.{profile}.json` — staging and production sessions never interfere.

---

## Core Concepts

**Cards** are the unit of knowledge. Every note, contact, topic, or insight is a card stored in your VistaBase.

**Notes** are cards with free-form markdown content — the fastest way to capture an idea.

**VistaBooks** are structured workflow templates. When you run a VistaBook, the AI agent works through its checklist step by step, reading your knowledge base and producing output.

**Profiles** map a name to an API URL, so `--profile staging` always hits your staging backend.

---

## Use Case 1 — Capture Insights from Podcasts

> **Scenario:** You've been listening to [Lenny's Podcast](https://github.com/ChatPRD/lennys-podcast-transcripts) and want to build a searchable knowledge base from founder interviews.

### Capture a note from an episode

After listening to Brian Chesky's episode on founder mode:

```bash
deepvista notes create \
  --title "Brian Chesky — Founder Mode" \
  --content "# Key Insights

- CEOs who operate in 'manager mode' lose touch with what's actually happening
- Founder mode means staying deeply involved in details — not micromanaging, but knowing
- 'Skip-level' meetings: Chesky talks directly to individual contributors, bypasses middle layers
- Airbnb's turnaround (2020 COVID): cut to essentials, rediscovered product obsession
- Best managers he's had were people deeply passionate about the work, not professional managers

## Memorable quote
'I learned that great founders don't just set vision and delegate. They stay in the arena.'

Source: Lenny's Podcast"
```

Capture another from Drew Houston on focus:

```bash
deepvista notes create \
  --title "Drew Houston — The Tennis Ball Theory" \
  --content "# Key Insights

- Successful founders are obsessed like a dog chasing a tennis ball — not motivated by money or status
- Dropbox survived because Drew was solving his own problem; deep personal understanding of the user
- Focus: pick one thing per quarter that matters. Everything else is distraction.
- 'Don't worry about failure. Worry about the things you don't try.'

Source: Lenny's Podcast"
```

### Search your knowledge base

```bash
# Find all notes on founder mindset
deepvista vistabase +search "founder obsession focus"

# Find insights on product thinking
deepvista vistabase +search "product iteration user feedback"

# Find similar cards to one you're reading
deepvista vistabase +similar <card_id>
```

### Quick capture during a session

```bash
# One-liner note while ideas are fresh
deepvista notes +quick "Tobi Lütke: 'The company is a tool to amplify your ability to do what you love' — not the destination, the instrument"
```

---

## Use Case 2 — Research to VistaBook Workflow

> **Scenario:** You've captured 20 founder interviews. Now you want the AI agent to synthesize patterns across them and produce a structured insight report.

This follows the `deepvista-recipe-research-to-vistabook` pattern.

### Step 1 — Search for relevant cards

```bash
# Find everything about growth and momentum
deepvista vistabase +search "growth momentum startup" --limit 10

# Find hiring and team patterns
deepvista vistabase +search "hiring team culture" --limit 10
```

### Step 2 — Find the right VistaBook

```bash
deepvista vistabook list
```

Look for a workflow like "Synthesize Research" or "Founder Patterns Report".

### Step 3 — Run the VistaBook with context

```bash
deepvista vistabook +run <vistabook_id> \
  --input "Synthesize patterns from my Lenny's Podcast notes. Focus on:
  1. What separates high-growth founders from average ones
  2. Common mistakes in the 0→1 phase
  3. Patterns in how great founders think about product"
```

Output streams as NDJSON — the agent works through the checklist live.

### Step 4 — Check run status

```bash
deepvista vistabook +status <run_chat_id>
```

### Step 5 — Continue the conversation

```bash
deepvista chat +send "Expand on the product section — give me 3 concrete frameworks I can apply" \
  --chat-id <run_chat_id>
```

---

## Use Case 3 — Build a Founder Playbook with AI

> **Scenario:** Inspired by [Sam Altman's Startup Playbook](https://playbook.samaltman.com/), you want to build your own personalised version grounded in the podcasts you've consumed and your own experience.

Sam Altman's playbook covers four areas: **Idea → Team → Product → Execution**. You can use DeepVista to build a living version of this for yourself.

### Capture the framework as knowledge cards

```bash
# Capture the idea validation framework
deepvista notes create \
  --title "Startup Playbook — Idea Validation" \
  --content "# What makes a fundable idea (Sam Altman)

- Can you explain it simply? Complexity is a red flag
- Are you the target user, or do you know them intimately?
- Is there an emerging technology shift this rides?
- Small market that will become large > large market that's mature
- Novel insight > derivative solution

## From Lenny interviews — patterns I've seen
- Brian Chesky: deeply personal problem (he was the customer)
- Drew Houston: scratching his own itch (lost USB drive → Dropbox)
- Tobi Lütke: built Shopify because no good e-commerce existed for his snowboard shop"

# Capture the execution framework
deepvista notes create \
  --title "Startup Playbook — Execution Principles" \
  --content "# Execution (Sam Altman + Lenny founder patterns)

## Momentum
- Never let it die — momentum is oxygen for an org
- Pick ONE growth metric; run the whole company toward it
- Share metrics internally; transparency aligns people

## Focus
- Say no constantly
- Speed beats perfect analysis
- Avoid early-success traps: press, conferences, personal brand

## Hiring
- Delay hiring — complexity compounds
- Great people are infectious; mediocre hires rarely improve
- Fire toxic people regardless of performance

## From Lenny interviews
- Molly Graham: 'Give away your legos' — let people own pieces as you scale
- Julie Zhuo: first-time managers underestimate how much communication is needed
- Claire Hughes Johnson: write down how you work — explicit operating principles scale"
```

### Design a VistaBook workflow

A VistaBook for "New Idea Evaluation" might have phases like:

```
Phase 1 — Problem clarity
  □ Can you explain the problem in one sentence?
  □ Who has this problem? How often? How painfully?
  □ What do they do today to solve it?

Phase 2 — Founder-market fit
  □ Why are you the right person to solve this?
  □ Do you have deep insight others don't?

Phase 3 — Market
  □ What's the minimum believable market size?
  □ What technology shift enables this now?

Phase 4 — Validation signal
  □ What's the smallest thing you can build to learn the most?
  □ Who are your first 10 users and how will you get them?
```

Build this in the DeepVista web app, then run it for any new idea:

```bash
# Find your idea evaluation VistaBook
deepvista vistabook list

# Run it with a specific idea as context
deepvista vistabook +run <vistabook_id> \
  --input "Idea: a CLI tool that lets developers query their observability stack in natural language.
  I work in DevOps, I've felt this pain daily for 3 years.
  Market: all companies running microservices on Kubernetes (~50k+ teams)."
```

### Export as a reusable skill

Once your VistaBook works well, export it so your agent can invoke it directly:

```bash
deepvista vistabook +export <vistabook_id> --format skill > idea-evaluator-skill.md
```

---

## VistaBook Patterns

VistaBooks shine for recurring, structured work. Some patterns to consider building:

| Pattern | Description |
|---------|-------------|
| **Research synthesis** | Search KB → read top cards → produce structured report |
| **Idea evaluation** | Run checklist against a new idea using founder frameworks |
| **Weekly review** | Surface pinned cards, capture the week's key learnings |
| **Interview debrief** | Structured questions → knowledge card creation |
| **Competitive analysis** | Search for a company/space → produce landscape summary |
| **Decision memo** | Structured thinking on a hard decision, grounded in your KB |

---

## Tips for AI Agents

When using the DeepVista skills with Claude Code or OpenCode:

**Read before write.** Always search before creating — avoid duplicates.

```
Search my knowledge base for anything on "founder mode" before creating a new note.
```

**Use profiles explicitly.** Tell the agent which environment you're on.

```
Use --profile staging for all commands today.
```

**Confirm writes.** The skills mark write commands with `[!CAUTION]` — your agent will ask before executing. This is intentional.

**Stream VistaBook runs.** When an agent runs a VistaBook, output comes as streaming NDJSON. Tell the agent to display progress as it arrives.

**Chain operations.** The agent can search → read → run a VistaBook in one shot with the `deepvista-recipe-research-to-vistabook` skill loaded.

```
Load my deepvista-vistabase and deepvista-vistabook skills, then search for everything
I've captured about "product-market fit", synthesize the patterns, and run my
"Research Synthesis" VistaBook with that context.
```

---

## See Also

- [skills/](./skills/) — All SKILL.md files, installable via `npx skills add`
- [deepvista.ai](https://deepvista.ai) — Web app to build and manage VistaBooks
- [PyPI](https://pypi.org/project/deepvista-cli/) — Package releases
- [GitHub Issues](https://github.com/DeepVista-AI/deepvista-cli/issues) — Bug reports and feature requests
