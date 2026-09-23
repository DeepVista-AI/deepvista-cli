# Skill — structured workflows

A Skill is a multi-step workflow the agent works through phase by phase.
Run `deepvista skill --help` or `deepvista skill <cmd> --help` for full flag reference.

## Commands

`list` · `get` · `run` · `phase` · `complete`
`create-from-note` · `sync` · `load`

## Agent conventions

> [!CAUTION] `run`, `phase`, `complete` are writes. Confirm first.

Read-only: `list`, `get`, `sync --dry-run`, `load`.

Show the app URL after writes: `https://app.deepvista.ai/skills/<id>`

## Executing a workflow skill — required sequence

> [!IMPORTANT] To run a workflow skill you **must** call `deepvista skill run <skill_id>` first. Do NOT call `skill get` and drive the phases manually — that skips the run record, phase tracking, and the host runtime contract entirely.

`skill run` does three things `skill get` does not:
1. Opens a run — a `run_log` card — and prints its `run_id` in the packet header.
2. Emits the host runtime contract that tells you to call the `skill phase` shims.
3. Indicates the `active_phase` so resumed runs continue from the right place.

**Required sequence for every workflow run:**

```bash
# 1. Open the run (emits run packet + host runtime contract; note the run_id)
deepvista skill run <skill_id>

# 2. For each phase — open → execute → done, always with the run_id
deepvista skill phase open <skill_id> "Phase N: <title>" --run-id <run_id>
# … execute the phase using your own tools …
deepvista skill phase done <skill_id> "Phase N: <title>" --run-id <run_id> [--next-phase "Phase N+1: <title>"]

# 3. Finalize
deepvista skill complete <skill_id> --run-id <run_id> --review "<3–6 retrospective bullets>"
```

> [!CAUTION] Never edit the workflow card (`<skill_id>`) during a run — it is the definition every run shares. All run state goes on the run card via `--run-id` (or `$DEEPVISTA_RUN_ID`). Without a run id the shims fall back to the pre-run-card behaviour of writing the workflow card.

If you called `skill get` and are already mid-workflow without a run, call `skill run` now. To continue a paused run, use the `resume_with` command it printed: `deepvista skill run <skill_id> --run-id <run_id>` — a bare `skill run` starts a separate run.

## Non-obvious: host-mode shims

After `skill run`, drive the run with (each takes `--run-id <run_id>`):

```bash
deepvista skill phase open       <skill_id> "Phase N: <title>"
deepvista skill phase done       <skill_id> "Phase N: <title>" [--artifact-card-id ID] [--next-phase "…"]
deepvista skill phase note       <skill_id> "Phase N: <title>" "<progress note>"
deepvista skill phase need-input <skill_id> "Phase N: <title>" --reason "<what's needed>"  # run waits on a person
deepvista skill phase pause      <skill_id> --reason "<sentence>"  # technical blocker → run waits where it stands
deepvista skill complete         <skill_id> --review "<3–6 retrospective bullets>" [--outcome error]
```

`complete` closes the run (done, or `--outcome error` for a run that cannot finish), records the review in the run's log, and emits `{"done": true}`. `phase reset` exists only for legacy run-less workflows; on a run, `phase open` the phase again instead.

## Non-obvious: `sync` and `load`

`sync` writes thin `SKILL.md` stubs (frontmatter + lazy-fetch shell) into the agent
skills directory. Safe in a `SessionStart` hook — always exits 0. Idempotent; only
touches dirs with the `x-deepvista-catalog` marker; never overwrites user-authored
skills.

`load` fetches the full SKILL.md body for a catalog skill at invocation time (5-min
cache). Called by stubs — rarely needed directly.

## Examples

```bash
deepvista skill list
deepvista skill run <skill_id> --input "Focus on Q4"
deepvista skill phase open <skill_id> "Phase 1: …" --run-id <run_id>
deepvista skill phase done <skill_id> "Phase 1: …" --run-id <run_id> --artifact-card-id <id>
deepvista skill complete <skill_id> --run-id <run_id> --review "clean run, shipped Friday"
deepvista skill sync --dry-run
```

## Importing a skill from a downloaded markdown file

When the user downloads a SKILL.md from another account and wants to import it
**without AI re-synthesis**, write the content directly as a `type=skill` card.
This is the right path when the markdown is already a complete, finished skill —
no processing needed.

> [!CAUTION] Write — confirm before running.

```bash
deepvista card create --type skill \
  --title "<Skill Name>" \
  --content-file /absolute/path/to/downloaded-skill.md \
  --no-enrich
```

`--no-enrich` skips entity enrichment. Use it here because the skill body is
already structured — enrichment would add latency and noise without value.

After creation, verify with:

```bash
deepvista card get <new_card_id>
# https://app.deepvista.ai/vistabase/<new_card_id>
```

Do **not** use `skill create-from-note` for this — that command runs the
DeepVista agent to synthesize a skill from raw notes, which is unnecessary
(and slow) when the SKILL.md content is already ready.

## See also

- [skill-create-from-note.md](skill-create-from-note.md) — synthesize a skill from notes
- [skill-research-to-skill.md](skill-research-to-skill.md) — research then run pattern
- [skill-analyze-notes.md](skill-analyze-notes.md) — notes synthesis pattern
- [vistabase-card.md](vistabase-card.md) — `card create` full flag reference
