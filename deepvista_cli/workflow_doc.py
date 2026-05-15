"""Parse and mutate a workflow Skill's SKILL.md body (`description`).

A workflow Skill body is a complete SKILL.md: YAML frontmatter, a mermaid
diagram, one ``<accordion>`` per phase, etc. The DeepVista server agent
mutates this body in place at run-time to reflect phase progress (see
``deepvista-skill-workflow/SKILL.md``). When a host agent (Claude Code /
OpenClaw / Cursor) drives the run via ``deepvista skill run --mode host``,
the same mutations need to happen client-side via the ``deepvista skill
phase ...`` CLI shims; this module is the parsing + mutation backbone.

Scope (v1):
- accordion attributes: open / checked
- mermaid node class markers: ``:::dvActive`` / ``:::dvDone`` / ``:::dvTodo``
- phase listing (parse accordion titles)
- ``phase_contract.tool_plan`` extraction for ``--mode auto`` routing
  (handles both new frontmatter contracts and legacy inline yaml blocks)

Out of scope (v1):
- Edge animation directive updates (``eN@{ animation: slow }``). Server-side
  runs continue to manage these; host-mode runs leave them static and the
  renderer falls back to a static diagram. The accordion + node-class
  invariants are sufficient for the frontend to show phase state.
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

# Mermaid class marker: ``...:::dvActive`` / ``:::dvDone`` / ``:::dvTodo`` /
# ``:::dvError``. We match the node label + the class so we can swap classes.
_MERMAID_NODE_CLASS_RE = re.compile(
    r"(?P<label_open>[\[\{\(])"
    r"(?P<label_text>[^\]\}\)]*?)"
    r"(?P<label_close>[\]\}\)])"
    r":::(?P<klass>dvActive|dvDone|dvTodo|dvError)"
)

# Fenced mermaid block.
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(?P<body>.*?)```", re.DOTALL)

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

    def open_phase(self, label: str) -> None:
        """Mark the accordion matching ``label`` as active (open + unchecked).

        All other accordions lose ``open="true"`` (their ``checked`` attr is
        preserved). The mermaid node whose label aligns with ``label`` gets
        its class marker set to ``:::dvActive``; the previously-active node
        (if any) is downgraded to ``:::dvDone`` — the assumption is that the
        caller has finished it before advancing. Use ``mark_phase_done``
        first if you want explicit ``done`` semantics on the prior phase.
        """
        if not self._has_phase(label):
            raise PhaseNotFoundError(label)

        self._body = _mutate_accordions(
            self._body,
            target_label=label,
            target_attrs={"checked": "false", "open": "true"},
        )
        # All non-target accordions lose ``open="true"``.
        self._body = _strip_open_from_other_accordions(self._body, keep_label=label)

        # Mermaid: previous active → dvDone, target → dvActive.
        self._body = _set_mermaid_class_for_label(self._body, label="*active*", new_klass="dvDone")
        self._body = _set_mermaid_class_for_label(self._body, label=label, new_klass="dvActive")

    def mark_phase_done(self, label: str) -> None:
        """Mark a phase complete: accordion checked, mermaid node ``dvDone``."""
        if not self._has_phase(label):
            raise PhaseNotFoundError(label)
        self._body = _mutate_accordions(self._body, target_label=label, target_attrs={"checked": "true"})
        self._body = _strip_open_from_other_accordions(self._body, keep_label=None)
        self._body = _set_mermaid_class_for_label(self._body, label=label, new_klass="dvDone")

    def append_artifact_block(self, label: str, card_id: str, card_type: str, title: str, summary: str) -> None:
        """Embed a ``<contextCardBlock>`` inside the named accordion's body.

        The block is inserted at the end of the accordion body (before the
        closing tag). Idempotent — calling with the same ``card_id`` again
        is a no-op.
        """
        if not self._has_phase(label):
            raise PhaseNotFoundError(label)
        block = (
            f'<contextCardBlock id="{card_id}" cardType="{card_type}" view="compact">\n'
            f"{title}\n{summary}\n"
            "</contextCardBlock>"
        )
        self._body = _append_to_accordion(self._body, label=label, block=block, dedupe_marker=f'id="{card_id}"')

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_phase(self, label: str) -> bool:
        return any(p.title == label for p in self.phases())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PhaseNotFoundError(ValueError):
    """Raised when a CLI command names a phase that's not in the workflow body."""

    def __init__(self, label: str) -> None:
        super().__init__(f"No accordion titled {label!r} found in workflow body")
        self.label = label


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


