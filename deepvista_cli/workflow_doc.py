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


def is_phase_server_routable(phase: PhaseInfo) -> bool:
    """Return True if every tool in this phase's plan is a DeepVista server tool.

    If the phase has no ``tool_plan`` at all, returns False — caller defaults
    such phases to host execution (the safe choice: the host has more
    capabilities, not fewer).
    """
    if not phase.tool_plan:
        return False
    return all(name in SERVER_ONLY_TOOLS for name in phase.tool_plan)
