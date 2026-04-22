# Create skills from one or more notes

`deepvista skill create-from-note` asks the DeepVista agent to read one or more
source notes (podcast episodes, interview transcripts, book chapters, research
summaries) and synthesize skill cards grounded in their content. Two kinds are
produced by default:

- **`persona`** — captures the interviewee/author's voice, philosophy, and
  decision-making lens. When loaded, the agent responds in their voice and
  applies their frameworks.
- **`workflow`** — turns the frameworks or steps they shared into an
  executable workflow (inputs → phases → output template).

Streams NDJSON identical to `chat +send` and `skill run`. Each generated
skill is stored as a context card of `type=skill`, linked back to every
source note via `related_context_card_ids`.

## Command

> [!CAUTION] Write — the agent creates skill cards in the user's project.
> Confirm before executing, or pass `--yes` for scripted/batch use.

```bash
deepvista skill create-from-note [NOTE_ID]...
  [--note-id UUID]...
  [--from-file PATH | -]
  [--from-search QUERY]
  [--from-similar SEED_NOTE_ID]
  [--from-tag TAG]
  [--from-grep REGEX]
  [--limit N]
  [--kind persona|workflow]...
  [--chat-id ID] [--yes] [--dry-run]
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `NOTE_ID...` | — | Zero or more positional source-note UUIDs. Back-compat: a single positional keeps the exact legacy prompt. |
| `--note-id UUID` | — | Repeatable alternative to positional IDs (friendlier in scripts). |
| `--from-file PATH` | — | Read one ID per line from a file. `#` lines and blank lines are ignored. Pass `-` for stdin. |
| `--from-search QUERY` | — | Hybrid vector + keyword search over notes (same backend as `card +search`). |
| `--from-similar SEED` | — | Graph-style neighbours: notes similar to a seed note by title + snippet. |
| `--from-tag TAG` | — | All notes whose `tags` list contains TAG (client-side filter over the latest 200 notes). |
| `--from-grep REGEX` | — | Notes whose content matches a regex (via `/grep_context_cards`). |
| `--limit N` | `5` (max 25) | Cap on resolved source notes so the synthesis prompt stays within the agent's usable context. |
| `--kind KIND` | `persona` + `workflow` | Repeatable. Restrict to one kind, e.g. `--kind persona`. |
| `--chat-id ID` | — | Continue an existing synthesis session (iterate on the skills). |
| `--yes` / `-y` | off | Skip the confirmation prompt. Required for scripts and cron. |
| `--dry-run` | — | Resolve the source notes and print the prompt without calling the agent. |

All selectors compose. Positional + `--note-id` + every `--from-*` flag are
union-merged and de-duplicated, capped by `--limit`.

## When to use

- You've captured one or more podcast episodes / interviews / book chapters
  as notes and want a reusable persona or workflow skill extracted.
- You want to synthesize across notes — e.g. three Lenny episodes on
  positioning → a single positioning workflow — not one skill per episode.
- You want to batch-convert a corpus (e.g. every note tagged `lenny`) into
  installable skills.

## Usage patterns

### 1. Single note — unchanged

```bash
deepvista skill create-from-note 0d5d1fb2-7414-4593-abc4-fb74984f4b2f
```

### 2. Multiple notes pinned by hand

```bash
deepvista skill create-from-note \
  0d5d1fb2-... 8a1f2c40-... 4f9e6b17-... \
  --kind workflow --yes
```

### 3. Pipe from a prior search

```bash
# Every note matching "positioning" → one synthesized workflow skill
deepvista notes list --limit 100 \
  | jq -r '.notes[] | select(.title | test("positioning"; "i")) | .id' \
  | deepvista skill create-from-note --from-file - --kind workflow --yes
```

### 4. Semantic selector — no prior IDs needed

```bash
deepvista skill create-from-note \
  --from-search "product-market fit signals" \
  --limit 5 --kind workflow --yes
```

### 5. Graph expansion from a seed

```bash
# Start from one great Lenny episode → synthesize across its neighbours.
deepvista skill create-from-note \
  --from-similar 0d5d1fb2-... --limit 4 --yes
```

### 6. Tag corpus rollup

```bash
# One skill that distills everything you've captured from Lenny's Podcast.
deepvista skill create-from-note --from-tag lenny --limit 10 --yes
```

### 7. Regex selector for ad-hoc corpora

```bash
deepvista skill create-from-note --from-grep "DRI|operating rhythm" --yes
```

### 8. Preview first

```bash
deepvista skill create-from-note --from-tag lenny --limit 5 --dry-run
```

The dry-run output includes `resolved_notes` (every ID + title the agent
will see) and the full `user_instruction` — inspect before spending tokens.

## After creation

Generated skills land with `status=unconfirmed`. Inspect each with
[`deepvista card get <card_id>`](vistabase-card.md) and verify the SKILL.md
body before running or exporting. See
[skill-export-knowledge.md](skill-export-knowledge.md) for turning a stored
skill into a portable `SKILL.md` file.

## See also

- [notes.md](notes.md) — capturing the source notes (`deepvista notes create`
  with `--content-file`) and re-indexing.
- [skill.md](skill.md) — listing, running, exporting the generated skills.
- [skill-research-to-skill.md](skill-research-to-skill.md) — broader pattern
  (search → synthesize → run) when the source material spans multiple cards.
