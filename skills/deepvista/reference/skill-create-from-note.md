# Create a workflow skill from one or more notes

`deepvista skill create-from-note` asks the DeepVista agent to read one or more
source notes (podcast episodes, interview transcripts, book chapters, research
summaries) and synthesize a **workflow** skill grounded in their content.
Run `deepvista skill create-from-note --help` for full flag reference.

The generated skill is stored as a context card of `type=skill`, linked back to
every source note via `related_context_card_ids`. Streams NDJSON identical to
`chat +send`.

## Agent conventions

> [!CAUTION] Write — the agent creates skill cards in the user's project.
> Confirm before executing, or pass `--yes` for scripted/batch use.

## Finding source notes

Pass note UUIDs positionally or via repeated `--note-id` (union-merged,
de-duplicated, capped by `--limit N` — default 5, max 25). When you don't know
the IDs upfront, resolve them first with the card search commands and pass the
results here:

```bash
deepvista card +search "product-market fit signals" --type note --limit 5
deepvista card +search-content "DRI OR operating rhythm" --type note
deepvista card +similar <seed_note_id>
```

Use `--dry-run` to preview the synthesis prompt before spending tokens.

## Examples

```bash
# Single note
deepvista skill create-from-note 0d5d1fb2-7414-4593-abc4-fb74984f4b2f

# Multiple notes
deepvista skill create-from-note 0d5d1fb2-... 8a1f2c40-... --yes

# Pipe from a prior search
deepvista notes list --limit 100 \
  | jq -r '.notes[] | select(.title | test("positioning"; "i")) | .id' \
  | xargs deepvista skill create-from-note --yes

# Preview first
deepvista skill create-from-note 0d5d1fb2-... --dry-run
```

## After creation

Generated skills land with `status=unconfirmed`. Inspect with
[`deepvista card get <card_id>`](vistabase-card.md) and verify the SKILL.md
body before running.

## See also

- [notes.md](notes.md) — capturing source notes
- [skill.md](skill.md) — listing and running the generated skills
- [skill-research-to-skill.md](skill-research-to-skill.md) — broader search → synthesize → run pattern
