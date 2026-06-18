"""Tests for WorkflowDocument phase parsing across accordion spellings.

Regression guard (DV-955): the backend normalizes phase accordions to the
chevron-only ``<accordion-plain>`` shortcode (DV-1084). The phase regex must
accept that spelling — otherwise ``phases()`` returns empty and
``task_queue run --host`` fails to emit a run packet ("Skill has no
<accordion> phases") for any normalized workflow skill, silently breaking
webhook-queued local runs.
"""

from __future__ import annotations

from deepvista_cli.workflow_doc import WorkflowDocument

_PLAIN = """---
name: workflow-demo
type: workflow
---

## Workflow

```mermaid
flowchart TD
  A --> B
```

## Node Description

<accordion-plain>
Phase 1: Capture & Log

Do the capture.
</accordion-plain>

<accordion-plain open="true">
Phase 2: Enrich

Do the enrichment.
</accordion-plain>
"""

_CHECKBOX = """---
name: workflow-demo
type: workflow
---

## Node Description

<accordion checked="true">
Phase 1: Capture & Log

Done.
</accordion>

<accordion checked="false">
Phase 2: Enrich

Pending.
</accordion>
"""


def test_phases_parsed_from_accordion_plain():
    phases = WorkflowDocument(_PLAIN).phases()
    assert [p.title for p in phases] == ["Phase 1: Capture & Log", "Phase 2: Enrich"]
    # `open="true"` on a plain accordion marks the active phase.
    assert phases[0].state == "pending"
    assert phases[1].state == "active"


def test_phases_parsed_from_legacy_checkbox_accordion():
    phases = WorkflowDocument(_CHECKBOX).phases()
    assert [p.title for p in phases] == ["Phase 1: Capture & Log", "Phase 2: Enrich"]
    assert phases[0].state == "done"
    assert phases[1].state == "pending"


def test_mixed_spellings_do_not_swallow_across_blocks():
    # A plain open tag must not pair with a legacy close tag (and vice versa),
    # which would merge two phases into one over-greedy match.
    body = _PLAIN + _CHECKBOX
    titles = [p.title for p in WorkflowDocument(body).phases()]
    assert titles.count("Phase 1: Capture & Log") == 2
    assert titles.count("Phase 2: Enrich") == 2
