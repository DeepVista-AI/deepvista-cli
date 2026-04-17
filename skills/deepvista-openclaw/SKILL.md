---
name: deepvista-openclaw
description: DeepVista auto-capture and knowledge integration for OpenClaw agents. Automatically saves notable user statements, decisions, and insights to DeepVista knowledge base. Use when the user shares facts about themselves, their work, decisions, or plans.
---

# DeepVista Auto-Capture for OpenClaw

## Overview

This skill enables automatic knowledge capture from OpenClaw conversations into DeepVista.
When the user shares notable information during a conversation, save it to DeepVista without
asking for confirmation.

## Prerequisites

- `deepvista` CLI installed and authenticated (`deepvista auth status`)
- If not authenticated, prompt: `deepvista auth login`

## Auto-Capture Rules

### ALWAYS capture (no confirmation needed):

- Personal or professional facts: role, company, team, background
- Decisions made or conclusions reached
- Key insights, learnings, or observations
- Action items, commitments, or plans
- Meeting or conversation highlights
- Relationships between people (who works with whom, who met whom)
- Product/business strategy decisions
- Important dates, deadlines, milestones

### NEVER capture:

- Passwords, API keys, tokens, or secrets
- Pure questions with no factual content
- Small talk, greetings, acknowledgments
- Commands directed at the agent (e.g., "list my notes")

## How to Capture

For single-line facts or short insights:
```bash
deepvista notes +quick "<text>"
```

For longer structured content (meeting notes, analyses, multi-point insights):
```bash
deepvista notes create --title "<title>" --content "<markdown content>"
```

## Capture Format Guidelines

- Preserve the user's original wording when possible
- For decisions: include the decision AND the reasoning
- For people: include the relationship context (e.g., "Jing is working with Bruce Wang on a thesis")
- For meetings: structure as bullet points with key takeaways
- Keep notes concise — capture the essence, not the entire conversation

## Integration with OpenClaw Heartbeat

If configured in HEARTBEAT.md, this skill supports periodic knowledge base maintenance:
- Search for recent notes and check for duplicates
- Suggest merges for similar notes
- Flag outdated information

## Checking DeepVista Status

Before first capture in a session, verify authentication:
```bash
deepvista auth status
```

If token is expired, inform the user:
> DeepVista auth expired. Please run: `deepvista auth login` and share the code.
