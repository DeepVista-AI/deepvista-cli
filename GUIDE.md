# DeepVista — Agent Usage Guide

DeepVista is a knowledge base for people who think for a living. This guide shows you how to use DeepVista through AI agents — Claude Code, OpenCode, and any other agent that supports skills.

The key idea: **install the skills once, then talk to your agent**. The agent handles CLI installation, authentication, and all commands on your behalf.

---

## Table of Contents

- [Step 1 — Install Skills](#step-1--install-skills)
- [Step 2 — Open Your Agent and Get Started](#step-2--open-your-agent-and-get-started)
- [Use Case 1 — Capture Insights from Podcasts](#use-case-1--capture-insights-from-podcasts)
- [Use Case 2 — Research and Synthesize with a VistaBook](#use-case-2--research-and-synthesize-with-a-vistabook)
- [Use Case 3 — Build a Founder Playbook](#use-case-3--build-a-founder-playbook)
- [VistaBook Patterns](#vistabook-patterns)
- [CLI Reference](#cli-reference)

---

## Step 1 — Install Skills

Install the DeepVista skills globally so they're available in every agent session:

```bash
cd ~ && npx skills add DeepVista-AI/deepvista-cli --yes
```

This installs 8 skills into `~/.claude/skills/` (Claude Code) or `~/.agents/skills/` (OpenCode and others). That's it — no CLI to install manually, no config to write.

**Skills installed:**

| Skill | What it teaches your agent |
|-------|---------------------------|
| `deepvista-shared` | Auth, profiles, global flags, security rules |
| `deepvista-vistabase` | Knowledge base — search, read, create, update cards |
| `deepvista-notes` | Quick note capture |
| `deepvista-vistabook` | Run structured AI workflows |
| `deepvista-chat` | Conversational AI agent |
| `deepvista-persona-knowledge-worker` | Daily knowledge workflow patterns |
| `deepvista-recipe-research-to-vistabook` | Search → synthesize → run workflow |
| `deepvista-recipe-export-knowledge-as-skills` | Turn your knowledge into installable skills |

---

## Step 2 — Open Your Agent and Get Started

Open Claude Code (or your agent) and load the skills, then ask it to set everything up:

```
Load skills: deepvista-shared deepvista-notes deepvista-vistabase deepvista-vistabook

Help me get started with DeepVista. Install the CLI if needed, then walk me through logging in.
```

Your agent will:
1. Check if `deepvista` is installed; install it via `pip` or `uv` if not
2. Open the browser login page
3. Guide you through pasting the auth code
4. Confirm you're logged in with `deepvista auth status`

> **Claude Code tip:** If you're prompted to confirm skill file reads, run once:
> ```bash
> claude config set allowedPaths "~/.claude/skills" --global
> ```

---

## Use Case 1 — Capture Insights from Podcasts

> Build a searchable knowledge base from founder interviews — [Lenny's Podcast](https://www.lennysnewsletter.com/podcast) is a great starting point.

### Capture an episode

After listening to an episode, ask your agent:

```
Load skills: deepvista-shared deepvista-notes

I just listened to the Lenny's Podcast episode with Brian Chesky about founder mode.
Here are my notes:

- CEOs in "manager mode" lose touch with what's actually happening in the product
- Founder mode means staying in the details — not micromanaging, but knowing
- Skip-level meetings: he talks directly to ICs, bypasses middle layers
- Airbnb COVID turnaround: cut to essentials, rediscovered product obsession
- "Great founders don't just set vision and delegate. They stay in the arena."

Save this to my knowledge base as a note titled "Brian Chesky — Founder Mode".
```

Try another:

```
Load skills: deepvista-shared deepvista-notes

Save a note called "Drew Houston — The Tennis Ball Theory" with these insights from his Lenny's interview:

- Obsessed founders chase the problem like a dog chasing a tennis ball — not for money or status
- Dropbox survived because he was solving his own problem; that gave him user insight nobody else had
- Focus: pick one thing per quarter that actually matters
- "Don't worry about failure. Worry about the things you don't try."
```

### Search and retrieve

```
Load skills: deepvista-shared deepvista-vistabase

Search my knowledge base for everything I've captured about founder mindset and obsession.
Show me the top 5 results.
```

```
Search my knowledge base for insights on product iteration and user feedback loops.
Find any cards similar to the most relevant result.
```

### Quick capture mid-session

```
Quick note: "Tobi Lütke on Lenny's — the company is a tool to amplify your ability to do what you love. Not the destination, the instrument."
```

---

## Use Case 2 — Research and Synthesize with a VistaBook

> You've captured 10–20 founder interviews. Now ask your agent to synthesize patterns across them.

### Single prompt — full workflow

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook deepvista-recipe-research-to-vistabook

I want to synthesize patterns from the founder interviews I've captured in my knowledge base.

1. Search for cards about growth, momentum, and early-stage execution
2. Search for cards about hiring and team building
3. Find my "Research Synthesis" VistaBook (or the most relevant one)
4. Run it with context focused on: what separates high-growth founders, common 0→1 mistakes, and how great founders think about product

Show me what you find before running the VistaBook so I can confirm.
```

The agent searches, reads your notes, finds the VistaBook, confirms with you, then streams the run live.

### Follow up after the run

```
The VistaBook run just completed. Continue the conversation and ask the agent:
expand on the product section — give me 3 concrete frameworks I can apply this week.
```

```
That synthesis was great. Save the key conclusions as a new note called
"Founder Pattern Synthesis — [today's date]" so I can reference it later.
```

---

## Use Case 3 — Build a Founder Playbook

> Inspired by [Sam Altman's Startup Playbook](https://playbook.samaltman.com/), build your own living version — grounded in the podcasts you've consumed and your own experience.

Sam Altman's playbook covers four areas: **Idea → Team → Product → Execution**. DeepVista helps you build a personalised version of each.

### Capture the frameworks

```
Load skills: deepvista-shared deepvista-notes

I want to build a personal founder playbook. Start by saving two notes:

Note 1 — "Startup Playbook: Idea Validation":
Key questions from Sam Altman's playbook:
- Can you explain the idea simply? Complexity is a red flag
- Are you the target user, or do you know them intimately?
- Is there an emerging technology shift this rides?
- Small market becoming large > mature large market
- Novel insight > derivative solution

From Lenny's podcast patterns:
- Brian Chesky: deep personal problem — he was the customer
- Drew Houston: scratching his own itch (lost USB → Dropbox)
- Tobi Lütke: built Shopify because no good e-commerce existed for his snowboard shop

Note 2 — "Startup Playbook: Execution Principles":
From Sam Altman + Lenny founder patterns:
- Momentum: pick ONE growth metric, run the whole company toward it
- Focus: say no constantly; speed beats perfect analysis
- Hiring: delay it — each person adds complexity; great people are infectious
- Fire toxic people regardless of performance; culture is defined by who stays
- "Do things that don't scale" early, optimize later

From Lenny's — specific:
- Molly Graham: "Give away your legos" — let people own pieces as you scale
- Julie Zhuo: first-time managers underestimate how much communication is needed
- Claire Hughes Johnson: write down how you work — explicit operating principles scale
```

### Run an idea evaluation workflow

```
Load skills: deepvista-shared deepvista-vistabase deepvista-vistabook

I have a new startup idea I want to evaluate against my founder playbook.

Idea: a CLI tool that lets developers query their observability stack in natural language.
Context: I work in DevOps, I've felt this pain daily for 3 years. Market: all companies
running microservices (~50k+ teams globally).

1. Search my knowledge base for any idea validation frameworks I've captured
2. Find my idea evaluation VistaBook
3. Run it with the above context — but show me the VistaBook first so I can review it
```

### Export your playbook as a reusable skill

Once your knowledge is rich enough, export it so any agent can use it:

```
Load skills: deepvista-shared deepvista-vistabook deepvista-recipe-export-knowledge-as-skills

Export my founder playbook VistaBook as a SKILL.md file so I can share it with my team.
```

---

## VistaBook Patterns

Build these workflows in the DeepVista web app, then invoke them through your agent:

| VistaBook | Prompt to invoke |
|-----------|-----------------|
| **Research synthesis** | "Search my KB for [topic] and run my Research Synthesis VistaBook" |
| **Idea evaluation** | "Evaluate this idea against my founder frameworks: [idea]" |
| **Weekly review** | "Run my weekly review — surface pinned cards and capture this week's key learnings" |
| **Interview debrief** | "I just finished a user interview. Run my Interview Debrief VistaBook with these notes: [notes]" |
| **Decision memo** | "Help me think through this decision using my knowledge base: [decision]" |
| **Competitive analysis** | "Run a competitive analysis on [company/space] using everything I've captured" |

---

## CLI Reference

The agent handles all of this for you, but here it is for reference.

### Auth

```bash
deepvista auth login                    # open browser
deepvista auth login --code <code>      # paste code from browser
deepvista auth status                   # check state
deepvista auth logout                   # clear credentials
```

### Profiles

```bash
deepvista config set staging --api-url https://api-staging.deepvista.ai
deepvista --profile staging auth login
deepvista config list
```

### Notes

```bash
deepvista notes create --title "..." --content "..."
deepvista notes +quick "one-liner note"
deepvista notes list
deepvista notes get <id>
```

### Knowledge base

```bash
deepvista vistabase +search "query" --limit 10
deepvista vistabase +similar <card_id>
deepvista vistabase get <card_id>
deepvista vistabase list --type note
```

### VistaBooks

```bash
deepvista vistabook list
deepvista vistabook +run <id> --input "context"
deepvista vistabook +status <run_chat_id>
deepvista vistabook +export <id> --format skill
```

### Global flags

```bash
deepvista --profile <name>    # use a named profile
deepvista --api-url <url>     # override API endpoint
deepvista --format table      # human-readable output
deepvista --dry-run           # preview without executing
deepvista --verbose           # show HTTP details
```

---

## See Also

- [skills/](./skills/) — SKILL.md files, installable via `npx skills add`
- [deepvista.ai](https://deepvista.ai) — Web app to build and manage VistaBooks
- [PyPI](https://pypi.org/project/deepvista-cli/) — Package releases
- [GitHub Issues](https://github.com/DeepVista-AI/deepvista-cli/issues) — Bug reports and feature requests
