# Bundle `deepvista-cli` PyPI package with its skill — portable skill + optional Claude Code plugin wrapper

## Context

Today `deepvista-cli` ships two artifacts from a single `v*` git tag:

- **PyPI wheel** (`deepvista-cli`) — the Python CLI, installed via `pipx`/`uv tool install`/`pip`.
- **Agent skill** (`skills/deepvista/`) — published via `gh skill publish`, copied into
  `~/.claude/skills/deepvista/`, `~/.cursor/skills/deepvista/`, `~/.opencode/skills/deepvista/`,
  `~/.openclaw/workspace/skills/deepvista/`, etc.

The two artifacts are decoupled: the skill assumes the `deepvista` binary is ambient on PATH
(documented in `skills/deepvista/reference/shared.md` with a `pipx install deepvista-cli` hint,
and declared in SKILL.md `metadata.openclaw.requires.bins: [deepvista]`), but there is no
version pin, no install-check, and no bootstrap. Users do a two-step install. Skill
v0.1.2 running against CLI v0.0.9 is a silent footgun.

**Research findings** (full report lives in the agent transcript; key points):

- Anthropic's own skills (pdf/docx/pptx/xlsx) delegate dependency handling to the agent at
  use time because they run in a controlled server sandbox — not safe to copy for a
  third-party PyPI CLI.
- The canonical 2026 answer inside Claude Code is **plugins** (`.claude-plugin/plugin.json`)
  with `bin/` auto-on-PATH, SessionStart hooks, and `.mcp.json`. But **plugins are Claude
  Code proprietary** — Gemini CLI, OpenClaw, Cursor, OpenCode don't read `plugin.json`.
- `gh skill` is now built into the official GitHub CLI (v2.90.0+, April 2026) but does
  **no** post-install bootstrap — it is a file copy.
- `uvx --from <pkg>==<ver> <bin> …` is universally available on any host with `uv` and works
  from any agent's Bash tool — cross-agent-portable, version-pinned, no prior install.

**Goal**: ship both artifacts from a single git tag with a **single install touchpoint per
user** and **zero skill↔CLI version drift**, while keeping the skill portable across all
agents that honor the agentskills.io spec.

**Non-goals**:
- Rewriting the CLI as an MCP server (Pattern C) — separate future initiative.
- Dropping PyPI distribution — power users still want `pipx install deepvista-cli` for
  interactive shell use.
- Dropping `gh skill publish` / `install.sh` — stays the cross-agent distribution path.

## Approach

Two-phase change landed in the same PR (or two sequential PRs off the same release):

1. **Phase 1 — Pin CLI version in the portable skill via `uvx`.** Every `deepvista …`
   invocation in SKILL.md and reference files becomes
   `uvx --from deepvista-cli==<version> deepvista …`. Release CI substitutes
   `<version>` into a placeholder at publish time, so the skill shipped from tag `v0.1.3`
   always calls `deepvista-cli==0.1.3`. Works in every agent that can run Bash. Eliminates
   drift. Users without `uv` installed get a clean error from `uvx`.
2. **Phase 2 — Add an opt-in Claude Code plugin wrapper** in the same repo. Thin plugin
   that re-exports the existing `skills/deepvista/` tree, adds a `bin/deepvista` shim +
   `SessionStart` uv bootstrap (venv under `${CLAUDE_PLUGIN_DATA}`), and is published to
   the plugin marketplace on the same `v*` tag. Claude Code users get `/plugin install
   deepvista` — one command, skill and CLI ready. Other agents are unaffected.

### Phase 1 — File-level changes

**Source of truth for the version**: `pyproject.toml` `version` field. Release CI already
reads it; extend that step to template the skill files.

