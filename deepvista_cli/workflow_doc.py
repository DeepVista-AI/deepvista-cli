"""Read-only parsing of a workflow Skill's SKILL.md body.

Provides phase listing for host-mode run packets. Phase mutations
(open/done/reset) are delegated to the server via ``POST /workflow_phase``
so all mutation logic lives in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Match a full <accordion ...>...</accordion> block, capturing attrs + body.
# Non-greedy body so multiple accordions in a body each match. The backend
# normalizes phase accordions to the chevron-only `<accordion-plain>` variant
# (DV-1084), so accept both spellings — without `-plain` the close tag
# `</accordion-plain>` never matched `</accordion>`, so `phases()` came back
# empty and `tasks run --host` couldn't emit packets for normalized skills.
_ACCORDION_RE = re.compile(
    r"<accordion(?:-plain)?(?P<attrs>[^>]*)>(?P<body>.*?)</accordion(?:-plain)?>",
    re.DOTALL,
)


@dataclass
class PhaseInfo:
    """Lightweight per-phase view emitted in the host run packet."""

    index: int  # 1-based, matching "Phase N:" prose where present
    title: str
    state: str  # "pending" | "active" | "done"


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
        for idx, match in enumerate(_ACCORDION_RE.finditer(self._body), start=1):
            attrs = match.group("attrs")
            body = match.group("body")
            title = _extract_phase_title(body)
            state = _state_from_accordion_attrs(attrs)
            result.append(PhaseInfo(index=idx, title=title, state=state))
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
