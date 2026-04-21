# Create skills from a note

`deepvista skill create-from-note <note_id>` asks the DeepVista agent to read
a source note (podcast episode, interview transcript, book chapter, research
summary) and synthesize one or more skill cards grounded in the note's
content. Two kinds are produced by default:

- **`persona`** — captures the interviewee/author's voice, philosophy, and
  decision-making lens. When loaded, the agent responds in their voice and
  applies their frameworks.
- **`workflow`** — turns the frameworks or steps they shared into an
  executable workflow (inputs → phases → output template).

Streams NDJSON identical to `chat +send` and `skill run`. Each generated
skill is stored as a context card of `type=skill` in the user's project.

## Command

> [!CAUTION] Write — the agent creates skill cards in the user's project.
> Confirm before executing, or pass `--yes` for scripted/batch use.

```bash
deepvista skill create-from-note <note_id> \
  [--kind persona|workflow]... [--chat-id ID] [--yes] [--dry-run]
```

| Flag | Default | Purpose |
|---|---|---|
| `<note_id>` | required | UUID of the source note. Must exist in the caller's project. |
| `--kind KIND` | `persona` + `workflow` | Repeatable. Restrict to one kind, e.g. `--kind persona`. |
| `--chat-id ID` | — | Continue an existing synthesis session (iterate on the skills). |
| `--yes` / `-y` | off | Skip the confirmation prompt. Required for scripts and cron. |
| `--dry-run` | — | Print the prompt without calling the agent. |

## When to use

- You've captured a podcast episode / interview / book chapter as a note.
- You want a reusable persona or workflow skill extracted from it.
- You want to batch-convert a corpus (e.g. every Lenny's Podcast note tagged
  `lenny`, every FounderCoHo note tagged `foundercoho`) into installable
  skills.

## Batch pattern

There's no built-in bulk flag — use a shell loop. The `--yes` flag avoids
per-note confirmation prompts:

```bash
# Every note tagged "lenny" → persona + workflow skills
deepvista notes list --limit 100 \
  | jq -r '.notes[] | select(.tags | index("lenny")) | .id' \
  | while read -r note_id; do
      deepvista skill create-from-note "$note_id" --yes \
        >> ~/.config/deepvista/logs/skill-synthesis.log 2>&1
    done
```

For a narrower pass (only the workflow):

```bash
deepvista skill create-from-note <note_id> --kind workflow --yes
```

## After creation

Generated skills land with `status=unconfirmed`. Inspect each with
[`deepvista card get <card_id>`](vistabase-card.md) and verify the SKILL.md
body before running or exporting. See [skill-export-knowledge.md](skill-export-knowledge.md)
for turning a stored skill into a portable `SKILL.md` file.

## Examples

```bash
# Both kinds, interactive confirm
deepvista skill create-from-note 0d5d1fb2-7414-4593-abc4-fb74984f4b2f

# Persona only, scripted
deepvista skill create-from-note 0d5d1fb2-... --kind persona --yes

# Preview prompt
deepvista skill create-from-note 0d5d1fb2-... --dry-run

# Iterate on a prior synthesis
deepvista skill create-from-note 0d5d1fb2-... --chat-id gmrpoqqw
```

## See also

- [notes.md](notes.md) — capturing the source note (`deepvista notes create`
  with `--content-file`) and re-indexing.
- [skill.md](skill.md) — listing, running, exporting the generated skills.
- [skill-research-to-skill.md](skill-research-to-skill.md) — broader pattern
  (search → synthesize → run) when the source material spans multiple cards.