- `skills/deepvista/SKILL.md` — replace every `deepvista <subcmd>` in shell snippets with
  `{{DEEPVISTA_INVOKE}} <subcmd>`. At publish time the CI replaces `{{DEEPVISTA_INVOKE}}`
  with `uvx --from deepvista-cli=={version} deepvista`. Also add a "Prerequisites" section
  noting that `uv` must be installed and linking to [astral.sh/uv](https://astral.sh/uv).
- `skills/deepvista/reference/*.md` — same placeholder substitution. 13 files under
  `reference/` (shared.md, notes.md, chat.md, skill.md, vistabase.md, vistabase-card.md,
  memory.md, openclaw.md, persona-knowledge-worker.md, skill-analyze-notes.md,
  skill-research-to-skill.md, skill-export-knowledge.md, skill-import-files.md).
- `scripts/release/template_skill.py` (new, ~30 LoC) — called from CI:
  `uv run python scripts/release/template_skill.py --version "$VERSION" --in skills/deepvista
   --out dist/skills/deepvista`. Writes a pinned copy; the source tree keeps the
  `{{DEEPVISTA_INVOKE}}` placeholder so repo edits stay version-agnostic.
- `.github/workflows/publish.yml` — in the `publish-github-skills` job, run
  `template_skill.py` before `gh skill publish` and point publish at `dist/skills/deepvista`.
- `.github/workflows/ci.yml` — the `gh skill publish --dry-run` validation currently runs
  against `skills/deepvista/`. Extend it to first materialize the pinned version into
  `dist/skills/deepvista` with a fake `0.0.0-dev` version so the dry-run sees a valid
  command, not a `{{DEEPVISTA_INVOKE}}` placeholder.
- `install.sh` — update the "skill lives at" path and the auto-capture snippet it injects
  into `~/.claude/CLAUDE.md` (and the equivalents for Cursor/OpenCode/OpenClaw) to use
  `uvx --from deepvista-cli deepvista notes +quick "…"` instead of bare `deepvista`.
  (Keep bare `deepvista` as a fallback when the binary is on PATH — the auto-capture block
  should prefer whichever is faster.)
- `skills/deepvista/reference/shared.md` lines 5–10 — replace the `uv tool install
  'deepvista-cli[ui]'` install block with a shorter "you don't need to install anything —
  the CLI runs on-demand via uvx. For interactive use, you can optionally install with
  `pipx install deepvista-cli`." section.

### Phase 2 — Claude Code plugin wrapper

All new files live at the repo root alongside `skills/`:

```
.claude-plugin/
  plugin.json            # name=deepvista, version=X.Y.Z (from pyproject.toml)
  marketplace.json       # single-plugin marketplace for direct install
bin/
  deepvista              # bash shim: exec "${CLAUDE_PLUGIN_DATA}/.venv/bin/deepvista" "$@"
hooks/
  hooks.json             # SessionStart diff-trigger uv sync
requirements.txt         # deepvista-cli[ui]==X.Y.Z (rewritten by release CI)
```

Files in detail:

- `.claude-plugin/plugin.json` — minimal: `name`, `version` (filled from `pyproject.toml`
  at release), `description`, `skills: ["./skills/deepvista"]`, `bin: "./bin"`,
  `hooks: "./hooks/hooks.json"`. Reuses the existing skill tree — no duplication.
- `.claude-plugin/marketplace.json` — so `/plugin marketplace add
  DeepVista-AI/deepvista-cli` works without us registering with
  `anthropics/claude-plugins-official` first. Mirrors the pattern in
  [anthropics/skills/.claude-plugin/marketplace.json](https://github.com/anthropics/skills/blob/main/.claude-plugin/marketplace.json).
- `bin/deepvista` — short shell shim. On first run the venv may not exist yet (e.g., if
  `SessionStart` didn't fire in a `--plugin-dir` dev session; see
  [anthropics/claude-code#11509](https://github.com/anthropics/claude-code/issues/11509)),
  so the shim should `uv sync` inline if `${CLAUDE_PLUGIN_DATA}/.venv/bin/deepvista`
  doesn't exist, then `exec` the binary. ~10 lines of bash.
- `hooks/hooks.json` — `SessionStart` hook modeled on the canonical diff-based bootstrap
  from the plugin reference:
  ```json
  {"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":
    "diff -q \"${CLAUDE_PLUGIN_ROOT}/requirements.txt\" \"${CLAUDE_PLUGIN_DATA}/requirements.txt\" >/dev/null 2>&1 || (mkdir -p \"${CLAUDE_PLUGIN_DATA}\" && cd \"${CLAUDE_PLUGIN_DATA}\" && uv venv .venv && cp \"${CLAUDE_PLUGIN_ROOT}/requirements.txt\" . && uv pip install --python .venv/bin/python -r requirements.txt) || rm -f \"${CLAUDE_PLUGIN_DATA}/requirements.txt\""
  }]}]}}
  ```
- `requirements.txt` — templated at release: `deepvista-cli[ui]==<X.Y.Z>`. The same
  `scripts/release/template_skill.py` handles this substitution (rename to
  `template_release.py` to reflect broader scope).
- `.github/workflows/publish.yml` — add a `publish-claude-plugin` job that runs after PyPI
  publish (so the version is resolvable on PyPI when users install) and in parallel with
  `publish-github-skills`. The plugin "publish" is a git push — plugins are distributed by
  git URL + tag — so the job just validates the plugin structure with `/plugin validate`
  (or a hand-written JSON schema check) and updates the release notes to mention the
  plugin install command.

### README + docs updates

- `README.md` — add a third install path **above** the current two:
  > **Recommended for Claude Code users**: `/plugin marketplace add
  > DeepVista-AI/deepvista-cli && /plugin install deepvista@deepvista-cli` — one command,
  > skill + CLI bootstrapped automatically on first session.
  Keep the existing `pipx install` + `gh skill install` paths labeled as "For Cursor /
  OpenCode / OpenClaw / Gemini CLI users" and "For manual install".
- `CLAUDE.md` (project) — add a note under "After editing skill files" that edits touch
  both the portable skill AND the Claude Code plugin surface, and that version
  substitution is automatic at release time so `{{DEEPVISTA_INVOKE}}` placeholders should
  be preserved in the source tree.
- `CHANGELOG.md` — entry describing the new plugin channel and the version-pin behavior.

## Critical files to modify

| File | Change type |
|------|-------------|
| `skills/deepvista/SKILL.md` | edit — replace `deepvista` with `{{DEEPVISTA_INVOKE}}` placeholder |
| `skills/deepvista/reference/*.md` (13 files) | edit — same placeholder substitution |
| `scripts/release/template_release.py` | **new** — ~40 LoC, stdlib only |
| `.github/workflows/publish.yml` | edit — new `publish-claude-plugin` job; call template step in existing skill-publish job |
| `.github/workflows/ci.yml` | edit — extend skill dry-run to materialize `0.0.0-dev` template |
| `install.sh` | edit — switch auto-capture snippet to `uvx`-based invocation; keep bare `deepvista` fallback |
| `.claude-plugin/plugin.json` | **new** |
| `.claude-plugin/marketplace.json` | **new** |
| `bin/deepvista` | **new** — bash shim, 10 lines, `chmod +x` |
| `hooks/hooks.json` | **new** — SessionStart diff-bootstrap |
| `requirements.txt` | **new** — templated at release time |
| `README.md` | edit — add plugin install path as primary recommendation |
| `CLAUDE.md` | edit — document placeholder convention + plugin repo layout |
| `CHANGELOG.md` | edit — release notes |
| `pyproject.toml` | no change — `version` stays the single source of truth |
| `skills/deepvista/reference/shared.md` | edit — rewrite install section (lines 5–10) |

## Existing utilities to reuse (not reinvent)

- **Semver conversion logic in `publish.yml` lines 107–118** — PEP 440 → semver translator
  for pre-release tags. The new plugin job reuses the same translated version for
  `plugin.json`, so `0.1.3a1` publishes as plugin version `0.1.3-alpha.1`.
- **`gh skill publish --dry-run`** already gated in CI — covers the portable skill. New
  plugin validation piggybacks by running in the same validation job.
- **`install.sh` agent-directory sweep** (lines 68–96) — already handles multi-agent copy.
  Keep it; just update the commands it injects.
- **Upgrade-check cadence** (`deepvista upgrade check`, ~1h cache) — already called from
  SKILL.md on load. Complements the pin: user sees a "newer version available" nag when
  the skill pins an older one.

## Verification

End-to-end test per channel:

1. **Portable skill (any agent)** — in a clean shell:
   ```bash
   uv tool install gh  # if gh not present
   gh skill install DeepVista-AI/deepvista-cli@v0.1.3-test
   # In Claude Code / Cursor / OpenCode: load deepvista skill, run the notes example.
   # Verify `uvx --from deepvista-cli==0.1.3 deepvista notes list` runs and returns output.
   rm -rf ~/.cache/uv  # force a cold cache
   # Re-run skill action; uvx resolves + runs without prior pipx install.
   ```
2. **Claude Code plugin** — in a clean Claude Code profile:
   ```bash
   # In Claude Code:
   /plugin marketplace add DeepVista-AI/deepvista-cli
   /plugin install deepvista@deepvista-cli
   /restart
   # SessionStart fires, uv sync materializes .venv at ${CLAUDE_PLUGIN_DATA}/.venv.
   # In a Bash tool call: `deepvista --version` resolves via bin/ shim.
   ```
   Then verify the diff-trigger: edit `requirements.txt` in the cached plugin, bump a
   test version, restart, and confirm the hook re-runs `uv pip install`.
3. **Version drift check**:
   ```bash
   grep -r 'deepvista-cli==' dist/skills/deepvista/ | grep -v "==$VERSION" && echo "DRIFT" || echo "OK"
   ```
   CI asserts OK before `gh skill publish`.
4. **Pre-release path**: push tag `v0.1.3a1`, verify:
   - PyPI gets `0.1.3a1`
   - GitHub Release + `gh skill publish` get `v0.1.3-alpha.1`
   - Plugin `plugin.json` version = `0.1.3-alpha.1`
   - `requirements.txt` inside the plugin pins `deepvista-cli==0.1.3a1`
5. **Multi-agent smoke**: manually test `install.sh` against a fresh macOS + Ubuntu VM;
   confirm Cursor, OpenCode, OpenClaw all see the pinned `uvx` invocation in their auto-
   capture blocks.

## Known risks and mitigations

- **`uv` not installed on user's host** → `uvx` returns `command not found`. Mitigation:
  SKILL.md "Prerequisites" section + `install.sh` already auto-installs `uv`.
- **Cold-cache `uvx` first-run latency** (2–5 s on slow networks). Mitigation: the
  optional plugin wrapper pre-warms via SessionStart; portable-skill users accept the
  one-time cost. Document in SKILL.md.
- **`SessionStart` hook doesn't fire in local `--plugin-dir` dev mode**
  ([anthropics/claude-code#11509](https://github.com/anthropics/claude-code/issues/11509)).
  Mitigation: `bin/deepvista` shim does a lazy `uv sync` if the venv is missing. Slower
  first Bash call in dev, but correct.
- **PyPI publish delay** — the plugin pins `deepvista-cli==X.Y.Z`, so if a user installs
  the plugin faster than PyPI replication, `uv pip install` fails. Mitigation: CI orders
  `publish-pypi` → wait → `publish-claude-plugin` (already sequential in the proposed
  workflow) and adds a 60 s PyPI availability poll before the plugin job declares success.
- **Increased source-tree noise** — skill source files now contain `{{DEEPVISTA_INVOKE}}`
  placeholders that render oddly in GitHub web preview. Mitigation: add a
  `skills/deepvista/README.md` (3 lines) explaining the placeholder and pointing at
  `scripts/release/template_release.py`.
