"""Read-only parsing of a workflow Skill's SKILL.md body.

Provides phase listing and ``tool_plan`` extraction used by the CLI for
``--mode auto`` routing decisions. Phase mutations (open/done/reset) are
delegated to the server via ``POST /workflow_phase`` so all mutation logic
lives in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# Match a full <accordion ...>...</accordion> block, capturing attrs + body.
# Non-greedy body so multiple accordions in a body each match.
_ACCORDION_RE = re.compile(
    r"<accordion(?P<attrs>[^>]*)>(?P<body>.*?)</accordion>",
    re.DOTALL,
)

# Inside an accordion body, the phase title is the first non-empty line.
_PHASE_TITLE_LINE_RE = re.compile(r"^\s*(.+?)\s*$", re.MULTILINE)

# Inline ```yaml ... ``` block within an accordion body — legacy phase contract.
_INLINE_YAML_RE = re.compile(r"```yaml\n(?P<body>.*?)```", re.DOTALL)

# YAML frontmatter at the very top of the document (must start with `---`).
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n?", re.DOTALL)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class PhaseInfo:
    """Lightweight per-phase view used by ``--mode auto`` routing.

    Title is the accordion's first non-empty line. ``tool_plan`` is the
    flattened list of tool names this phase intends to use, drawn from
    either the document frontmatter's ``phase_contract`` (new spec) or
    the legacy inline ``\\`\\`\\`yaml`` block inside the accordion.
    Empty list means "no contract found" — caller decides the routing
    default.
    """

    index: int  # 1-based, matching "Phase N:" prose where present
    title: str
    state: str  # "pending" | "active" | "done"
    tool_plan: list[str]


@dataclass
class PreflightPhase:
    """Per-phase preflight view: likely inputs, permissions, expected output.

    All three fields are best-effort heuristics derived from the phase body
    (see :meth:`WorkflowDocument.analyze_preflight`). ``inputs`` is labelled
    heuristic because no formal ``inputs:`` metadata exists in v1.
    """

    index: int  # 1-based, mirrors PhaseInfo.index
    title: str
    inputs: list[str]  # heuristic placeholders / imperative cues, capped per phase
    permission: str  # human-readable permission requirement
    runs_on_deepvista: bool  # True => no local perms needed
    expected_output: str  # done_when contract if present, else falls back to title


@dataclass
class PreflightReport:
    """Structured result of :meth:`WorkflowDocument.analyze_preflight`."""

    phases: list[PreflightPhase]


# Permission labels reused by ``analyze_preflight`` and the CLI body renderer.
PERMISSION_SERVER = "runs on DeepVista (no local perms)"
PERMISSION_LOCAL = "needs local agent permissions"

# Cap on heuristic inputs surfaced per phase, so the summary stays scannable.
_MAX_INPUTS_PER_PHASE = 5

# Angle-bracket (``<...>``) and brace (``{{...}}``) placeholders in a phase body.
# Angle-bracket match is conservative: no whitespace-only or HTML-tag-like
# captures (those are accordion/markup, not input slots).
_BRACE_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_ANGLE_PLACEHOLDER_RE = re.compile(r"<([a-z0-9 _./-]{2,60})>", re.IGNORECASE)

# Imperative cues that signal the phase expects something from the user.
_INPUT_CUE_RE = re.compile(
    r"(?:provide|ask the user|prompt for|paste|specify)\b[^.\n]{0,80}",
    re.IGNORECASE,
)

# ``done_when:`` line(s) inside a yaml block — the phase's expected output.
_DONE_WHEN_RE = re.compile(r"^\s*done_when:\s*(?P<inline>.*)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Tool names that only the DeepVista server agent has (not the CLI)
# ---------------------------------------------------------------------------
# Source: deepvista-skill-workflow/SKILL.md `tool_plan` allowed values.
# A phase whose tool_plan is a subset of this set can be routed to /imagine;
# anything else stays host-local.
SERVER_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "chat_cypher_search",
        "grep_context_cards",
        "read_context_card",
        "find_similar_cards",
        "exa_search",
        "upsert_context_card",
        "edit_context_card",
        "enrich_card_entities",
        "load_skill",
        "run_skill",
        # NB: ``run_command`` is intentionally NOT here — it requires the
        # host agent's shell.
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class WorkflowDocument:
    """Mutable view of a workflow Skill's SKILL.md body."""

    def __init__(self, body: str) -> None:
        self._body = body

    @property
    def body(self) -> str:
        return self._body

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def phases(self) -> list[PhaseInfo]:
        """Return one ``PhaseInfo`` per ``<accordion>`` in document order."""
        result: list[PhaseInfo] = []
        # Map "Phase N: ..." → tool_plan from doc frontmatter, if any.
        fm_contracts = _parse_frontmatter_phase_contracts(self._body)

        for idx, match in enumerate(_ACCORDION_RE.finditer(self._body), start=1):
            attrs = match.group("attrs")
            body = match.group("body")
            title = _extract_phase_title(body)
            state = _state_from_accordion_attrs(attrs)

            tool_plan = _extract_inline_tool_plan(body)
            if not tool_plan:
                tool_plan = fm_contracts.get(title, [])

            result.append(PhaseInfo(index=idx, title=title, state=state, tool_plan=tool_plan))
        return result

    def active_phase(self) -> PhaseInfo | None:
        for p in self.phases():
            if p.state == "active":
                return p
        return None

    def first_pending_phase(self) -> PhaseInfo | None:
        for p in self.phases():
            if p.state == "pending":
                return p
        return None

    def analyze_preflight(self) -> PreflightReport:
        """Produce a best-effort preflight summary, one entry per phase.

        Pure / read-only: never mutates the document. For each ``<accordion>``
        phase it derives:

        - ``inputs`` — heuristic placeholders (``<...>`` / ``{{...}}``) and
          imperative cues ("provide", "ask the user", "prompt for", "paste",
          "specify") found in the phase body. Deduped, capped per phase.
        - ``permission`` — reuses ``tool_plan`` + ``is_phase_server_routable``:
          server-routable phases need no local perms; everything else needs
          local agent permissions.
        - ``expected_output`` — the phase's ``done_when`` contract if present,
          otherwise the phase title.
        """
        phase_infos = self.phases()
        bodies = [m.group("body") for m in _ACCORDION_RE.finditer(self._body)]

        out: list[PreflightPhase] = []
        for info, body in zip(phase_infos, bodies):
            server = is_phase_server_routable(info)
            done_when = _done_when_from_yaml_text(body)
            out.append(
                PreflightPhase(
                    index=info.index,
                    title=info.title,
                    inputs=_heuristic_inputs(body),
                    permission=PERMISSION_SERVER if server else PERMISSION_LOCAL,
                    runs_on_deepvista=server,
                    expected_output=done_when or info.title,
                )
            )
        return PreflightReport(phases=out)

    # ------------------------------------------------------------------
    # Mutate — accordions
    # ------------------------------------------------------------------

    def append_review(self, review_md: str) -> None:
        """Append a ``## Review`` section to the doc body if not already present.

        Idempotent: if a ``## Review`` heading exists, the new content is
        appended after the existing section instead of duplicating the
        heading.
        """
        if "## Review" in self._body:
            # Already has a Review section — append a separator + new content.
            self._body = self._body.rstrip() + "\n\n" + review_md.strip() + "\n"
        else:
            self._body = self._body.rstrip() + "\n\n## Review\n\n" + review_md.strip() + "\n"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_phase_title(accordion_body: str) -> str:
    """Return the first non-empty line of the accordion body (the phase title)."""
    for raw_line in accordion_body.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return ""


def _state_from_accordion_attrs(attrs: str) -> str:
    checked = _attr_value(attrs, "checked")
    is_open = _attr_value(attrs, "open") == "true"
    if checked == "true":
        return "done"
    if is_open:
        return "active"
    return "pending"


def _attr_value(attrs: str, name: str) -> str | None:
    """Extract the value of ``name`` from a string like ``checked="false" open="true"``."""
    m = re.search(rf'{re.escape(name)}\s*=\s*"([^"]*)"', attrs)
    return m.group(1) if m else None


def _extract_inline_tool_plan(accordion_body: str) -> list[str]:
    """Return the flattened tool names from any inline ```yaml``` block inside an accordion.

    Legacy parent workflows still embed the contract inline; new specs put
    it in frontmatter. This handles the legacy case.
    """
    yaml_match = _INLINE_YAML_RE.search(accordion_body)
    if not yaml_match:
        return []
    return _tool_plan_names_from_yaml_text(yaml_match.group("body"))


def _parse_frontmatter_phase_contracts(body: str) -> dict[str, list[str]]:
    """Parse the doc-level frontmatter and return ``{phase_label: [tool_names]}``.

    For child workflows the frontmatter carries a single ``phase_contract``
    (not multiple). The contract applies to whatever ``parent_phase`` the
    child is anchored to — we surface it under that label so a host-mode
    runner inspecting a child can route by it.
    """
    fm = _FRONTMATTER_RE.match(body)
    if not fm:
        return {}
    parent_phase = re.search(r'^\s*parent_phase:\s*"([^"]+)"', fm.group("body"), re.MULTILINE)
    if not parent_phase:
        return {}
    tools = _tool_plan_names_from_yaml_text(fm.group("body"))
    if not tools:
        return {}
    return {parent_phase.group(1): tools}


def _tool_plan_names_from_yaml_text(yaml_text: str) -> list[str]:
    """Extract tool names from a ``tool_plan:`` block in raw yaml text.

    Avoids pulling in PyYAML — the structure is well-known (`tool_plan:` then
    a flat list of ``- name: "..."`` mappings under it).
    """
    # Find the ``tool_plan:`` line and consume the indented block underneath.
    lines = yaml_text.splitlines()
    out: list[str] = []
    in_block = False
    block_indent: int | None = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        if not in_block:
            if stripped.startswith("tool_plan:"):
                in_block = True
                block_indent = len(line) - len(stripped)
            continue
        if not stripped:
            continue
        cur_indent = len(line) - len(stripped)
        if cur_indent <= (block_indent or 0):
            break
        # Entries look like ``- chat_cypher_search: "..."`` or ``- name: chat_cypher_search``.
        item_match = re.match(r"-\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
        if item_match:
            out.append(item_match.group(1))
    return out


def _heuristic_inputs(accordion_body: str) -> list[str]:
    """Best-effort guess at inputs a phase expects from the user.

    Combines two signals from the phase body, in document order:

    1. Placeholders: ``{{ name }}`` and ``<name>`` slots.
    2. Imperative cues: short snippets following "provide", "ask the user",
       "prompt for", "paste", "specify".

    Results are stripped, de-duplicated case-insensitively, and capped at
    ``_MAX_INPUTS_PER_PHASE``. These are heuristics, not a formal schema.
    """
    candidates: list[str] = []
    for m in _BRACE_PLACEHOLDER_RE.finditer(accordion_body):
        candidates.append("{{ " + m.group(1).strip() + " }}")
    for m in _ANGLE_PLACEHOLDER_RE.finditer(accordion_body):
        candidates.append("<" + m.group(1).strip() + ">")
    for m in _INPUT_CUE_RE.finditer(accordion_body):
        snippet = " ".join(m.group(0).split())
        if snippet:
            candidates.append(snippet)

    out: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        key = cand.lower()
        if cand and key not in seen:
            seen.add(key)
            out.append(cand)
        if len(out) >= _MAX_INPUTS_PER_PHASE:
            break
    return out


def _done_when_from_yaml_text(accordion_body: str) -> str:
    """Return the phase's ``done_when`` contract if present, else ``""``.

    Mirrors the lightweight, PyYAML-free extraction used for ``tool_plan``:
    finds the ``done_when:`` key inside any inline ```` ```yaml ```` block in
    the accordion and returns its value. Supports an inline scalar
    (``done_when: text``) or a block list of ``- item`` lines joined with
    "; ".
    """
    yaml_match = _INLINE_YAML_RE.search(accordion_body)
    yaml_text = yaml_match.group("body") if yaml_match else accordion_body

    m = _DONE_WHEN_RE.search(yaml_text)
    if not m:
        return ""

    inline = m.group("inline").strip().strip("\"'")
    if inline:
        return inline

    # Block form: collect ``- item`` lines indented under ``done_when:``.
    lines = yaml_text[m.end() :].splitlines()
    items: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        item_match = re.match(r"-\s*(.+)$", stripped)
        if item_match:
            items.append(item_match.group(1).strip().strip("\"'"))
        else:
            break
    return "; ".join(items)


def is_phase_server_routable(phase: PhaseInfo) -> bool:
    """Return True if every tool in this phase's plan is a DeepVista server tool.

    If the phase has no ``tool_plan`` at all, returns False — caller defaults
    such phases to host execution (the safe choice: the host has more
    capabilities, not fewer).
    """
    if not phase.tool_plan:
        return False
    return all(name in SERVER_ONLY_TOOLS for name in phase.tool_plan)
