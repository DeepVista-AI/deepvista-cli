---
license: Apache-2.0
name: deepvista
description: |
  DeepVista CLI — knowledge base, notes, chat, skills, and memory from the terminal.
  One skill for the full `deepvista` CLI. Load when the user wants to: take a note, jot
  this down, save a fact, or list and edit notes; create, search, pin, archive, edit,
  or grep knowledge-base cards of any type (person, topic, file, note, todo…); view or
  semantic-search implicit memory ("vistabase" / "memory"); chat with the AI agent or
  manage sessions; list, run, export, install, or discover Skills; research then run a
  Skill with synthesized context; analyze / summarize notes; import a folder as file
  cards; run a knowledge-worker daily loop; auto-capture facts (OpenClaw); periodically
  lint the vistabase for duplicates / contradictions / stale claims / orphans / missing
  refs / gaps; or re-index notes to trigger entity extraction. Pick the matching
  reference file in `reference/` for the subcommand.
metadata:
  openclaw:
    category: service
    requires:
      bins:
        - deepvista
    install:
      - kind: uv
        package: deepvista-cli
        bins: [deepvista]
    homepage: https://cli.deepvista.ai
    cliHelp: "deepvista --help"
---

# DeepVista CLI

> Your second brain, from the terminal. Chat, notes, skills, knowledge base, and memory —
> one skill for the whole CLI. Pick the reference file for the subcommand you need.

## Before you start

Read [reference/shared.md](reference/shared.md) — it covers authentication, profiles,
global flags, exit codes, and the "global flags come BEFORE the resource" rule. Every
other reference file assumes you know it.

## Subcommand index

| Subcommand | Use when | Reference |
|---|---|---|
| `deepvista auth` / `agents` / `config` / `upgrade` / `ui` | authenticating, registering an agent, switching profiles, checking for updates | [shared.md](reference/shared.md) |
| `deepvista notes` | taking a note, jotting something down, listing / updating / deleting notes, quick-capture of a single-line fact, re-indexing notes for entity extraction | [notes.md](reference/notes.md) |
| `deepvista lint` | periodic LLM health check over the vistabase — duplicates, contradictions, stale claims, orphans, missing cross-references, data gaps | [lint.md](reference/lint.md) |
| `deepvista card` | creating / searching / pinning / archiving / grepping knowledge base cards across any type (person, topic, file, note, todo, etc.) | [vistabase-card.md](reference/vistabase-card.md) |
| `deepvista vistabase` (alias: `memory`) | viewing or semantic-searching implicit memory accumulated from chat | [vistabase.md](reference/vistabase.md) · [memory.md](reference/memory.md) |
| `deepvista chat` | sending a message to the AI agent, listing / deleting chat sessions, continuing a conversation | [chat.md](reference/chat.md) |
| `deepvista skill` | listing, running, exporting, installing, discovering, or **catalog-syncing** (`sync` / `load`) structured Skill workflows | [skill.md](reference/skill.md) |
| — analyze notes | searching → reading → synthesizing notes to surface themes / patterns | [skill-analyze-notes.md](reference/skill-analyze-notes.md) |
| — research → run | finding context in the knowledge base, then running a Skill with synthesized input | [skill-research-to-skill.md](reference/skill-research-to-skill.md) |
| — export | exporting a DeepVista Skill as a portable `SKILL.md` file for another agent | [skill-export-knowledge.md](reference/skill-export-knowledge.md) |
| — create from note | synthesizing a persona + workflow skill from a podcast / interview / book note; batch-converting a corpus | [skill-create-from-note.md](reference/skill-create-from-note.md) |
| — import files | recursively importing a local folder as `type=file` cards | [skill-import-files.md](reference/skill-import-files.md) |
| persona: knowledge worker | daily workflow — check pinned cards, capture insights, run a Skill, ask the agent to synthesize | [persona-knowledge-worker.md](reference/persona-knowledge-worker.md) |
| auto-capture for OpenClaw | automatically saving notable facts from conversations without confirmation | [openclaw.md](reference/openclaw.md) |

## On load — update check

Silently run this once when the skill is loaded:

```bash
deepvista upgrade check 2>/dev/null || true
```

The command is cached (~1 hour TTL) so repeated invocations are cheap.

| stdout | Exit | What to do |
|---|---|---|
| *(empty)* | 0 | Up to date, snoozed, disabled, or network unreachable — say nothing. |
| `JUST_UPGRADED <old> <new>` | 0 | Briefly confirm: "deepvista-cli upgraded to `<new>`." |
| `UPGRADE_AVAILABLE <old> <new>` | 1 | Tell the user and offer `deepvista upgrade` — it fetches the changelog between `<old>` and `<new>` and prompts before installing. Snooze with `deepvista upgrade snooze`; disable with `deepvista upgrade disable`. |

If `deepvista` is not on `PATH`, skip silently — do not attempt to install it automatically.

## Install

```bash
uv tool install 'deepvista-cli[ui]'
# or
pip install 'deepvista-cli[ui]'
```

Then authenticate:

```bash
deepvista auth login       # opens browser
deepvista auth status      # verify
```

Full instructions: [reference/shared.md](reference/shared.md).

## Conventions agents must follow

1. **Confirm before any write.** Commands marked `> [!CAUTION]` in each reference file
   create, update, or delete data. Describe what will happen, then ask before running.
   Use `--dry-run` (supported on every stateful command) to preview first.
2. **Show the app URL after writes.** Surface a clickable link so the user can verify:
   - notes → `https://app.deepvista.ai/notes/<id>`
   - cards → `https://app.deepvista.ai/vistabase?contextId=<id>`
   - skills → `https://app.deepvista.ai/skills/<id>`
3. **Use `--content-file` for non-trivial content.** Never paste large content,
   files, or URLs inline — pass `--content-file <absolute-path>` (or `--content-file -`
   to read from stdin) so the exact bytes are stored.
4. **Read-only commands are safe.** `list`, `get`, `+search`, `+grep`, `+similar`,
   `show`, `discover`, `export`, `status` — run without confirmation.

## See also

- Homepage: https://cli.deepvista.ai
- Repo: https://github.com/DeepVista-AI/deepvista-cli
- Install: `uv tool install deepvista-cli` · `pip install deepvista-cli` · `gh skill install DeepVista-AI/deepvista-cli`