def _mutate_accordions(body: str, target_label: str, target_attrs: dict[str, str]) -> str:
    """Re-emit accordions, replacing the target accordion's attrs.

    Non-target accordions are left structurally intact; only the target's
    opening tag is rewritten so the merge between ``target_attrs`` and the
    existing attrs preserves attributes we don't touch (e.g. custom data-*).
    """

    def repl(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body_inner = match.group("body")
        title = _extract_phase_title(body_inner)
        if title != target_label:
            return match.group(0)
        new_attrs = _merge_attrs(attrs, target_attrs)
        return f"<accordion{new_attrs}>{body_inner}</accordion>"

    return _ACCORDION_RE.sub(repl, body)


def _strip_open_from_other_accordions(body: str, keep_label: str | None) -> str:
    """Drop ``open="true"`` from every accordion except the one matching ``keep_label``."""

    def repl(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body_inner = match.group("body")
        title = _extract_phase_title(body_inner)
        if keep_label is not None and title == keep_label:
            return match.group(0)
        new_attrs = _remove_attr(attrs, "open")
        return f"<accordion{new_attrs}>{body_inner}</accordion>"

    return _ACCORDION_RE.sub(repl, body)


def _merge_attrs(existing: str, updates: dict[str, str]) -> str:
    """Merge ``updates`` into the attribute string ``existing``.

    Existing attribute values are overwritten by ``updates``; attributes not
    in ``updates`` are preserved. The returned string starts with a single
    leading space so it can be re-spliced into ``<accordion{attrs}>``.
    """
    parts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', existing):
        key, val = m.group(1), m.group(2)
        if key in updates:
            val = updates[key]
        seen.add(key)
        parts.append((key, val))
    for key, val in updates.items():
        if key not in seen:
            parts.append((key, val))
    if not parts:
        return ""
    return " " + " ".join(f'{k}="{v}"' for k, v in parts)


def _remove_attr(existing: str, name: str) -> str:
    """Return ``existing`` with the ``name`` attribute (if any) removed."""
    cleaned = re.sub(rf'\s*{re.escape(name)}\s*=\s*"[^"]*"', "", existing)
    cleaned = cleaned.strip()
    return (" " + cleaned) if cleaned else ""


def _set_mermaid_class_for_label(body: str, label: str, new_klass: str) -> str:
    """Update the ``:::dvX`` class marker on the mermaid node aligned with ``label``.

    ``label`` may be the special sentinel ``"*active*"`` — matches whatever
    node is currently ``:::dvActive`` (used to demote the prior active node
    when opening a new phase).

    Matching is structural: the node label text either equals the accordion
    title or contains the phase prefix (``"Phase N:"`` / ``"Step N:"``).
    """
    blocks = list(_MERMAID_BLOCK_RE.finditer(body))
    if not blocks:
        return body

    def rewrite_node(node_match: re.Match[str], in_block: str) -> str | None:
        klass = node_match.group("klass")
        text = node_match.group("label_text").strip()
        if label == "*active*":
            if klass != "dvActive":
                return None
        else:
            if not _labels_align(text, label):
                return None
        # Rewrite the class only — keep label punctuation as-is.
        return (
            node_match.group("label_open")
            + node_match.group("label_text")
            + node_match.group("label_close")
            + ":::"
            + new_klass
        )

    new_body = body
    # Iterate blocks back-to-front so substring positions don't shift.
    for block in reversed(blocks):
        original = block.group("body")
        rewritten = _MERMAID_NODE_CLASS_RE.sub(
            lambda nm, original=original: rewrite_node(nm, original) or nm.group(0),
            original,
        )
        if rewritten != original:
            start, end = block.span("body")
            new_body = new_body[:start] + rewritten + new_body[end:]
    return new_body


def _labels_align(node_text: str, phase_title: str) -> bool:
    """Heuristic: does a mermaid node label correspond to a given accordion title?

    True if:
    - exact string equality after stripping wrapping quotes (case-insensitive), OR
    - both share the same ``Phase N:`` / ``Step N:`` prefix.
    """
    n = node_text.strip().strip('"').strip()
    p = phase_title.strip().strip('"').strip()
    if n.lower() == p.lower():
        return True
    n_prefix = _phase_prefix(n)
    p_prefix = _phase_prefix(p)
    return bool(n_prefix and n_prefix == p_prefix)


def _phase_prefix(text: str) -> str:
    """Return the ``Phase N`` / ``Step N`` / ``N.`` prefix, or empty string."""
    m = re.match(r"\s*(Phase\s+\d+|Step\s+\d+|\d+\.)\s*[:.]?", text, re.IGNORECASE)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip().lower()


def _append_to_accordion(body: str, label: str, block: str, dedupe_marker: str) -> str:
    """Insert ``block`` inside the named accordion's body, idempotently."""

    def repl(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body_inner = match.group("body")
        title = _extract_phase_title(body_inner)
        if title != label:
            return match.group(0)
        if dedupe_marker in body_inner:
            return match.group(0)
        new_body = body_inner.rstrip() + "\n\n" + block + "\n"
        return f"<accordion{attrs}>{new_body}</accordion>"

    return _ACCORDION_RE.sub(repl, body)


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
